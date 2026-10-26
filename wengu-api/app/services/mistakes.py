"""P1-6 错题本服务：唯一写入路径 + 两级标签版本。

Phase 0 边界表未回填：不存在"判错即自动入本"。mistakes 只由用户确认/申诉
verdict=wrong 时创建或复活；verdict=correct 只作废，不删除历史。
mistake_versions 只追加；建议值（确定性匹配）与确认值（用户操作）分离存储，
确认值一旦写入即优先，后续建议永不覆盖。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Concept,
    GradingResult,
    KnowledgeSeed,
    Mistake,
    MistakeVersion,
    ProblemBankItem,
)
from app.models.mistakes import MISTAKE_ACTIVE, MISTAKE_VOIDED
from app.services.concepts import (
    CategoryNotFound,
    ConceptConflict,
    concept_family_ids,
    resolve_concepts,
)
from app.services.events import append_mistake_version, record_event
from app.services.labels import suggest_labels
from app.services.review import schedule_initial

MAX_CONCEPTS = 10
MAX_ERROR_CAUSE_LENGTH = 32

ERROR_CAUSES: dict[str, str] = {
    "prerequisite_gap": "前置知识缺失",
    "concept_unclear": "概念不清",
    "method_missing": "方法不会",
    "calculation": "计算失误",
    "careless": "审题粗心",
    "expression": "表达书写",
    "other": "其他",
}

MISTAKE_LABELED = "mistake_labeled"


class MistakeNotFound(LookupError):
    pass


class MistakeConflict(ValueError):
    pass


class MistakeVersionConflict(MistakeConflict):
    pass


@dataclass(frozen=True)
class EffectiveLabels:
    confirmed: bool
    category_id: str | None
    concept_ids: tuple[int, ...]
    error_cause: str | None


def load_concept_ids(raw: str) -> list[int]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [
        item
        for item in data
        if isinstance(item, int) and not isinstance(item, bool)
    ]


def effective_labels(version: MistakeVersion) -> EffectiveLabels:
    """确认值优先；未确认（confirmed_by 为空）时才回退到确定性建议值。"""

    confirmed = version.confirmed_by is not None
    return EffectiveLabels(
        confirmed=confirmed,
        category_id=(
            version.confirmed_category_id
            if confirmed
            else version.suggested_category_id
        ),
        concept_ids=tuple(
            load_concept_ids(
                version.confirmed_concept_ids_json
                if confirmed
                else version.suggested_concept_ids_json
            )
        ),
        error_cause=(
            version.confirmed_error_cause
            if confirmed
            else version.suggested_error_cause
        ),
    )


def error_cause_label(value: str | None) -> str | None:
    if value is None:
        return None
    return ERROR_CAUSES.get(value, value)


async def _subject_for(
    session: AsyncSession, grading: GradingResult
) -> str | None:
    if grading.problem_bank_id is None:
        return None
    item = await session.get(ProblemBankItem, grading.problem_bank_id)
    return item.subject if item is not None else None


async def sync_mistake_for_verdict(
    session: AsyncSession,
    grading: GradingResult,
    *,
    verdict: str,
    actor: Literal["student", "parent"] = "student",
    category_id: str | None = None,
    now: datetime | None = None,
) -> Mistake | None:
    """把用户确认/申诉的 verdict 同步到错题生命周期。

    wrong  → 建根 + 首版快照（含零模型确定性标签建议），已存在则复活；
    correct → 已存在则作废，不删除任何版本。
    category_id 是用户确认值，只在新建错题时落库；已有错题不覆盖标签。
    返回 wrong 时的错题根；correct 或无错题时返回 None。
    """

    if verdict not in ("correct", "wrong"):
        raise MistakeConflict("只有 correct/wrong 能触发错题本同步")
    moment = now or datetime.now(UTC)
    cleaned_category = (category_id or "").strip() or None

    existing = (
        await session.execute(
            select(Mistake).where(Mistake.source_grading_id == grading.id)
        )
    ).scalar_one_or_none()

    if verdict == "correct":
        if existing is not None and existing.status == MISTAKE_ACTIVE:
            existing.status = MISTAKE_VOIDED
            existing.updated_at = moment
            await session.flush()
        return None

    if existing is not None:
        if existing.status != MISTAKE_ACTIVE:
            existing.status = MISTAKE_ACTIVE
            existing.updated_at = moment
            await session.flush()
        return existing

    if (
        cleaned_category is not None
        and await session.get(KnowledgeSeed, cleaned_category) is None
    ):
        raise CategoryNotFound("知识点 category 不存在")

    root = Mistake(
        source_grading_id=grading.id,
        status=MISTAKE_ACTIVE,
        current_version=1,
        created_at=moment,
        updated_at=moment,
    )
    try:
        async with session.begin_nested():
            session.add(root)
            await session.flush()
    except IntegrityError:
        existing = (
            await session.execute(
                select(Mistake).where(Mistake.source_grading_id == grading.id)
            )
        ).scalar_one()
        return existing

    suggestions = await suggest_labels(
        session,
        grading.problem_text,
        subject=await _subject_for(session, grading),
    )
    await append_mistake_version(
        session,
        root.id,
        problem_text=grading.problem_text,
        standard_answer=grading.standard_answer,
        student_answer=grading.student_answer,
        is_correct=False,
        status="confirmed",
        suggested_category_id=suggestions.category_id,
        suggested_concept_ids=suggestions.concept_ids,
        confirmed_category_id=cleaned_category,
        confirmed_by=actor if cleaned_category is not None else None,
    )
    await schedule_initial(
        session,
        root.id,
        completed_on=moment.date(),
        actor=actor,
        now=moment,
    )
    return root


async def get_latest_version(
    session: AsyncSession, mistake_id: int
) -> MistakeVersion | None:
    return (
        await session.execute(
            select(MistakeVersion)
            .where(MistakeVersion.mistake_id == mistake_id)
            .order_by(MistakeVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_mistake(session: AsyncSession, mistake_id: int) -> Mistake:
    mistake = await session.get(Mistake, mistake_id)
    if mistake is None:
        raise MistakeNotFound("错题不存在")
    return mistake


async def append_label_version(
    session: AsyncSession,
    *,
    mistake_id: int,
    base_version: int,
    actor: str,
    category_id: str | None,
    concept_ids: Sequence[int],
    error_cause: str | None,
) -> tuple[Mistake, MistakeVersion]:
    """全量替换错题标签并追加版本；base_version 做乐观锁。"""

    if actor not in ("student", "parent"):
        raise MistakeConflict("只有 student/parent 可以确认标签")
    mistake = await get_mistake(session, mistake_id)
    if mistake.status != MISTAKE_ACTIVE:
        raise MistakeConflict("已作废错题不能修改标签")
    if base_version != mistake.current_version:
        raise MistakeVersionConflict(
            f"版本已变化，当前版本 {mistake.current_version}"
        )
    latest = await get_latest_version(session, mistake_id)
    if latest is None:
        raise MistakeConflict("错题内容版本缺失")

    cleaned_category = (category_id or "").strip() or None
    if (
        cleaned_category is not None
        and await session.get(KnowledgeSeed, cleaned_category) is None
    ):
        raise CategoryNotFound("知识点 category 不存在")

    raw_ids: list[int] = []
    for value in concept_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ConceptConflict("concept_id 必须是正整数")
        raw_ids.append(value)
    if len(set(raw_ids)) > MAX_CONCEPTS:
        raise MistakeConflict(f"细标签不能超过 {MAX_CONCEPTS} 个")
    if raw_ids and cleaned_category is None:
        raise MistakeConflict("选择细标签前必须先选 category")

    resolved: list[Concept] = await resolve_concepts(session, raw_ids)
    canonical_ids = [concept.id for concept in resolved]
    if len(canonical_ids) < len(set(raw_ids)):
        raise ConceptConflict("存在已归并或已失效的概念，请刷新后重试")
    if cleaned_category is not None:
        mismatched = [
            concept
            for concept in resolved
            if concept.category_id != cleaned_category
        ]
        if mismatched:
            raise ConceptConflict("细标签不属于所选 category")

    cleaned_error_cause = (error_cause or "").strip() or None
    if cleaned_error_cause is not None:
        if len(cleaned_error_cause) > MAX_ERROR_CAUSE_LENGTH:
            raise MistakeConflict("错因取值过长")
        if cleaned_error_cause not in ERROR_CAUSES:
            raise MistakeConflict("未知错因")

    version = await append_mistake_version(
        session,
        mistake.id,
        problem_text=latest.problem_text,
        problem_images=latest.problem_images,
        standard_answer=latest.standard_answer,
        student_answer=latest.student_answer,
        is_correct=latest.is_correct,
        status=latest.status,
        suggested_category_id=latest.suggested_category_id,
        category_confidence=latest.category_confidence,
        suggested_concept_ids=load_concept_ids(
            latest.suggested_concept_ids_json
        ),
        confirmed_category_id=cleaned_category,
        confirmed_concept_ids=canonical_ids,
        confirmed_by=actor,
        suggested_error_cause=latest.suggested_error_cause,
        confirmed_error_cause=cleaned_error_cause,
    )
    mistake.current_version = version.version
    mistake.updated_at = version.created_at
    await session.flush()

    await record_event(
        session,
        MISTAKE_LABELED,
        actor,
        idempotency_key=f"mistake:{mistake.id}:v{version.version}",
        mistake_id=mistake.id,
        payload={
            "mistake_id": mistake.id,
            "mistake_version": version.version,
            "category_id": cleaned_category,
            "concept_ids": canonical_ids,
            "error_cause": cleaned_error_cause,
        },
    )
    return mistake, version


async def list_mistakes(
    session: AsyncSession,
    *,
    status: str = "active",
    category_id: str | None = None,
    concept_id: int | None = None,
    error_cause: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Mistake, MistakeVersion]], int]:
    """按最新版本的有效标签检索；concept 过滤会展开人工归并前的历史 id。"""

    latest_version = (
        select(func.max(MistakeVersion.version))
        .where(MistakeVersion.mistake_id == Mistake.id)
        .correlate(Mistake)
        .scalar_subquery()
    )
    stmt = select(Mistake, MistakeVersion).join(
        MistakeVersion,
        and_(
            MistakeVersion.mistake_id == Mistake.id,
            MistakeVersion.version == latest_version,
        ),
    )
    if status != "all":
        stmt = stmt.where(Mistake.status == status)

    rows = (await session.execute(stmt)).all()
    family = (
        await concept_family_ids(session, concept_id)
        if concept_id is not None
        else None
    )

    filtered: list[tuple[Mistake, MistakeVersion]] = []
    for mistake, version in rows:
        labels = effective_labels(version)
        if category_id is not None and labels.category_id != category_id:
            continue
        if error_cause is not None and labels.error_cause != error_cause:
            continue
        if family is not None and not (set(labels.concept_ids) & family):
            continue
        filtered.append((mistake, version))

    filtered.sort(key=lambda item: item[0].id, reverse=True)
    total = len(filtered)
    return filtered[offset : offset + limit], total
