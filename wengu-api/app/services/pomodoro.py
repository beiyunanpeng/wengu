"""P2-2 番茄钟打点：计时在前端，后端只接收"完成"事实。

口径（TICKETS P2-2）：
- 每次完成 = 一条 append-only 的 `pomodoro_completed` 事件，payload 只有
  `mistake_id / duration_minutes / completed_on`；不建新表、不写 attempts；
- 幂等键 `pomodoro:{started_at.timestamp():.0f}`：同一开始秒重放返回已有事件，
  刷新/重试不会重复计数；
- `duration_minutes` 由服务端钳制到 5–120，前端只负责计时，其数值不被信任；
- 番茄只用于看板展示专注时长：**不计入掌握度、不计入 streak、不进错题本**，
  也不触发任何排期/队列变化（`summarize_pomodoros` 仅供 dashboard 使用）。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LearningEvent
from app.services.events import record_event
from app.services.recompute import Event

POMODORO_COMPLETED = "pomodoro_completed"
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 120


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
