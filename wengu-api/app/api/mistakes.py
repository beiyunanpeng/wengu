"""P1-6 错题本 API：检索、详情、标签确认（唯一写入在批改确认/申诉路径）。

GET 一律纯查询；标签确认只追加 mistake_versions 与 learning_events。
Phase 0：不提供"直接新建错题"端点，也不触发任何排期。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.database import get_session
from app.models import Concept, KnowledgeSeed, Mistake, MistakeVersion
from app.services.concepts import CategoryNotFound, ConceptConflict, resolve_concept_map
from app.services.mistakes import (
    ERROR_CAUSES,
    MAX_VOID_REASON_LENGTH,
    MistakeConflict,
    MistakeNotFound,
    MistakeStateConflict,
    MistakeVersionConflict,
    append_label_version,
    effective_labels,
    error_cause_label,
    get_latest_version,
    get_mistake,
    list_mistakes,
    load_concept_ids,
    unvoid_mistake,
    void_mistake,
)

router = APIRouter(tags=["mistakes"])


class ConceptInfo(BaseModel):
    id: int
    name: str
    category_id: str


class MistakeLabels(BaseModel):
    confirmed: bool
    category_id: str | None
    category_name: str | None
    concepts: list[ConceptInfo]
    error_cause: str | None
    error_cause_label: str | None
    confirmed_by: str | None


class MistakeSuggestion(BaseModel):
    category_id: str | None
    category_name: str | None
    concepts: list[ConceptInfo]
    error_cause: str | None
    error_cause_label: str | None


class MistakeDetail(BaseModel):
    id: int
    status: str
    source_grading_id: int
    current_version: int
    problem_text: str | None
    student_answer: str | None
    standard_answer: str | None
    is_correct: bool | None
    labels: MistakeLabels
    suggestion: MistakeSuggestion
    created_at: datetime
    updated_at: datetime


class MistakeListResponse(BaseModel):
    items: list[MistakeDetail]
    total: int
    limit: int
    offset: int


class ErrorCauseOption(BaseModel):
    id: str
    label: str


class MistakeOptions(BaseModel):
    error_causes: list[ErrorCauseOption]


class LabelRequest(BaseModel):
    base_version: int = Field(ge=1)
    category_id: str | None = Field(default=None, max_length=64)
    concept_ids: list[int] = Field(default_factory=list, max_length=10)
    error_cause: str | None = Field(default=None, max_length=32)
    actor: Literal["student", "parent"] = "student"


class VoidRequest(BaseModel):
    # actor 用自由字符串交给服务层校验：非法角色按 409 状态冲突返回
    actor: str = Field(default="student", max_length=16)
    reason: str | None = Field(default=None, max_length=MAX_VOID_REASON_LENGTH)


class UnvoidRequest(BaseModel):
    actor: str = Field(default="student", max_length=16)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _concept_infos(
    concept_ids: tuple[int, ...], concept_map: dict[int, Concept]
) -> list[ConceptInfo]:
    seen: set[int] = set()
    infos: list[ConceptInfo] = []
    for concept_id in concept_ids:
        concept = concept_map.get(concept_id)
        if concept is None or concept.id in seen:
            continue
        seen.add(concept.id)
        infos.append(
            ConceptInfo(
                id=concept.id,
                name=concept.name,
                category_id=concept.category_id,
            )
        )
    infos.sort(key=lambda info: info.id)
    return infos


def _collect_concept_ids(version: MistakeVersion) -> set[int]:
    return {
        *effective_labels(version).concept_ids,
        *load_concept_ids(version.suggested_concept_ids_json),
    }


def _to_detail(
    mistake: Mistake,
    version: MistakeVersion,
    *,
    category_names: dict[str, str],
    concept_map: dict[int, Concept],
) -> MistakeDetail:
    labels = effective_labels(version)
    suggested_ids = tuple(load_concept_ids(version.suggested_concept_ids_json))
    return MistakeDetail(
        id=mistake.id,
        status=mistake.status,
        source_grading_id=mistake.source_grading_id,
        current_version=mistake.current_version,
        problem_text=version.problem_text,
        student_answer=version.student_answer,
        standard_answer=version.standard_answer,
        is_correct=version.is_correct,
        labels=MistakeLabels(
            confirmed=labels.confirmed,
            category_id=labels.category_id,
            category_name=(
                category_names.get(labels.category_id)
                if labels.category_id
                else None
            ),
            concepts=_concept_infos(labels.concept_ids, concept_map),
            error_cause=labels.error_cause,
            error_cause_label=error_cause_label(labels.error_cause),
            confirmed_by=version.confirmed_by,
        ),
        suggestion=MistakeSuggestion(
            category_id=version.suggested_category_id,
            category_name=(
                category_names.get(version.suggested_category_id)
                if version.suggested_category_id
                else None
            ),
            concepts=_concept_infos(suggested_ids, concept_map),
            error_cause=version.suggested_error_cause,
            error_cause_label=error_cause_label(version.suggested_error_cause),
        ),
        created_at=_naive_utc(mistake.created_at),
        updated_at=_naive_utc(mistake.updated_at),
    )


async def _load_lookup(
    session: AsyncSession, versions: list[MistakeVersion]
) -> tuple[dict[str, str], dict[int, Concept]]:
    category_ids = {
        value
        for version in versions
        for value in (version.suggested_category_id, version.confirmed_category_id)
        if value
    }
    concept_ids: set[int] = set()
    for version in versions:
        concept_ids.update(_collect_concept_ids(version))

    category_names: dict[str, str] = {}
    if category_ids:
        rows = (
            await session.execute(
                select(KnowledgeSeed.id, KnowledgeSeed.name).where(
                    KnowledgeSeed.id.in_(category_ids)
                )
            )
        ).all()
        category_names = dict(rows)
    concept_map = await resolve_concept_map(session, concept_ids)
    return category_names, concept_map


async def _render_detail(
    session: AsyncSession, mistake: Mistake
) -> MistakeDetail:
    version = await get_latest_version(session, mistake.id)
    if version is None:
        raise HTTPException(status_code=404, detail="错题内容版本缺失")
    category_names, concept_map = await _load_lookup(session, [version])
    return _to_detail(
        mistake,
        version,
        category_names=category_names,
        concept_map=concept_map,
    )


@router.get("/api/mistakes/options", response_model=MistakeOptions)
async def mistake_options() -> MistakeOptions:
    return MistakeOptions(
        error_causes=[
            ErrorCauseOption(id=key, label=label)
            for key, label in ERROR_CAUSES.items()
        ]
    )


@router.get("/api/mistakes", response_model=MistakeListResponse)
async def list_mistakes_endpoint(
    status: Literal["active", "voided", "all"] = "active",
    category_id: str | None = Query(default=None, max_length=64),
    concept_id: int | None = Query(default=None, ge=1),
    error_cause: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> MistakeListResponse:
    async with session.begin():
        rows, total = await list_mistakes(
            session,
            status=status,
            category_id=category_id,
            concept_id=concept_id,
            error_cause=error_cause,
            limit=limit,
            offset=offset,
        )
        category_names, concept_map = await _load_lookup(
            session, [version for _, version in rows]
        )
        items = [
            _to_detail(
                mistake,
                version,
                category_names=category_names,
                concept_map=concept_map,
            )
            for mistake, version in rows
        ]
    return MistakeListResponse(
        items=items, total=total, limit=limit, offset=offset
    )


@router.get("/api/mistakes/{mistake_id}", response_model=MistakeDetail)
async def get_mistake_endpoint(
    mistake_id: int, session: AsyncSession = Depends(get_session)
) -> MistakeDetail:
    async with session.begin():
        try:
            mistake = await get_mistake(session, mistake_id)
        except MistakeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return await _render_detail(session, mistake)


@router.post(
    "/api/mistakes/{mistake_id}/void",
    response_model=MistakeDetail,
    dependencies=[Depends(require_parent)],
)
async def void_mistake_endpoint(
    mistake_id: int,
    payload: VoidRequest,
    session: AsyncSession = Depends(get_session),
) -> MistakeDetail:
    """作废错题：退出活跃列表与到期队列，可撤销；不删任何历史。"""

    async with session.begin():
        try:
            mistake = await void_mistake(
                session,
                mistake_id,
                actor=payload.actor,
                reason=payload.reason,
            )
        except MistakeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except MistakeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return await _render_detail(session, mistake)


@router.post(
    "/api/mistakes/{mistake_id}/unvoid",
    response_model=MistakeDetail,
    dependencies=[Depends(require_parent)],
)
async def unvoid_mistake_endpoint(
    mistake_id: int,
    payload: UnvoidRequest,
    session: AsyncSession = Depends(get_session),
) -> MistakeDetail:
    """撤销作废：恢复活跃；未完成排期到期后自然重回队列。"""

    async with session.begin():
        try:
            mistake = await unvoid_mistake(
                session, mistake_id, actor=payload.actor
            )
        except MistakeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except MistakeConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return await _render_detail(session, mistake)


@router.post("/api/mistakes/{mistake_id}/labels", response_model=MistakeDetail)
async def update_mistake_labels(
    mistake_id: int,
    payload: LabelRequest,
    session: AsyncSession = Depends(get_session),
) -> MistakeDetail:
    """局部更新：未提交的字段保留已确认值；显式 null/[] 才清空。"""

    async with session.begin():
        latest = await get_latest_version(session, mistake_id)
        if latest is None:
            raise HTTPException(status_code=404, detail="错题不存在")
        base_category: str | None = None
        base_concepts: list[int] = []
        base_error_cause: str | None = None
        if latest.confirmed_by is not None:
            base_category = latest.confirmed_category_id
            base_concepts = load_concept_ids(latest.confirmed_concept_ids_json)
            base_error_cause = latest.confirmed_error_cause

        provided = payload.model_fields_set
        category_id = (
            payload.category_id if "category_id" in provided else base_category
        )
        concept_ids = (
            payload.concept_ids if "concept_ids" in provided else base_concepts
        )
        error_cause = (
            payload.error_cause if "error_cause" in provided else base_error_cause
        )

        try:
            mistake, version = await append_label_version(
                session,
                mistake_id=mistake_id,
                base_version=payload.base_version,
                actor=payload.actor,
                category_id=category_id,
                concept_ids=concept_ids,
                error_cause=error_cause,
            )
        except MistakeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (MistakeVersionConflict, MistakeStateConflict) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except (MistakeConflict, CategoryNotFound, ConceptConflict) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

        category_names, concept_map = await _load_lookup(session, [version])
        return _to_detail(
            mistake,
            version,
            category_names=category_names,
            concept_map=concept_map,
        )
