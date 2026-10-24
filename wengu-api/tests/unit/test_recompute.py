"""确定性重算骨架：掌握度/毕业/统计全部从事件序列推导，同输入同输出。"""

from __future__ import annotations

import pytest
from app.services.recompute import (
    ATTEMPT_CORRECT,
    ATTEMPT_WRONG,
    Event,
    is_graduated,
    mastery,
    stats,
)


def _attempt(mistake_id: int, correct: bool, seq: int, concept_id: str = "cnm_x") -> Event:
    return Event(
        type=ATTEMPT_CORRECT if correct else ATTEMPT_WRONG,
        actor="student",
        mistake_id=mistake_id,
        payload={"concept_id": concept_id},
        occurred_at=seq,
    )


@pytest.mark.unit
def test_mastery_is_correct_ratio() -> None:
    events = [
        _attempt(1, True, 1, "cnm_a"),
        _attempt(2, True, 2, "cnm_a"),
        _attempt(3, False, 3, "cnm_a"),
        _attempt(4, True, 4, "cnm_b"),  # 别的知识点不计入
    ]
    assert mastery(events, "cnm_a") == pytest.approx(2 / 3)
    assert mastery(events, "cnm_b") == 1.0
    assert mastery(events, "cnm_absent") == 0.0  # 无信号 = 0，不虚假精确


@pytest.mark.unit
def test_is_graduated_requires_tail_streak_of_three() -> None:
    assert not is_graduated([_attempt(1, True, 1), _attempt(1, True, 2)], 1)
    assert is_graduated([_attempt(1, True, 1), _attempt(1, True, 2), _attempt(1, True, 3)], 1)
    # 答错不断阶梯，但断毕业 streak
    broken = [_attempt(1, True, 1), _attempt(1, True, 2), _attempt(1, False, 3),
              _attempt(1, True, 4), _attempt(1, True, 5)]
    assert not is_graduated(broken, 1)
    assert is_graduated([*broken, _attempt(1, True, 6)], 1)
    # 与 mistake 无关的事件不影响
    assert not is_graduated([_attempt(2, True, 1), _attempt(2, True, 2), _attempt(2, True, 3)], 1)


@pytest.mark.unit
def test_is_graduated_uses_occurred_order_not_input_order() -> None:
    # 时间序：对(1)、错(2)、对(3)、对(4) → streak=2 不毕业；
    # 若错用输入序（错在最前）会得到 streak=3 → 本用例能区分是否真按 occurred_at 排序。
    out_of_order = [_attempt(1, False, 2), _attempt(1, True, 1),
                    _attempt(1, True, 3), _attempt(1, True, 4)]
    assert not is_graduated(out_of_order, 1)


@pytest.mark.unit
def test_stats_counts() -> None:
    events = [
        _attempt(1, True, 1),
        _attempt(1, False, 2),
        Event(type="mistake_confirmed", actor="parent", occurred_at=3),
    ]
    result = stats(events)
    assert result["total_events"] == 3
    assert result["by_type"] == {ATTEMPT_CORRECT: 1, ATTEMPT_WRONG: 1, "mistake_confirmed": 1}
    assert result["attempts_correct"] == 1
    assert result["attempts_wrong"] == 1
    assert result["attempt_accuracy"] == pytest.approx(0.5)


@pytest.mark.unit
def test_stats_accuracy_none_without_attempts() -> None:
    assert stats([Event(type="mistake_confirmed", actor="student")])["attempt_accuracy"] is None


@pytest.mark.unit
def test_recompute_is_deterministic_and_accepts_mapping_rows() -> None:
    """同事件序列重放 → 同结果；函数同时接受 ORM 行/字典视图（payload 为 JSON 字符串）。"""

    import json

    rows = [
        {"type": ATTEMPT_CORRECT, "actor": "student", "mistake_id": 1,
         "payload": json.dumps({"concept_id": "cnm_a"}), "occurred_at": 1},
        {"type": ATTEMPT_WRONG, "actor": "student", "mistake_id": 1,
         "payload": json.dumps({"concept_id": "cnm_a"}), "occurred_at": 2},
    ]
    first = (mastery(rows, "cnm_a"), is_graduated(rows, 1), stats(rows))
    second = (mastery(rows, "cnm_a"), is_graduated(rows, 1), stats(rows))
    assert first == second
    assert first[0] == 0.5
