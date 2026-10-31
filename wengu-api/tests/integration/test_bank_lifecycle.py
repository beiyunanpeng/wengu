"""P3-1c 题库修订：编辑重走闸门 + 软作废（退出检索池、不改写历史）。

DoD（TICKETS P3-1c）：
1. PATCH 合并后重跑 `check_approvable` + `classify_verify`：沙箱注入/纯数值矛盾/
   缺答案/占位/答案不在选项 key 一律 422 带稳定错误码；合法编辑 200 且 verify_status 重算。
2. void 后运行时池不再含该题（同 topic 抽出不再命中、统计重算），unvoid 恢复；两者幂等。
3. 作废/编辑前后 attempts / learning_events / review_schedules 行与内容完全不变。
4. 家长面全部 403；seed JSON 字节不变。
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
from app.models import KnowledgeSeed, ReviewSchedule
from app.services.bank import (
    BankReplayError,
    find_same_type,
    get_runtime_bank,
    replay,
)
from app.services.review import quiz_seed
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
SEED_PATH = API_DIR.parent / "seeds" / "data" / "questions.json"
PIN = "2468"
CHANNEL = "agent_transcribe_v1"

PHYSICS_TOPIC = "cnp_001"
CHEMISTRY_TOPIC = "cnh_001"

SNAPSHOT_TABLES = ("attempts", "learning_events", "review_schedules")


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "bank-lifecycle.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(
    factory: async_sessionmaker, *, unlock: bool = True
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if unlock:
            status = await client.get("/api/session/status")
            if status.json()["pin_set"]:
                response = await client.post(
                    "/api/session/unlock", json={"pin": PIN}
                )
            else:
                response = await client.post(
                    "/api/session/pin/set", json={"pin": PIN}
                )
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


async def _create_item(
    client: AsyncClient,
    *,
    topic_id: str,
    prompt: str,
    answer: str,
    verify: str = "",
    type_: str = "numeric",
    choices: list[dict[str, str]] | None = None,
) -> int:
    payload: dict[str, object] = {
        "topic_id": topic_id,
        "type": type_,
        "difficulty": "easy",
        "prompt": prompt,
        "answer": answer,
        "verify": verify,
        "choices": choices or [],
        "source_ref": f"家长补录 {uuid4().hex}",
    }
    response = await client.post("/api/bank/items", json=payload)
    assert response.status_code == 201, response.text
    return int(response.json()["problem_bank_id"])


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


async def _runtime_bank(factory: async_sessionmaker):
    async with factory() as session:
        return await get_runtime_bank(session)


async def _snapshot(factory: async_sessionmaker) -> dict[str, list[tuple]]:
    async with factory() as session:
        return {
            table: [tuple(row) for row in (
                await session.execute(text(f"SELECT * FROM {table} ORDER BY id"))
            ).all()]
            for table in SNAPSHOT_TABLES
        }


@pytest.mark.integration
async def test_edit_reruns_gate_and_recomputes_verify_status(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)

    async with _client(factory) as client:
        item_id = await _create_item(
            client,
            topic_id=PHYSICS_TOPIC,
            prompt="家长补录：5×2 等于多少？",
            answer="10",
            verify="5*2",
        )

        listed = await client.get("/api/bank/items")
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] == 1
        (item,) = body["items"]
        assert item["id"] == item_id
        assert item["external_id"].startswith("manual_")
        assert item["status"] == "active"
        assert item["verify_status"] == "verified"
        assert item["answer"] == "10"
        assert item["topic_name"] == "长度和时间的测量"
        assert item["updated_at"] is None
        assert item["unaudited"] is True
        assert item["blind_verified"] is False
        original_external_id = item["external_id"]

        by_topic = await client.get(
            "/api/bank/items", params={"topic_id": PHYSICS_TOPIC}
        )
        assert by_topic.json()["total"] == 1
        by_other = await client.get(
            "/api/bank/items", params={"subject": "化学"}
        )
        assert by_other.json()["total"] == 0
        voided_view = await client.get(
            "/api/bank/items", params={"status": "voided"}
        )
        assert voided_view.json()["total"] == 0

        empty = await client.patch(f"/api/bank/items/{item_id}", json={})
        assert empty.status_code == 422, empty.text
        assert empty.json()["detail"]["code"] == "no_fields"

        # 沙箱注入 / 赋值 / 属性访问 → 422 稳定码，题面不被改写
        for verify in ("__import__('os')", "x = 1", "(1).__class__"):
            rejected = await client.patch(
                f"/api/bank/items/{item_id}", json={"verify": verify}
            )
            assert rejected.status_code == 422, (verify, rejected.text)
            code = rejected.json()["detail"]["code"]
            assert code.startswith("verify_error:"), code

        # 纯数值矛盾：verify 仍为 5*2，答案改成 11 → 拒绝
        mismatch = await client.patch(
            f"/api/bank/items/{item_id}", json={"answer": "11"}
        )
        assert mismatch.status_code == 422, mismatch.text
        assert mismatch.json()["detail"]["code"] == "verify_mismatch"

        # 缺答案 / 占位 → 422 missing_fields
        missing = await client.patch(
            f"/api/bank/items/{item_id}", json={"answer": "  "}
        )
        assert missing.status_code == 422, missing.text
        assert missing.json()["detail"]["code"] == "missing_fields"
        assert missing.json()["detail"]["errors"][0]["field"] == "answer"

        placeholder = await client.patch(
            f"/api/bank/items/{item_id}", json={"prompt": "题目残缺〔?〕"}
        )
        assert placeholder.status_code == 422, placeholder.text
        assert placeholder.json()["detail"]["code"] == "missing_fields"
        assert placeholder.json()["detail"]["errors"][0]["reason"].startswith(
            "placeholder"
        )

        after_rejects = await client.get("/api/bank/items")
        (still,) = after_rejects.json()["items"]
        assert still["prompt"] == "家长补录：5×2 等于多少？"
        assert still["answer"] == "10"
        assert still["verify_status"] == "verified"
        assert still["updated_at"] is None

        # 选择题：answer 改成不存在的 key → normalize_failed
        choice_id = await _create_item(
            client,
            topic_id=PHYSICS_TOPIC,
            prompt="家长补录：下列哪个是偶数？",
            answer="A",
            type_="choice",
            choices=[
                {"key": "A", "text": "4"},
                {"key": "B", "text": "5"},
                {"key": "C", "text": "7"},
                {"key": "D", "text": "9"},
            ],
        )
        bad_key = await client.patch(
            f"/api/bank/items/{choice_id}", json={"answer": "E"}
        )
        assert bad_key.status_code == 422, bad_key.text
        assert bad_key.json()["detail"]["code"] == "normalize_failed"
        assert any(
            error["reason"].startswith("answer_not_in_choices")
            for error in bad_key.json()["detail"]["errors"]
        )

        # 合法编辑：verify_status 重算、updated_at 落值、external_id 不变
        edited = await client.patch(
            f"/api/bank/items/{item_id}",
            json={
                "prompt": "家长补录：6×2 等于多少？",
                "answer": "12",
                "verify": "6*2",
                "difficulty": "medium",
            },
        )
        assert edited.status_code == 200, edited.text
        edited_body = edited.json()
        assert edited_body["prompt"] == "家长补录：6×2 等于多少？"
        assert edited_body["answer"] == "12"
        assert edited_body["difficulty"] == "medium"
        assert edited_body["verify_status"] == "verified"
        assert edited_body["external_id"] == original_external_id
        assert edited_body["updated_at"] is not None

        # 清空 verify → unverifiable（不阻塞编辑）
        unverified = await client.patch(
            f"/api/bank/items/{item_id}", json={"verify": ""}
        )
        assert unverified.status_code == 200, unverified.text
        assert unverified.json()["verify_status"] == "unverifiable"


@pytest.mark.integration
async def test_void_and_unvoid_move_item_out_of_runtime_pool(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    seed_before = SEED_PATH.read_bytes()

    async with _client(factory) as client:
        item_id = await _create_item(
            client,
            topic_id=PHYSICS_TOPIC,
            prompt="家长补录：24÷6 等于多少？",
            answer="4",
            verify="24/6",
        )
        created = await client.get("/api/bank/items")
        external_id = created.json()["items"][0]["external_id"]

        before_bank = await _runtime_bank(factory)
        assert before_bank.stats.by_subject["物理"] == 369
        assert any(
            question.id == external_id
            for question in before_bank.questions_for(PHYSICS_TOPIC)
        )
        hot_seed = next(
            seed
            for seed in range(100_000)
            if find_same_type(PHYSICS_TOPIC, seed, bank=before_bank).question_id
            == external_id
        )
        old_pick = find_same_type(PHYSICS_TOPIC, hot_seed, bank=before_bank)

        voided = await client.post(f"/api/bank/items/{item_id}/void")
        assert voided.status_code == 200, voided.text
        assert voided.json()["status"] == "voided"
        first_voided_at = voided.json()["updated_at"]
        assert first_voided_at is not None

        repeated = await client.post(f"/api/bank/items/{item_id}/void")
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == voided.json()

        active_view = await client.get("/api/bank/items")
        assert active_view.json()["total"] == 0
        voided_view = await client.get(
            "/api/bank/items", params={"status": "voided"}
        )
        assert voided_view.json()["total"] == 1
        assert voided_view.json()["items"][0]["status"] == "voided"
        all_view = await client.get("/api/bank/items", params={"status": "all"})
        assert all_view.json()["total"] == 1

        after_void = await _runtime_bank(factory)
        assert after_void.stats.by_subject["物理"] == 368
        assert external_id not in after_void.by_id
        assert all(
            question.id != external_id
            for question in after_void.questions_for(PHYSICS_TOPIC)
        )
        # 作废题在同 topic 的任意种子里都不再被抽中
        assert all(
            find_same_type(PHYSICS_TOPIC, seed, bank=after_void).question_id
            != external_id
            for seed in range(5_000)
        )
        # 池变化 → 旧 pick 重放显式失败，绝不静默换题
        with pytest.raises(BankReplayError):
            replay(old_pick, bank=after_void)

        restored = await client.post(f"/api/bank/items/{item_id}/unvoid")
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "active"
        assert restored.json()["updated_at"] is not None
        repeated_restore = await client.post(f"/api/bank/items/{item_id}/unvoid")
        assert repeated_restore.json() == restored.json()

        after_restore = await _runtime_bank(factory)
        assert after_restore.stats.by_subject["物理"] == 369
        assert external_id in after_restore.by_id
        assert replay(old_pick, bank=after_restore) == old_pick

    assert SEED_PATH.read_bytes() == seed_before


@pytest.mark.integration
async def test_edit_and_void_leave_history_untouched(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    seed_before = SEED_PATH.read_bytes()

    async with _client(factory) as client:
        item_id = await _create_item(
            client,
            topic_id=CHEMISTRY_TOPIC,
            prompt="化学补录：1+1 等于多少？",
            answer="2",
            verify="1+1",
        )
        mistake_id = await _confirm_wrong(
            client,
            subject="化学",
            topic_id=CHEMISTRY_TOPIC,
            problem_text="化学：空气中最多的气体是什么？",
        )
        await _set_due_today(factory, mistake_id)

        (due_item,) = await _due_items(client, date.today())
        assert due_item["task"] == "quiz"
        quiz = due_item["quiz"]
        assert quiz["question_id"].startswith("manual_")
        assert quiz["pool_size"] == 1

        async with factory() as session:
            schedule = (
                await session.scalars(
                    select(ReviewSchedule).where(
                        ReviewSchedule.mistake_id == mistake_id,
                        ReviewSchedule.completed_at.is_(None),
                    )
                )
            ).one()
        assert quiz["seed"] == quiz_seed(mistake_id, schedule.id)

        completed = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": schedule.id,
                "question_id": quiz["question_id"],
                "answer": "2",
                "completed_on": date.today().isoformat(),
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["verdict"] == "correct"

        bank_before = await _runtime_bank(factory)
        pick = find_same_type(CHEMISTRY_TOPIC, quiz["seed"], bank=bank_before)
        assert pick.question_id == quiz["question_id"]
        history_before = await _snapshot(factory)
        assert history_before["attempts"]
        assert history_before["learning_events"]
        assert history_before["review_schedules"]

        edited = await client.patch(
            f"/api/bank/items/{item_id}",
            json={
                "prompt": "化学补录：2+2 等于多少？",
                "answer": "4",
                "verify": "2+2",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["external_id"] == quiz["question_id"]

        # 内容修订不回溯：id 不变，旧 pick 仍可按身份重放（拿到新内容）
        bank_edited = await _runtime_bank(factory)
        replayed = replay(pick, bank=bank_edited)
        assert replayed.question_id == pick.question_id
        assert replayed.pool_ids == pick.pool_ids
        assert replayed.question.prompt == "化学补录：2+2 等于多少？"

        voided = await client.post(f"/api/bank/items/{item_id}/void")
        assert voided.status_code == 200, voided.text
        bank_voided = await _runtime_bank(factory)
        with pytest.raises(BankReplayError):
            replay(pick, bank=bank_voided)

        restored = await client.post(f"/api/bank/items/{item_id}/unvoid")
        assert restored.status_code == 200, restored.text

        # attempts/events/排期是 append-only 事实，编辑/作废只动检索池，不写历史
        history_after = await _snapshot(factory)
        assert history_after == history_before

    assert SEED_PATH.read_bytes() == seed_before


@pytest.mark.integration
async def test_bank_item_lifecycle_requires_parent(tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)

    async with _client(factory, unlock=False) as locked:
        listed = await locked.get("/api/bank/items")
        patched = await locked.patch("/api/bank/items/1", json={"answer": "1"})
        voided = await locked.post("/api/bank/items/1/void")
        unvoided = await locked.post("/api/bank/items/1/unvoid")
    assert [
        listed.status_code,
        patched.status_code,
        voided.status_code,
        unvoided.status_code,
    ] == [403, 403, 403, 403]
