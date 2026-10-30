"""P2-6 极简打卡纯函数：锚定规则、断签、答错续签、考核事件与日期回退。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.services.recompute import ATTEMPT_CORRECT, ATTEMPT_WRONG, Event
from app.services.streak import RECENT_DAYS, StreakDay, summarize_streak

TODAY = date(2026, 10, 31)


def _event(
    day: date,
    *,
    verdict: str = "correct",
    completed_on: bool | str = True,
    mistake_id: int | None = 1,
    kind: str = "review",
    occurred_at: Any = None,
) -> Event:
    payload: dict[str, Any] = {"kind": kind}
    if completed_on is True:
        payload["completed_on"] = day.isoformat()
    elif isinstance(completed_on, str):
        payload["completed_on"] = completed_on
    return Event(
        type=ATTEMPT_CORRECT if verdict == "correct" else ATTEMPT_WRONG,
        actor="student",
        mistake_id=mistake_id,
        payload=payload,
        occurred_at=occurred_at or datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
    )


def _days_ago(*offsets: int) -> list[Event]:
    return [_event(TODAY - timedelta(days=offset)) for offset in offsets]


def test_consecutive_days_count_from_today() -> None:
    summary = summarize_streak(_days_ago(0, 1, 2), TODAY)

    assert summary.today_done is True
    assert summary.current_streak == 3
    assert summary.longest_streak == 3
    assert summary.learning_days_total == 3
    assert summary.recent_days[-1] == StreakDay(date=TODAY, done=True)


def test_gap_restarts_current_streak() -> None:
    # 昨天缺席：今天有作答 → 当前连续从今天重新起算，历史最长保留。
    summary = summarize_streak(_days_ago(0, 2, 3), TODAY)

    assert summary.today_done is True
    assert summary.current_streak == 1
    assert summary.longest_streak == 2


def test_today_missing_but_yesterday_done_anchors_yesterday() -> None:
    summary = summarize_streak(_days_ago(1, 2, 3), TODAY)

    assert summary.today_done is False
    assert summary.current_streak == 3
    assert summary.longest_streak == 3


def test_two_missing_days_reset_to_zero() -> None:
    summary = summarize_streak(_days_ago(2, 3, 4), TODAY)

    assert summary.today_done is False
    assert summary.current_streak == 0
    assert summary.longest_streak == 3


def test_wrong_answer_continues_streak() -> None:
    events = [_event(TODAY, verdict="wrong"), _event(TODAY - timedelta(days=1))]

    summary = summarize_streak(events, TODAY)

    assert summary.today_done is True
    assert summary.current_streak == 2


def test_quiz_event_without_mistake_counts() -> None:
    events = [_event(TODAY, mistake_id=None, kind="paper_quiz")]

    summary = summarize_streak(events, TODAY)

    assert summary.today_done is True
    assert summary.current_streak == 1


def test_missing_completed_on_falls_back_to_occurred_at() -> None:
    events = [_event(TODAY, completed_on=False)]

    summary = summarize_streak(events, TODAY)

    assert summary.today_done is True
    assert summary.current_streak == 1


def test_invalid_completed_on_falls_back_to_occurred_at() -> None:
    events = [_event(TODAY - timedelta(days=1), completed_on="不是日期")]

    summary = summarize_streak(events, TODAY)

    assert summary.today_done is False
    assert summary.current_streak == 1


def test_non_attempt_events_do_not_count() -> None:
    events = [
        Event(
            type="mistake_voided",
            actor="parent",
            mistake_id=1,
            payload={"completed_on": TODAY.isoformat()},
            occurred_at=datetime(2026, 10, 31, 12, tzinfo=UTC),
        )
    ]

    summary = summarize_streak(events, TODAY)

    assert summary.today_done is False
    assert summary.current_streak == 0
    assert summary.learning_days_total == 0


def test_duplicate_days_count_once() -> None:
    events = _days_ago(0, 0, 0, 1)

    summary = summarize_streak(events, TODAY)

    assert summary.current_streak == 2
    assert summary.learning_days_total == 2


def test_longest_streak_spans_multiple_runs() -> None:
    summary = summarize_streak(_days_ago(0, 1, 3, 4, 5, 6), TODAY)

    assert summary.current_streak == 2
    assert summary.longest_streak == 4


def test_empty_events_yield_zero_and_full_recent_window() -> None:
    summary = summarize_streak([], TODAY)

    assert summary.today_done is False
    assert summary.current_streak == 0
    assert summary.longest_streak == 0
    assert summary.learning_days_total == 0
    assert len(summary.recent_days) == RECENT_DAYS
    assert summary.recent_days[0].date == TODAY - timedelta(days=RECENT_DAYS - 1)
    assert summary.recent_days[-1].date == TODAY
    assert all(day.done is False for day in summary.recent_days)


def test_recent_window_marks_done_days_and_excludes_older() -> None:
    events = _days_ago(0, 29, 40)

    summary = summarize_streak(events, TODAY)

    assert summary.learning_days_total == 3
    assert summary.recent_days[0].date == TODAY - timedelta(days=29)
    assert summary.recent_days[0].done is True
    assert summary.recent_days[-1].done is True
    assert sum(1 for day in summary.recent_days if day.done) == 2


def test_summary_is_deterministic_and_order_independent() -> None:
    events = _days_ago(0, 1, 2, 4, 5)

    first = summarize_streak(events, TODAY)
    second = summarize_streak(events, TODAY)
    reversed_events = summarize_streak(list(reversed(events)), TODAY)
    shuffled = summarize_streak([events[2], events[4], events[0], events[3], events[1]], TODAY)

    assert first == second == reversed_events == shuffled
