"""P2-2 番茄钟纯函数：duration 钳制、看板汇总、不影响既有信号。"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from app.services.pomodoro import (
    MAX_DURATION_MINUTES,
    MIN_DURATION_MINUTES,
    POMODORO_COMPLETED,
    clamp_duration,
    summarize_pomodoros,
)
from app.services.recompute import (
    ATTEMPT_CORRECT,
    Event,
    is_graduated,
    mastery,
)
from app.services.streak import summarize_streak


def _pomodoro(
    day: date, minutes: int | str, *, occurred_at: datetime | None = None
) -> Event:
    payload: dict[str, object] = {
        "duration_minutes": minutes,
        "completed_on": day.isoformat(),
    }
    return Event(
        type=POMODORO_COMPLETED,
        actor="student",
        payload=payload,
        occurred_at=occurred_at or datetime(2026, 11, 4, 9, 0),
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (-5, MIN_DURATION_MINUTES),
        (0, MIN_DURATION_MINUTES),
        (1, MIN_DURATION_MINUTES),
        (5, 5),
        (25, 25),
        (120, 120),
        (121, MAX_DURATION_MINUTES),
        (9999, MAX_DURATION_MINUTES),
    ],
)
def test_duration_is_clamped_to_5_120(raw: int, expected: int) -> None:
    assert clamp_duration(raw) == expected


@pytest.mark.parametrize("raw", [True, False, "25", 3.5, None])
def test_duration_rejects_non_int(raw: object) -> None:
    with pytest.raises(TypeError):
        clamp_duration(raw)  # type: ignore[arg-type]


def test_summary_counts_today_and_this_week_only() -> None:
    today = date(2026, 11, 4)  # 周三
    week_start = date(2026, 11, 2)
    events = [
        _pomodoro(today, 25),
        _pomodoro(today, 40),
        _pomodoro(date(2026, 11, 2), 30),
        _pomodoro(date(2026, 10, 25), 60),  # 上一周
        _pomodoro(today, "35"),  # 非法时长不计分钟
        Event(
            type=ATTEMPT_CORRECT,
            actor="student",
            payload={"completed_on": today.isoformat()},
            occurred_at=datetime(2026, 11, 4, 9, 0),
        ),
    ]

    summary = summarize_pomodoros(events, today, week_start)

    assert summary.pomodoros_today == 3
    assert summary.focus_minutes_this_week == 25 + 40 + 30


def test_summary_falls_back_to_occurred_at_day() -> None:
    event = Event(
        type=POMODORO_COMPLETED,
        actor="student",
        payload={"duration_minutes": 25},
        occurred_at=datetime(2026, 11, 4, 23, 30, tzinfo=UTC),
    )

    summary = summarize_pomodoros(
        [event], date(2026, 11, 4), date(2026, 11, 2)
    )

    assert summary.pomodoros_today == 1
    assert summary.focus_minutes_this_week == 25


def test_empty_events_are_all_zero() -> None:
    summary = summarize_pomodoros([], date(2026, 11, 4), date(2026, 11, 2))

    assert summary.pomodoros_today == 0
    assert summary.focus_minutes_this_week == 0


def test_pomodoro_does_not_change_mastery_streak_or_graduation() -> None:
    today = date(2026, 11, 4)
    attempts = [
        Event(
            type=ATTEMPT_CORRECT,
            actor="student",
            mistake_id=1,
            payload={
                "concept_id": 7,
                "source": "student_self",
                "completed_on": today.isoformat(),
            },
            occurred_at=datetime(2026, 11, 4, 9, 0),
        )
    ]
    with_pomodoro = [*attempts, _pomodoro(today, 25)]

    assert mastery(with_pomodoro, 7) == mastery(attempts, 7) == 1.0
    assert summarize_streak(with_pomodoro, today) == summarize_streak(
        attempts, today
    )
    assert is_graduated(with_pomodoro, 1) == is_graduated(attempts, 1)
    assert is_graduated(attempts, 1) is False
