"""P3-3a 英语背诵 API：家长维护条目，孩子按记忆阶梯自评。

读接口（列表 / 到期）对孩子开放；条目新增与编辑挂 `require_parent`。
自评只写 `learning_events` 与 `recitation_reviews`，不写错题本/attempts/排期，
因此掌握度与复习队列不受影响；同日重复提交幂等返回既有结果。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.database import get_session
from app.models import RecitationItem
from app.services.recitation import (
    RecitationConflict,
    RecitationDuplicate,
    RecitationInvalid,
    RecitationNotFound,
    ReviewOutcome,
    create_item,
    due_items,
    list_items,
    review_item,
    update_item,
)

router = APIRouter(tags=["recitations"])

ItemStatus = Literal["active", "retired"]
Verdict = Literal["remembered", "forgot"]


class ItemView(BaseModel):
    id: int
    subject: str
    prompt: str
    answer: str | None
    unit: str | None
    status: ItemStatus
    created_by: str
    created_at: datetime


class ItemListResponse(BaseModel):
    items: list[ItemView]
    total: int


class CreateItemRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=500)
    answer: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=80)


class UpdateItemRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=80)
    status: ItemStatus | None = None


class DueItemView(BaseModel):
    item: ItemView
    rung: int
    scheduled_next: date | None
    graduated: bool
    reviewed_on: date | None


class DueListResponse(BaseModel):
    items: list[DueItemView]
    due_total: int
    returned: int
    limit: int
    today: date


class ReviewRequest(BaseModel):
    verdict: Verdict
    reviewed_on: date | None = None
    actor: Literal["student", "parent"] = "student"


class ReviewResponse(BaseModel):
    item: ItemView
    review_id: int
    event_id: int
    verdict: Verdict
    rung: int
    reviewed_on: date
    scheduled_next: date | None
    graduated: bool
    created: bool


def _item_view(item: RecitationItem) -> ItemView:
    return ItemView(
        id=item.id,
        subject=item.subject,
        prompt=item.prompt,
        answer=item.answer,
        unit=item.unit,
        status=item.status,
        created_by=item.created_by,
        created_at=item.created_at,
    )


def _review_response(outcome: ReviewOutcome) -> ReviewResponse:
    review = outcome.review
    return ReviewResponse(
        item=_item_view(outcome.item),
        review_id=review.id,
        event_id=outcome.event.id,
        verdict=review.verdict,
        rung=review.rung,
        reviewed_on=review.reviewed_on,
        scheduled_next=review.scheduled_next,
        graduated=review.scheduled_next is None,
        created=outcome.created,
    )


@router.get("/api/recitations", response_model=ItemListResponse)
async def get_recitations(
    subject: str | None = Query(default=None, max_length=80),
    status: ItemStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ItemListResponse:
    async with session.begin():
        try:
            result = await list_items(
                session,
                subject=subject,
                status=status,
                limit=limit,
                offset=offset,
            )
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return ItemListResponse(
        items=[_item_view(item) for item in result.items],
        total=result.total,
    )


@router.get("/api/recitations/due", response_model=DueListResponse)
async def get_due_recitations(
    today: date | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> DueListResponse:
    day = today or date.today()
    async with session.begin():
        try:
            due = await due_items(session, day, limit=limit)
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except RecitationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    return DueListResponse(
        items=[
            DueItemView(
                item=_item_view(entry.item),
                rung=entry.state.rung,
                scheduled_next=entry.state.scheduled_next,
                graduated=entry.state.graduated,
                reviewed_on=entry.state.reviewed_on,
            )
            for entry in due.items
        ],
        due_total=due.due_total,
        returned=due.returned,
        limit=due.limit,
        today=day,
    )


@router.post(
    "/api/recitations",
    response_model=ItemView,
    dependencies=[Depends(require_parent)],
)
async def create_recitation(
    payload: CreateItemRequest,
    session: AsyncSession = Depends(get_session),
) -> ItemView:
    async with session.begin():
        try:
            item = await create_item(
                session,
                subject=payload.subject,
                prompt=payload.prompt,
                answer=payload.answer,
                unit=payload.unit,
                created_by="parent",
            )
        except RecitationDuplicate as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _item_view(item)


@router.patch(
    "/api/recitations/{item_id}",
    response_model=ItemView,
    dependencies=[Depends(require_parent)],
)
async def patch_recitation(
    item_id: int,
    payload: UpdateItemRequest,
    session: AsyncSession = Depends(get_session),
) -> ItemView:
    async with session.begin():
        try:
            item = await update_item(
                session,
                item_id,
                prompt=payload.prompt,
                answer=payload.answer,
                unit=payload.unit,
                status=payload.status,
            )
        except RecitationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RecitationDuplicate as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _item_view(item)


@router.post(
    "/api/recitations/{item_id}/review", response_model=ReviewResponse
)
async def review_recitation(
    item_id: int,
    payload: ReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    reviewed_on = payload.reviewed_on or date.today()
    async with session.begin():
        try:
            outcome = await review_item(
                session,
                item_id,
                verdict=payload.verdict,
                reviewed_on=reviewed_on,
                actor=payload.actor,
            )
        except RecitationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RecitationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _review_response(outcome)
