"""P2-2 番茄钟打点：计时在前端，后端只接收"完成"事实。

口径（TICKETS P2-2）：
- 每次完成 = 一条 append-only 的 `pomodoro_completed` 事件，payload 只有
  `mistake_id / duration_minutes / completed_on`；不建新表、不写 attempts；
- 幂等键 `pomodoro:{started_at.timestamp():.0f}`：同一开始秒重放返回已有事件，
  刷新/重试不会重复计数；
- `duration_minutes` 由服务端钳制到 5–120，前端只负责计时，其数值不被信任；
- 番茄只用于看板展示专注时长：**不计入掌握度、不计入 streak、不进错题本**，
  也不触发任何排期/队列变化（`summarize_pomodoros` 仅供 dashboard 使用）。

P2-2b 增补（进行中轮次服务端续走）：`pomodoro_sessions` 只承载计时器运行态
（何时开始 / 计划多少分钟 / active·completed·abandoned），**事实源与 payload 键
一字不改**：完成仍走 `record_pomodoro`，放弃不写任何事件。剩余时间不入库，由
`started_at + planned_minutes` 与服务端当前时间推导，因此刷新/切页/换设备都能续走。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LearningEvent, PomodoroSession
from app.models.pomodoro import (
    SESSION_ABANDONED,
    SESSION_ACTIVE,
    SESSION_COMPLETED,
)
from app.services.events import record_event
from app.services.recompute import Event

POMODORO_COMPLETED = "pomodoro_completed"
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 120


class PomodoroSessionNotFound(LookupError):
    """轮次不存在（API 映射 404）。"""


class PomodoroSessionConflict(RuntimeError):
    """轮次状态不允许该操作（API 映射 409）。"""


class PomodoroAlreadyRunning(RuntimeError):
    """已有进行中轮次（API 映射 409）：先完成或放弃它。"""


@dataclass(frozen=True)
class PomodoroRecord:
    event: LearningEvent
    created: bool
    duration_minutes: int


@dataclass(frozen=True)
class PomodoroSummary:
    pomodoros_today: int
    focus_minutes_this_week: int


def clamp_duration(minutes: int) -> int:
    """5–120 分钟；不接受 bool（它虽是 int 子类，但不是时长）。"""

    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise TypeError("duration_minutes 必须是整数")
    return max(MIN_DURATION_MINUTES, min(MAX_DURATION_MINUTES, minutes))


def _payload(event: LearningEvent | Event) -> dict[str, Any]:
    raw = event.payload
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
    else:
        data = raw
    return data if isinstance(data, dict) else {}


def _stored_duration(event: LearningEvent) -> int | None:
    value = _payload(event).get("duration_minutes")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return clamp_duration(value)


async def record_pomodoro(
    session: AsyncSession,
    *,
    mistake_id: int | None,
    duration_minutes: int,
    started_at: datetime,
    completed_on: date,
    actor: str = "student",
) -> PomodoroRecord:
    """追加一条番茄完成事实；同 `started_at` 秒重放返回已有事件。"""

    minutes = clamp_duration(duration_minutes)
    event, created = await record_event(
        session,
        POMODORO_COMPLETED,
        actor,
        idempotency_key=f"pomodoro:{started_at.timestamp():.0f}",
        mistake_id=mistake_id,
        payload={
            "mistake_id": mistake_id,
            "duration_minutes": minutes,
            "completed_on": completed_on.isoformat(),
        },
    )
    return PomodoroRecord(
        event=event,
        created=created,
        duration_minutes=_stored_duration(event) or minutes,
    )


def _as_utc(value: datetime) -> datetime:
    """SQLite 的 DateTime 回读不带时区，而写入一律是 UTC，故 naive 即 UTC。"""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def remaining_seconds(
    started_at: datetime, planned_minutes: int, now: datetime
) -> int:
    """剩余秒数：计划时长减去服务端已走过的秒；不为负、不超过计划时长。"""

    total = planned_minutes * 60
    elapsed = int((_as_utc(now) - _as_utc(started_at)).total_seconds())
    return max(0, min(total, total - elapsed))


@dataclass(frozen=True)
class PomodoroSessionView:
    id: int
    started_at: datetime
    planned_minutes: int
    mistake_id: int | None
    actor: str
    status: str
    remaining_seconds: int
    server_now: datetime


@dataclass(frozen=True)
class PomodoroCompletion:
    record: PomodoroRecord
    session: PomodoroSessionView


def _view(row: PomodoroSession, now: datetime) -> PomodoroSessionView:
    return PomodoroSessionView(
        id=row.id,
        started_at=_as_utc(row.started_at),
        planned_minutes=row.planned_minutes,
        mistake_id=row.mistake_id,
        actor=row.actor,
        status=row.status,
        remaining_seconds=remaining_seconds(
            row.started_at, row.planned_minutes, now
        ),
        server_now=now,
    )


async def _active_row(session: AsyncSession) -> PomodoroSession | None:
    return (
        await session.scalars(
            select(PomodoroSession)
            .where(PomodoroSession.status == SESSION_ACTIVE)
            .order_by(PomodoroSession.id.desc())
        )
    ).first()


async def start_session(
    session: AsyncSession,
    *,
    planned_minutes: int,
    mistake_id: int | None = None,
    actor: str = "student",
    now: datetime | None = None,
) -> PomodoroSessionView:
    """开一轮：同一时刻只允许一个进行中轮次，已有的必须先完成或放弃。"""

    moment = now or datetime.now(UTC)
    if await _active_row(session) is not None:
        raise PomodoroAlreadyRunning("已有进行中的专注轮次：请先完成或放弃它")
    row = PomodoroSession(
        started_at=moment,
        planned_minutes=planned_minutes,
        mistake_id=mistake_id,
        actor=actor,
        status=SESSION_ACTIVE,
    )
    session.add(row)
    await session.flush()
    return _view(row, moment)


async def active_session(
    session: AsyncSession, *, now: datetime | None = None
) -> PomodoroSessionView | None:
    """供续走：返回进行中轮次与推导出的剩余秒数；没有则 None。"""

    moment = now or datetime.now(UTC)
    row = await _active_row(session)
    return None if row is None else _view(row, moment)


async def complete_session(
    session: AsyncSession,
    session_id: int,
    *,
    duration_minutes: int,
    completed_on: date | None = None,
    now: datetime | None = None,
) -> PomodoroCompletion:
    """完成一轮：写既有 `pomodoro_completed` 事实（payload 键不变）+ 置 completed。

    `duration_minutes` 是实际分钟（提前完成也照实记）；重复完成命中既有幂等键
    `pomodoro:{started_at秒}`，不产生第二条事件。已放弃的轮次不能记为完成。
    键格式沿用 P2-2 不改，因此"同一开始秒的两轮"仍会命中同一条事实。
    """

    moment = now or datetime.now(UTC)
    row = await session.get(PomodoroSession, session_id)
    if row is None:
        raise PomodoroSessionNotFound("专注轮次不存在")
    if row.status == SESSION_ABANDONED:
        raise PomodoroSessionConflict("这一轮已放弃，不能记为完成")
    record = await record_pomodoro(
        session,
        mistake_id=row.mistake_id,
        duration_minutes=duration_minutes,
        started_at=_as_utc(row.started_at),
        completed_on=completed_on or moment.date(),
        actor=row.actor,
    )
    row.status = SESSION_COMPLETED
    await session.flush()
    return PomodoroCompletion(record=record, session=_view(row, moment))


async def abandon_session(
    session: AsyncSession,
    session_id: int,
    *,
    now: datetime | None = None,
) -> PomodoroSessionView:
    """放弃一轮：只翻状态，**不写任何事件**；重复放弃幂等。"""

    moment = now or datetime.now(UTC)
    row = await session.get(PomodoroSession, session_id)
    if row is None:
        raise PomodoroSessionNotFound("专注轮次不存在")
    if row.status == SESSION_COMPLETED:
        raise PomodoroSessionConflict("这一轮已完成，不能放弃")
    row.status = SESSION_ABANDONED
    await session.flush()
    return _view(row, moment)


def _event_day(event: Event) -> date | None:
    if event.type != POMODORO_COMPLETED:
        return None
    raw = _payload(event).get("completed_on")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    moment = event.occurred_at
    if isinstance(moment, datetime):
        if moment.tzinfo is not None:
            return moment.astimezone(UTC).date()
        return moment.date()
    if isinstance(moment, date):
        return moment
    return None


def _event_minutes(event: Event) -> int:
    value = _payload(event).get("duration_minutes")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return 0
    return value


def summarize_pomodoros(
    events: Sequence[Event], today: date, week_start: date
) -> PomodoroSummary:
    """今日番茄个数 + 本周（周一至今）专注分钟；只读事件，不做任何推断。"""

    today_count = 0
    week_minutes = 0
    for event in events:
        day = _event_day(event)
        if day is None:
            continue
        if day == today:
            today_count += 1
        if week_start <= day <= today:
            week_minutes += _event_minutes(event)
    return PomodoroSummary(
        pomodoros_today=today_count,
        focus_minutes_this_week=week_minutes,
    )
