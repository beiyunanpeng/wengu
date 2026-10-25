"""P1-6 复习策略纯函数：只算下一次间隔，不落库、不生成排期。

Phase 0 边界表未回填前不自动排复习；本模块只提供确定性接口，
P1-7 闸门回填后再由调度服务调用并写 review_schedules。

契约（设计文档 §5.4）：
- 实际间隔 = 基础档 × (1 + mastery × 4)，times_wrong > 1 时折半，最少 1 天；
- 答错不倒退阶梯，只 +times_wrong、清尾部连对；
- 答对阶梯前进、times_wrong 减一；times_wrong 归零且尾部连对 ≥3 才毕业；
- 到期日从实际完成日起算。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.services.recompute import GRADUATION_STREAK

MATH_LADDER: tuple[int, ...] = (1, 10, 30)
MEMORY_LADDER: tuple[int, ...] = (1, 3, 7, 14, 30)

MATH_SUBJECTS = frozenset({"数学", "物理", "化学"})
MEMORY_SUBJECTS = frozenset(
    {"语文", "英语", "历史", "道德与法治", "道法", "生物", "地理"}
)

SUBJECT_LADDERS: dict[str, tuple[int, ...]] = {
    **{subject: MATH_LADDER for subject in MATH_SUBJECTS},
    **{subject: MEMORY_LADDER for subject in MEMORY_SUBJECTS},
}


@dataclass(frozen=True)
class ReviewState:
    rung: int
    times_wrong: int
    trailing_correct: int


@dataclass(frozen=True)
class ReviewDecision:
    state: ReviewState
    base_days: int
    interval_days: int | None
    due_on: date | None
    graduated: bool


def initial_state() -> ReviewState:
    """新错题首次入复习：第 0 档，错题计数从 1 起（首次答错已经发生）。"""

    return ReviewState(rung=0, times_wrong=1, trailing_correct=0)


def ladder_for(subject: str) -> tuple[int, ...]:
    try:
        return SUBJECT_LADDERS[subject]
    except KeyError:
        raise ValueError(f"未配置复习阶梯: {subject}") from None


def _validated(
    state: ReviewState, ladder: tuple[int, ...]
) -> tuple[int, ...]:
    if not ladder or any(step < 1 for step in ladder):
        raise ValueError("阶梯必须是正整数序列")
    if state.rung < 0 or state.rung >= len(ladder):
        raise ValueError("rung 超出阶梯范围")
    if state.times_wrong < 0 or state.trailing_correct < 0:
        raise ValueError("计数不能为负")
    return ladder


def review_interval(
    base_days: int,
    *,
    mastery: float = 0.0,
    times_wrong: int = 1,
) -> int:
    """实际间隔 = 基础档 × (1 + mastery×4)，多次错题折半，最少 1 天。"""

    if base_days < 1:
        raise ValueError("基础间隔必须 ≥1 天")
    value = 0.0 if not math.isfinite(mastery) else min(1.0, max(0.0, mastery))
    interval = math.ceil(base_days * (1 + value * 4))
    if times_wrong > 1:
        interval = math.ceil(interval / 2)
    return max(1, interval)


def decide(
    state: ReviewState,
    *,
    correct: bool,
    completed_on: date,
    mastery: float = 0.0,
    ladder: tuple[int, ...] = MATH_LADDER,
) -> ReviewDecision:
    """输入当前状态与本次结果，输出下一状态与到期日；纯函数、无副作用。"""

    _validated(state, ladder)

    if correct:
        next_state = ReviewState(
            rung=min(state.rung + 1, len(ladder) - 1),
            times_wrong=max(0, state.times_wrong - 1),
            trailing_correct=state.trailing_correct + 1,
        )
        base_days = ladder[next_state.rung]
        graduated = (
            next_state.times_wrong == 0
            and next_state.trailing_correct >= GRADUATION_STREAK
        )
    else:
        next_state = ReviewState(
            rung=state.rung,
            times_wrong=state.times_wrong + 1,
            trailing_correct=0,
        )
        base_days = ladder[next_state.rung]
        graduated = False

    if graduated:
        return ReviewDecision(
            state=next_state,
            base_days=base_days,
            interval_days=None,
            due_on=None,
            graduated=True,
        )

    interval = review_interval(
        base_days, mastery=mastery, times_wrong=next_state.times_wrong
    )
    return ReviewDecision(
        state=next_state,
        base_days=base_days,
        interval_days=interval,
        due_on=completed_on + timedelta(days=interval),
        graduated=False,
    )
