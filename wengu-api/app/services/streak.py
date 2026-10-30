"""P2-6 极简打卡：从 learning_events 事实推导，不落库、不调模型。

口径（与 TICKETS P2-6 对齐）：
- 打卡 = 当天产生任一作答事件（`attempt_correct` / `attempt_wrong`），
  含复习（`payload.kind="review"`）与自造同类题考核（quiz）；答错也算"来了"；
- 学习日优先取事件的 `payload.completed_on`（本地日期），缺失或非法回退
  `occurred_at` 的日期；不把 UTC 时间拼成本地日期；
- 锚定规则：今天有 → 从今天倒数；今天没有但昨天有 → 从昨天倒数，仍不算断；
  连续两天都没有才开始归零；
- 输出纯展示数据，只看"来了"，不据此下任何学习效果结论。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.services.recompute import ATTEMPT_CORRECT, ATTEMPT_WRONG, Event

RECENT_DAYS = 30
ATTEMPT_TYPES = frozenset({ATTEMPT_CORRECT, ATTEMPT_WRONG})


@dataclass(frozen=True)
class StreakDay:
    date: date
    done: bool


@dataclass(frozen=True)
class StreakSummary:
    today_done: bool
    current_streak: int
    longest_streak: int
    learning_days_total: int
    recent_days: tuple[StreakDay, ...]


def _payload(event: Event) -> Mapping[str, Any]:
    raw = event.payload
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, Mapping) else {}
    return raw if isinstance(raw, Mapping) else {}


def _fallback_day(moment: Any) -> date | None:
    if isinstance(moment, datetime):
        return moment.date()
    if isinstance(moment, date):
        return moment
    if isinstance(moment, str):
        try:
            return datetime.fromisoformat(moment).date()
        except ValueError:
            return None
    return None


def _learning_day(event: Event) -> date | None:
    """作答事件对应的学习日；非作答事件返回 None。"""

    if event.type not in ATTEMPT_TYPES:
        return None
    raw = _payload(event).get("completed_on")
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return _fallback_day(event.occurred_at)


def summarize_streak(events: Sequence[Event], today: date) -> StreakSummary:
    """从事件序列现算打卡摘要；同输入（与顺序无关）必得同一输出。"""

    days = {day for event in events if (day := _learning_day(event)) is not None}

    today_done = today in days
    if today_done:
        anchor: date | None = today
    elif (today - timedelta(days=1)) in days:
        anchor = today - timedelta(days=1)
    else:
        anchor = None

    current = 0
    cursor = anchor
    while cursor is not None and cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day

    start = today - timedelta(days=RECENT_DAYS - 1)
    recent = tuple(
        StreakDay(date=day, done=day in days)
        for day in (start + timedelta(days=offset) for offset in range(RECENT_DAYS))
    )

    return StreakSummary(
        today_done=today_done,
        current_streak=current,
        longest_streak=longest,
        learning_days_total=len(days),
        recent_days=recent,
    )
