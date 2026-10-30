"""P1-5 批改单持久化与确认/申诉版本服务（v2.5：真实题在系统外判）。

纪律（AGENTS §5 / 设计文档 §16）：
- 本模块只做"核对页确认入本"的落库与版本追加，不做任何判分/模型调用；
  系统自造同类题考核的判分在 `services/quiz.py` 走 `judge_answer`。
- 建议值与确认值分离：grading_results 存逻辑单，grading_versions 只追加，
  确认写 learning_events（幂等键含 grading_id + version）。
- 新批改单 status=pending，不自动建错题/排复习（入本一律经核对页确认）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GradingResult, GradingVersion
from app.models.grading import (
    STATUS_APPEALED,
    STATUS_CONFIRMED,
    STATUS_PENDING,
)
from app.services.events import record_event
from app.services.mistakes import sync_mistake_for_verdict
from app.services.recompute import ATTEMPT_CORRECT, ATTEMPT_WRONG

QuestionType = Literal["objective", "process"]
UserVerdict = Literal["correct", "wrong"]


@dataclass(frozen=True)
class SourceProblem:
    source_kind: str
    source_id: int
    problem_text: str
    student_answer: str | None
    ready: bool
    manual_reason: str | None = None


@dataclass(frozen=True)
class Suggestion:
    verdict: str
    source: str
    confidence: float | None
    reason: str
    provider: str | None = None
    model: str | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None


@dataclass(frozen=True)
class ConfirmationDetails:
    """转录草稿转正时随确认一起提交的字段（正常批改确认不用）。"""

    standard_answer: str | None = None
    primary_topic_id: str | None = None
    suggested_category_id: str | None = None
    suggested_concept_ids: tuple[int, ...] | None = None
    suggested_error_cause: str | None = None
    confirmed_concept_ids: tuple[int, ...] = ()
    confirmed_error_cause: str | None = None
    review_subject: str | None = None


async def get_by_source(
    session: AsyncSession, source_kind: str, source_id: int
) -> GradingResult | None:
    return (
        await session.execute(
            select(GradingResult).where(
                GradingResult.source_kind == source_kind,
                GradingResult.source_id == source_id,
            )
        )
    ).scalar_one_or_none()


async def get_versions(session: AsyncSession, grading_id: int) -> list[GradingVersion]:
    rows = (
        await session.execute(
            select(GradingVersion)
            .where(GradingVersion.grading_id == grading_id)
            .order_by(GradingVersion.version)
        )
    ).scalars().all()
    return list(rows)


async def persist_grading(
    session: AsyncSession,
    *,
    source: SourceProblem,
    question_type: QuestionType,
    suggestion: Suggestion,
) -> tuple[GradingResult, bool]:
    """幂等落库：同源已存在则返回旧单；竞态由 UNIQUE 兜底。"""

    existing = await get_by_source(session, source.source_kind, source.source_id)
    if existing is not None:
        return existing, False

    now = datetime.now(UTC)
    root = GradingResult(
        source_kind=source.source_kind,
        source_id=source.source_id,
        problem_bank_id=None,
        question_type=question_type,
        problem_text=source.problem_text,
        student_answer=source.student_answer,
        standard_answer=None,
        acceptable_answers_json="[]",
        unordered=False,
        status=STATUS_PENDING,
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    version = GradingVersion(
        grading_id=0,  # flush 后回填
        version=1,
        action="suggested",
        verdict=suggestion.verdict,
        source=suggestion.source,
        confidence=suggestion.confidence,
        reason=suggestion.reason,
        provider=suggestion.provider,
        model=suggestion.model,
        prompt_id=suggestion.prompt_id,
        prompt_version=suggestion.prompt_version,
        sample_verdicts_json="[]",
        created_at=now,
    )

    try:
        async with session.begin_nested():
            session.add(root)
            await session.flush()
            version.grading_id = root.id
            session.add(version)
            await session.flush()
    except IntegrityError:
        existing = await get_by_source(session, source.source_kind, source.source_id)
        if existing is None:
            raise
        return existing, False
    return root, True


async def append_user_decision(
    session: AsyncSession,
    grading: GradingResult,
    *,
    action: Literal["confirmed", "appealed"],
    verdict: UserVerdict,
    actor: Literal["student", "parent"],
    reason: str,
    category_id: str | None = None,
    details: ConfirmationDetails | None = None,
    allow_unscheduled: bool = False,
) -> GradingVersion:
    """追加确认/申诉版本并写事实事件；版本号即幂等边界。"""

    next_version = grading.current_version + 1
    now = datetime.now(UTC)
    if details is not None and details.standard_answer is not None:
        grading.standard_answer = details.standard_answer
    version = GradingVersion(
        grading_id=grading.id,
        version=next_version,
        action=action,
        verdict=verdict,
        source=actor,
        confidence=None,
        reason=reason,
        sample_verdicts_json="[]",
        created_at=now,
    )
    session.add(version)
    grading.current_version = next_version
    grading.status = STATUS_CONFIRMED if action == "confirmed" else STATUS_APPEALED
    grading.updated_at = now
    await session.flush()

    extra = details or ConfirmationDetails()
    mistake = await sync_mistake_for_verdict(
        session,
        grading,
        verdict=verdict,
        actor=actor,
        category_id=category_id,
        now=now,
        primary_topic_id=extra.primary_topic_id,
        standard_answer=extra.standard_answer,
        suggested_category_id=extra.suggested_category_id,
        suggested_concept_ids=extra.suggested_concept_ids,
        suggested_error_cause=extra.suggested_error_cause,
        confirmed_concept_ids=extra.confirmed_concept_ids,
        confirmed_error_cause=extra.confirmed_error_cause,
        review_subject=extra.review_subject,
        allow_unscheduled=allow_unscheduled,
    )
    event_mistake_id = mistake.id if verdict == "wrong" and mistake is not None else None

    await record_event(
        session,
        ATTEMPT_CORRECT if verdict == "correct" else ATTEMPT_WRONG,
        actor,
        mistake_id=event_mistake_id,
        idempotency_key=f"grading:{grading.id}:v{next_version}",
        payload={
            "grading_id": grading.id,
            "grading_version": next_version,
            "verdict": verdict,
            "question_type": grading.question_type,
            "source_kind": grading.source_kind,
            "source_id": grading.source_id,
            "mistake_id": event_mistake_id,
        },
    )
    return version
