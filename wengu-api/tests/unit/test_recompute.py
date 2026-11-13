"""确定性重算骨架：掌握度/毕业/统计全部从事件序列推导，同输入同输出。"""

from __future__ import annotations

import pytest
from app.services.recompute import (
    ATTEMPT_CORRECT,
    ATTEMPT_WRONG,
    MASTERY_MIN_SAMPLE,
    MASTERY_WINDOW_SIZE,
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
def test_mastery_counts_student_self_and_system_quiz_only() -> None:
    """双来源：自评与系统考核各计 1 次；manual 不进掌握度。"""

    def sourced(correct: bool, seq: int, source: str) -> Event:
        return Event(
            type=ATTEMPT_CORRECT if correct else ATTEMPT_WRONG,
            actor="student",
            payload={"concept_id": "cnm_a", "source": source},
            occurred_at=seq,
        )

    events = [
        sourced(True, 1, "student_self"),
        sourced(False, 2, "system_quiz"),
        sourced(True, 3, "manual"),
        sourced(False, 4, "manual"),
    ]
    assert mastery(events, "cnm_a") == 0.5
    assert mastery([sourced(True, 1, "manual")], "cnm_a") == 0.0


@pytest.mark.unit
def test_mastery_counts_review_events_with_multiple_concepts() -> None:
    """一次复习挂多 concept 时，同一事件对各 concept 各计 1 次。"""

    event = Event(
        type=ATTEMPT_CORRECT,
        actor="student",
        mistake_id=1,
        payload={"concept_ids": [7, 9], "source": "system_quiz"},
        occurred_at=1,
    )
    assert mastery([event], 7) == 1.0
    assert mastery([event], 9) == 1.0
    assert mastery([event], 8) == 0.0


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


@pytest.mark.unit
def test_grading_versions_only_latest_counts() -> None:
    """申诉/改判追加版本，但掌握度与统计只看同一 grading 的最高版本。"""

    def graded(grading_id: int, version: int, correct: bool, seq: int) -> Event:
        return Event(
            type=ATTEMPT_CORRECT if correct else ATTEMPT_WRONG,
            actor="student",
            payload={
                "grading_id": grading_id,
                "grading_version": version,
                "concept_id": "cnm_a",
            },
            occurred_at=seq,
        )

    events = [
        graded(7, 1, False, 1),
        graded(7, 2, True, 2),
        graded(7, 3, False, 3),
        graded(8, 1, True, 4),
    ]
    assert mastery(events, "cnm_a") == pytest.approx(0.5)

    result = stats(events)
    assert result["total_events"] == 2
    assert result["attempts_correct"] == 1
    assert result["attempts_wrong"] == 1
    assert result["attempt_accuracy"] == pytest.approx(0.5)


# --- P4-5：mastery 近期窗口（N=20，样本<5 回退全历史）八条 DoD ---


@pytest.mark.unit
def test_mastery_window_all_correct_in_window() -> None:
    """DoD①：窗口内全对 → 1.0，即便更早历史有错（全历史会是 20/30）。"""

    events = [_attempt(1, i > 10, i, "cnm_a") for i in range(1, 31)]  # 前 10 错、后 20 对
    assert mastery(events, "cnm_a") == 1.0


@pytest.mark.unit
def test_mastery_window_all_wrong_drops_despite_correct_history() -> None:
    """DoD②：窗口内全错但历史全对 → 显著下降，证明截断生效而非全历史。"""

    events = [_attempt(1, i <= 20, i, "cnm_a") for i in range(1, 41)]  # 前 20 对、后 20 错
    result = mastery(events, "cnm_a")
    assert result == pytest.approx(0.0)
    assert result < 0.5  # 全历史正确率会是 20/40=0.5；窗口把它压到 0


@pytest.mark.unit
def test_mastery_falls_back_to_full_history_below_min_sample() -> None:
    """DoD③：样本 < MASTERY_MIN_SAMPLE → 回退全历史，与不截断一致。"""

    n = MASTERY_MIN_SAMPLE - 1  # 4 条：3 对 1 错
    events = [_attempt(1, i != n, i, "cnm_a") for i in range(1, n + 1)]
    assert mastery(events, "cnm_a") == pytest.approx((n - 1) / n)  # 3/4，全历史


@pytest.mark.unit
def test_mastery_window_boundary_at_size_and_size_plus_one() -> None:
    """DoD④：恰好 N 条最旧的错仍在窗口；N+1 条把最旧的错挤出窗口。"""

    n = MASTERY_WINDOW_SIZE  # 20
    twenty = [_attempt(1, i != 1, i, "cnm_a") for i in range(1, n + 1)]  # seq1 错、其余对
    assert mastery(twenty, "cnm_a") == pytest.approx((n - 1) / n)  # 19/20，错仍在窗口
    twenty_one = [_attempt(1, i != 1, i, "cnm_a") for i in range(1, n + 2)]  # 多一条对
    assert mastery(twenty_one, "cnm_a") == 1.0  # 末 20 全对，最旧的错被挤出


@pytest.mark.unit
def test_mastery_window_still_dedupes_grading_versions() -> None:
    """DoD⑤：窗口生效（≥20 条）时，申诉改判仍只计最高 grading_version。"""

    def graded(grading_id: int, version: int, correct: bool, seq: int) -> Event:
        return Event(
            type=ATTEMPT_CORRECT if correct else ATTEMPT_WRONG,
            actor="student",
            payload={"grading_id": grading_id, "grading_version": version, "concept_id": "cnm_a"},
            occurred_at=seq,
        )

    background = [_attempt(1, True, i, "cnm_a") for i in range(1, 20)]  # 19 条对 seq1..19
    appeals = [graded(99, 1, True, 20), graded(99, 2, False, 21), graded(99, 3, False, 22)]
    # dedup 只留最高 v3(错) → 19 对 + 1 错 = 20 条，窗口=全 20 → 19/20
    assert mastery(background + appeals, "cnm_a") == pytest.approx(19 / 20)


@pytest.mark.unit
def test_mastery_window_per_concept_supports_min() -> None:
    """DoD⑥：各 concept 独立窗口；排期取最小的契约不变（min 由 review._mastery_for 执行）。"""

    a = [_attempt(1, True, i, "cnm_a") for i in range(1, 21)]  # 20 全对 → 1.0
    b = [_attempt(2, False, i, "cnm_b") for i in range(1, 21)]  # 20 全错 → 0.0
    events = a + b
    assert mastery(events, "cnm_a") == 1.0
    assert mastery(events, "cnm_b") == 0.0
    assert min(mastery(events, c) for c in ("cnm_a", "cnm_b")) == 0.0


@pytest.mark.unit
def test_is_graduated_unaffected_by_mastery_window() -> None:
    """DoD⑦：毕业仍看 mistake 尾部连对（全历史），不受 mastery 窗口截断影响。"""

    events = [_attempt(1, i > 27, i, "cnm_a") for i in range(1, 31)]  # 前 27 错、尾 3 对
    assert is_graduated(events, 1) is True  # 尾部连对 3 → 毕业，既有规则一字未改
    assert mastery(events, "cnm_a") == pytest.approx(3 / 20)  # 窗口末 20 = 17 错 + 3 对


@pytest.mark.unit
def test_mastery_window_is_deterministic_replay() -> None:
    """DoD⑧：同序列两次重算相等；打乱输入顺序也不变（按 occurred_at 定窗）。"""

    events = [_attempt(1, i % 3 != 0, i, "cnm_a") for i in range(1, 41)]  # 40 条
    first = mastery(events, "cnm_a")
    assert first == mastery(events, "cnm_a")  # 幂等
    assert mastery(list(reversed(events)), "cnm_a") == first  # 输入序无关
