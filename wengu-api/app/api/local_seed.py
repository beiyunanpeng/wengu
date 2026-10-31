"""家长自建章级 seed（语文/化学）：列表 + 新增/编辑/删除（全部家长专属）。

文件真源在 `<data_dir>/seeds_local/topics_<学科>.json`（Docker 内 `./seeds` 只读、
`data/` 随备份走）；SQLite `knowledge_seed` 只是装载副本，`source='local'`。
删除只允许 local 行，引用侧显式解绑并返回受影响计数；历史错题/事件不删。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models import KnowledgeSeed
from app.services.bank import reset_bank_cache
from app.services.local_seed import (
    LocalSeedConflict,
    LocalSeedError,
    LocalSeedNotFound,
    create_local_topic,
    delete_local_topic,
    list_local_topics,
    update_local_topic,
    usage_counts,
)

router = APIRouter(tags=["local-seed"], dependencies=[Depends(require_parent)])


class LocalTopicInfo(BaseModel):
    id: str
    name: str
    subject: str
    grade: str | None
    semester: str | None
    chapter: str | None
    domain: str | None
    description: str | None
    type: str | None
    mastery_criteria: list[str] | None
    unaudited: bool
    blind_verified: bool
    mistake_count: int
    problem_count: int


class LocalTopicList(BaseModel):
    items: list[LocalTopicInfo]
    total: int


class LocalTopicCreate(BaseModel):
    subject: str = Field(min_length=1, max_length=8)
    name: str = Field(min_length=1, max_length=40)
    grade: int | None = Field(default=None, ge=7, le=9)
    semester: str | None = Field(default=None, max_length=20)
    chapter: str | None = Field(default=None, max_length=100)
    domain: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    mastery_criteria: list[str] | None = None
    type: str | None = Field(default=None, max_length=20)


class LocalTopicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    grade: int | None = Field(default=None, ge=7, le=9)
    semester: str | None = Field(default=None, max_length=20)
    chapter: str | None = Field(default=None, max_length=100)
    domain: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    mastery_criteria: list[str] | None = None
    type: str | None = Field(default=None, max_length=20)


class LocalTopicDeleteResponse(BaseModel):
    id: str
    removed: bool
    mistakes_unbound: int
    problems_unbound: int


def _criteria(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return [raw]
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return None


def _info(row: KnowledgeSeed, usage: dict[str, int] | None = None) -> LocalTopicInfo:
    counts = usage or {"mistakes": 0, "problems": 0}
    return LocalTopicInfo(
        id=row.id,
        name=row.name,
        subject=row.subject,
        grade=row.grade,
        semester=row.semester,
        chapter=row.chapter,
        domain=row.domain,
        description=row.description,
        type=row.type,
        mastery_criteria=_criteria(row.mastery_criteria),
        unaudited=row.unaudited,
        blind_verified=row.blind_verified,
        mistake_count=counts["mistakes"],
        problem_count=counts["problems"],
    )


def _raise(exc: LocalSeedError) -> None:
    if isinstance(exc, LocalSeedNotFound):
        status = 404
    elif isinstance(exc, LocalSeedConflict):
        status = 409
    else:
        status = 422
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/api/local-seed/topics", response_model=LocalTopicList)
async def local_topics(
    subject: str | None = Query(default=None, max_length=8),
    session: AsyncSession = Depends(get_session),
) -> LocalTopicList:
    try:
        rows = await list_local_topics(session, subject)
    except LocalSeedError as exc:
        _raise(exc)
    usage = await usage_counts(session, [row.id for row in rows])
    return LocalTopicList(
        items=[_info(row, usage[row.id]) for row in rows],
        total=len(rows),
    )


@router.post("/api/local-seed/topics", response_model=LocalTopicInfo, status_code=201)
async def create_topic(
    payload: LocalTopicCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LocalTopicInfo:
    data: dict[str, Any] = payload.model_dump(exclude={"subject"})
    try:
        row = await create_local_topic(session, settings, subject=payload.subject, data=data)
    except LocalSeedError as exc:
        _raise(exc)
    reset_bank_cache()
    return _info(row)


@router.patch("/api/local-seed/topics/{topic_id}", response_model=LocalTopicInfo)
async def update_topic(
    topic_id: str,
    payload: LocalTopicUpdate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LocalTopicInfo:
    try:
        row = await update_local_topic(
            session, settings, topic_id, payload.model_dump(exclude_unset=True)
        )
    except LocalSeedError as exc:
        _raise(exc)
    reset_bank_cache()
    usage = await usage_counts(session, [row.id])
    return _info(row, usage[row.id])


@router.delete(
    "/api/local-seed/topics/{topic_id}", response_model=LocalTopicDeleteResponse
)
async def delete_topic(
    topic_id: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LocalTopicDeleteResponse:
    try:
        counts = await delete_local_topic(session, settings, topic_id)
    except LocalSeedError as exc:
        _raise(exc)
    reset_bank_cache()
    return LocalTopicDeleteResponse(id=topic_id, removed=True, **counts)
