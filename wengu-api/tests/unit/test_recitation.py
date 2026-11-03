"""P3-3a 背诵阶梯纯函数：逐档推进、答错不倒退、从完成日起算、顶层毕业。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.services.recitation import (
    VERDICT_FORGOT,
    VERDICT_REMEMBERED,
    decide,
    is_due,
    replay_state,
)
from app.services.review_policy import MEMORY_LADDER

DAY = date(2026, 11, 3)


def _offset(days: int) -> date:
    return DAY + timedelta(days=days)


def test_remembered_walks_every_ladder_step_from_review_date() -> None:
    rung = 0
    current = DAY
    expected = list(MEMORY_LADDER[1:])  # 首答 remembered 从第 1 档起算 3 天

    for interval in expected:
        decision = decide(rung, VERDICT_REMEMBERED, current)
        rung = decision.rung
        assert decision.scheduled_next == current + timedelta(days=interval)
        assert decision.graduated is False
        current = decision.scheduled_next


def test_remembered_at_top_rung_graduates_without_scheduling() -> None:
    top = len(MEMORY_LADDER) - 1

    decision = decide(top, VERDICT_REMEMBERED, DAY)

    assert decision.rung == top
    assert decision.scheduled_next is None
    assert decision.graduated is True


def test_forgot_keeps_rung_and_schedules_from_review_date() -> None:
    first = decide(0, VERDICT_FORGOT, DAY)
    assert first.rung == 0
    assert first.scheduled_next == DAY + timedelta(days=MEMORY_LADDER[0])
    assert first.graduated is False

    third = decide(3, VERDICT_FORGOT, DAY)
    assert third.rung == 3
    assert third.scheduled_next == DAY + timedelta(days=MEMORY_LADDER[3])


def test_forgot_at_top_rung_keeps_waiting_instead_of_graduating() -> None:
    top = len(MEMORY_LADDER) - 1

    decision = decide(top, VERDICT_FORGOT, DAY)

    assert decision.rung == top
    assert decision.scheduled_next == DAY + timedelta(days=MEMORY_LADDER[top])
    assert decision.graduated is False


def test_schedule_starts_from_actual_review_day_not_today() -> None:
    late = decide(1, VERDICT_REMEMBERED, _offset(-10))

    assert late.scheduled_next == _offset(-10) + timedelta(days=MEMORY_LADDER[2])


def test_replay_state_is_deterministic_and_order_sensitive() -> None:
    history = [
        (DAY, VERDICT_REMEMBERED),
        (_offset(3), VERDICT_FORGOT),
        (_offset(6), VERDICT_REMEMBERED),
    ]

    state = replay_state(history)

    assert state.rung == 2
    assert state.reviewed_on == _offset(6)
    assert state.scheduled_next == _offset(6) + timedelta(days=MEMORY_LADDER[2])
    assert state.graduated is False
    assert state == replay_state(history)


def test_replay_empty_history_is_new_and_due() -> None:
    state = replay_state([])

    assert state.rung == 0
    assert state.reviewed_on is None
    assert state.scheduled_next is None
    assert is_due(state, DAY) is True


def test_is_due_only_on_or_after_scheduled_day() -> None:
    state = replay_state([(DAY, VERDICT_REMEMBERED)])

    assert state.scheduled_next == _offset(3)
    assert is_due(state, _offset(2)) is False
    assert is_due(state, _offset(3)) is True
    assert is_due(state, _offset(4)) is True


def test_graduated_item_is_never_due() -> None:
    history = [(DAY, VERDICT_REMEMBERED)] * 5

    state = replay_state(history)

    assert state.graduated is True
    assert state.scheduled_next is None
    assert is_due(state, _offset(365)) is False


@pytest.mark.parametrize("verdict", ["", "correct", "remembered ", None])
def test_unknown_verdict_is_rejected(verdict: object) -> None:
    with pytest.raises(ValueError):
        decide(0, verdict, DAY)  # type: ignore[arg-type]


@pytest.mark.parametrize("rung", [-1, len(MEMORY_LADDER)])
def test_rung_outside_ladder_is_rejected(rung: int) -> None:
    with pytest.raises(ValueError):
        decide(rung, VERDICT_REMEMBERED, DAY)
