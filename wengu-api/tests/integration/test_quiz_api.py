"""P1-11 家长手动组卷集成测试：确定性抽题、服务端判分、防作弊、无答案泄漏。

模型调用为零：判分只走确定性 judgeAnswer。考核结果写 attempts、不建错题，
掌握度按知识点下已确认 concepts 归属，可整体重放。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    Concept,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
)
from app.seed.bank import BankQuestion
from app.services.bank import get_bank
from app.services.recompute import Event as RecomputeEvent
from app.services.recompute import mastery
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

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
    db_path = tmp_path / "quizzes.db"
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
        # 手动组卷属家长区：统一先设 PIN 或解锁（PIN 行为本身由 test_session_api 覆盖）
        status = await client.get("/api/session/status")
        if status.json()["pin_set"]:
            response = await client.post("/api/session/unlock", json={"pin": "2468"})
        else:
            response = await client.post("/api/session/pin/set", json={"pin": "2468"})
        assert response.status_code == 200, response.text
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


async def _seed_concept(
    factory: async_sessionmaker,
    *,
    name: str,
    category_id: str = "cnm_001",
) -> int:
    async with factory() as session, session.begin():
        row = Concept(
            name=name,
            category_id=category_id,
            source="student",
            status="confirmed",
            merged_into_id=None,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _mastery(factory: async_sessionmaker, concept_id: int) -> float:
    async with factory() as session:
        rows = (await session.scalars(select(LearningEvent))).all()
    events = [
        RecomputeEvent(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    return mastery(events, concept_id)


def _wrong_answer(question: BankQuestion) -> str:
    if question.type == "choice":
        for choice in question.choices:
            if choice.key != question.answer and choice.key not in question.accept:
                return choice.key
        return "Z"
    if question.type == "numeric":
        return "999999"
    return "这是一段不会与标准答案等价的作答"


async def _paper(
    client: AsyncClient, *, topic_id: str = "cnm_001", count: int = 2, seed: int = 7
) -> dict:
    response = await client.get(
        "/api/quizzes/paper",
        params={"topic_id": topic_id, "count": count, "seed": seed},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
async def test_quiz_topics_and_paper_are_deterministic_and_answer_free(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        topics = await client.get(
            "/api/quizzes/topics", params={"subject": "数学", "limit": 200}
        )
        assert topics.status_code == 200, topics.text
        rows = topics.json()["items"]
        assert topics.json()["total"] >= 1
        row = next(item for item in rows if item["topic_id"] == "cnm_001")
        assert row["subject"] == "数学"
        assert row["answerable"] >= 4
        assert row["total"] >= row["answerable"]

        first = await _paper(client, count=2, seed=7)
        assert first["seed"] == 7
        assert first["count"] == 2
        assert len(first["items"]) == 2
        assert first["answerable_total"] >= 4
        assert first["coverage"] == "ok"
        assert first["bank_gap"] is False
        assert first["shortfall"] is False
        assert all(item["mode"] == "system" for item in first["items"])
        _assert_no_answer_keys(first)

        again = await _paper(client, count=2, seed=7)
        assert again["items"] == first["items"]

        # 组卷前缀稳定：count 变大只在卷尾追加，前 N 题不变
        longer = await _paper(client, count=4, seed=99)
        shorter = await _paper(client, count=2, seed=99)
        assert [item["question_id"] for item in shorter["items"]] == [
            item["question_id"] for item in longer["items"][:2]
        ]

        missing = await client.get(
            "/api/quizzes/paper", params={"topic_id": "cnm_999999"}
        )
        assert missing.status_code == 404


@pytest.mark.integration
async def test_paper_answer_key_is_parent_only_and_matches_bank(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        paper = await _paper(client, count=2, seed=7)
        response = await client.get(
            "/api/quizzes/paper/answers",
            params={"topic_id": "cnm_001", "count": 2, "seed": 7},
        )
        assert response.status_code == 200, response.text
        keys = response.json()
        assert keys["topic_id"] == "cnm_001"
        assert keys["seed"] == 7
        assert [item["question_id"] for item in keys["items"]] == [
            item["question_id"] for item in paper["items"]
        ]
        assert all("explanation" not in item for item in keys["items"])
        assert all("verify" not in item for item in keys["items"])

        bank = get_bank()
        for key, item in zip(keys["items"], paper["items"], strict=True):
            question = bank.question(item["question_id"])
            assert question is not None
            assert key["answer"] == question.answer
            assert key["acceptable_answers"] == list(question.accept)
            assert key["mode"] == item["mode"]

        # 孩子侧组卷响应仍无答案字段
        _assert_no_answer_keys(paper)

        missing = await client.get(
            "/api/quizzes/paper/answers",
            params={"topic_id": "cnm_999999", "count": 2, "seed": 7},
        )
        assert missing.status_code == 404

        locked = await client.post("/api/session/lock")
        assert locked.status_code == 200
        forbidden = await client.get(
            "/api/quizzes/paper/answers",
            params={"topic_id": "cnm_001", "count": 2, "seed": 7},
        )
        assert forbidden.status_code == 403


@pytest.mark.integration
async def test_paper_submit_is_server_judged_and_counts_toward_mastery(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    concept_id = await _seed_concept(factory, name="有理数加法")

    async with _client(factory) as client:
        paper = await _paper(client, count=2, seed=7)
        bank = get_bank()
        first_question, second_question = paper["items"]
        right = bank.question(first_question["question_id"])
        wrong = bank.question(second_question["question_id"])
        assert right is not None and wrong is not None

        payload = {
            "topic_id": "cnm_001",
            "seed": 7,
            "count": 2,
            "answers": [
                {
                    "question_id": right.id,
                    "answer": right.answer,
                    # 客户端谎报必须被忽略：服务端按 bank answer 判
                    "correct": False,
                },
                {
                    "question_id": wrong.id,
                    "answer": _wrong_answer(wrong),
                    "correct": True,
                },
            ],
        }
        submitted = await client.post("/api/quizzes/paper/submit", json=payload)
        assert submitted.status_code == 200, submitted.text
        body = submitted.json()
        assert [item["status"] for item in body["items"]] == ["correct", "wrong"]
        assert body["correct"] == 1
        assert body["wrong"] == 1
        assert all(item["mode"] == "system" for item in body["items"])
        assert all(item["replayed"] is False for item in body["items"])
        assert all(item["attempt_id"] is not None for item in body["items"])
        _assert_no_answer_keys(body)

        assert await _count(factory, Mistake) == 0  # 考核结果绝不新建错题
        assert await _count(factory, Attempt) == 2

        records = (
            await client.get("/api/attempts", params={"source": "system_quiz"})
        ).json()
        assert records["total"] == 2
        assert all(
            item["mistake_id"] is None and item["kind"] == "quiz"
            for item in records["items"]
        )
        record = next(
            item
            for item in records["items"]
            if item["question_id"] == first_question["question_id"]
        )
        assert record["topic_id"] == "cnm_001"
        assert record["problem_text"] == first_question["prompt"]
        assert record["answer_text"] is None

        assert await _mastery(factory, concept_id) == 0.5

        repeated = await client.post("/api/quizzes/paper/submit", json=payload)
        assert repeated.status_code == 200, repeated.text
        assert all(item["replayed"] is True for item in repeated.json()["items"])
        assert [item["attempt_id"] for item in repeated.json()["items"]] == [
            item["attempt_id"] for item in body["items"]
        ]
        assert await _count(factory, Attempt) == 2
        assert await _mastery(factory, concept_id) == 0.5


@pytest.mark.integration
async def test_paper_self_eval_downgrade_requires_verdict_and_blank_is_skipped(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_258", name="相似三角形")

    async with _client(factory) as client:
        paper = await _paper(client, topic_id="cnm_258", count=2, seed=11)
        assert paper["answerable_total"] == 0
        assert len(paper["items"]) == 2
        assert all(item["mode"] == "self_eval" for item in paper["items"])
        assert all(item["figure"] for item in paper["items"])
        _assert_no_answer_keys(paper)

        question_id = paper["items"][0]["question_id"]
        missing_verdict = await client.post(
            "/api/quizzes/paper/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "answers": [{"question_id": question_id, "answer": "纸上完成"}],
            },
        )
        assert missing_verdict.status_code == 422

        skipped = await client.post(
            "/api/quizzes/paper/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "answers": [{"question_id": question_id}],
            },
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json()["items"][0]["status"] == "skipped"
        assert await _count(factory, Attempt) == 0

        graded = await client.post(
            "/api/quizzes/paper/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "answers": [{"question_id": question_id, "correct": True}],
            },
        )
        assert graded.status_code == 200, graded.text
        assert graded.json()["items"][0]["status"] == "correct"

        records = await client.get("/api/attempts")
        assert records.json()["total"] == 1
        assert records.json()["items"][0]["source"] == "student_self"
        assert records.json()["items"][0]["problem_text"] == paper["items"][0]["prompt"]

        foreign = await client.post(
            "/api/quizzes/paper/submit",
            json={
                "topic_id": "cnm_258",
                "seed": 11,
                "count": 2,
                "answers": [{"question_id": "cnm_001_q1", "answer": "-3"}],
            },
        )
        assert foreign.status_code == 422

        unknown_topic = await client.post(
            "/api/quizzes/paper/submit",
            json={
                "topic_id": "cnm_999999",
                "seed": 11,
                "count": 2,
                "answers": [{"question_id": "cnm_001_q1", "answer": "-3"}],
            },
        )
        assert unknown_topic.status_code == 404
