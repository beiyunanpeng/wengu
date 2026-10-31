"""P2-2 番茄钟 API：只接收前端计时器的"完成"打点。

硬边界：番茄钟是计时器，不是规划器。本模块不自动开始下一个番茄、不做时间块、
不做后台计时或通知；写入只有一条 `pomodoro_completed` 事实事件，供看板展示
专注时长。它不计入掌握度 / streak / 错题本，也不影响到期队列。

校验：duration 由服务端钳制 5–120（API 只要求正整数，0/负数/非整数 → 422）；
`mistake_id` 可空（自由专注），指向不存在的错题 → 404。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictInt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Mistake
from app.services.pomodoro import record_pomodoro

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
