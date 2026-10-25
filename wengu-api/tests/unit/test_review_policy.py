"""复习策略纯函数：固定阶梯、自适应因子、抗挫败三规则、毕业判定。"""

from __future__ import annotations

import math
from datetime import date

import pytest
from app.services.review_policy import (
    MATH_LADDER,
    MEMORY_LADDER,
    ReviewState,
    decide,
    initial_state,
    ladder_for,
    review_interval,
)

DAY = date(2026, 10, 25)


def test_initial_state_enters_first_rung_with_one_wrong() -> None:
    assert initial_state() == ReviewState(rung=0, times_wrong=1, trailing_correct=0)


def test_wrong_stays_on_rung_and_halves_after_repeat() -> None:
    decision = decide(initial_state(), correct=False, completed_on=DAY)

    assert decision.state == ReviewState(rung=0, times_wrong=2, trailing_correct=0)
    assert decision.base_days == MATH_LADDER[0]
    assert decision.interval_days == 1  # 1 天折半后仍保底 1 天
    assert decision.due_on == date(2026, 10, 26)
    assert decision.graduated is False


def test_correct_advances_rung_and_uses_next_base() -> None:
    decision = decide(initial_state(), correct=True, completed_on=DAY)

    assert decision.state == ReviewState(rung=1, times_wrong=0, trailing_correct=1)
    assert decision.base_days == MATH_LADDER[1]
    assert decision.interval_days == 10
    assert decision.due_on == date(2026, 11, 4)
    assert decision.graduated is False


def test_mastery_factor_and_repeat_wrong_halving() -> None:
    assert review_interval(10, mastery=0.0) == 10
    assert review_interval(10, mastery=0.5) == 30
    assert review_interval(10, mastery=1.0) == 50
    assert review_interval(10, mastery=1.0, times_wrong=2) == 25
    assert review_interval(10, mastery=2.0) == 50
    assert review_interval(10, mastery=-1.0) == 10
    assert review_interval(10, mastery=math.nan) == 10
    assert review_interval(1, mastery=0.5, times_wrong=3) == 2
    assert review_interval(1, mastery=0.0, times_wrong=3) == 1


def test_graduate_only_when_times_wrong_zero_and_tail_streak_reaches_three() -> None:
    state = ReviewState(rung=2, times_wrong=1, trailing_correct=2)
    decision = decide(state, correct=True, completed_on=DAY)

    assert decision.state == ReviewState(rung=2, times_wrong=0, trailing_correct=3)
    assert decision.graduated is True
    assert decision.interval_days is None
    assert decision.due_on is None


def test_correct_with_remaining_wrong_count_does_not_graduate() -> None:
    state = ReviewState(rung=2, times_wrong=2, trailing_correct=2)
    decision = decide(state, correct=True, completed_on=DAY)

    assert decision.state.times_wrong == 1
    assert decision.graduated is False
    assert decision.due_on is not None
    assert decision.interval_days == 30  # 折半只发生在更新后 times_wrong > 1


def test_repeat_wrong_on_high_rung_halves_interval() -> None:
    state = ReviewState(rung=2, times_wrong=1, trailing_correct=0)
    decision = decide(state, correct=False, completed_on=DAY)

    assert decision.state.times_wrong == 2
    assert decision.base_days == MATH_LADDER[2]
    assert decision.interval_days == 15


def test_wrong_never_regresses_rung_but_resets_streak() -> None:
    state = ReviewState(rung=2, times_wrong=0, trailing_correct=2)
    decision = decide(state, correct=False, completed_on=DAY)

    assert decision.state == ReviewState(rung=2, times_wrong=1, trailing_correct=0)
    assert decision.base_days == MATH_LADDER[2]
    assert decision.graduated is False


def test_memory_and_math_ladders_are_subject_specific() -> None:
    assert ladder_for("数学") == MATH_LADDER
    assert ladder_for("物理") == MATH_LADDER
    assert ladder_for("英语") == MEMORY_LADDER
    assert ladder_for("历史") == MEMORY_LADDER
    with pytest.raises(ValueError, match="未配置复习阶梯"):
        ladder_for("信息技术")


def test_invalid_state_or_ladder_is_rejected() -> None:
    with pytest.raises(ValueError, match="rung"):
        decide(ReviewState(rung=3, times_wrong=1, trailing_correct=0), correct=True, completed_on=DAY)
    with pytest.raises(ValueError, match="计数"):
        decide(ReviewState(rung=0, times_wrong=-1, trailing_correct=0), correct=True, completed_on=DAY)
    with pytest.raises(ValueError, match="阶梯"):
        decide(initial_state(), correct=True, completed_on=DAY, ladder=())
    with pytest.raises(ValueError, match="基础间隔"):
        review_interval(0)
