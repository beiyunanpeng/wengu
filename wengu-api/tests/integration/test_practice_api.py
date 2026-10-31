"""P3-2 同类题加练集成测试：派生表隔离、服务端判分、确定性、可清空。

硬不变量：加练只写 practice_records——不写 attempts/learning_events、
不新建错题、不改掌握度/复习排期/打卡；整表可清空。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    PracticeRecord,
    ProblemBankItem,
    ReviewSchedule,
)
from app.seed.bank import BankQuestion
from app.services.bank import get_bank
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"
FORBIDDEN_KEYS = {"answer", "accept", "explanation", "verify"}


def _assert_no_answer_keys(payload: object) -> None:
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in FORBIDDEN_KEYS, (key, node)
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "practice.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(factory: async_sessionmaker) -> AsyncIterator[AsyncClient]:
    """刻意不解锁家长区：练习端点对孩子完全开放。"""

    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _seed_topic(
    factory: async_sessionmaker,
    *,
    topic_id: str = "cnm_001",
    name: str = "有理数",
    subject: str = "数学",
) -> None:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=topic_id,
                subject=subject,
                name=name,
                domain="数与代数",
                grade="七年级",
                semester="上册",
                chapter=name,
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _create_mistake(
    client: AsyncClient,
    *,
    primary_topic_id: str | None = "cnm_001",
) -> int:
    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": "数学",
                    "problem_text": "解方程 2x=4，注意移项",
                    "student_answer": "x=3",
                    "standard_answer": "x=2",
                    "error_cause_suggestion": "计算失误",
                    "suggested_topic_id": "cnm_001",
                    "source_ref": f"练习测试卷 第3题 {uuid4().hex}",
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
    payload: dict = {"actor": "student"}
    if primary_topic_id is not None:
        payload["primary_topic_id"] = primary_topic_id
    confirmed = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm", json=payload
    )
    assert confirmed.status_code == 200, confirmed.text
    return int(confirmed.json()["mistake_id"])


async def _facts(factory: async_sessionmaker) -> dict:
    """事实源与排期的内容快照：任何练习写入都不得改变它们。"""

    async with factory() as session:
        attempts = (
            await session.execute(select(Attempt).order_by(Attempt.id))
        ).scalars().all()
        events = (
            await session.execute(select(LearningEvent).order_by(LearningEvent.id))
        ).scalars().all()
        schedules = (
            await session.execute(
                select(ReviewSchedule).order_by(ReviewSchedule.id)
            )
        ).scalars().all()
        mistakes = (
            await session.execute(
                select(
                    Mistake.id,
                    Mistake.status,
                    Mistake.current_version,
                    Mistake.primary_topic_id,
                ).order_by(Mistake.id)
            )
        ).all()
        return {
            "attempts": [
                (
                    row.id,
                    row.mistake_id,
                    row.learning_event_id,
                    row.problem_bank_id,
                    row.kind,
                    row.source,
                    row.answer_text,
                    row.is_correct,
                    row.created_at,
                )
                for row in attempts
            ],
            "events": [
                (
                    row.id,
                    row.type,
                    row.actor,
                    row.mistake_id,
                    row.payload,
                    row.occurred_at,
                    row.idempotency_key,
                )
                for row in events
            ],
            "schedules": [
                (
                    row.id,
                    row.mistake_id,
                    row.rung,
                    row.base_interval_days,
                    row.due_date,
                    row.source_event_id,
                    row.completed_attempt_id,
                    row.completed_at,
                )
                for row in schedules
            ],
            "mistakes": [tuple(row) for row in mistakes],
        }


async def _dashboard(client: AsyncClient) -> dict:
    response = await client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


async def _due(client: AsyncClient) -> dict:
    response = await client.get("/api/reviews/due")
    assert response.status_code == 200, response.text
    return response.json()


def _wrong_answer(question: BankQuestion) -> str:
    if question.type == "choice":
        for choice in question.choices:
            if choice.key != question.answer and choice.key not in question.accept:
                return choice.key
        return "Z"
    if question.type == "numeric":
        return "999999"
    return "这是一段不会与标准答案等价的作答"


@pytest.mark.integration
async def test_practice_start_is_deterministic_answer_free_and_child_open(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        status = await client.get("/api/session/status")
        assert status.json()["pin_set"] is False
        assert status.json()["parent_unlocked"] is False

        first = await client.post(
            "/api/practice/start",
            json={"topic_id": "cnm_001", "count": 3, "seed": 7},
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["topic_id"] == "cnm_001"
        assert body["seed"] == 7
        assert body["count"] == 3
        assert body["bank_gap"] is False
        assert body["message"] is None
        assert len(body["items"]) == 3
        assert all(item["mode"] == "system" for item in body["items"])
        _assert_no_answer_keys(body)

        again = await client.post(
            "/api/practice/start",
            json={"topic_id": "cnm_001", "count": 3, "seed": 7},
        )
        assert again.status_code == 200, again.text
        assert again.json()["items"] == body["items"]

        gap = await client.post(
            "/api/practice/start",
            json={"topic_id": "cnm_999999", "count": 3},
        )
        assert gap.status_code == 200, gap.text
        assert gap.json()["items"] == []
        assert gap.json()["bank_gap"] is True
        assert gap.json()["coverage"] == "gap"
        assert gap.json()["message"] == "该知识点暂无同类题"

        missing_source = await client.post(
            "/api/practice/start", json={"count": 3}
        )
        assert missing_source.status_code == 422
        both_sources = await client.post(
            "/api/practice/start",
            json={"mistake_id": 1, "topic_id": "cnm_001", "count": 3},
        )
        assert both_sources.status_code == 422
        too_many = await client.post(
            "/api/practice/start",
            json={"topic_id": "cnm_001", "count": 11},
        )
        assert too_many.status_code == 422
        missing_mistake = await client.post(
            "/api/practice/start", json={"mistake_id": 999, "count": 3}
        )
        assert missing_mistake.status_code == 404


@pytest.mark.integration
async def test_practice_submit_writes_only_practice_records_and_clears(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = await _create_mistake(client)
        facts_before = await _facts(factory)
        dashboard_before = await _dashboard(client)
        due_before = await _due(client)
        assert facts_before["attempts"] == []
        assert facts_before["events"]  # 入本本身有事实事件；练习不得再追加

        started = await client.post(
            "/api/practice/start",
            json={"mistake_id": mistake_id, "count": 2, "seed": 7},
        )
        assert started.status_code == 200, started.text
        paper = started.json()
        assert paper["topic_id"] == "cnm_001"
        assert len(paper["items"]) == 2
        _assert_no_answer_keys(paper)

        bank = get_bank()
        right_view, wrong_view = paper["items"]
        right = bank.question(right_view["question_id"])
        wrong = bank.question(wrong_view["question_id"])
        assert right is not None and wrong is not None

        submitted = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": paper["topic_id"],
                "seed": paper["seed"],
                "count": paper["count"],
                "mistake_id": mistake_id,
                "items": [
                    {
                        "question_id": right.id,
                        "answer": right.answer,
                        # 客户端谎报必须被忽略：system 题由服务端判
                        "correct": False,
                    },
                    {
                        "question_id": wrong.id,
                        "answer": _wrong_answer(wrong),
                        "correct": True,
                    },
                ],
            },
        )
        assert submitted.status_code == 200, submitted.text
        result = submitted.json()
        assert [item["status"] for item in result["items"]] == [
            "correct",
            "wrong",
        ]
        assert result["correct"] == 1
        assert result["wrong"] == 1
        assert all(item["mode"] == "system" for item in result["items"])
        assert all(item["practice_record_id"] is not None for item in result["items"])
        _assert_no_answer_keys(result)

        facts_after = await _facts(factory)
        assert facts_after == facts_before
        assert await _count(factory, PracticeRecord) == 2
        assert await _count(factory, Mistake) == 1
        assert await _count(factory, Attempt) == 0
        assert await _dashboard(client) == dashboard_before
        assert await _due(client) == due_before

        listed = await client.get(
            "/api/practice", params={"mistake_id": mistake_id}
        )
        assert listed.status_code == 200, listed.text
        records = listed.json()
        assert records["total"] == 2
        newest, oldest = records["items"]
        assert newest["kind"] == "variant"
        assert newest["source_mistake_id"] == mistake_id
        assert newest["problem_bank_id"] is None  # seed 题没有 problem_bank 行
        assert newest["problem_text"] == wrong.prompt
        assert newest["student_answer"] == _wrong_answer(wrong)
        assert newest["is_correct"] is False
        assert oldest["problem_text"] == right.prompt
        assert oldest["student_answer"] == right.answer
        assert oldest["is_correct"] is True

        detail = await client.get(f"/api/mistakes/{mistake_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["id"] == mistake_id

        cleared = await client.delete("/api/practice")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["deleted"] == 2
        assert await _count(factory, PracticeRecord) == 0
        assert (await client.get("/api/practice")).json()["total"] == 0
        assert await _facts(factory) == facts_before
        assert await _dashboard(client) == dashboard_before
        assert await _due(client) == due_before


@pytest.mark.integration
async def test_practice_self_eval_accepts_verdict_and_blank_is_skipped(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_258", name="相似三角形")

    async with _client(factory) as client:
        started = await client.post(
            "/api/practice/start",
            json={"topic_id": "cnm_258", "count": 2, "seed": 11},
        )
        assert started.status_code == 200, started.text
        paper = started.json()
        assert paper["answerable_total"] == 0
        assert len(paper["items"]) == 2
        assert all(item["mode"] == "self_eval" for item in paper["items"])
        _assert_no_answer_keys(paper)
        question_id = paper["items"][0]["question_id"]

        missing_verdict = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "items": [
                    {"question_id": question_id, "answer": "纸上完成"}
                ],
            },
        )
        assert missing_verdict.status_code == 422
        assert await _count(factory, PracticeRecord) == 0

        skipped = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "items": [{"question_id": question_id}],
            },
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json()["items"][0]["status"] == "skipped"
        assert skipped.json()["items"][0]["practice_record_id"] is None
        assert await _count(factory, PracticeRecord) == 0

        graded = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "items": [{"question_id": question_id, "correct": True}],
            },
        )
        assert graded.status_code == 200, graded.text
        assert graded.json()["items"][0]["status"] == "correct"
        assert await _count(factory, PracticeRecord) == 1
        async with factory() as session:
            row = (
                await session.execute(select(PracticeRecord))
            ).scalar_one()
            assert row.kind == "variant"
            assert row.is_correct is True
            assert row.problem_text
            assert row.source_mistake_id is None
        assert await _count(factory, Attempt) == 0

        foreign = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "items": [
                    {"question_id": "cnm_001_q1", "answer": "-3"}
                ],
            },
        )
        assert foreign.status_code == 422


@pytest.mark.integration
async def test_practice_records_problem_bank_id_for_parent_question(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_practice_db", name="家长自建考点")
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = ProblemBankItem(
            external_id="cnm_practice_db_q1",
            subject="数学",
            problem_text="计算 2+2",
            answer="4",
            acceptable_answers_json="[]",
            unordered=False,
            verify="4",
            verify_vars_json="{}",
            verify_status="verified",
            source="test",
            created_at=now,
            topic_id="cnm_practice_db",
            question_type="numeric",
            difficulty="easy",
            choices_json="[]",
            figure=None,
            hide_choice_text=False,
            percent=False,
            unaudited=True,
            blind_verified=False,
            status="active",
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        bank_pk = row.id

    async with _client(factory) as client:
        started = await client.post(
            "/api/practice/start",
            json={"topic_id": "cnm_practice_db", "count": 1, "seed": 3},
        )
        assert started.status_code == 200, started.text
        question = started.json()["items"][0]
        assert question["question_id"] == "cnm_practice_db_q1"
        assert question["prompt"] == "计算 2+2"

        submitted = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": "cnm_practice_db",
                "seed": 3,
                "count": 1,
                "items": [{"question_id": "cnm_practice_db_q1", "answer": "4"}],
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["items"][0]["status"] == "correct"

        records = (await client.get("/api/practice")).json()["items"]
        assert len(records) == 1
        assert records[0]["problem_bank_id"] == bank_pk
        assert records[0]["is_correct"] is True
