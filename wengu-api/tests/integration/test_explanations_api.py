"""P1-8 讲解 API：模式选择、软闸门、质量/泄漏闸门、错误映射与事实写入。"""

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
    ImportBatch,
    IngestionDraft,
    KnowledgeSeed,
    LearningEvent,
    PhotoCapture,
    ProblemBankItem,
    ProblemExtraction,
)
from app.prompts.loader import PromptError
from app.providers.base import CallMeta, Explanation
from app.services.ai_gateway import get_ai_gateway
from app.services.explanation import (
    EXPLANATION_ATTEMPTED,
    EXPLANATION_SHOWN,
    SAFE_CONSOLIDATION,
    SAFE_STEP,
)
from app.services.model_audit import DailyLimitExceeded
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "explanations.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


class FakeExplanationGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.result = _full_result()
        self.error: Exception | None = None

    async def solve_explain(
        self,
        problem_text: str,
        *,
        prompt_id: str = "explain_guide",
        hint_level: int = 0,
        extra_values: dict[str, str] | None = None,
    ) -> tuple[Explanation, CallMeta]:
        self.calls.append(
            {
                "problem_text": problem_text,
                "prompt_id": prompt_id,
                "hint_level": hint_level,
                "extra_values": dict(extra_values or {}),
            }
        )
        if self.error is not None:
            raise self.error
        meta = CallMeta(
            provider="fake",
            model="fake-v1",
            latency_ms=7,
            prompt_id=prompt_id,
            prompt_version=1,
            raw={"cache_hit": False},
        )
        return self.result, meta


def _full_result() -> Explanation:
    return Explanation(
        focus="先看清楚要求解什么",
        steps=("把含未知数的项留在一侧", "两边同时除以 2，得到结果"),
        consolidation="把结果代回原方程检查",
        answer="x=2",
        hint_level=0,
    )


def _client(factory: async_sessionmaker, gateway) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_topic(factory: async_sessionmaker) -> None:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id="cnm_explain_equation",
                subject="数学",
                name="一元一次方程",
                domain="数与代数",
                grade="七年级",
                semester="上册",
                chapter="一元一次方程",
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )


async def _seed_extraction(
    factory: async_sessionmaker,
    *,
    problem_text: str = "解方程 2x=4",
    student_answer: str | None = "x=3",
    gate_status: str = "ready_for_grading",
    review_reasons: tuple[str, ...] = (),
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
            review_reasons_json=json.dumps(list(review_reasons)),
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


async def _seed_draft(factory: async_sessionmaker) -> int:
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
                {"problem_text": "求 2x=4 的解", "student_answer": "", "subject": "数学"},
                ensure_ascii=False,
            ),
            has_placeholder=False,
            is_incomplete=True,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _seed_bank(factory: async_sessionmaker) -> int:
    async with factory() as session, session.begin():
        row = ProblemBankItem(
            external_id=uuid4().hex,
            subject="数学",
            problem_text="解方程 2x=4",
            answer="x=2",
            acceptable_answers_json="[]",
            unordered=False,
            verify="2",
            verify_vars_json="{}",
            verify_status="verified",
            source="test",
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _create_mistake(
    client: AsyncClient,
    factory: async_sessionmaker,
    *,
    error_cause: str = "method_missing",
) -> int:
    extraction_id = await _seed_extraction(factory)
    bank_id = await _seed_bank(factory)
    created = await client.post(
        "/api/gradings",
        json={
            "source_kind": "problem_extraction",
            "source_id": extraction_id,
            "question_type": "objective",
            "problem_bank_id": bank_id,
        },
    )
    assert created.status_code == 200, created.text
    grading = created.json()["grading"]
    confirmed = await client.post(
        f"/api/gradings/{grading['id']}/confirm",
        json={"base_version": 1, "verdict": "wrong"},
    )
    assert confirmed.status_code == 200, confirmed.text
    mistake_id = int(confirmed.json()["mistake_id"])
    labeled = await client.post(
        f"/api/mistakes/{mistake_id}/labels",
        json={
            "base_version": 1,
            "category_id": "cnm_explain_equation",
            "error_cause": error_cause,
            "actor": "student",
        },
    )
    assert labeled.status_code == 200, labeled.text
    return mistake_id


async def _events(factory: async_sessionmaker) -> list[LearningEvent]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(LearningEvent)
                    .where(
                        LearningEvent.type.in_(
                            (EXPLANATION_ATTEMPTED, EXPLANATION_SHOWN)
                        )
                    )
                    .order_by(LearningEvent.id)
                )
            ).all()
        )


@pytest.mark.integration
async def test_guide_default_masks_standard_answer_and_drops_answer_field(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    gateway = FakeExplanationGateway()
    gateway.result = Explanation(
        focus="先看题目条件",
        steps=("两边同时除以 2", "所以答案是 x=2"),
        consolidation="把答案 x=2 代回检查",
        answer="x=2",
        hint_level=1,
    )

    async with _client(factory, gateway) as client:
        mistake_id = await _create_mistake(client, factory)
        response = await client.post(
            "/api/explanations",
            json={
                "source_kind": "mistake",
                "source_id": mistake_id,
                "request_id": "req-guide",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entry"] == "mistake"
    assert body["mode"] == "guide"
    assert body["default_mode"] == "guide"
    assert body["strategy"] == "method_hint"
    assert body["strategy_label"] == "给方法"
    assert body["hint_level"] == 1
    assert body["next_hint_level"] == 2
    assert body["attempted"] is False
    assert body["soft_gate"] is False
    assert body["answer_shown"] is False
    assert body["explanation"]["answer"] is None
    assert body["explanation"]["steps"] == ["两边同时除以 2", SAFE_STEP]
    assert body["explanation"]["consolidation"] == SAFE_CONSOLIDATION
    assert "answer_field_dropped" in body["leak_flags"]
    assert "standard_answer_masked" in body["leak_flags"]

    call = gateway.calls[0]
    assert call["prompt_id"] == "explain_guide"
    assert call["hint_level"] == 1
    assert call["extra_values"]["CONTEXT_LABEL"] == "错题订正"
    assert call["extra_values"]["ERROR_CAUSE"] == "方法不会"
    assert call["extra_values"]["STRATEGY"] == "给方法"
    assert call["extra_values"]["ATTEMPTED"] == "否"
    assert call["extra_values"]["STANDARD_ANSWER"] == "x=2"
    assert "PROBLEM_TEXT" not in call["extra_values"]

    events = await _events(factory)
    assert [event.type for event in events] == [EXPLANATION_SHOWN]
    payload = json.loads(events[0].payload or "{}")
    assert payload["mode"] == "guide"
    assert payload["answer_shown"] is False
    assert payload["attempted"] is False
    assert payload["prompt_id"] == "explain_guide"
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "2x=4" not in dumped
    assert "x=3" not in dumped


@pytest.mark.integration
async def test_full_is_soft_gated_without_attempt_and_unlocks_after_attempt(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    gateway = FakeExplanationGateway()

    async with _client(factory, gateway) as client:
        mistake_id = await _create_mistake(client, factory)
        first = await client.post(
            "/api/explanations",
            json={
                "source_kind": "mistake",
                "source_id": mistake_id,
                "mode": "full",
                "request_id": "req-full-1",
            },
        )
        attempt = await client.post(
            "/api/explanations/attempts",
            json={
                "source_kind": "mistake",
                "source_id": mistake_id,
                "attempt_id": "try-1",
                "mode": "guide",
                "hint_level": 2,
            },
        )
        repeat_attempt = await client.post(
            "/api/explanations/attempts",
            json={
                "source_kind": "mistake",
                "source_id": mistake_id,
                "attempt_id": "try-1",
                "mode": "guide",
                "hint_level": 2,
            },
        )
        second = await client.post(
            "/api/explanations",
            json={
                "source_kind": "mistake",
                "source_id": mistake_id,
                "mode": "full",
                "request_id": "req-full-2",
            },
        )

    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["mode"] == "full"
    assert first_body["default_mode"] == "guide"
    assert first_body["soft_gate"] is True
    assert first_body["attempted"] is False
    assert first_body["answer_shown"] is True
    assert first_body["explanation"]["answer"] == "x=2"
    assert gateway.calls[0]["prompt_id"] == "explain_full"
    assert gateway.calls[0]["hint_level"] == 0

    assert attempt.status_code == 200, attempt.text
    assert attempt.json()["recorded"] is True
    assert attempt.json()["attempted"] is True
    assert repeat_attempt.json()["recorded"] is False
    assert repeat_attempt.json()["attempted"] is True

    assert second.status_code == 200, second.text
    assert second.json()["soft_gate"] is False
    assert second.json()["attempted"] is True
    assert len(gateway.calls) == 2

    events = await _events(factory)
    assert [event.type for event in events] == [
        EXPLANATION_SHOWN,
        EXPLANATION_ATTEMPTED,
        EXPLANATION_SHOWN,
    ]
    first_payload = json.loads(events[0].payload or "{}")
    attempt_payload = json.loads(events[1].payload or "{}")
    assert first_payload["soft_gate"] is True
    assert first_payload["attempted"] is False
    assert attempt_payload["hint_level"] == 2
    assert events[1].idempotency_key == f"explanation:attempt:mistake:{mistake_id}:try-1"
    assert "2x=4" not in json.dumps(first_payload, ensure_ascii=False)


@pytest.mark.integration
async def test_question_entry_reuses_engine_for_open_grading_and_drafts(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeExplanationGateway()
    extraction_id = await _seed_extraction(
        factory, problem_text="求 2x=4 的解", student_answer=""
    )
    draft_id = await _seed_draft(factory)

    async with _client(factory, gateway) as client:
        open_route = await client.post(
            "/api/gradings",
            json={
                "source_kind": "problem_extraction",
                "source_id": extraction_id,
                "question_type": "open",
            },
        )
        question = await client.post(
            "/api/explanations",
            json={
                "source_kind": "problem_extraction",
                "source_id": extraction_id,
                "request_id": "req-question",
            },
        )
        draft = await client.post(
            "/api/explanations",
            json={
                "source_kind": "ingestion_draft",
                "source_id": draft_id,
                "request_id": "req-draft",
            },
        )
        question_attempt = await client.post(
            "/api/explanations/attempts",
            json={
                "source_kind": "problem_extraction",
                "source_id": extraction_id,
                "attempt_id": "q-1",
                "hint_level": 1,
            },
        )

    assert open_route.status_code == 200, open_route.text
    assert open_route.json() == {"route": "explanation", "duplicate": False, "grading": None}

    assert question.status_code == 200, question.text
    question_body = question.json()
    assert question_body["entry"] == "question"
    assert question_body["mode"] == "full"
    assert question_body["default_mode"] == "full"
    assert question_body["strategy"] == "general_solve"
    assert question_body["soft_gate"] is False
    assert question_body["attempted"] is False
    assert question_body["answer_shown"] is True
    assert gateway.calls[0]["prompt_id"] == "explain_full"
    assert gateway.calls[0]["extra_values"]["CONTEXT_LABEL"] == "拍照答疑"
    assert gateway.calls[0]["extra_values"]["STUDENT_ANSWER"] == "（未提供）"

    assert draft.status_code == 200, draft.text
    assert draft.json()["entry"] == "question"
    assert draft.json()["mode"] == "full"
    assert gateway.calls[1]["problem_text"] == "求 2x=4 的解"

    assert question_attempt.status_code == 422
    assert question_attempt.json()["detail"]["reason"] == "attempt_not_required"


@pytest.mark.integration
async def test_error_mapping_and_no_event_on_failure(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeExplanationGateway()

    async with _client(factory, gateway) as client:
        missing = await client.post(
            "/api/explanations", json={"source_kind": "mistake", "source_id": 999}
        )
        figure_id = await _seed_extraction(
            factory,
            problem_text="求阴影面积",
            student_answer="4",
            gate_status="figure_dependent",
            review_reasons=("figure_dependency",),
        )
        blocked = await client.post(
            "/api/explanations",
            json={"source_kind": "problem_extraction", "source_id": figure_id},
        )
        bad_hint = await client.post(
            "/api/explanations",
            json={"source_kind": "problem_extraction", "source_id": figure_id, "hint_level": 4},
        )
        bad_mode = await client.post(
            "/api/explanations",
            json={"source_kind": "figure", "source_id": 1},
        )

    assert missing.status_code == 404
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["reason"] == "figure_dependency"
    assert bad_hint.status_code == 422
    assert bad_mode.status_code == 422
    assert gateway.calls == []
    assert await _events(factory) == []


@pytest.mark.integration
async def test_model_and_quality_failures_map_without_writing_shown_event(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeExplanationGateway()
    extraction_id = await _seed_extraction(factory, problem_text="求 2x=4 的解")

    async with _client(factory, gateway) as client:
        gateway.error = PromptError("missing")
        unconfigured = await client.post(
            "/api/explanations",
            json={"source_kind": "problem_extraction", "source_id": extraction_id},
        )
        gateway.error = DailyLimitExceeded("当日模型调用已达上限")
        limited = await client.post(
            "/api/explanations",
            json={"source_kind": "problem_extraction", "source_id": extraction_id},
        )
        gateway.error = RuntimeError("upstream down")
        failed = await client.post(
            "/api/explanations",
            json={"source_kind": "problem_extraction", "source_id": extraction_id},
        )
        gateway.error = None
        gateway.result = Explanation(focus="", steps=(), consolidation="", answer=None)
        low_quality = await client.post(
            "/api/explanations",
            json={"source_kind": "problem_extraction", "source_id": extraction_id},
        )

    assert unconfigured.status_code == 503
    assert limited.status_code == 429
    assert failed.status_code == 502
    assert low_quality.status_code == 502
    reasons = low_quality.json()["detail"]["reasons"]
    assert "focus_empty" in reasons
    assert "steps_empty" in reasons
    assert "answer_missing" in reasons
    assert await _events(factory) == []
