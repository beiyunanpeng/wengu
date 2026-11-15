"""P2-12 复习日历：只读按日投影（v2.7 §18 D9），非自动排课、不落库、零模型。

口径（三条坑的落点）：
- `review_schedules` 无 status 列：开放行 = `completed_at IS NULL`，历史行 = 非空；
  planned 取区间内 `due_date` 的行（含历史），统一按 `Mistake.status=active` 过滤
  （与 `due_queue` 同一把尺）；`completed` 由 `completed_at` 判定；
  `overdue` = 未完成且 `due_date < today`。
- `kind` 沿用 `review.task_pick`/`task_kind`（与 `due_queue` 共用判定，不另建）；
  它是按查询时 `primary_topic_id` 现算的值（P1-18 后主考点可事后更正），**不是快照、不落库**。
- `done` 按日归属采用 **streak 的回退规则**（`completed_on` 优先 → 回退 `occurred_at` 的日期），
  但白名单是日历自己的 9 个真实 type：**不复用** `streak._learning_day`（它只收 3 个 type），
  也**不照抄** dashboard `_review_completed_on`/`_recitation_completed_on` 那套缺
  `completed_on` 就返回 None 的口径（否则 5 类无 completed_on 的事件整类消失）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LearningEvent, Mistake, ReviewSchedule
from app.models.mistakes import MISTAKE_ACTIVE
from app.services.bank import get_runtime_bank
from app.services.mistakes import (
    MISTAKE_LABELED,
    MISTAKE_PRIMARY_TOPIC_SET,
    MISTAKE_REACTIVATED_EVENT,
    MISTAKE_VOIDED_EVENT,
)
from app.services.pomodoro import POMODORO_COMPLETED
from app.services.recompute import (
    ATTEMPT_CORRECT,
    ATTEMPT_WRONG,
    RECITATION_REVIEWED,
    Event,
)
from app.services.review import REVIEW_SCHEDULED, task_kind, task_pick
from app.services.streak import _fallback_day, _payload

# 展示白名单：逐条对齐真实写入的 9 个 type（分散在 6 个 services 文件），不臆造、
# 不含盘上不存在的 mistake_confirmed。用常量引用而非字面串，改名即编译期暴露。
CALENDAR_EVENT_TYPES = frozenset(
    {
        ATTEMPT_CORRECT,
        ATTEMPT_WRONG,
        RECITATION_REVIEWED,
        POMODORO_COMPLETED,
        REVIEW_SCHEDULED,
        MISTAKE_LABELED,
        MISTAKE_VOIDED_EVENT,
        MISTAKE_REACTIVATED_EVENT,
        MISTAKE_PRIMARY_TOPIC_SET,
    }
)

DEFAULT_PAST_DAYS = 7
DEFAULT_FUTURE_DAYS = 30
MAX_SPAN_DAYS = 92


class CalendarRangeError(ValueError):
    """from/to 非法（倒置或超跨度）；API 层映射 422。"""


@dataclass(frozen=True)
class CalendarPlanned:
    mistake_id: int
    due_date: date
    kind: str
    overdue: bool
    completed: bool


@dataclass(frozen=True)
class CalendarDone:
    date: date
    type: str
    mistake_id: int | None


@dataclass(frozen=True)
class CalendarDay:
    date: date
    planned: tuple[CalendarPlanned, ...]
    done: tuple[CalendarDone, ...]


def _calendar_day(event: Event) -> date | None:
    """日历按日归属：白名单内 completed_on 优先、否则回退 occurred_at（streak 同规则）。

    与 streak._learning_day 的回退实现逐行同构（复用 _payload/_fallback_day），
    仅白名单不同；白名单外返回 None。
    """

    if event.type not in CALENDAR_EVENT_TYPES:
        return None
    raw = _payload(event).get("completed_on")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return _fallback_day(event.occurred_at)


def resolve_range(
    today: date, start: date | None, end: date | None
) -> tuple[date, date]:
    lo = start if start is not None else today - timedelta(days=DEFAULT_PAST_DAYS)
    hi = end if end is not None else today + timedelta(days=DEFAULT_FUTURE_DAYS)
    if hi < lo:
        raise CalendarRangeError("from 不能晚于 to")
    if (hi - lo).days > MAX_SPAN_DAYS:
        raise CalendarRangeError(f"跨度不能超过 {MAX_SPAN_DAYS} 天")
    return lo, hi


async def build_calendar(
    session: AsyncSession,
    today: date,
    start: date | None = None,
    end: date | None = None,
) -> tuple[CalendarDay, ...]:
    """区间内逐日投影（含空日），纯查询、不写库。"""

    lo, hi = resolve_range(today, start, end)

    rows = (
        await session.execute(
            select(ReviewSchedule, Mistake)
            .join(Mistake, Mistake.id == ReviewSchedule.mistake_id)
            .where(
                ReviewSchedule.due_date >= lo,
                ReviewSchedule.due_date <= hi,
                Mistake.status == MISTAKE_ACTIVE,
            )
            .order_by(ReviewSchedule.due_date, Mistake.id, ReviewSchedule.id)
        )
    ).all()
    bank = await get_runtime_bank(session)
    planned_by_day: dict[date, list[CalendarPlanned]] = {}
    for schedule, mistake in rows:
        completed = schedule.completed_at is not None
        planned_by_day.setdefault(schedule.due_date, []).append(
            CalendarPlanned(
                mistake_id=mistake.id,
                due_date=schedule.due_date,
                kind=task_kind(task_pick(mistake, schedule, bank)),
                overdue=(not completed) and schedule.due_date < today,
                completed=completed,
            )
        )

    # 按 type 白名单扫（ix_learning_events_type），归属日在 Python 侧用 streak 规则算：
    # occurred_at 以 UTC 落库、completed_on 是本地日期，SQL 日期边界易错，故不在 SQL 截日。
    event_rows = (
        await session.scalars(
            select(LearningEvent)
            .where(LearningEvent.type.in_(CALENDAR_EVENT_TYPES))
            .order_by(LearningEvent.id)
        )
    ).all()
    done_by_day: dict[date, list[CalendarDone]] = {}
    for row in event_rows:
        event = Event(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        day = _calendar_day(event)
        if day is None or day < lo or day > hi:
            continue
        done_by_day.setdefault(day, []).append(
            CalendarDone(date=day, type=row.type, mistake_id=row.mistake_id)
        )

    return tuple(
        CalendarDay(
            date=lo + timedelta(days=offset),
            planned=tuple(planned_by_day.get(lo + timedelta(days=offset), ())),
            done=tuple(done_by_day.get(lo + timedelta(days=offset), ())),
        )
        for offset in range((hi - lo).days + 1)
    )
