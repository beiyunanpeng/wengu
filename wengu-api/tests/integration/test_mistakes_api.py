"""P1-6 错题本集成测试：唯一写入、两级标签、派生练习表、seed/concept 查询。

模型一律 FakeGateway；这里只验证纪律与数据隔离，不验证真实模型质量。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Concept,
    ConceptAlias,
    GradingVersion,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    PhotoCapture,
    PracticeRecord,
    ProblemBankItem,
    ProblemExtraction,
    ReviewSchedule,
)
from app.providers.base import CallMeta, GradeResult
from app.services.ai_gateway import get_ai_gateway
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "mistakes.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


class FakeGradeGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.default = GradeResult(
            verdict="correct", confidence=0.9, source="ai", rationale="ok"
        )
        self.error: Exception | None = None

    async def grade(
        self,
        problem_text: str,
        student_answer: str,
        *,
        prompt: str = "",
        standard_answer: str = "",
        sample_index: int = 0,
    ) -> tuple[GradeResult, CallMeta]:
        self.calls.append(
            {
                "problem_text": problem_text,
                "student_answer": student_answer,
                "standard_answer": standard_answer,
                "sample_index": sample_index,
                "prompt": prompt,
            }
        )
        if self.error is not None:
            raise self.error
        return self.default, CallMeta(
            provider="fake",
            model="fake-v1",
            latency_ms=1,
            prompt_id="grade",
            prompt_version=1,
        )


def _client(factory: async_sessionmaker, gateway) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_extraction(
    factory: async_sessionmaker,
    *,
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str | None = "x=3",
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        capture = PhotoCapture(
            sha256=uuid4().hex,
            stored_path="pages/x.png",
            original_name="x.png",
            source="phone",
            status="sliced",
            created_at=now,
        )
        session.add(capture)
        await session.flush()
        row = ProblemExtraction(
            photo_capture_id=capture.id,
            seq=1,
            source_kind="slice",
            image_path="slices/x-01.png",
            problem_text=problem_text,
            student_answer=student_answer,
            confidence=0.9,
            problem_complete=True,
            gate_status="ready_for_grading",
            review_reasons_json="[]",
            figure_keywords_json="[]",
            prompt_id="extract_problem",
            prompt_version=1,
            provider="fake",
            model="fake-v1",
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _seed_topic(
    factory: async_sessionmaker,
    *,
    topic_id: str = "cnm_test_equation",
    name: str = "一元一次方程",
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
                chapter="一元一次方程",
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )


async def _seed_concept(
    factory: async_sessionmaker,
    *,
    name: str,
    category_id: str,
    aliases: tuple[str, ...] = (),
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = Concept(
            name=name,
            category_id=category_id,
            source="student",
            status="confirmed",
            merged_into_id=None,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        for alias in aliases:
            session.add(ConceptAlias(concept_id=row.id, alias=alias))
        await session.flush()
        return row.id


async def _seed_bank(
    factory: async_sessionmaker,
    *,
    problem_text: str = "求 1/2",
    answer: str = "1/2",
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = ProblemBankItem(
            external_id=uuid4().hex,
            subject="数学",
            problem_text=problem_text,
            answer=answer,
            acceptable_answers_json="[]",
            unordered=False,
            verify=answer,
            verify_vars_json="{}",
            verify_status="verified",
            source="test",
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _create_mistake(
    client: AsyncClient,
    factory: async_sessionmaker,
    *,
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str = "x=3",
    answer: str = "x=2",
    confirm_verdict: str | None = None,
) -> dict:
    extraction_id = await _seed_extraction(
        factory, problem_text=problem_text, student_answer=student_answer
    )
    created = await client.post(
        "/api/gradings",
        json={
            "source_kind": "problem_extraction",
            "source_id": extraction_id,
            "question_type": "objective",
            "answer": answer,
        },
    )
    assert created.status_code == 200
    grading = created.json()["grading"]
    confirmed = await client.post(
        f"/api/gradings/{grading['id']}/confirm",
        json={"base_version": 1, "verdict": confirm_verdict},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


@pytest.mark.integration
async def test_zero_input_wrong_creates_mistake_once_and_correct_voids(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )

    async with _client(factory, gateway) as client:
        body = await _create_mistake(client, factory)
        mistake_id = body["mistake_id"]
        count_after_create = await _count(factory, Mistake)
        versions_after_create = await _count(factory, MistakeVersion)

        listed = await client.get("/api/mistakes")
        detail = await client.get(f"/api/mistakes/{mistake_id}")

        again = await client.post(
            f"/api/gradings/{body['id']}/confirm",
            json={"base_version": 2},
        )
        voided = await client.post(
            f"/api/gradings/{body['id']}/appeal",
            json={"base_version": 3, "verdict": "correct"},
        )
        active_after_void = await client.get("/api/mistakes")
        voided_list = await client.get("/api/mistakes?status=voided")
        reactivated = await client.post(
            f"/api/gradings/{body['id']}/appeal",
            json={"base_version": 4, "verdict": "wrong"},
        )

    assert body["mistake_status"] == "active"
    assert body["mistake_id"] is not None
    assert count_after_create == 1
    assert versions_after_create == 1

    assert listed.status_code == 200
    listing = listed.json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["id"] == mistake_id
    assert item["problem_text"] == "一元一次方程：解方程 2x=4，注意移项"
    assert item["is_correct"] is False
    assert item["labels"]["confirmed"] is False
    assert item["labels"]["category_id"] == "cnm_test_equation"
    assert item["labels"]["category_name"] == "一元一次方程"
    assert [c["id"] for c in item["labels"]["concepts"]] == [concept_id]
    assert item["suggestion"]["category_id"] == "cnm_test_equation"

    assert detail.status_code == 200
    assert detail.json() == item

    assert again.json()["mistake_id"] == mistake_id
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, MistakeVersion) == 1  # 重复确认不追加内容版本

    assert voided.json()["mistake_status"] == "voided"
    assert active_after_void.json()["total"] == 0
    assert voided_list.json()["total"] == 1
    assert reactivated.json()["mistake_id"] == mistake_id
    assert reactivated.json()["mistake_status"] == "active"
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, ReviewSchedule) == 1  # 复活不重复排期

    async with factory() as session:
        events = (await session.scalars(select(LearningEvent).order_by(LearningEvent.id))).all()
    assert [event.type for event in events] == [
        "review_scheduled",
        "attempt_wrong",
        "attempt_wrong",
        "attempt_correct",
        "attempt_wrong",
    ]
    assert [event.mistake_id for event in events] == [
        mistake_id,
        mistake_id,
        mistake_id,
        None,
        mistake_id,
    ]


@pytest.mark.integration
async def test_ai_suggestion_alone_never_enters_mistake_book(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    gateway.default = GradeResult(
        verdict="wrong", confidence=0.9, source="ai", rationale="wrong"
    )

    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(factory)
        response = await client.post(
            "/api/gradings",
            json={
                "source_kind": "problem_extraction",
                "source_id": extraction_id,
                "question_type": "process",
                "answer": "x=2",
            },
        )
        grading = response.json()["grading"]
        mistakes = await client.get("/api/mistakes")

    assert grading["current_verdict"] == "wrong"
    assert grading["mistake_id"] is None
    assert mistakes.json()["total"] == 0
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, MistakeVersion) == 0
    assert await _count(factory, ReviewSchedule) == 0
    assert len(gateway.calls) == 1


@pytest.mark.integration
async def test_label_confirmation_optimistic_lock_and_filters(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)
    await _seed_topic(
        factory,
        topic_id="cne_test_reading",
        name="阅读理解",
        subject="英语",
    )
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )
    other_concept_id = await _seed_concept(
        factory, name="略读", category_id="cne_test_reading"
    )

    async with _client(factory, gateway) as client:
        body = await _create_mistake(client, factory)
        mistake_id = body["mistake_id"]

        labeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
                "error_cause": "calculation",
                "actor": "student",
            },
        )
        stale = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 1, "category_id": "cnm_test_equation"},
        )
        bad_cause = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "error_cause": "made_up"},
        )
        bad_category = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "category_id": "cnm_missing"},
        )
        wrong_category = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 2,
                "category_id": "cnm_test_equation",
                "concept_ids": [other_concept_id],
            },
        )
        by_category = await client.get(
            "/api/mistakes?category_id=cnm_test_equation"
        )
        by_concept = await client.get(f"/api/mistakes?concept_id={concept_id}")
        by_cause = await client.get("/api/mistakes?error_cause=calculation")
        miss = await client.get("/api/mistakes?error_cause=careless")

    assert labeled.status_code == 200, labeled.text
    labeled_body = labeled.json()
    assert labeled_body["current_version"] == 2
    assert labeled_body["labels"]["confirmed"] is True
    assert labeled_body["labels"]["confirmed_by"] == "student"
    assert labeled_body["labels"]["category_id"] == "cnm_test_equation"
    assert labeled_body["labels"]["error_cause"] == "calculation"
    assert labeled_body["labels"]["error_cause_label"] == "计算失误"
    assert [c["id"] for c in labeled_body["labels"]["concepts"]] == [concept_id]

    assert stale.status_code == 409
    assert bad_cause.status_code == 422
    assert bad_category.status_code == 422
    assert wrong_category.status_code == 422
    assert by_category.json()["total"] == 1
    assert by_concept.json()["total"] == 1
    assert by_cause.json()["total"] == 1
    assert miss.json()["total"] == 0
    assert await _count(factory, MistakeVersion) == 2

    async with factory() as session:
        events = (await session.scalars(select(LearningEvent))).all()
    labeled_events = [event for event in events if event.type == "mistake_labeled"]
    assert len(labeled_events) == 1
    assert labeled_events[0].idempotency_key == f"mistake:{mistake_id}:v2"
    assert labeled_events[0].mistake_id == mistake_id


@pytest.mark.integration
async def test_partial_label_update_preserves_other_confirmed_values(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )

    async with _client(factory, gateway) as client:
        body = await _create_mistake(client, factory)
        mistake_id = body["mistake_id"]
        await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
                "error_cause": "calculation",
            },
        )
        partial = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "error_cause": "careless"},
        )
        cleared = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 3, "concept_ids": []},
        )

    assert partial.status_code == 200, partial.text
    labels = partial.json()["labels"]
    assert labels["category_id"] == "cnm_test_equation"
    assert [c["id"] for c in labels["concepts"]] == [concept_id]
    assert labels["error_cause"] == "careless"

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["labels"]["category_id"] == "cnm_test_equation"
    assert cleared.json()["labels"]["concepts"] == []
    assert cleared.json()["labels"]["error_cause"] == "careless"
    assert await _count(factory, MistakeVersion) == 4


@pytest.mark.integration
async def test_concept_create_reuse_merge_and_historical_label_resolution(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)

    async with _client(factory, gateway) as client:
        first = await client.post(
            "/api/concepts",
            json={
                "name": "移项",
                "category_id": "cnm_test_equation",
                "aliases": ["移项法则"],
            },
        )
        reused = await client.post(
            "/api/concepts",
            json={"name": "移项法则", "category_id": "cnm_test_equation"},
        )
        target = await client.post(
            "/api/concepts",
            json={"name": "等式性质", "category_id": "cnm_test_equation"},
        )
        concept_id = first.json()["id"]
        target_id = target.json()["id"]

        body = await _create_mistake(client, factory)
        mistake_id = body["mistake_id"]
        await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
            },
        )
        merged = await client.post(
            "/api/concepts/merge",
            json={"source_id": concept_id, "target_id": target_id},
        )
        detail = await client.get(f"/api/mistakes/{mistake_id}")
        concepts = await client.get("/api/concepts?category_id=cnm_test_equation")
        q = await client.get("/api/concepts?q=法则")

    assert first.status_code == 200, first.text
    assert first.json()["reused"] is False
    assert first.json()["aliases"] == ["移项法则"]
    assert reused.status_code == 200
    assert reused.json()["id"] == concept_id
    assert reused.json()["reused"] is True

    assert merged.status_code == 200, merged.text
    assert merged.json()["source"]["merged_into_id"] == target_id
    assert merged.json()["target"]["id"] == target_id
    assert merged.json()["aliases_moved"] >= 1

    assert detail.status_code == 200
    resolved = detail.json()["labels"]["concepts"]
    assert len(resolved) == 1
    assert resolved[0]["id"] == target_id
    assert resolved[0]["name"] == "等式性质"

    ids = {item["id"] for item in concepts.json()["items"]}
    assert concept_id not in ids
    assert target_id in ids
    assert [item["id"] for item in q.json()["items"]] == [target_id]


@pytest.mark.integration
async def test_practice_records_are_isolated_and_clearable(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)
    bank_id = await _seed_bank(factory)

    async with _client(factory, gateway) as client:
        body = await _create_mistake(client, factory)
        mistake_id = body["mistake_id"]
        before = (
            await _count(factory, MistakeVersion),
            await _count(factory, LearningEvent),
            await _count(factory, GradingVersion),
        )

        variant = await client.post(
            "/api/practice-records",
            json={
                "kind": "variant",
                "source_mistake_id": mistake_id,
                "problem_bank_id": bank_id,
                "student_answer": "1/2",
                "is_correct": True,
            },
        )
        extra = await client.post(
            "/api/practice-records",
            json={
                "kind": "extra",
                "problem_text": "自选加练：3x=6",
                "student_answer": "x=2",
            },
        )
        listed = await client.get(
            f"/api/practice-records?source_mistake_id={mistake_id}"
        )
        all_rows = await client.get("/api/practice-records")
        cleared = await client.delete("/api/practice-records")
        empty = await client.get("/api/practice-records")
        detail = await client.get(f"/api/mistakes/{mistake_id}")

        missing_mistake = await client.post(
            "/api/practice-records",
            json={"kind": "extra", "source_mistake_id": 999, "problem_text": "x"},
        )
        missing_text = await client.post(
            "/api/practice-records", json={"kind": "extra"}
        )

    assert variant.status_code == 200, variant.text
    assert variant.json()["problem_text"] == "求 1/2"
    assert variant.json()["problem_bank_id"] == bank_id
    assert extra.status_code == 200
    assert extra.json()["problem_text"] == "自选加练：3x=6"

    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == variant.json()["id"]
    assert all_rows.json()["total"] == 2
    assert cleared.json()["deleted"] == 2
    assert empty.json()["total"] == 0
    assert detail.status_code == 200
    assert detail.json()["id"] == mistake_id

    after = (
        await _count(factory, MistakeVersion),
        await _count(factory, LearningEvent),
        await _count(factory, GradingVersion),
    )
    assert before == after  # 派生表不写事件、不动错题版本/批改版本

    assert missing_mistake.status_code == 404
    assert missing_text.status_code == 422
    assert await _count(factory, PracticeRecord) == 0


@pytest.mark.integration
async def test_seed_topics_query_and_mistake_options(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory,
        topic_id="cne_test_word",
        name="词汇",
        subject="英语",
    )

    async with _client(factory, FakeGradeGateway()) as client:
        all_topics = await client.get("/api/seed/topics")
        math_topics = await client.get("/api/seed/topics?subject=数学")
        search = await client.get("/api/seed/topics?q=方程")
        paged = await client.get("/api/seed/topics?limit=1&offset=1")
        options = await client.get("/api/mistakes/options")

    assert all_topics.status_code == 200, all_topics.text
    assert all_topics.json()["total"] == 2
    assert math_topics.json()["total"] == 1
    assert math_topics.json()["items"][0]["id"] == "cnm_test_equation"
    assert [item["id"] for item in search.json()["items"]] == ["cnm_test_equation"]
    assert paged.json()["total"] == 2
    assert len(paged.json()["items"]) == 1

    causes = {item["id"]: item["label"] for item in options.json()["error_causes"]}
    assert causes["prerequisite_gap"] == "前置知识缺失"
    assert causes["calculation"] == "计算失误"
    assert "other" in causes
