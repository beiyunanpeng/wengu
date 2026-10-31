"""P2-3 课表/日历 API：录入（家长）→ 展示（孩子同见）→ 考试日放宽复习上限。

硬边界：课表/日历是**约束层**，不是任务源主体。这里只有 CRUD 与窗口查询，
不生成任务、不做时间块、不做冲突检测、不建"考试科目↔知识点"映射。
写操作（增删）挂 `require_parent`；读操作属于孩子区，免 PIN。

校验：weekday 1–7、period 1–12、kind 枚举、日期合法一律 422；同一节次
重复录入由 `UNIQUE(weekday, period)` 兜底返回 409（编辑 = 删了重加）。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.database import get_session
from app.models import CalendarEvent, TimetableSlot

router = APIRouter(tags=["schedule"])

CalendarKind = Literal["exam", "competition", "leave", "other"]
SubjectText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
]
TitleText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
NoteText = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=200)
]

DEFAULT_EVENT_WINDOW_DAYS = 30


class TimetableSlotView(BaseModel):
    id: int
    weekday: int
    period: int
    subject: str
    note: str | None


class TimetableSlotCreate(BaseModel):
    weekday: int = Field(ge=1, le=7)
    period: int = Field(ge=1, le=12)
    subject: SubjectText
    note: NoteText | None = None


class TimetableResponse(BaseModel):
    items: list[TimetableSlotView]


class CalendarEventView(BaseModel):
    id: int
    date: date
    title: str
    kind: CalendarKind
    subject: str | None
    note: str | None


class CalendarEventCreate(BaseModel):
    date: date
    title: TitleText
    kind: CalendarKind
    subject: SubjectText | None = None
    note: NoteText | None = None


class CalendarEventsResponse(BaseModel):
    items: list[CalendarEventView]


def _slot_view(row: TimetableSlot) -> TimetableSlotView:
    return TimetableSlotView(
        id=row.id,
        weekday=row.weekday,
        period=row.period,
        subject=row.subject,
        note=row.note,
    )


def _event_view(row: CalendarEvent) -> CalendarEventView:
    return CalendarEventView(
        id=row.id,
        date=row.date,
        title=row.title,
        kind=row.kind,
        subject=row.subject,
        note=row.note,
    )


@router.get("/api/timetable", response_model=TimetableResponse)
async def list_timetable(
    session: AsyncSession = Depends(get_session),
) -> TimetableResponse:
    """全周固定节次，按 weekday / period 升序（孩子与家长看同一份）。"""

    async with session.begin():
        rows = (
            await session.scalars(
                select(TimetableSlot).order_by(
                    TimetableSlot.weekday, TimetableSlot.period
                )
            )
        ).all()
    return TimetableResponse(items=[_slot_view(row) for row in rows])


@router.post(
    "/api/timetable/slots",
    response_model=TimetableSlotView,
    status_code=201,
    dependencies=[Depends(require_parent)],
)
async def create_timetable_slot(
    payload: TimetableSlotCreate,
    session: AsyncSession = Depends(get_session),
) -> TimetableSlotView:
    try:
        async with session.begin():
            row = TimetableSlot(
                weekday=payload.weekday,
                period=payload.period,
                subject=payload.subject,
                note=payload.note or None,
            )
            session.add(row)
            await session.flush()
            view = _slot_view(row)
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="该节次已有课程；请先删除原课程再重新添加",
        ) from None
    return view


@router.delete(
    "/api/timetable/slots/{slot_id}",
    dependencies=[Depends(require_parent)],
)
async def delete_timetable_slot(
    slot_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    async with session.begin():
        row = await session.get(TimetableSlot, slot_id)
        if row is None:
            raise HTTPException(status_code=404, detail="节次不存在")
        await session.delete(row)
    return {"deleted": slot_id}


@router.get("/api/calendar/events", response_model=CalendarEventsResponse)
async def list_calendar_events(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_session),
) -> CalendarEventsResponse:
    """按日期升序返回窗口内事件；缺省为未来 30 天（含今天）。"""

    start = from_date or date.today()
    end = to_date or start + timedelta(days=DEFAULT_EVENT_WINDOW_DAYS)
    if end < start:
        raise HTTPException(status_code=422, detail="to 不能早于 from")
    async with session.begin():
        rows = (
            await session.scalars(
                select(CalendarEvent)
                .where(CalendarEvent.date >= start, CalendarEvent.date <= end)
                .order_by(CalendarEvent.date, CalendarEvent.id)
            )
        ).all()
    return CalendarEventsResponse(items=[_event_view(row) for row in rows])


@router.post(
    "/api/calendar/events",
    response_model=CalendarEventView,
    status_code=201,
    dependencies=[Depends(require_parent)],
)
async def create_calendar_event(
    payload: CalendarEventCreate,
    session: AsyncSession = Depends(get_session),
) -> CalendarEventView:
    async with session.begin():
        row = CalendarEvent(
            date=payload.date,
            title=payload.title,
            kind=payload.kind,
            subject=payload.subject or None,
            note=payload.note or None,
        )
        session.add(row)
        await session.flush()
        view = _event_view(row)
    return view


@router.delete(
    "/api/calendar/events/{event_id}",
    dependencies=[Depends(require_parent)],
)
async def delete_calendar_event(
    event_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    async with session.begin():
        row = await session.get(CalendarEvent, event_id)
        if row is None:
            raise HTTPException(status_code=404, detail="事件不存在")
        await session.delete(row)
    return {"deleted": event_id}
