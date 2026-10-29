"""核对页确认入本集成测试（P1-6 · v2.5）。

覆盖：待确认队列建议值、一键确认走唯一写入路径、转正闸门（正答必填、
占位符拒绝、主考点可空但存在性校验、错答可空）、建议值/确认值分列存储、
重复确认幂等、attempts 按 source 过滤回看。
"""

from __future__ import annotations

import json
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
    GradingResult,
    GradingVersion,
    IngestionDraft,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    PracticeRecord,
    ReviewSchedule,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "intake.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_topics(factory: async_sessionmaker) -> tuple[int, int]:
    """两门数学知识点 + 两个细标签；返回 (方程概念 id, 有理数概念 id)。"""

    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add_all(
            [
                KnowledgeSeed(
                    id="cnm_001",
                    subject="数学",
                    name="一元一次方程",
                    unaudited=True,
                ),
                KnowledgeSeed(
                    id="cnm_002",
                    subject="数学",
                    name="有理数运算",
                    unaudited=True,
                ),
            ]
        )
        await session.flush()
        equation = Concept(
            name="移项变号",
            category_id="cnm_001",
            source="parent",
            status="confirmed",
            created_at=now,
        )
        numbers = Concept(
            name="异号相加",
            category_id="cnm_002",
            source="parent",
            status="confirmed",
            created_at=now,
        )
        session.add_all([equation, numbers])
        await session.flush()
        return equation.id, numbers.id


def _client(factory: async_sessionmaker) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _item(**overrides) -> dict:
    item = {
        "subject": "数学",
        "problem_text": "解方程 2x=4",
        "student_answer": "x=3",
        "standard_answer": "x=2",
        "error_cause_suggestion": "计算失误",
        "suggested_topic_id": "cnm_001",
        "source_ref": "期中卷 第3题",
        "captured_at": "2026-10-28",
    }
    item.update(overrides)
    return item


async def _import_drafts(client: AsyncClient, items: list[dict]) -> list[int]:
    response = await client.post(
        "/api/imports",
        content=json.dumps({"channel": CHANNEL, "items": items}, ensure_ascii=False),
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch_id"]
    drafts = await client.get(f"/api/imports/{batch_id}/drafts")
    return [draft["id"] for draft in drafts.json()["drafts"]]


@pytest.mark.integration
async def test_pending_drafts_list_shows_side_by_side_and_suggestions(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        await _import_drafts(client, [_item()])
        response = await client.get("/api/imports/drafts")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    draft = body["items"][0]
    assert draft["status"] == "draft"
    assert draft["problem_text"] == "解方程 2x=4"
    assert draft["student_answer"] == "x=3"
    assert draft["standard_answer"] == "x=2"
    assert draft["source_ref"] == "期中卷 第3题"
    assert draft["suggestion"] == {
        "topic_id": "cnm_001",
        "topic_name": "一元一次方程",
        "error_cause": "calculation",
        "error_cause_label": "计算失误",
        "source": "agent",
    }
    assert draft["grading_id"] is None
    assert draft["mistake_id"] is None


@pytest.mark.integration
async def test_confirm_promotes_draft_through_unique_write_path(tmp_path) -> None:
    factory = _migrated(tmp_path)
    equation_id, _ = await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        response = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={
                "primary_topic_id": "cnm_001",
                "concept_ids": [equation_id],
                "error_cause": "calculation",
                "actor": "parent",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["already_promoted"] is False
    assert body["primary_topic_id"] == "cnm_001"
    assert body["standard_answer"] == "x=2"
    assert body["due_on"] is not None

    async with factory() as session:
        draft = await session.get(IngestionDraft, draft_id)
        assert draft.status == "promoted"

        grading = (
            await session.execute(
                select(GradingResult).where(
                    GradingResult.source_kind == "ingestion_draft",
                    GradingResult.source_id == draft_id,
                )
            )
        ).scalar_one()
        assert grading.id == body["grading_id"]
        assert grading.status == "confirmed"
        assert grading.current_version == 2
        assert grading.standard_answer == "x=2"

        versions = (
            await session.execute(
                select(GradingVersion)
                .where(GradingVersion.grading_id == grading.id)
                .order_by(GradingVersion.version)
            )
        ).scalars().all()
        assert [(v.version, v.action, v.verdict) for v in versions] == [
            (1, "suggested", "wrong"),
            (2, "confirmed", "wrong"),
        ]
        assert versions[1].source == "parent"

        mistake = await session.get(Mistake, body["mistake_id"])
        assert mistake.source_grading_id == grading.id
        assert mistake.primary_topic_id == "cnm_001"
        assert mistake.status == "active"

        version = (
            await session.execute(
                select(MistakeVersion).where(MistakeVersion.mistake_id == mistake.id)
            )
        ).scalar_one()
        assert version.standard_answer == "x=2"
        assert version.student_answer == "x=3"
        assert version.confirmed_by == "parent"
        assert version.confirmed_category_id == "cnm_001"
        assert json.loads(version.confirmed_concept_ids_json) == [equation_id]
        assert version.confirmed_error_cause == "calculation"
        assert version.suggested_error_cause == "calculation"

        schedule = (
            await session.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake.id
                )
            )
        ).scalar_one()
        assert schedule.due_date.isoformat() == body["due_on"]

        # 唯一写入路径不新建 attempts（考核闭环才写），只记事实事件
        assert (
            await session.execute(select(func.count()).select_from(Attempt))
        ).scalar_one() == 0
        event_types = set(
            (await session.execute(select(LearningEvent.type))).scalars().all()
        )
        assert "attempt_wrong" in event_types
        assert "review_scheduled" in event_types

    async with _client(factory) as client:
        pending = (await client.get("/api/imports/drafts")).json()
        promoted = (await client.get("/api/imports/drafts?status=promoted")).json()
        detail = await client.get(f"/api/mistakes/{body['mistake_id']}")

    assert pending["total"] == 0
    assert promoted["total"] == 1
    assert promoted["items"][0]["mistake_id"] == body["mistake_id"]
    assert detail.status_code == 200
    labels = detail.json()["labels"]
    assert labels["confirmed"] is True
    assert labels["category_id"] == "cnm_001"
    assert [concept["id"] for concept in labels["concepts"]] == [equation_id]


@pytest.mark.integration
async def test_confirm_without_primary_topic_still_promotes(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        response = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"error_cause": "calculation", "actor": "parent"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["primary_topic_id"] is None
    assert body["due_on"] is not None

    async with factory() as session:
        draft = await session.get(IngestionDraft, draft_id)
        assert draft.status == "promoted"

        mistake = await session.get(Mistake, body["mistake_id"])
        assert mistake.primary_topic_id is None
        assert mistake.status == "active"

        version = (await session.execute(select(MistakeVersion))).scalar_one()
        assert version.confirmed_by == "parent"
        assert version.confirmed_category_id is None
        assert version.suggested_category_id == "cnm_001"
        assert version.confirmed_error_cause == "calculation"

        # 无主考点仍按草稿学科排原题复习；不写任何考核 attempt
        schedule = (
            await session.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake.id
                )
            )
        ).scalar_one()
        assert schedule.due_date.isoformat() == body["due_on"]
        assert (
            await session.execute(select(func.count()).select_from(Attempt))
        ).scalar_one() == 0


@pytest.mark.integration
async def test_confirm_allows_empty_student_answer(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(
            client, [_item(student_answer="")]
        )
        response = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["already_promoted"] is False

    async with factory() as session:
        version = (await session.execute(select(MistakeVersion))).scalar_one()
        assert version.student_answer == ""
        mistake = (await session.execute(select(Mistake))).scalar_one()
        assert mistake.primary_topic_id == "cnm_001"


@pytest.mark.integration
async def test_confirm_rejects_unknown_primary_topic(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        unknown = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"primary_topic_id": "cnm_999"},
        )

    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "primary_topic_unknown"

    async with factory() as session:
        draft = await session.get(IngestionDraft, draft_id)
        assert draft.status == "draft"
        assert (
            await session.execute(select(func.count()).select_from(Mistake))
        ).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(GradingResult))
        ).scalar_one() == 0


@pytest.mark.integration
async def test_confirm_gates_missing_standard_answer_and_placeholder(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (missing_std,) = await _import_drafts(
            client, [_item(standard_answer="")]
        )
        (placeholder,) = await _import_drafts(
            client, [_item(problem_text="解方程 2x=〔?〕")]
        )
        (student_placeholder,) = await _import_drafts(
            client, [_item(student_answer="x=〔?〕")]
        )
        (fixable,) = await _import_drafts(
            client, [_item(standard_answer="〔?〕")]
        )

        missing_response = await client.post(
            f"/api/imports/drafts/{missing_std}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )
        placeholder_response = await client.post(
            f"/api/imports/drafts/{placeholder}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )
        student_placeholder_response = await client.post(
            f"/api/imports/drafts/{student_placeholder}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )
        # 卷面没有订正答案时，由核对页补填正答即视为确认值
        fixed_response = await client.post(
            f"/api/imports/drafts/{fixable}/confirm",
            json={"primary_topic_id": "cnm_001", "standard_answer": "x=2"},
        )

    assert missing_response.status_code == 422
    assert missing_response.json()["detail"]["code"] == "standard_answer_missing"
    assert placeholder_response.status_code == 422
    assert placeholder_response.json()["detail"]["code"] == "placeholder"
    assert student_placeholder_response.status_code == 422
    assert student_placeholder_response.json()["detail"]["code"] == "placeholder"
    assert fixed_response.status_code == 200, fixed_response.text
    assert fixed_response.json()["standard_answer"] == "x=2"

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(Mistake))
        ).scalar_one() == 1
        version = (await session.execute(select(MistakeVersion))).scalar_one()
        assert version.standard_answer == "x=2"


@pytest.mark.integration
async def test_confirm_rejects_concept_from_other_topic(tmp_path) -> None:
    factory = _migrated(tmp_path)
    _, numbers_id = await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        response = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={
                "primary_topic_id": "cnm_001",
                "concept_ids": [numbers_id],
            },
        )
        invalid_cause = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"primary_topic_id": "cnm_001", "error_cause": "瞎猜"},
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "concept_category_mismatch"
    assert invalid_cause.status_code == 422
    assert invalid_cause.json()["detail"]["code"] == "error_cause_invalid"


@pytest.mark.integration
async def test_confirm_is_idempotent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        first = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )
        second = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["already_promoted"] is True
    assert second.json()["mistake_id"] == first.json()["mistake_id"]

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(GradingResult))
        ).scalar_one() == 1
        assert (
            await session.execute(select(func.count()).select_from(Mistake))
        ).scalar_one() == 1
        assert (
            await session.execute(select(func.count()).select_from(ReviewSchedule))
        ).scalar_one() == 1
        grading = (await session.execute(select(GradingResult))).scalar_one()
        assert grading.current_version == 2
        assert (
            await session.execute(select(func.count()).select_from(GradingVersion))
        ).scalar_one() == 2


@pytest.mark.integration
async def test_suggested_and_confirmed_labels_are_kept_separately(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        confirmed = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={
                "primary_topic_id": "cnm_002",
                "error_cause": "careless",
                "actor": "student",
            },
        )
        detail = await client.get(
            f"/api/mistakes/{confirmed.json()['mistake_id']}"
        )

    assert confirmed.status_code == 200, confirmed.text
    body = detail.json()
    assert body["labels"]["confirmed"] is True
    assert body["labels"]["category_id"] == "cnm_002"
    assert body["labels"]["error_cause"] == "careless"
    assert body["suggestion"]["category_id"] == "cnm_001"
    assert body["suggestion"]["error_cause"] == "calculation"

    async with factory() as session:
        version = (await session.execute(select(MistakeVersion))).scalar_one()
        assert version.suggested_category_id == "cnm_001"
        assert version.confirmed_category_id == "cnm_002"
        assert version.suggested_error_cause == "calculation"
        assert version.confirmed_error_cause == "careless"
        mistake = (await session.execute(select(Mistake))).scalar_one()
        assert mistake.primary_topic_id == "cnm_002"


@pytest.mark.integration
async def test_attempts_query_filters_by_source(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    async with _client(factory) as client:
        (draft_id,) = await _import_drafts(client, [_item()])
        confirmed = await client.post(
            f"/api/imports/drafts/{draft_id}/confirm",
            json={"primary_topic_id": "cnm_001"},
        )
        mistake_id = confirmed.json()["mistake_id"]

        async with factory() as session, session.begin():
            now = datetime.now(UTC)
            quiz_event = LearningEvent(
                type="attempt_correct",
                actor="student",
                mistake_id=mistake_id,
                payload=json.dumps({"kind": "quiz"}),
                occurred_at=now,
                idempotency_key="quiz:test:1",
            )
            self_event = LearningEvent(
                type="attempt_correct",
                actor="student",
                mistake_id=mistake_id,
                payload=json.dumps({"kind": "self"}),
                occurred_at=now,
                idempotency_key="self:test:1",
            )
            session.add_all([quiz_event, self_event])
            await session.flush()
            session.add_all(
                [
                    Attempt(
                        mistake_id=mistake_id,
                        learning_event_id=quiz_event.id,
                        kind="quiz",
                        source="system_quiz",
                        answer_text="x=2",
                        is_correct=True,
                        created_at=now,
                    ),
                    Attempt(
                        mistake_id=mistake_id,
                        learning_event_id=self_event.id,
                        kind="review",
                        source="student_self",
                        answer_text=None,
                        is_correct=True,
                        created_at=now,
                    ),
                ]
            )
            await session.flush()
            session.add(
                PracticeRecord(
                    source_mistake_id=mistake_id,
                    kind="variant",
                    problem_text="解方程 3x=9",
                    student_answer="x=3",
                    is_correct=True,
                    created_at=now,
                )
            )

        quiz = await client.get("/api/attempts?source=system_quiz")
        all_attempts = await client.get("/api/attempts")
        practice = await client.get("/api/practice-records?kind=variant")

    assert quiz.status_code == 200
    assert quiz.json()["total"] == 1
    item = quiz.json()["items"][0]
    assert item["source"] == "system_quiz"
    assert item["problem_text"] == "解方程 2x=4"
    assert all_attempts.json()["total"] == 2
    assert practice.json()["total"] == 1
    assert practice.json()["items"][0]["problem_text"] == "解方程 3x=9"
