"""核对页确认入本（P1-6 · v2.5 主入本通道）。

外部 agent 转录的草稿只会落 `ingestion_drafts`；本模块负责"人工确认后转正"：
- 闸门（缺正答 / 含占位符 / 主考点不存在 / 细标签不属于主考点）→ 拒绝转正；
  主考点与错答可空（未确认主考点仍入本、存 NULL；整题没做也算错题），
  但占位符〔?〕一律拒绝——留空≠看不清；
- 通过后建 `GradingResult(source_kind='ingestion_draft')` 并走唯一写入路径
  （`append_user_decision` → `sync_mistake_for_verdict`），不另开建错题旁路；
- 转录里的 `error_cause_suggestion / suggested_topic_id` 只作建议值，与用户
  确认值分列存储（`mistake_versions.suggested_*` vs `confirmed_*`）；
- 全程零模型调用；重复确认幂等返回首次结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.judge.normalize import PLACEHOLDER
from app.models import (
    GradingResult,
    ImportBatch,
    IngestionDraft,
    KnowledgeSeed,
    Mistake,
    ReviewSchedule,
)
from app.models.grading import (
    QUESTION_OBJECTIVE,
    SOURCE_INGESTION_DRAFT,
)
from app.services.concepts import resolve_concepts
from app.services.grading import (
    ConfirmationDetails,
    SourceProblem,
    Suggestion,
    append_user_decision,
    get_by_source,
    persist_grading,
)
from app.services.labels import suggest_labels
from app.services.mistakes import ERROR_CAUSES, MAX_CONCEPTS, clean_error_cause

# 转录模板（docs/templates/doubao_transcribe_v1.md）里的中文错因候选 → 系统错因键
SUGGESTED_ERROR_CAUSES: dict[str, str] = {
    "概念不清": "concept_unclear",
    "计算失误": "calculation",
    "审题不清": "careless",
    "审题粗心": "careless",
    "方法不会": "method_missing",
    "记忆模糊": "prerequisite_gap",
    "步骤跳步": "expression",
    "抄写错误": "careless",
    "表达书写": "expression",
    "前置知识缺失": "prerequisite_gap",
    "其他": "other",
}


class DraftNotFound(LookupError):
    pass


class DraftGateError(ValueError):
    """转正闸门不通过；code 供前端定位原因。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DraftInfo:
    draft: IngestionDraft
    filename: str | None
    normalized: dict[str, str]
    grading_id: int | None
    mistake_id: int | None
    suggested_topic_id: str | None
    suggested_topic_name: str | None
    suggested_error_cause: str | None
    suggestion_source: str | None


@dataclass(frozen=True)
class PromotionResult:
    draft_id: int
    grading_id: int
    mistake_id: int
    primary_topic_id: str | None
    standard_answer: str
    due_on: date | None
    already_promoted: bool


def map_suggested_error_cause(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if text in ERROR_CAUSES:
        return text
    return SUGGESTED_ERROR_CAUSES.get(text)


def load_normalized(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: value for key, value in data.items() if isinstance(value, str)
    }


async def _topic_name(session: AsyncSession, topic_id: str | None) -> str | None:
    if not topic_id:
        return None
    seed = await session.get(KnowledgeSeed, topic_id)
    return seed.name if seed is not None else None


async def _suggestion(
    session: AsyncSession, normalized: dict[str, str]
) -> tuple[str | None, str | None, str | None, str | None]:
    """返回 (topic_id, topic_name, error_cause, source)。"""

    error_cause = map_suggested_error_cause(
        normalized.get("error_cause_suggestion")
    )
    agent_topic = (normalized.get("suggested_topic_id") or "").strip() or None
    if agent_topic is not None:
        name = await _topic_name(session, agent_topic)
        if name is not None:
            return agent_topic, name, error_cause, "agent"
    problem_text = (normalized.get("problem_text") or "").strip()
    if problem_text:
        deterministic = await suggest_labels(
            session,
            problem_text,
            subject=(normalized.get("subject") or "").strip() or None,
        )
        if deterministic.category_id is not None:
            return (
                deterministic.category_id,
                await _topic_name(session, deterministic.category_id),
                error_cause,
                "deterministic",
            )
    return None, None, error_cause, None


async def list_drafts(
    session: AsyncSession,
    *,
    status: Literal["draft", "promoted", "all"] = "draft",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DraftInfo], int]:
    conditions = [] if status == "all" else [IngestionDraft.status == status]
    total = (
        await session.execute(
            select(func.count()).select_from(IngestionDraft).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(IngestionDraft, ImportBatch.filename)
            .join(ImportBatch, ImportBatch.id == IngestionDraft.import_batch_id)
            .where(*conditions)
            .order_by(IngestionDraft.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    items: list[DraftInfo] = []
    for draft, filename in rows:
        normalized = load_normalized(draft.normalized_json)
        grading = await get_by_source(session, SOURCE_INGESTION_DRAFT, draft.id)
        mistake_id: int | None = None
        if grading is not None:
            mistake_id = (
                await session.execute(
                    select(Mistake.id).where(
                        Mistake.source_grading_id == grading.id
                    )
                )
            ).scalar_one_or_none()
        topic_id, topic_name, error_cause, source = await _suggestion(
            session, normalized
        )
        items.append(
            DraftInfo(
                draft=draft,
                filename=filename,
                normalized=normalized,
                grading_id=grading.id if grading is not None else None,
                mistake_id=mistake_id,
                suggested_topic_id=topic_id,
                suggested_topic_name=topic_name,
                suggested_error_cause=error_cause,
                suggestion_source=source,
            )
        )
    return items, total


def _require_text(
    normalized: dict[str, str],
    field: str,
    code: str,
    message: str,
    *,
    override: str | None = None,
) -> str:
    value = (override if override is not None else normalized.get(field) or "").strip()
    if not value:
        raise DraftGateError(code, message)
    if PLACEHOLDER in value:
        raise DraftGateError(
            "placeholder", "草稿含占位符〔?〕，请重新拍照转录后再确认"
        )
    return value


def _optional_text(normalized: dict[str, str], field: str) -> str:
    """允许留空（整题没做），但不允许用占位符冒充留空（转录失败须重拍）。"""

    value = (normalized.get(field) or "").strip()
    if PLACEHOLDER in value:
        raise DraftGateError(
            "placeholder", "草稿含占位符〔?〕，请重新拍照转录后再确认"
        )
    return value


async def _existing_promotion(
    session: AsyncSession, grading: GradingResult
) -> PromotionResult | None:
    mistake = (
        await session.execute(
            select(Mistake).where(Mistake.source_grading_id == grading.id)
        )
    ).scalar_one_or_none()
    if mistake is None:
        return None
    schedule = (
        await session.execute(
            select(ReviewSchedule)
            .where(ReviewSchedule.mistake_id == mistake.id)
            .order_by(ReviewSchedule.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return PromotionResult(
        draft_id=grading.source_id,
        grading_id=grading.id,
        mistake_id=mistake.id,
        primary_topic_id=mistake.primary_topic_id,
        standard_answer=grading.standard_answer or "",
        due_on=schedule.due_date if schedule is not None else None,
        already_promoted=True,
    )


async def promote_draft(
    session: AsyncSession,
    draft_id: int,
    *,
    primary_topic_id: str | None = None,
    standard_answer: str | None = None,
    error_cause: str | None = None,
    concept_ids: tuple[int, ...] = (),
    question_type: str = QUESTION_OBJECTIVE,
    actor: Literal["student", "parent"] = "student",
) -> PromotionResult:
    draft = await session.get(IngestionDraft, draft_id)
    if draft is None:
        raise DraftNotFound("草稿不存在")

    grading = await get_by_source(session, SOURCE_INGESTION_DRAFT, draft.id)
    if grading is not None:
        existing = await _existing_promotion(session, grading)
        if existing is not None:
            return existing
        raise DraftGateError("state_inconsistent", "草稿已有批改单但缺错题记录")

    normalized = load_normalized(draft.normalized_json)
    problem_text = _require_text(
        normalized, "problem_text", "problem_text_missing", "草稿缺少题目文本"
    )
    student_answer = _optional_text(normalized, "student_answer")
    confirmed_standard = _require_text(
        normalized,
        "standard_answer",
        "standard_answer_missing",
        "缺正答：请先在卷面订正，或在核对页补填正答",
        override=standard_answer,
    )

    cleaned_topic = (primary_topic_id or "").strip() or None
    if cleaned_topic is not None:
        topic = await session.get(KnowledgeSeed, cleaned_topic)
        if topic is None:
            raise DraftGateError("primary_topic_unknown", "主考点不存在")

    try:
        cleaned_error = clean_error_cause(error_cause)
    except ValueError as exc:
        raise DraftGateError("error_cause_invalid", str(exc)) from None

    raw_ids: list[int] = []
    for value in concept_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise DraftGateError("concept_invalid", "concept_id 必须是正整数")
        raw_ids.append(value)
    if len(set(raw_ids)) > MAX_CONCEPTS:
        raise DraftGateError("concept_invalid", f"细标签不能超过 {MAX_CONCEPTS} 个")
    resolved = await resolve_concepts(session, raw_ids)
    canonical_ids = tuple(concept.id for concept in resolved)
    if len(canonical_ids) < len(set(raw_ids)):
        raise DraftGateError("concept_invalid", "存在已归并或已失效的概念，请刷新后重试")
    if any(concept.category_id != cleaned_topic for concept in resolved):
        raise DraftGateError(
            "concept_category_mismatch",
            "细标签不属于所选主考点" if cleaned_topic else "选细标签前必须先确认主考点",
        )

    suggested_topic, _, suggested_error, _ = await _suggestion(session, normalized)
    draft_subject = (normalized.get("subject") or "").strip() or None

    source = SourceProblem(
        source_kind=SOURCE_INGESTION_DRAFT,
        source_id=draft.id,
        problem_text=problem_text,
        student_answer=student_answer,
        ready=True,
    )
    grading, created = await persist_grading(
        session,
        source=source,
        question_type=question_type,  # type: ignore[arg-type]
        suggestion=Suggestion(
            verdict="wrong",
            source="ai",
            confidence=None,
            reason="agent_transcribe",
        ),
    )
    if not created:
        existing = await _existing_promotion(session, grading)
        if existing is not None:
            return existing
    await append_user_decision(
        session,
        grading,
        action="confirmed",
        verdict="wrong",
        actor=actor,
        reason="intake_confirmed",
        category_id=cleaned_topic,
        details=ConfirmationDetails(
            standard_answer=confirmed_standard,
            primary_topic_id=cleaned_topic,
            suggested_category_id=suggested_topic,
            suggested_concept_ids=None,
            suggested_error_cause=suggested_error,
            confirmed_concept_ids=canonical_ids,
            confirmed_error_cause=cleaned_error,
            review_subject=draft_subject,
        ),
        allow_unscheduled=True,
    )
    mistake = (
        await session.execute(
            select(Mistake).where(Mistake.source_grading_id == grading.id)
        )
    ).scalar_one_or_none()
    if mistake is None:
        raise DraftGateError("state_inconsistent", "错题写入失败")

    schedule = (
        await session.execute(
            select(ReviewSchedule)
            .where(ReviewSchedule.mistake_id == mistake.id)
            .order_by(ReviewSchedule.id)
            .limit(1)
        )
    ).scalar_one_or_none()

    draft.status = "promoted"
    await session.flush()
    return PromotionResult(
        draft_id=draft.id,
        grading_id=grading.id,
        mistake_id=mistake.id,
        primary_topic_id=cleaned_topic,
        standard_answer=confirmed_standard,
        due_on=schedule.due_date if schedule is not None else None,
        already_promoted=False,
    )
