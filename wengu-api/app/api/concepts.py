"""P1-6 细粒度 concept 受控生长 API：查询、创建/复用、人工归并。

没有模型调用；名称/别名在 category 内归一查重，归并只改 merged_into_id 与别名。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Concept
from app.services.concepts import (
    CategoryNotFound,
    ConceptConflict,
    ConceptNotFound,
    ConceptResult,
    create_or_reuse_concept,
    get_concept_with_aliases,
    list_concepts,
    merge_concepts,
)

router = APIRouter(tags=["concepts"])


class ConceptInfo(BaseModel):
    id: int
    name: str
    category_id: str
    source: str
    status: str
    merged_into_id: int | None
    aliases: list[str]


class ConceptListResponse(BaseModel):
    items: list[ConceptInfo]


class ConceptCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    category_id: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    actor: Literal["student", "parent"] = "student"


class ConceptCreateResponse(ConceptInfo):
    reused: bool


class ConceptMergeRequest(BaseModel):
    source_id: int = Field(ge=1)
    target_id: int = Field(ge=1)
    actor: Literal["student", "parent"] = "student"


class ConceptMergeResponse(BaseModel):
    source: ConceptInfo
    target: ConceptInfo
    aliases_moved: int


def _info(concept: Concept, aliases: list[str]) -> ConceptInfo:
    return ConceptInfo(
        id=concept.id,
        name=concept.name,
        category_id=concept.category_id,
        source=concept.source,
        status=concept.status,
        merged_into_id=concept.merged_into_id,
        aliases=aliases,
    )


def _from_result(result: ConceptResult) -> ConceptCreateResponse:
    return ConceptCreateResponse(
        **_info(result.concept, list(result.aliases)).model_dump(),
        reused=result.reused,
    )


@router.get("/api/concepts", response_model=ConceptListResponse)
async def list_concepts_endpoint(
    category_id: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> ConceptListResponse:
    async with session.begin():
        rows = await list_concepts(
            session, category_id=category_id, q=q, limit=limit
        )
    return ConceptListResponse(
        items=[_info(concept, list(aliases)) for concept, aliases in rows]
    )


@router.post("/api/concepts", response_model=ConceptCreateResponse)
async def create_concept(
    payload: ConceptCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> ConceptCreateResponse:
    async with session.begin():
        try:
            result = await create_or_reuse_concept(
                session,
                name=payload.name,
                category_id=payload.category_id,
                actor=payload.actor,
                aliases=payload.aliases,
            )
        except CategoryNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ConceptConflict as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return _from_result(result)


@router.post("/api/concepts/merge", response_model=ConceptMergeResponse)
async def merge_concepts_endpoint(
    payload: ConceptMergeRequest,
    session: AsyncSession = Depends(get_session),
) -> ConceptMergeResponse:
    async with session.begin():
        try:
            source, target, moved = await merge_concepts(
                session,
                source_id=payload.source_id,
                target_id=payload.target_id,
                actor=payload.actor,
            )
            _, source_aliases = await get_concept_with_aliases(session, source.id)
            _, target_aliases = await get_concept_with_aliases(session, target.id)
        except ConceptNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ConceptConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return ConceptMergeResponse(
            source=_info(source, list(source_aliases)),
            target=_info(target, list(target_aliases)),
            aliases_moved=moved,
        )
