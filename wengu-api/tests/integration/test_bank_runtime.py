"""P3-1b 家长题进入运行时检索池：合并、缓存失效、确定性重放、gap/thin 统计。

DoD（TICKETS P3-1b）：
1. 录 2 道物理新题 → 审核通过 → 物理到期错题的 quiz 从含新题的池中出题，
   同 seed 重放稳定；
2. 看板 `bank_gap` / 到期队列 `coverage=thin` 随池更新，统计与合并题集一致；
3. 旧 pick 在新池下 replay 抛 `BankReplayError`，绝不静默换题；
4. seed JSON 全程只读，家长题只进 SQLite `problem_bank`。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import KnowledgeSeed, Mistake, ReviewSchedule
from app.services.bank import (
    BankReplayError,
    find_same_type,
    get_bank,
    get_runtime_bank,
    replay,
)
from app.services.review import quiz_seed
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
SEED_PATH = API_DIR.parent / "seeds" / "data" / "questions.json"
PIN = "2468"
CHANNEL = "agent_transcribe_v1"

PHYSICS_TOPIC = "cnp_001"
CHEMISTRY_TOPIC = "cnh_001"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "bank-runtime.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(factory: async_sessionmaker) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        status = await client.get("/api/session/status")
        if status.json()["pin_set"]:
            response = await client.post("/api/session/unlock", json={"pin": PIN})
        else:
            response = await client.post("/api/session/pin/set", json={"pin": PIN})
        assert response.status_code == 200, response.text
        yield client


async def _seed_topics(factory: async_sessionmaker) -> None:
    async with factory() as session, session.begin():
        session.add_all(
            [
                KnowledgeSeed(
                    id=PHYSICS_TOPIC,
                    subject="物理",
                    name="长度和时间的测量",
                    domain="运动与相互作用",
                    grade="八年级",
                    semester="上册",
                    type="procedural",
                    unaudited=True,
                    blind_verified=False,
                ),
                KnowledgeSeed(
                    id=CHEMISTRY_TOPIC,
                    subject="化学",
                    name="物质构成的奥秘",
                    domain="物质的组成与结构",
                    grade="九年级",
                    semester="上册",
                    type="conceptual",
                    unaudited=True,
                    blind_verified=False,
                ),
            ]
        )


async def _confirm_wrong(
    client: AsyncClient,
    *,
    subject: str,
    topic_id: str,
    problem_text: str,
) -> int:
    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": subject,
                    "problem_text": problem_text,
                    "student_answer": "错误作答",
                    "standard_answer": "正确作答",
                    "suggested_topic_id": topic_id,
                    "source_ref": f"测试卷 {uuid4().hex}",
                    "captured_at": "2026-10-28",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch_id"]
    drafts = await client.get(f"/api/imports/{batch_id}/drafts")
    assert drafts.status_code == 200, drafts.text
    (draft_id,) = (draft["id"] for draft in drafts.json()["drafts"])
    confirmed = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm",
        json={"actor": "student", "primary_topic_id": topic_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    return int(confirmed.json()["mistake_id"])


async def _set_due_today(factory: async_sessionmaker, mistake_id: int) -> None:
    async with factory() as session, session.begin():
        rows = (
            await session.scalars(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
            )
        ).all()
        assert rows
        for row in rows:
            row.due_date = date.today()


async def _due_items(client: AsyncClient, day: date) -> list[dict]:
    response = await client.get(
        "/api/reviews/due", params={"today": day.isoformat()}
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _manual_item(
    *,
    topic_id: str,
    subject: str,
    prompt: str,
    answer: str,
    verify: str,
    **extra: object,
) -> dict:
    payload: dict[str, object] = {
        "topic_id": topic_id,
        "type": "numeric",
        "difficulty": "easy",
        "prompt": prompt,
        "answer": answer,
        "verify": verify,
        "source_ref": f"家长补录 {uuid4().hex}",
    }
    payload.update(extra)
    return payload


async def _runtime_bank(factory: async_sessionmaker):
    async with factory() as session:
        return await get_runtime_bank(session)


@pytest.mark.integration
async def test_parent_questions_join_physics_pool_and_break_old_replay(
    tmp_path: Path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    seed_before = SEED_PATH.read_bytes()

    async with _client(factory) as client:
        mistake_id = await _confirm_wrong(
            client,
            subject="物理",
            topic_id=PHYSICS_TOPIC,
            problem_text="测量长度的工具是什么？",
        )
        await _set_due_today(factory, mistake_id)

        (before_item,) = await _due_items(client, date.today())
        before_quiz = before_item["quiz"]
        assert before_item["task"] == "quiz"
        assert before_quiz["pool_size"] == 4
        assert before_quiz["quality"]["unaudited"] is True
        old_seed = before_quiz["seed"]

        seed_bank = get_bank()
        old_pick = find_same_type(PHYSICS_TOPIC, old_seed, bank=seed_bank)
        assert old_pick.question_id == before_quiz["question_id"]

        for prompt, answer, verify in (
            ("家长补录：5×2 等于多少？", "10", "5*2"),
            ("家长补录：24÷6 等于多少？", "4", "24/6"),
        ):
            created = await client.post(
                "/api/bank/items",
                json=_manual_item(
                    topic_id=PHYSICS_TOPIC,
                    subject="物理",
                    prompt=prompt,
                    answer=answer,
                    verify=verify,
                ),
            )
            assert created.status_code == 201, created.text
            assert created.json()["verify_status"] == "verified"

        (after_item,) = await _due_items(client, date.today())
        after_quiz = after_item["quiz"]
        assert after_quiz["seed"] == old_seed
        assert after_quiz["pool_size"] == before_quiz["pool_size"] + 2
        assert after_item["task"] == "quiz"

        merged = await _runtime_bank(factory)
        dynamic_ids = {
            question.id
            for question in merged.questions_for(PHYSICS_TOPIC)
            if question.id.startswith("manual_")
        }
        assert len(dynamic_ids) == 2
        # 统计随合并池重算：物理总数 +2，仍低于 thin 阈值
        assert merged.stats.by_subject["物理"] == 370
        assert merged.stats.total == seed_bank.stats.total + 2
        assert merged.topics[PHYSICS_TOPIC]["name"] == "长度和时间的测量"

        # DoD 3：旧 pick 在新池下显式失败，绝不静默换题
        with pytest.raises(BankReplayError):
            replay(old_pick, bank=merged)
        # 旧 seed 索引本身不变，旧 pick 在 seed 索引下仍可重放
        assert replay(old_pick, bank=seed_bank) == old_pick

        # 新题确实可被抽中；同一 seed 在合并池下重放稳定
        reachable = next(
            seed
            for seed in range(200_000)
            if find_same_type(PHYSICS_TOPIC, seed, bank=merged).question_id
            in dynamic_ids
        )
        hot_pick = find_same_type(PHYSICS_TOPIC, hot_seed := reachable, bank=merged)
        assert hot_pick.question_id in dynamic_ids
        assert hot_pick.coverage == "thin"
        assert replay(hot_pick, bank=merged).question_id == hot_pick.question_id
        served = await client.get(
            "/api/quizzes/topics", params={"subject": "物理", "q": "长度"}
        )
        assert served.status_code == 200, served.text
        physics = served.json()["items"][0]
        assert physics["total"] == 6

        # 到期队列用同一 merge 池：热 seed 对应题在 quiz 视图里没有答案字段
        quiz_view = await client.get(
            "/api/quizzes/paper",
            params={"topic_id": PHYSICS_TOPIC, "count": 2, "seed": hot_seed},
        )
        assert quiz_view.status_code == 200, quiz_view.text
        text = quiz_view.text
        for key in ('"answer"', '"accept"', '"verify"', '"explanation"'):
            assert key not in text

    assert SEED_PATH.read_bytes() == seed_before


@pytest.mark.integration
async def test_dashboard_bank_gap_closes_when_parent_question_added(
    tmp_path: Path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)

    async with _client(factory) as client:
        mistake_id = await _confirm_wrong(
            client,
            subject="化学",
            topic_id=CHEMISTRY_TOPIC,
            problem_text="化学：空气中最多的气体是什么？",
        )
        await _set_due_today(factory, mistake_id)

        (before_item,) = await _due_items(client, date.today())
        assert before_item["task"] == "redo"
        assert before_item["bank_gap"] is True

        dashboard = await client.get(
            "/api/dashboard", params={"today": date.today().isoformat()}
        )
        assert dashboard.status_code == 200, dashboard.text
        gap_before = dashboard.json()["bank_gap"]["topics"]
        assert any(item["topic_id"] == CHEMISTRY_TOPIC for item in gap_before)

        created = await client.post(
            "/api/bank/items",
            json=_manual_item(
                topic_id=CHEMISTRY_TOPIC,
                subject="化学",
                prompt="化学补录：1+1 等于多少？",
                answer="2",
                verify="1+1",
            ),
        )
        assert created.status_code == 201, created.text

        merged = await _runtime_bank(factory)
        assert merged.stats.by_subject["化学"] == 1
        assert len(merged.questions_for(CHEMISTRY_TOPIC)) == 1
        assert merged.topics[CHEMISTRY_TOPIC]["domain"] == "物质的组成与结构"

        dashboard_after = await client.get(
            "/api/dashboard", params={"today": date.today().isoformat()}
        )
        assert dashboard_after.status_code == 200, dashboard_after.text
        payload = dashboard_after.json()
        assert all(
            item["topic_id"] != CHEMISTRY_TOPIC
            for item in payload["bank_gap"]["topics"]
        )
        # 错题本存量不受题库变化影响（gap 只反映检索池）
        assert any(
            item["topic_id"] == CHEMISTRY_TOPIC for item in payload["weak_topics"]
        )

        (after_item,) = await _due_items(client, date.today())
        assert after_item["task"] == "quiz"
        assert after_item["bank_gap"] is False
        assert after_item["coverage"] == "thin"
        assert after_item["quiz"]["question_id"].startswith("manual_")
        assert after_item["quiz"]["pool_size"] == 1
        assert after_item["coverage_hint"] == "覆盖偏薄"

        schedule = None
        async with factory() as session:
            mistake = await session.get(Mistake, mistake_id)
            assert mistake is not None
            schedule = (
                await session.scalars(
                    select(ReviewSchedule).where(
                        ReviewSchedule.mistake_id == mistake_id,
                        ReviewSchedule.completed_at.is_(None),
                    )
                )
            ).one()
            assert schedule.due_date == date.today()
        expected_seed = quiz_seed(mistake_id, schedule.id)
        assert after_item["quiz"]["seed"] == expected_seed
        pick = find_same_type(CHEMISTRY_TOPIC, expected_seed, bank=merged)
        assert pick.question_id == after_item["quiz"]["question_id"]
        assert replay(pick, bank=merged) == pick
        assert pick.coverage == "thin"

        # 物理未被本轮补题波及：368 题、仍判 thin
        physics_total = merged.stats.by_subject["物理"]
        assert physics_total == 368
        physics_pick = find_same_type(PHYSICS_TOPIC, 1, bank=merged)
        assert physics_pick.coverage == "thin"
