"""P1-4 提取质量前置闸门：纯函数、零模型、零数据库。"""

from __future__ import annotations

import pytest
from app.providers.base import ExtractedProblem
from app.services.extraction import (
    GATE_FIGURE,
    GATE_MANUAL,
    GATE_READY,
    REASON_ANSWER_EMPTY,
    REASON_COMPLETENESS_UNKNOWN,
    REASON_FIGURE,
    REASON_PLACEHOLDER,
    REASON_PROBLEM_EMPTY,
    REASON_PROBLEM_INCOMPLETE,
    REASON_WHOLE_PAGE,
    SOURCE_SLICE,
    SOURCE_WHOLE_PAGE,
    ExtractionRejected,
    apply_extraction_gate,
    detect_figure_keywords,
)


def _problem(
    text: str = "1. 计算：1+1=____",
    answer: str | None = "2",
    *,
    complete: bool | None = True,
    confidence: float | None = 0.9,
) -> ExtractedProblem:
    return ExtractedProblem(
        problem_text=text,
        student_answer=answer,
        confidence=confidence,
        problem_complete=complete,
    )


def test_complete_answer_passes_the_gate() -> None:
    decision = apply_extraction_gate(_problem(), source_kind=SOURCE_SLICE)

    assert decision.gate_status == GATE_READY
    assert decision.review_reasons == ()
    assert decision.problem_text == "1. 计算：1+1=____"
    assert decision.student_answer == "2"
    assert decision.problem_complete is True


def test_empty_problem_routes_to_manual() -> None:
    decision = apply_extraction_gate(_problem(text="  \n\t "), source_kind=SOURCE_SLICE)

    assert decision.gate_status == GATE_MANUAL
    assert REASON_PROBLEM_EMPTY in decision.review_reasons


def test_incomplete_and_unknown_completeness_both_route_to_manual() -> None:
    incomplete = apply_extraction_gate(
        _problem(complete=False), source_kind=SOURCE_SLICE
    )
    unknown = apply_extraction_gate(_problem(complete=None), source_kind=SOURCE_SLICE)

    assert incomplete.gate_status == GATE_MANUAL
    assert REASON_PROBLEM_INCOMPLETE in incomplete.review_reasons
    assert unknown.gate_status == GATE_MANUAL
    assert REASON_COMPLETENESS_UNKNOWN in unknown.review_reasons


def test_placeholder_in_problem_or_answer_routes_to_manual() -> None:
    in_problem = apply_extraction_gate(
        _problem(text="3. 已知 a=〔?〕，求 a+1"), source_kind=SOURCE_SLICE
    )
    in_answer = apply_extraction_gate(
        _problem(answer="〔?〕"), source_kind=SOURCE_SLICE
    )

    assert in_problem.gate_status == GATE_MANUAL
    assert REASON_PLACEHOLDER in in_problem.review_reasons
    assert in_answer.gate_status == GATE_MANUAL
    assert REASON_PLACEHOLDER in in_answer.review_reasons


@pytest.mark.parametrize("answer", [None, "", "   \n"])
def test_empty_answer_routes_to_manual(answer: str | None) -> None:
    decision = apply_extraction_gate(_problem(answer=answer), source_kind=SOURCE_SLICE)

    assert decision.gate_status == GATE_MANUAL
    assert REASON_ANSWER_EMPTY in decision.review_reasons
    assert decision.student_answer is None


def test_figure_dependency_is_distinct_from_manual_review() -> None:
    decision = apply_extraction_gate(
        _problem(text="4. 如图，在三角形 ABC 中，求 AB 的长", answer="5"),
        source_kind=SOURCE_SLICE,
    )

    assert decision.gate_status == GATE_FIGURE
    assert decision.review_reasons == (REASON_FIGURE,)
    assert "如图" in decision.figure_keywords


def test_plain_figure_noun_is_not_flagged() -> None:
    decision = apply_extraction_gate(
        _problem(text="5. 求这个图形的面积", answer="12"), source_kind=SOURCE_SLICE
    )

    assert decision.gate_status == GATE_READY
    assert decision.figure_keywords == ()


@pytest.mark.parametrize(
    "text",
    ["见下图", "如右图所示", "图1中的阴影部分", "图甲所示", "【依赖图形】已知……"],
)
def test_figure_keyword_variants(text: str) -> None:
    assert detect_figure_keywords(text)


def test_manual_review_wins_over_figure_dependency() -> None:
    decision = apply_extraction_gate(
        _problem(text="6. 如图，已知〔?〕", complete=None), source_kind=SOURCE_SLICE
    )

    assert decision.gate_status == GATE_MANUAL
    assert REASON_FIGURE in decision.review_reasons
    assert REASON_COMPLETENESS_UNKNOWN in decision.review_reasons


def test_whole_page_fallback_always_routes_to_manual() -> None:
    decision = apply_extraction_gate(_problem(), source_kind=SOURCE_WHOLE_PAGE)

    assert decision.gate_status == GATE_MANUAL
    assert REASON_WHOLE_PAGE in decision.review_reasons
    assert decision.review_reasons == (REASON_WHOLE_PAGE,)


def test_control_chars_are_cleaned_before_gate() -> None:
    decision = apply_extraction_gate(
        _problem(text="1. 计算：\x00" + "1+1=____", answer="2\x01"),
        source_kind=SOURCE_SLICE,
    )

    assert decision.problem_text == "1. 计算：1+1=____"
    assert decision.student_answer == "2"
    assert decision.gate_status == GATE_READY


def test_overlong_problem_is_rejected_not_truncated() -> None:
    with pytest.raises(ExtractionRejected) as exc_info:
        apply_extraction_gate(_problem(text="题" * 8001), source_kind=SOURCE_SLICE)
    assert exc_info.value.reason == "problem_text_too_long"


def test_overlong_answer_is_rejected() -> None:
    with pytest.raises(ExtractionRejected) as exc_info:
        apply_extraction_gate(
            _problem(answer="答" * 2001), source_kind=SOURCE_SLICE
        )
    assert exc_info.value.reason == "student_answer_too_long"


def test_unknown_source_kind_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="未知 source_kind"):
        apply_extraction_gate(_problem(), source_kind="pdf")
