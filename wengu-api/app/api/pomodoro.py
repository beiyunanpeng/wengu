"""P2-2 番茄钟 API：只接收前端计时器的"完成"打点。

硬边界：番茄钟是计时器，不是规划器。本模块不自动开始下一个番茄、不做时间块、
不做后台计时或通知；写入只有一条 `pomodoro_completed` 事实事件，供看板展示
专注时长。它不计入掌握度 / streak / 错题本，也不影响到期队列。

校验：duration 由服务端钳制 5–120（API 只要求正整数，0/负数/非整数 → 422）；
`mistake_id` 可空（自由专注），指向不存在的错题 → 404。

P2-2b 增补：进行中轮次走 `/start`、`/active`、`/{id}/complete`、`/{id}/abandon`，
与既有打点端点同权限（孩子区免 PIN）。新端点的时长**严格** 5–120（越界 422，
不静默钳制）；`/active` 返回服务端当前时间，剩余秒数由服务端推导，客户端时钟
不参与计算。放弃只翻状态、不写事件；完成仍写同一条 `pomodoro_completed`。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Mistake
from app.services.pomodoro import (
    MAX_DURATION_MINUTES,
    MIN_DURATION_MINUTES,
    PomodoroAlreadyRunning,
    PomodoroSessionConflict,
    PomodoroSessionNotFound,
    PomodoroSessionView,
    abandon_session,
    active_session,
    complete_session,
    record_pomodoro,
    start_session,
)

router = APIRouter(tags=["pomodoro"])


class PomodoroCreate(BaseModel):
    mistake_id: StrictInt | None = Field(default=None, ge=1)
    duration_minutes: StrictInt = Field(ge=1)
    started_at: datetime
    completed_on: date
    actor: Literal["student", "parent"] = "student"


class PomodoroResponse(BaseModel):
    id: int
    duration_minutes: int


class PomodoroStart(BaseModel):
    planned_minutes: StrictInt = Field(
        ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES
    )
    mistake_id: StrictInt | None = Field(default=None, ge=1)
    actor: Literal["student", "parent"] = "student"


class PomodoroComplete(BaseModel):
    duration_minutes: StrictInt = Field(
        ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES
    )
    completed_on: date | None = None


class PomodoroSessionResponse(BaseModel):
    id: int
    started_at: datetime
    planned_minutes: int
    mistake_id: int | None
    actor: str
    status: str
    remaining_seconds: int
    server_now: datetime


class ActivePomodoroResponse(BaseModel):
    session: PomodoroSessionResponse | None


class PomodoroCompletionResponse(BaseModel):
    id: int
    duration_minutes: int
    session_id: int
    status: str


class PomodoroAbandonResponse(BaseModel):
    session_id: int
    status: str


def _session_response(view: PomodoroSessionView) -> PomodoroSessionResponse:
    return PomodoroSessionResponse(
        id=view.id,
        started_at=view.started_at,
        planned_minutes=view.planned_minutes,
        mistake_id=view.mistake_id,
        actor=view.actor,
        status=view.status,
        remaining_seconds=view.remaining_seconds,
        server_now=view.server_now,
    )


@router.post(
    "/api/pomodoros", response_model=PomodoroResponse, status_code=201
)
async def create_pomodoro(
    payload: PomodoroCreate,
    session: AsyncSession = Depends(get_session),
) -> PomodoroResponse:
    async with session.begin():
        if (
            payload.mistake_id is not None
            and await session.get(Mistake, payload.mistake_id) is None
        ):
            raise HTTPException(status_code=404, detail="错题不存在")
        record = await record_pomodoro(
            session,
            mistake_id=payload.mistake_id,
            duration_minutes=payload.duration_minutes,
            started_at=payload.started_at,
            completed_on=payload.completed_on,
            actor=payload.actor,
        )
        event_id = record.event.id
        minutes = record.duration_minutes
    return PomodoroResponse(id=event_id, duration_minutes=minutes)


@router.post(
    "/api/pomodoros/start",
    response_model=PomodoroSessionResponse,
    status_code=201,
)
async def start_pomodoro(
    payload: PomodoroStart,
    session: AsyncSession = Depends(get_session),
) -> PomodoroSessionResponse:
    async with session.begin():
        if (
            payload.mistake_id is not None
            and await session.get(Mistake, payload.mistake_id) is None
        ):
            raise HTTPException(status_code=404, detail="错题不存在")
        try:
            view = await start_session(
                session,
                planned_minutes=payload.planned_minutes,
                mistake_id=payload.mistake_id,
                actor=payload.actor,
            )
        except PomodoroAlreadyRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    return _session_response(view)


@router.get("/api/pomodoros/active", response_model=ActivePomodoroResponse)
async def get_active_pomodoro(
    session: AsyncSession = Depends(get_session),
) -> ActivePomodoroResponse:
    async with session.begin():
        view = await active_session(session)
    return ActivePomodoroResponse(
        session=None if view is None else _session_response(view)
    )


@router.post(
    "/api/pomodoros/{session_id}/complete",
    response_model=PomodoroCompletionResponse,
)
async def complete_pomodoro(
    session_id: int,
    payload: PomodoroComplete,
    session: AsyncSession = Depends(get_session),
) -> PomodoroCompletionResponse:
    async with session.begin():
        try:
            completion = await complete_session(
                session,
                session_id,
                duration_minutes=payload.duration_minutes,
                completed_on=payload.completed_on,
            )
        except PomodoroSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except PomodoroSessionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        event_id = completion.record.event.id
        minutes = completion.record.duration_minutes
        view = completion.session
    return PomodoroCompletionResponse(
        id=event_id,
        duration_minutes=minutes,
        session_id=view.id,
        status=view.status,
    )


@router.post(
    "/api/pomodoros/{session_id}/abandon",
    response_model=PomodoroAbandonResponse,
)
async def abandon_pomodoro(
    session_id: int,
    session: AsyncSession = Depends(get_session),
) -> PomodoroAbandonResponse:
    async with session.begin():
        try:
            view = await abandon_session(session, session_id)
        except PomodoroSessionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except PomodoroSessionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    return PomodoroAbandonResponse(session_id=view.id, status=view.status)
