"""judgeAnswer 规范化规则：每条规则都要有正例、反例，宁严勿松。"""

from __future__ import annotations

import pytest
from app.judge.normalize import PLACEHOLDER, JudgeOutcome, judge_answer


def _correct(student: str, standard: str, **kwargs) -> JudgeOutcome:
    outcome = judge_answer(student, standard, **kwargs)
    assert outcome.verdict == "correct", outcome
    return outcome


def _wrong(student: str, standard: str, **kwargs) -> JudgeOutcome:
    outcome = judge_answer(student, standard, **kwargs)
    assert outcome.verdict == "wrong", outcome
    return outcome


@pytest.mark.unit
@pytest.mark.parametrize(
    ("student", "standard"),
    [
        ("0.5", "1/2"),
        ("1/2", "0.5"),
        ("50%", "1/2"),
        ("1/2", "50%"),
        ("0.50", "1/2"),
        ("2/4", "1/2"),
        ("1.5", "1又1/2"),
        ("1 1/2", "1.5"),
        ("1½", "1.5"),
        ("-1/2", "-0.5"),
        ("−1/2", "-0.5"),
        ("1,000", "1000"),
        ("1,000元", "1000元"),
    ],
)
def test_numeric_equivalence_is_exact(student: str, standard: str) -> None:
    _correct(student, standard)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("student", "standard"),
    [
        ("0.333", "1/3"),
        ("0.333333", "1/3"),
        ("1/3", "0.333"),
        ("-0.5", "1/2"),
        ("2", "2.001"),
    ],
)
def test_numeric_false_positives_are_rejected(student: str, standard: str) -> None:
    _wrong(student, standard)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("student", "standard"),
    [
        ("5cm", "5厘米"),
        ("5 CM", "5cm"),
        ("1kg", "1千克"),
        ("1公斤", "1kg"),
        ("500ml", "500毫升"),
        ("2小时", "2h"),
        ("30°", "30度"),
        ("5元", "5块"),
        ("1平方米", "1m2"),
        ("1m²", "1平方米"),
        ("3立方厘米", "3cm3"),
    ],
)
def test_unit_aliases_match_but_do_not_convert(student: str, standard: str) -> None:
    _correct(student, standard)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("student", "standard"),
    [
        ("5", "5cm"),
        ("5cm", "5"),
        ("5cm", "5m"),
        ("1kg", "1000g"),
        ("1小时", "60分钟"),
        ("5斤", "5公斤"),
    ],
)
def test_missing_or_different_units_are_wrong(student: str, standard: str) -> None:
    _wrong(student, standard)


@pytest.mark.unit
def test_coordinate_normalization() -> None:
    _correct("（1，2）", "(1,2)")
    _correct("1,2", "(1,2)")
    _correct("(1, 2); (3, 4)", "（1，2）；（3，4）")
    _correct("(3,4);(1,2)", "(1,2);(3,4)", unordered=True)
    _wrong("(3,4);(1,2)", "(1,2);(3,4)")
    _wrong("(1,3)", "(1,2)")
    _wrong("(1,2,3)", "(1,2)")


@pytest.mark.unit
def test_choice_normalization() -> None:
    _correct("a", "A")
    _correct("A.", "a")
    _correct("（A）", "A")
    _correct("A,B", "A,B")
    _correct("AB", "A,B")
    _correct("B,A", "A,B", unordered=True)
    _wrong("B,A", "A,B")
    _wrong("AB", "A")
    _wrong("A,C", "A,B")


@pytest.mark.unit
def test_multi_answer_normalization() -> None:
    _correct("3,2", "2,3", unordered=True)
    _wrong("3,2", "2,3")
    _correct("3和2", "2,3", unordered=True)
    _correct("B或A", "A,B", unordered=True)
    _wrong("2,2", "2")
    _wrong("2", "2,3")
    _correct("1/2和0.5", "0.5和50%", unordered=True)


@pytest.mark.unit
def test_text_normalization() -> None:
    _correct("光合 作用", "光合作用")
    _correct("Apple", "apple")
    _correct("New York", "New York")
    _wrong("NewYork", "New York")
    _wrong("光合作用", "光合")
    _correct("饱和溶液", "饱和溶液")


@pytest.mark.unit
def test_soft_split_does_not_break_chinese_words() -> None:
    _correct("共和国", "共和国")
    _wrong("国共", "共和国", unordered=True)
    _wrong("苹果和梨", "梨和苹果", unordered=True)
    _correct("2和3", "3和2", unordered=True)


@pytest.mark.unit
def test_acceptable_aliases() -> None:
    outcome = _correct("50%", "二分之一", acceptable=["1/2", "二分之一"])
    assert outcome.reason == "accepted_alias"
    assert outcome.rule == "numeric"
    _correct("二分之一", "0.5", acceptable=["1/2", "二分之一"])


@pytest.mark.unit
def test_placeholder_always_manual() -> None:
    assert judge_answer(f"3{PLACEHOLDER}", "3").verdict == "uncertain"
    assert judge_answer("3", f"{PLACEHOLDER}").verdict == "uncertain"
    assert judge_answer("3", "3", acceptable=[PLACEHOLDER]).verdict == "correct"


@pytest.mark.unit
@pytest.mark.parametrize("student", [None, "", "   ", "。"])
def test_empty_student_is_manual(student) -> None:
    outcome = judge_answer(student, "3")
    assert outcome.verdict == "uncertain"
    assert outcome.reason == "empty_answer"


@pytest.mark.unit
@pytest.mark.parametrize("standard", [None, "", "   ", "。"])
def test_empty_reference_is_manual(standard) -> None:
    outcome = judge_answer("3", standard)
    assert outcome.verdict == "uncertain"
    assert outcome.reason == "empty_reference"


@pytest.mark.unit
def test_trailing_punctuation_is_ignored() -> None:
    _correct("3。", "3")
    _correct("A.", "a")
    _correct("光合作用。", "光合作用")


@pytest.mark.unit
def test_reason_and_rule_are_stable() -> None:
    assert judge_answer("0.5", "1/2") == JudgeOutcome("correct", "numeric_equal", "numeric")
    assert judge_answer("5cm", "5厘米") == JudgeOutcome(
        "correct", "numeric_unit_equal", "numeric_unit"
    )
    assert judge_answer("（1，2）", "(1,2)").reason == "coordinate_equal"
    assert judge_answer("a", "A").reason == "choice_equal"
    assert judge_answer("3,2", "2,3", unordered=True).reason == "multiset_equal"
    assert judge_answer("苹果", "苹果").reason == "text_equal"
    assert judge_answer("4", "3") == JudgeOutcome("wrong", "mismatch")
