"""P1-5 判分服务（v2.5：真实题不在系统内判，只判自造同类题）。

纪律（AGENTS §5 / 设计文档 §16.B）：
- 真实作业的批改/引导/解析全部外部完成；本模块不再做过程题模型初判，
  也不再做多次采样一致性检查（整段已随 v2.5 退役）。
- 客观题仍走确定性 judge_answer 规范化比对，零模型调用；不确定一律 uncertain。
- 提取质量闸门未过 / 缺可信标准答案 / 占位 / 作答为空 → manual，不猜、不调模型。
- 建议值与确认值分离：grading_results 存逻辑单，grading_versions 只追加，
  确认/申诉写 learning_events（幂等键含 grading_id + version）。
- 所有新批改单 status=pending，不自动建错题/排复习（入本一律经核对页确认）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.judge.normalize import PLACEHOLDER, judge_answer
from app.models import (
    GradingResult,
    GradingVersion,
    IngestionDraft,
    ProblemBankItem,
    ProblemExtraction,
)
from app.models.grading import (
    SOURCE_INGESTION_DRAFT,
    SOURCE_PROBLEM_EXTRACTION,
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
class Reference:
    answer: str
    acceptable: tuple[str, ...]
    unordered: bool
    bank_id: int | None = None


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


class SourceNotFound(LookupError):
    pass


class ReferenceNotFound(LookupError):
    pass


def _manual(reason: str) -> Suggestion:
    return Suggestion("uncertain", "code", None, reason)


def _placeholder_in(*values: str | None) -> bool:
    return any(PLACEHOLDER in value for value in values if value)


def _draft_fields(raw: str) -> tuple[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    problem_text = data.get("problem_text")
    student_answer = data.get("student_answer")
    return (
        problem_text if isinstance(problem_text, str) else "",
        student_answer if isinstance(student_answer, str) else "",
    )


async def read_source(
    session: AsyncSession, source_kind: str, source_id: int
) -> SourceProblem:
    """读取待批改来源并执行提取质量闸门；不调模型、不落库。"""

    if source_kind == SOURCE_PROBLEM_EXTRACTION:
        row = await session.get(ProblemExtraction, source_id)
        if row is None:
            raise SourceNotFound("extraction 不存在")
        if row.gate_status != "ready_for_grading":
            reason = f"extraction_gate:{row.gate_status}"
            return SourceProblem(
                source_kind, source_id, row.problem_text, row.student_answer, False, reason
            )
        if _placeholder_in(row.problem_text, row.student_answer):
            return SourceProblem(
                source_kind, source_id, row.problem_text, row.student_answer, False, "placeholder"
            )
        if not (row.student_answer or "").strip():
            return SourceProblem(
                source_kind,
                source_id,
                row.problem_text,
                row.student_answer,
                False,
                "student_answer_empty",
            )
        return SourceProblem(
            source_kind, source_id, row.problem_text, row.student_answer, True, None
        )

    if source_kind == SOURCE_INGESTION_DRAFT:
        row = await session.get(IngestionDraft, source_id)
        if row is None:
            raise SourceNotFound("draft 不存在")
        problem_text, student_answer = _draft_fields(row.normalized_json)
        if row.has_placeholder or _placeholder_in(problem_text, student_answer):
            return SourceProblem(
                source_kind, source_id, problem_text, student_answer, False, "placeholder"
            )
        if row.is_incomplete or not student_answer.strip():
            return SourceProblem(
                source_kind,
                source_id,
                problem_text,
                student_answer,
                False,
                "student_answer_empty",
            )
        return SourceProblem(
            source_kind, source_id, problem_text, student_answer, True, None
        )

    raise SourceNotFound(f"不支持的 source_kind: {source_kind}")


def parse_acceptable(raw: str) -> tuple[str, ...]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(item for item in data if isinstance(item, str))


async def resolve_reference(
    session: AsyncSession,
    *,
    problem_bank_id: int | None,
    answer: str | None,
    acceptable: list[str],
    unordered: bool,
) -> tuple[Reference | None, str | None]:
    """解析可信标准答案；返回 (reference, manual_reason)，两者互斥。"""

    if problem_bank_id is not None:
        item = await session.get(ProblemBankItem, problem_bank_id)
        if item is None:
            raise ReferenceNotFound("problem_bank 条目不存在")
        if not item.answer.strip() or PLACEHOLDER in item.answer:
            return None, "reference_invalid"
        return (
            Reference(
                answer=item.answer,
                acceptable=parse_acceptable(item.acceptable_answers_json),
                unordered=item.unordered,
                bank_id=item.id,
            ),
            None,
        )

    if answer is None:
        return None, "reference_missing"
    if not answer.strip() or PLACEHOLDER in answer:
        return None, "reference_invalid"
    return (
        Reference(
            answer=answer,
            acceptable=tuple(item for item in acceptable if item.strip()),
            unordered=unordered,
        ),
        None,
    )


def objective_suggestion(
    source: SourceProblem,
    reference: Reference | None,
    *,
    reference_reason: str | None = None,
) -> Suggestion:
    """客观题：确定性比对，零模型调用。"""

    if not source.ready:
        return _manual(source.manual_reason or "extraction_not_ready")
    if reference is None:
        return _manual(reference_reason or "reference_missing")
    judged = judge_answer(
        source.student_answer,
        reference.answer,
        acceptable=reference.acceptable,
        unordered=reference.unordered,
    )
    if judged.verdict == "uncertain":
        return _manual(judged.reason)
    return Suggestion(judged.verdict, "code", None, judged.reason)


def process_suggestion(
    source: SourceProblem,
    reference: Reference | None,
    *,
    reference_reason: str | None = None,
) -> Suggestion:
    """过程题：v2.5 起系统内不判，一律转人工确认（真实题在卷面已批改）。

    保留该分支只为兼容旧入口：不调模型、不做采样，直接落 uncertain。
    """

    if not source.ready:
        return _manual(source.manual_reason or "extraction_not_ready")
    if reference is None:
        return _manual(reference_reason or "reference_missing")
    return _manual("real_homework_external")


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
    reference: Reference | None,
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
        problem_bank_id=reference.bank_id if reference else None,
        question_type=question_type,
        problem_text=source.problem_text,
        student_answer=source.student_answer,
        standard_answer=reference.answer if reference else None,
        acceptable_answers_json=json.dumps(
            list(reference.acceptable) if reference else [], ensure_ascii=False
        ),
        unordered=reference.unordered if reference else False,
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
