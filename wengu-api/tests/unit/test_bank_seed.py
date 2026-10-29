"""P1-10 真实 seed 题库回归：2803 题全覆盖、固定种子稳定、缺口标记、配图净化。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.judge.normalize import judge_answer
from app.seed.bank import load_bank
from app.services.bank import find_same_type, replay

SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"


@pytest.fixture(scope="module")
def bank():
    return load_bank(SEEDS_DIR)


@pytest.mark.unit
def test_real_seed_counts(bank) -> None:
    assert bank.stats.total == 2803
    assert bank.stats.by_subject == {"数学": 1407, "物理": 368, "英语": 1028}
    assert bank.stats.by_type == {"choice": 1824, "numeric": 950, "self": 6, "short": 23}
    assert bank.stats.topics_total == 664
    assert bank.stats.topics_with_questions == 664
    assert bank.stats.dropped == {}
    assert bank.stats.verified == 1738
    assert bank.stats.unverifiable == 1065
    assert bank.stats.verify_reasons == {
        "choice_text_mismatch": 35,
        "no_verify": 532,
        "sandbox:bad_comprehension_target": 1,
        "sandbox:forbidden_call": 492,
        "sandbox:non_integer_exponent": 3,
        "sandbox:type_error": 2,
    }


@pytest.mark.unit
def test_every_topic_has_four_or_five_questions(bank) -> None:
    sizes = {len(items) for items in bank.by_topic.values()}
    assert sizes <= {4, 5}
    for topic_id, items in bank.by_topic.items():
        assert all(q.topic_id == topic_id for q in items)
        assert len({q.id for q in items}) == len(items)


@pytest.mark.unit
def test_fixed_seed_pick_is_stable_and_replayable(bank) -> None:
    first = find_same_type("cnm_001", 42, bank=bank)
    assert first.question_id == "cnm_001_q3"
    assert first.coverage == "ok"
    assert first.bank_gap is False
    assert find_same_type("cnm_001", 42, bank=bank) == first
    assert replay(first, bank=bank) == first

    picked = {find_same_type("cnm_001", seed, bank=bank).question_id for seed in range(20)}
    assert len(picked) > 1
    assert all(item.startswith("cnm_001_q") for item in picked if item)


@pytest.mark.unit
def test_missing_topic_returns_gap(bank) -> None:
    pick = find_same_type("cnm_999999", 1, bank=bank)
    assert pick.bank_gap is True
    assert pick.coverage == "gap"
    assert pick.question is None
    assert replay(pick, bank=bank) == pick


@pytest.mark.unit
def test_physics_thin_math_ok(bank) -> None:
    assert find_same_type("cnp_001", 7, bank=bank).coverage == "thin"
    assert find_same_type("cnm_001", 7, bank=bank).coverage == "ok"


@pytest.mark.unit
def test_every_verify_expression_was_checked_at_ingest(bank) -> None:
    """入库时每题 verify 都过 AST 沙箱并落状态；未通过者必须给原因。"""

    assert bank.stats.verified + bank.stats.unverifiable == bank.stats.total
    questions = [q for items in bank.by_topic.values() for q in items]
    assert len(questions) == 2803
    assert all(q.verify_status in ("verified", "unverifiable") for q in questions)
    assert all(
        q.verify_reason
        for q in questions
        if q.verify_status == "unverifiable"
    )
    assert all(q.verify for q in questions if q.verify_status == "verified")
    assert "mismatch" not in bank.stats.verify_reasons


@pytest.mark.unit
def test_every_seed_standard_answer_judges_itself_correct(bank) -> None:
    """P1-5 DoD：seed 题库 2803 题的标准答案过 judgeAnswer 全部判对。"""

    checked = 0
    for items in bank.by_topic.values():
        for question in items:
            outcome = judge_answer(
                question.answer,
                question.answer,
                acceptable=question.accept,
                unordered=question.unordered,
            )
            assert outcome.verdict == "correct", (question.id, question.answer, outcome)
            checked += 1
    assert checked == 2803


@pytest.mark.unit
def test_choice_distractors_are_judged_wrong(bank) -> None:
    """选择题的错误选项不得被判定为正确（含别名也不能放行）。"""

    checked = 0
    for items in bank.by_topic.values():
        for question in items:
            if question.type != "choice":
                continue
            distractor = next(
                (
                    choice.key
                    for choice in question.choices
                    if choice.key != question.answer
                    and choice.key not in question.accept
                ),
                None,
            )
            if distractor is None:
                continue
            outcome = judge_answer(
                distractor,
                question.answer,
                acceptable=question.accept,
                unordered=question.unordered,
            )
            assert outcome.verdict == "wrong", (question.id, distractor, outcome)
            checked += 1
    assert checked > 1000


@pytest.mark.unit
def test_seed_answers_accept_harmless_formatting(bank) -> None:
    """孩子常见的全角/尾标点差异不影响判对（抽样覆盖三类题型）。"""

    seen: set[str] = set()
    for items in bank.by_topic.values():
        for question in items:
            if question.type in seen:
                continue
            seen.add(question.type)
            decorated = f" {question.answer}。"
            outcome = judge_answer(
                decorated,
                question.answer,
                acceptable=question.accept,
                unordered=question.unordered,
            )
            assert outcome.verdict == "correct", (question.id, question.type, outcome)
    assert seen == {"choice", "numeric", "self", "short"}


@pytest.mark.unit
def test_all_figures_are_sanitized(bank) -> None:
    figures = [
        figure
        for items in bank.by_topic.values()
        for question in items
        for figure in [question.figure, *(choice.figure for choice in question.choices)]
        if figure
    ]
    assert len(figures) == 76
    for figure in figures:
        assert "<script" not in figure
        assert "onload" not in figure
        assert "javascript:" not in figure
        assert "foreignObject" not in figure
        assert "alert(" not in figure
    assert any("viewBox" in figure for figure in figures)
