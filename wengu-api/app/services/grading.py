"""P1-5 批改分级闸服务：客观题确定性判、过程题保守初判、确认/申诉版本化。

纪律（AGENTS §5 / TICKETS P1-5）：
- 客观题零模型调用，只走 judge_answer 规范化比对；模型只提作答，绝不二次判分。
- 过程题才调模型，默认落 pending；多次采样不一致一律 uncertain。
- 提取质量闸门未过 / 缺可信标准答案 / 占位 / 作答为空 → manual，不猜、不调模型。
- 建议值与确认值分离：grading_results 存逻辑单，grading_versions 只追加，
  确认/申诉写 learning_events（幂等键含 grading_id + version）。
- Phase 0 边界表未回填：所有新批改单 status=pending，不自动建错题/排复习。
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

MAX_SAMPLES = 3


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
    sample_verdicts: tuple[str, ...] = ()


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


async def process_suggestion(
    source: SourceProblem,
    reference: Reference | None,
    *,
    gateway,
    samples: int,
    reference_reason: str | None = None,
) -> Suggestion:
    """过程题：模型保守初判（1–3 次采样，任一次不确定/不一致 → uncertain）。"""

    if not source.ready:
        return _manual(source.manual_reason or "extraction_not_ready")
    if reference is None:
        return _manual(reference_reason or "reference_missing")

    results = []
    metas = []
    for index in range(max(1, min(samples, MAX_SAMPLES))):
        result, meta = await gateway.grade(
            source.problem_text,
            source.student_answer or "",
            standard_answer=reference.answer,
            sample_index=index,
        )
        results.append(result)
        metas.append(meta)

    verdicts = tuple(result.verdict for result in results)
    if len(set(verdicts)) > 1:
        verdict = "uncertain"
        reason = "sampling_disagreement"
    elif verdicts[0] == "uncertain":
        verdict = "uncertain"
        reason = "ai_uncertain"
    else:
        verdict = verdicts[0]
        reason = "ai_consistent" if len(verdicts) > 1 else "ai_initial"

    confidences = [r.confidence for r in results if r.confidence is not None]
    meta = metas[-1]
    return Suggestion(
        verdict=verdict,
        source="ai",
        confidence=min(confidences) if confidences else None,
        reason=reason,
        provider=meta.provider,
        model=meta.model,
        prompt_id=meta.prompt_id,
        prompt_version=meta.prompt_version,
        sample_verdicts=verdicts,
    )


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
        sample_verdicts_json=json.dumps(list(suggestion.sample_verdicts), ensure_ascii=False),
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
) -> GradingVersion:
    """追加确认/申诉版本并写事实事件；版本号即幂等边界。"""

    next_version = grading.current_version + 1
    now = datetime.now(UTC)
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

    mistake = await sync_mistake_for_verdict(
        session, grading, verdict=verdict, now=now
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
