"""P1-5 判分 API 集成测试：闸门、客观确定性判、过程转人工、确认/申诉、幂等。

v2.5：过程题不在系统内判、不调模型；FakeGateway 仅保留作"绝不被调用"的探针。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    GradingResult,
    GradingVersion,
    ImportBatch,
    IngestionDraft,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    PhotoCapture,
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
    db_path = tmp_path / "grading.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


class FakeGradeGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.outcomes: dict[int, GradeResult] = {}
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
        result = self.outcomes.get(sample_index, self.default)
        return result, CallMeta(
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
    problem_text: str = "1+1=?",
    student_answer: str | None = "2",
    gate_status: str = "ready_for_grading",
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
            gate_status=gate_status,
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


async def _seed_draft(
    factory: async_sessionmaker,
    *,
    problem_text: str = "3+4=?",
    student_answer: str | None = "7",
    has_placeholder: bool = False,
    is_incomplete: bool = False,
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        batch = ImportBatch(
            channel="doubao_json",
            sha256=uuid4().hex,
            filename="d.json",
            item_count=1,
            status="imported",
            created_at=now,
        )
        session.add(batch)
        await session.flush()
        row = IngestionDraft(
            import_batch_id=batch.id,
            seq=0,
            normalized_json=json.dumps(
                {
                    "problem_text": problem_text,
                    "student_answer": student_answer or "",
                    "subject": "数学",
                },
                ensure_ascii=False,
            ),
            has_placeholder=has_placeholder,
            is_incomplete=is_incomplete,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _seed_bank(
    factory: async_sessionmaker,
    *,
    external_id: str | None = None,
    answer: str = "1/2",
    acceptable: tuple[str, ...] = ("0.5",),
    unordered: bool = False,
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = ProblemBankItem(
            external_id=external_id or uuid4().hex,
            subject="数学",
            problem_text="求 1/2",
            answer=answer,
            acceptable_answers_json=json.dumps(list(acceptable), ensure_ascii=False),
            unordered=unordered,
            verify="1/2",
            verify_vars_json="{}",
            verify_status="verified",
            source="test",
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _seed_category(
    factory: async_sessionmaker,
    category_id: str = "cnm_test_add",
    *,
    name: str = "测试加法",
    subject: str = "数学",
) -> str:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=category_id,
                subject=subject,
                name=name,
                unaudited=True,
                blind_verified=False,
            )
        )
    return category_id


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


def _request(
    source_id: int,
    *,
    question_type: str = "objective",
    source_kind: str = "problem_extraction",
    **extra,
) -> dict:
    return {
        "source_kind": source_kind,
        "source_id": source_id,
        "question_type": question_type,
        **extra,
    }


@pytest.mark.integration
async def test_objective_is_deterministic_and_get_is_query_only(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(
            factory, problem_text="1/2 + 1/2 = ?", student_answer="1"
        )
        response = await client.post(
            "/api/gradings",
            json=_request(extraction_id, answer="100%"),
        )
        get_response = await client.get(f"/api/gradings/{response.json()['grading']['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "grading"
    assert body["duplicate"] is False
    grading = body["grading"]
    assert grading["current_verdict"] == "correct"
    assert grading["status"] == "pending"  # Phase 0：未确认前不自动入本
    assert grading["standard_answer"] == "100%"
    assert grading["problem_text"] == "1/2 + 1/2 = ?"
    assert grading["student_answer"] == "1"
    assert grading["versions"][0]["source"] == "code"
    assert grading["versions"][0]["action"] == "suggested"
    assert grading["versions"][0]["reason"] == "numeric_equal"
    assert gateway.calls == []  # 客观题零模型调用

    calls_after_post = len(gateway.calls)
    assert get_response.status_code == 200
    assert get_response.json() == grading
    assert len(gateway.calls) == calls_after_post


@pytest.mark.integration
async def test_objective_uses_acceptable_aliases(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(factory, student_answer="50%")
        bank_id = await _seed_bank(factory, answer="二分之一", acceptable=("1/2",))
        bank = await client.post(
            "/api/gradings",
            json=_request(extraction_id, problem_bank_id=bank_id),
        )
        second_id = await _seed_extraction(factory, student_answer="50%")
        explicit = await client.post(
            "/api/gradings",
            json=_request(
                second_id, answer="二分之一", acceptable=["1/2"]
            ),
        )

    assert bank.status_code == 200
    assert bank.json()["grading"]["current_verdict"] == "correct"
    assert bank.json()["grading"]["problem_bank_id"] == bank_id
    assert bank.json()["grading"]["acceptable_answers"] == ["1/2"]
    assert explicit.json()["grading"]["current_verdict"] == "correct"
    assert gateway.calls == []


@pytest.mark.integration
async def test_missing_reference_and_gate_fall_to_manual(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        no_reference = await _seed_extraction(factory)
        missing = await client.post(
            "/api/gradings", json=_request(no_reference)
        )

        gated = await _seed_extraction(
            factory, gate_status="manual_review", problem_text="2. 求 x"
        )
        gate = await client.post(
            "/api/gradings",
            json=_request(gated, question_type="process", answer="x=2"),
        )

    assert missing.status_code == 200
    missing_grading = missing.json()["grading"]
    assert missing_grading["current_verdict"] == "uncertain"
    assert missing_grading["versions"][0]["reason"] == "reference_missing"
    assert missing_grading["standard_answer"] is None
    assert gate.json()["grading"]["versions"][0]["reason"] == "extraction_gate:manual_review"
    assert gateway.calls == []  # 闸门未过/缺答案：连过程题也不调模型


@pytest.mark.integration
async def test_placeholder_and_empty_answer_never_enter_grading(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        placeholder_id = await _seed_draft(
            factory, student_answer="〔?〕", has_placeholder=True
        )
        placeholder = await client.post(
            "/api/gradings",
            json=_request(
                placeholder_id,
                source_kind="ingestion_draft",
                answer="7",
            ),
        )
        empty_id = await _seed_draft(factory, student_answer=None, is_incomplete=True)
        empty = await client.post(
            "/api/gradings",
            json=_request(empty_id, source_kind="ingestion_draft", answer="7"),
        )

    assert placeholder.json()["grading"]["versions"][0]["reason"] == "placeholder"
    assert empty.json()["grading"]["versions"][0]["reason"] == "student_answer_empty"
    assert gateway.calls == []


@pytest.mark.integration
async def test_process_question_is_manual_and_never_calls_model(tmp_path) -> None:
    """v2.5：过程题真实作业在卷面外部批改；系统内只落 uncertain 待确认。"""

    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(
            factory, problem_text="解方程 2x=4", student_answer="x=2"
        )
        response = await client.post(
            "/api/gradings",
            json=_request(extraction_id, question_type="process", answer="x=2"),
        )
        grading_id = response.json()["grading"]["id"]
        fetched = await client.get(f"/api/gradings/{grading_id}")

    assert response.status_code == 200
    grading = response.json()["grading"]
    assert grading["current_verdict"] == "uncertain"
    assert grading["status"] == "pending"
    version = grading["versions"][0]
    assert version["source"] == "code"
    assert version["reason"] == "real_homework_external"
    assert version["sample_verdicts"] == []
    assert version["provider"] is None
    assert gateway.calls == []  # 过程题零模型调用
    assert fetched.json() == grading


@pytest.mark.integration
async def test_open_question_routes_to_explanation_without_persisting(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(factory)
        response = await client.post(
            "/api/gradings",
            json=_request(extraction_id, question_type="open"),
        )

    assert response.status_code == 200
    assert response.json() == {"route": "explanation", "duplicate": False, "grading": None}
    assert await _count(factory, GradingResult) == 0
    assert gateway.calls == []


@pytest.mark.integration
async def test_confirm_appends_version_and_event_once(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(factory)
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="2"))
        ).json()["grading"]
        confirmed = await client.post(
            f"/api/gradings/{created['id']}/confirm", json={"base_version": 1}
        )
        stale = await client.post(
            f"/api/gradings/{created['id']}/confirm", json={"base_version": 1}
        )

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["current_version"] == 2
    assert body["current_verdict"] == "correct"
    assert body["versions"][1]["action"] == "confirmed"
    assert body["versions"][1]["source"] == "student"
    assert stale.status_code == 409  # 旧 base_version 不能重复计数
    assert await _count(factory, GradingVersion) == 2
    assert await _count(factory, LearningEvent) == 1

    async with factory() as session:
        event = (await session.scalars(select(LearningEvent))).one()
    assert event.type == "attempt_correct"
    assert event.idempotency_key == f"grading:{created['id']}:v2"
    assert json.loads(event.payload)["grading_version"] == 2


@pytest.mark.integration
async def test_appeal_supersedes_previous_verdict(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    bank_id = await _seed_bank(factory, answer="2", acceptable=("2",))
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(factory, student_answer="2")
        created = (
            await client.post(
                "/api/gradings",
                json=_request(extraction_id, problem_bank_id=bank_id),
            )
        ).json()["grading"]
        await client.post(
            f"/api/gradings/{created['id']}/confirm", json={"base_version": 1}
        )
        appealed = await client.post(
            f"/api/gradings/{created['id']}/appeal",
            json={"base_version": 2, "verdict": "wrong", "reason": "标准答案有误"},
        )

    assert appealed.status_code == 200
    body = appealed.json()
    assert body["status"] == "appealed"
    assert body["current_version"] == 3
    assert body["current_verdict"] == "wrong"
    assert body["versions"][2]["action"] == "appealed"
    assert body["versions"][2]["reason"] == "标准答案有误"
    assert await _count(factory, LearningEvent) == 3
    assert await _count(factory, ReviewSchedule) == 1

    async with factory() as session:
        events = (
            await session.scalars(select(LearningEvent).order_by(LearningEvent.id))
        ).all()
    assert [e.type for e in events] == [
        "attempt_correct",
        "review_scheduled",
        "attempt_wrong",
    ]
    assert [e.idempotency_key for e in events] == [
        f"grading:{created['id']}:v2",
        f"review:schedule:{body['mistake_id']}:init",
        f"grading:{created['id']}:v3",
    ]


@pytest.mark.integration
async def test_create_is_idempotent_per_source(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(factory)
        first = await client.post(
            "/api/gradings", json=_request(extraction_id, answer="2")
        )
        second = await client.post(
            "/api/gradings", json=_request(extraction_id, answer="2")
        )

    assert first.json()["grading"]["id"] == second.json()["grading"]["id"]
    assert second.json()["duplicate"] is True
    assert await _count(factory, GradingResult) == 1
    assert await _count(factory, GradingVersion) == 1
    assert gateway.calls == []


@pytest.mark.integration
async def test_unknown_sources_return_404(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory, FakeGradeGateway()) as client:
        post = await client.post("/api/gradings", json=_request(999, answer="2"))
        get = await client.get("/api/gradings/999")
        missing_bank = await client.post(
            "/api/gradings", json=_request(999, problem_bank_id=999)
        )

    assert post.status_code == 404
    assert get.status_code == 404
    assert missing_bank.status_code == 404


@pytest.mark.integration
async def test_confirm_wrong_with_category_creates_mistake_and_schedule(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        category_id = await _seed_category(factory)
        extraction_id = await _seed_extraction(
            factory, problem_text="3+4=?", student_answer="7"
        )
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="8"))
        ).json()["grading"]
        assert created["current_verdict"] == "wrong"

        confirmed = await client.post(
            f"/api/gradings/{created['id']}/confirm",
            json={
                "base_version": 1,
                "verdict": "wrong",
                "category_id": category_id,
            },
        )
        mistake_id = confirmed.json()["mistake_id"]
        detail = await client.get(f"/api/mistakes/{mistake_id}")
        async with factory() as session:
            schedule = (await session.scalars(select(ReviewSchedule))).one()
        due = await client.get(
            "/api/reviews/due", params={"today": schedule.due_date.isoformat()}
        )

    assert confirmed.status_code == 200
    assert detail.status_code == 200
    labels = detail.json()["labels"]
    assert labels["confirmed"] is True
    assert labels["category_id"] == category_id
    assert labels["confirmed_by"] == "student"
    assert detail.json()["suggestion"]["category_id"] is None
    assert due.json()["total"] == 1
    assert due.json()["items"][0]["mistake_id"] == mistake_id
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, ReviewSchedule) == 1

    async with factory() as session:
        events = (
            await session.scalars(select(LearningEvent).order_by(LearningEvent.id))
        ).all()
    assert [event.type for event in events] == ["review_scheduled", "attempt_wrong"]


@pytest.mark.integration
async def test_confirm_wrong_with_unknown_category_rolls_back(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(
            factory, problem_text="3+4=?", student_answer="7"
        )
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="8"))
        ).json()["grading"]
        rejected = await client.post(
            f"/api/gradings/{created['id']}/confirm",
            json={
                "base_version": 1,
                "verdict": "wrong",
                "category_id": "cnm_missing",
            },
        )
        fetched = await client.get(f"/api/gradings/{created['id']}")

    assert rejected.status_code == 422
    assert fetched.json()["current_version"] == 1
    assert fetched.json()["status"] == "pending"
    assert fetched.json()["mistake_id"] is None
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, ReviewSchedule) == 0
    assert await _count(factory, LearningEvent) == 0


@pytest.mark.integration
async def test_confirm_wrong_without_category_and_subject_rolls_back(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(
            factory, problem_text="3+4=?", student_answer="7"
        )
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="8"))
        ).json()["grading"]
        rejected = await client.post(
            f"/api/gradings/{created['id']}/confirm",
            json={"base_version": 1, "verdict": "wrong"},
        )

    assert rejected.status_code == 422
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, ReviewSchedule) == 0
    assert await _count(factory, LearningEvent) == 0


@pytest.mark.integration
async def test_confirm_correct_ignores_category(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        category_id = await _seed_category(factory)
        extraction_id = await _seed_extraction(factory)
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="2"))
        ).json()["grading"]
        confirmed = await client.post(
            f"/api/gradings/{created['id']}/confirm",
            json={
                "base_version": 1,
                "verdict": "correct",
                "category_id": category_id,
            },
        )

    assert confirmed.status_code == 200
    assert confirmed.json()["mistake_id"] is None
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, ReviewSchedule) == 0


@pytest.mark.integration
async def test_appeal_wrong_with_category_creates_schedule(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        category_id = await _seed_category(factory)
        extraction_id = await _seed_extraction(factory)
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="2"))
        ).json()["grading"]
        appealed = await client.post(
            f"/api/gradings/{created['id']}/appeal",
            json={
                "base_version": 1,
                "verdict": "wrong",
                "reason": "自判改判",
                "category_id": category_id,
            },
        )
        mistake_id = appealed.json()["mistake_id"]
        detail = await client.get(f"/api/mistakes/{mistake_id}")

    assert appealed.status_code == 200
    assert detail.json()["labels"]["category_id"] == category_id
    assert await _count(factory, ReviewSchedule) == 1


@pytest.mark.integration
async def test_existing_mistake_keeps_confirmed_category(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    async with _client(factory, gateway) as client:
        first_category = await _seed_category(factory)
        second_category = await _seed_category(
            factory, "cnm_test_other", name="测试减法"
        )
        extraction_id = await _seed_extraction(
            factory, problem_text="3+4=?", student_answer="7"
        )
        created = (
            await client.post("/api/gradings", json=_request(extraction_id, answer="8"))
        ).json()["grading"]
        confirmed = await client.post(
            f"/api/gradings/{created['id']}/confirm",
            json={
                "base_version": 1,
                "verdict": "wrong",
                "category_id": first_category,
            },
        )
        mistake_id = confirmed.json()["mistake_id"]
        await client.post(
            f"/api/gradings/{created['id']}/appeal",
            json={
                "base_version": 2,
                "verdict": "wrong",
                "reason": "再次申诉",
                "category_id": second_category,
            },
        )
        detail = await client.get(f"/api/mistakes/{mistake_id}")

    assert detail.json()["labels"]["category_id"] == first_category
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, ReviewSchedule) == 1
