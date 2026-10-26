"""P1-8 讲解上下文读取与事实事件：闸门、标签解析、幂等与隐私。

不调用模型：这里只验证“看什么上下文”和“记什么事实”，模型质量另由 eval 脚本覆盖。
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
    Concept,
    ImportBatch,
    IngestionDraft,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    PhotoCapture,
    ProblemBankItem,
    ProblemExtraction,
)
from app.providers.base import CallMeta
from app.services.ai_gateway import get_ai_gateway
from app.services.explanation import (
    CONTEXT_DRAFT,
    CONTEXT_EXTRACTION,
    CONTEXT_MISTAKE,
    EXPLANATION_ATTEMPTED,
    EXPLANATION_SHOWN,
    ExplainContextNotFound,
    ExplainContextUnavailable,
    has_attempt,
    read_context,
    record_attempt,
    record_shown,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "explanation.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


class FakeGradeGateway:
    async def grade(self, *args, **kwargs):
        raise AssertionError("讲解上下文测试不应调用判分模型")


def _client(factory: async_sessionmaker) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_gateway] = lambda: FakeGradeGateway()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_topic(
    factory: async_sessionmaker,
    *,
    topic_id: str = "cnm_explain_equation",
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
    factory: async_sessionmaker, name: str, category_id: str
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


async def _seed_draft(
    factory: async_sessionmaker,
    *,
    normalized: str | dict,
    has_placeholder: bool = False,
    is_incomplete: bool = False,
) -> int:
    now = datetime.now(UTC)
    payload = normalized if isinstance(normalized, str) else json.dumps(
        normalized, ensure_ascii=False
    )
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
            normalized_json=payload,
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
    problem_text: str = "解方程 2x=4",
    answer: str = "x=2",
) -> int:
    async with factory() as session, session.begin():
        row = ProblemBankItem(
            external_id=uuid4().hex,
            subject="数学",
            problem_text=problem_text,
            answer=answer,
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
    problem_text: str = "解方程 2x=4",
    student_answer: str = "x=3",
) -> int:
    extraction_id = await _seed_extraction(
        factory, problem_text=problem_text, student_answer=student_answer
    )
    bank_id = await _seed_bank(factory, problem_text=problem_text)
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
    return int(confirmed.json()["mistake_id"])


@pytest.mark.integration
async def test_mistake_context_uses_effective_labels_and_rejects_voided(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    concept_id = await _seed_concept(factory, "移项", "cnm_explain_equation")

    async with _client(factory) as client:
        mistake_id = await _create_mistake(
            client, factory, problem_text="解方程 2x=4", student_answer="x=3"
        )
        labeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_explain_equation",
                "concept_ids": [concept_id],
                "error_cause": "calculation",
                "actor": "student",
            },
        )
        assert labeled.status_code == 200, labeled.text

    async with factory() as session:
        context = await read_context(session, CONTEXT_MISTAKE, mistake_id)

    assert context.entry == "mistake"
    assert context.problem_text == "解方程 2x=4"
    assert context.student_answer == "x=3"
    assert context.standard_answer == "x=2"
    assert context.subject == "数学"
    assert context.category_name == "一元一次方程"
    assert context.concepts == ("移项",)
    assert context.error_cause == "calculation"
    assert context.mistake_id == mistake_id
    assert context.key == f"mistake:{mistake_id}"

    async with factory() as session, session.begin():
        mistake = await session.get(Mistake, mistake_id)
        mistake.status = "voided"
    async with factory() as session:
        with pytest.raises(ExplainContextUnavailable, match="voided"):
            await read_context(session, CONTEXT_MISTAKE, mistake_id)
        with pytest.raises(ExplainContextNotFound):
            await read_context(session, CONTEXT_MISTAKE, 999)


@pytest.mark.integration
async def test_mistake_context_blocks_placeholder_and_figure_text(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        placeholder_id = await _create_mistake(
            client,
            factory,
            problem_text="解方程 〔?〕=4",
            student_answer="x=3",
        )
        figure_id = await _create_mistake(
            client,
            factory,
            problem_text="如图，求阴影面积",
            student_answer="4",
        )

    async with factory() as session:
        for mistake_id, reason in (
            (placeholder_id, "placeholder"),
            (figure_id, "figure_dependency"),
        ):
            with pytest.raises(ExplainContextUnavailable, match=reason):
                await read_context(session, CONTEXT_MISTAKE, mistake_id)


@pytest.mark.integration
async def test_extraction_context_allows_answer_gaps_but_not_problem_gaps(tmp_path) -> None:
    factory = _migrated(tmp_path)
    ready_id = await _seed_extraction(
        factory, problem_text="求 1/2 + 1/3", student_answer=None
    )
    manual_answer_id = await _seed_extraction(
        factory,
        problem_text="求 1/2 + 1/3",
        student_answer="",
        gate_status="manual_review",
        review_reasons=("student_answer_empty",),
    )
    manual_problem_id = await _seed_extraction(
        factory,
        problem_text="求 1/2 + 1/3",
        student_answer="1",
        gate_status="manual_review",
        review_reasons=("problem_incomplete",),
    )
    figure_id = await _seed_extraction(
        factory,
        problem_text="求阴影面积",
        student_answer="4",
        gate_status="figure_dependent",
        review_reasons=("figure_dependency",),
    )
    placeholder_id = await _seed_extraction(
        factory, problem_text="求 〔?〕 + 1/3", student_answer="1"
    )
    figure_text_id = await _seed_extraction(
        factory, problem_text="如下图所示，求面积", student_answer="4"
    )

    async with factory() as session:
        ready = await read_context(session, CONTEXT_EXTRACTION, ready_id)
        manual_answer = await read_context(session, CONTEXT_EXTRACTION, manual_answer_id)
        assert ready.entry == "question"
        assert ready.student_answer == ""
        assert manual_answer.student_answer == ""

        for context_id, reason in (
            (manual_problem_id, "extraction_problem_incomplete"),
            (figure_id, "figure_dependency"),
            (placeholder_id, "placeholder"),
            (figure_text_id, "figure_dependency"),
        ):
            with pytest.raises(ExplainContextUnavailable, match=reason):
                await read_context(session, CONTEXT_EXTRACTION, context_id)
        with pytest.raises(ExplainContextNotFound):
            await read_context(session, CONTEXT_EXTRACTION, 999)


@pytest.mark.integration
async def test_draft_context_parses_json_and_keeps_empty_answer(tmp_path) -> None:
    factory = _migrated(tmp_path)
    valid_id = await _seed_draft(
        factory,
        normalized={"problem_text": "求 2x=4 的解", "student_answer": "", "subject": "数学"},
        is_incomplete=True,
    )
    bad_json_id = await _seed_draft(factory, normalized="{not-json")
    missing_problem_id = await _seed_draft(factory, normalized={"student_answer": "1"})
    too_long_id = await _seed_draft(
        factory, normalized={"problem_text": "x" * 8001, "student_answer": ""}
    )

    async with factory() as session:
        context = await read_context(session, CONTEXT_DRAFT, valid_id)
        assert context.entry == "question"
        assert context.problem_text == "求 2x=4 的解"
        assert context.student_answer == ""
        assert context.subject == "数学"
        assert context.key == f"ingestion_draft:{valid_id}"

        for draft_id, reason in (
            (bad_json_id, "draft_invalid"),
            (missing_problem_id, "problem_text_empty"),
            (too_long_id, "problem_text_too_long"),
        ):
            with pytest.raises(ExplainContextUnavailable, match=reason):
                await read_context(session, CONTEXT_DRAFT, draft_id)


@pytest.mark.integration
async def test_attempt_and_shown_events_are_idempotent_and_private(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        mistake_id = await _create_mistake(
            client, factory, problem_text="解方程 2x=4", student_answer="x=3"
        )
    question_id = await _seed_extraction(factory, problem_text="求 1/2 + 1/3")

    async with factory() as session:
        mistake_context = await read_context(session, CONTEXT_MISTAKE, mistake_id)
        question_context = await read_context(session, CONTEXT_EXTRACTION, question_id)

        assert await has_attempt(session, mistake_context) is False
        assert await has_attempt(session, question_context) is False

        first, created = await record_attempt(
            session, mistake_context, attempt_id="a-1", mode="guide", hint_level=1
        )
        await session.commit()
        repeat, created_again = await record_attempt(
            session, mistake_context, attempt_id="a-1", mode="guide", hint_level=2
        )
        await session.commit()

        assert created is True
        assert created_again is False
        assert repeat.id == first.id
        assert await has_attempt(session, mistake_context) is True

        meta = CallMeta(
            provider="mock",
            model="mock-vision",
            latency_ms=1,
            prompt_id="explain_guide",
            prompt_version=1,
            raw={"cache_hit": True},
        )
        shown, shown_created = await record_shown(
            session,
            mistake_context,
            request_id="r-1",
            mode="full",
            requested_mode="full",
            default_mode="guide",
            strategy="method_hint",
            hint_level=None,
            attempted=True,
            soft_gate=False,
            answer_shown=True,
            leak_flags=("answer_phrase_masked",),
            meta=meta,
        )
        await session.commit()
        shown_repeat, shown_again = await record_shown(
            session,
            mistake_context,
            request_id="r-1",
            mode="full",
            requested_mode="full",
            default_mode="guide",
            strategy="method_hint",
            hint_level=None,
            attempted=True,
            soft_gate=False,
            answer_shown=True,
            leak_flags=(),
            meta=meta,
        )
        await session.commit()

        assert shown_created is True
        assert shown_again is False
        assert shown_repeat.id == shown.id

        with pytest.raises(ValueError, match="guide/full"):
            await record_attempt(
                session, mistake_context, attempt_id="a-2", mode="auto", hint_level=1
            )
        with pytest.raises(ValueError, match="1–3"):
            await record_attempt(
                session, mistake_context, attempt_id="a-2", mode="guide", hint_level=0
            )

    events = []
    async with factory() as session:
        rows = (
            await session.scalars(select(LearningEvent).order_by(LearningEvent.id))
        ).all()
        events = [
            row for row in rows if row.type in (EXPLANATION_ATTEMPTED, EXPLANATION_SHOWN)
        ]
        assert [row.id for row in events] == [first.id, shown.id]

    attempt_payload = json.loads(events[0].payload or "{}")
    shown_payload = json.loads(events[1].payload or "{}")
    assert events[0].type == EXPLANATION_ATTEMPTED
    assert events[0].mistake_id == mistake_id
    assert events[0].idempotency_key == f"explanation:attempt:mistake:{mistake_id}:a-1"
    assert attempt_payload == {
        "context_kind": "mistake",
        "context_id": mistake_id,
        "mode": "guide",
        "hint_level": 1,
    }
    assert shown_payload["cache_hit"] is True
    assert shown_payload["prompt_id"] == "explain_guide"
    assert shown_payload["prompt_version"] == 1
    assert shown_payload["answer_shown"] is True
    assert shown_payload["leak_flags"] == ["answer_phrase_masked"]

    dumped = json.dumps([attempt_payload, shown_payload], ensure_ascii=False)
    for secret in ("解方程", "2x=4", "x=3", "x=2", "求 1/2"):
        assert secret not in dumped
    async with factory() as session:
        explanation_count = await session.scalar(
            select(func.count())
            .select_from(LearningEvent)
            .where(
                LearningEvent.type.in_((EXPLANATION_ATTEMPTED, EXPLANATION_SHOWN))
            )
        )
    assert explanation_count == 2
