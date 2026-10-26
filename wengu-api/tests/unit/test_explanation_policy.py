from __future__ import annotations

import pytest
from app.providers.base import Explanation
from app.services.explanation import (
    ENTRY_QUESTION,
    LEAK_ANSWER_FIELD_DROPPED,
    LEAK_ANSWER_PHRASE_MASKED,
    LEAK_STANDARD_ANSWER_MASKED,
    MODE_FULL,
    MODE_GUIDE,
    SAFE_FOCUS,
    SAFE_STEP,
    ExplainContext,
    ExplanationQualityError,
    choose_strategy,
    default_mode,
    needs_soft_gate,
    next_hint_level,
    prompt_values,
    quality_gate,
    resolve_mode,
)


def _context(**overrides) -> ExplainContext:
    values = {
        "kind": "mistake",
        "context_id": 12,
        "entry": "mistake",
        "problem_text": "解方程 2x + 3 = 11。",
        "student_answer": "x = 5",
        "standard_answer": "x = 4",
        "subject": "数学",
        "category_name": "一元一次方程",
        "concepts": ("移项",),
        "error_cause": "method_missing",
        "mistake_id": 12,
    }
    values.update(overrides)
    return ExplainContext(**values)


def _explanation(**overrides) -> Explanation:
    values = {
        "focus": "先看未知数在哪一边。",
        "steps": ("把常数项移到右边。", "两边同时除以未知数的系数。"),
        "consolidation": "自己把移项那一步再写一遍。",
        "answer": "x = 4",
        "hint_level": 1,
    }
    values.update(overrides)
    return Explanation(**values)


@pytest.mark.unit
def test_default_mode_follows_error_cause_and_entry() -> None:
    assert default_mode(_context(error_cause="method_missing")) == MODE_GUIDE
    assert default_mode(_context(error_cause="concept_unclear")) == MODE_FULL
    assert default_mode(_context(error_cause="prerequisite_gap")) == MODE_FULL
    assert default_mode(_context(error_cause="calculation")) == MODE_GUIDE
    assert default_mode(_context(error_cause="careless")) == MODE_GUIDE
    assert default_mode(_context(error_cause="expression")) == MODE_GUIDE
    assert default_mode(_context(error_cause=None)) == MODE_GUIDE
    assert default_mode(_context(subject="英语", error_cause="concept_unclear")) == MODE_GUIDE
    assert default_mode(_context(entry=ENTRY_QUESTION, error_cause=None)) == MODE_FULL


@pytest.mark.unit
def test_resolve_mode_and_strategy() -> None:
    context = _context()
    assert resolve_mode(context, "auto") == MODE_GUIDE
    assert resolve_mode(context, "full") == MODE_FULL
    with pytest.raises(ValueError, match="未知讲解模式"):
        resolve_mode(context, "deep")

    assert choose_strategy(context) == "method_hint"
    assert choose_strategy(_context(error_cause="concept_unclear")) == "concept_explain"
    assert choose_strategy(_context(entry=ENTRY_QUESTION, error_cause=None)) == "general_solve"
    assert choose_strategy(_context(subject="英语", error_cause=None)) == "recall"
    assert choose_strategy(_context(error_cause=None)) == "general_guide"


@pytest.mark.unit
def test_soft_gate_only_for_explicit_full_after_guide_default() -> None:
    context = _context(error_cause="method_missing")
    assert needs_soft_gate(context, mode=MODE_FULL, attempted=False) is True
    assert needs_soft_gate(context, mode=MODE_FULL, attempted=True) is False
    assert needs_soft_gate(context, mode=MODE_GUIDE, attempted=False) is False
    assert (
        needs_soft_gate(
            _context(error_cause="concept_unclear"), mode=MODE_FULL, attempted=False
        )
        is False
    )
    assert (
        needs_soft_gate(_context(entry=ENTRY_QUESTION), mode=MODE_FULL, attempted=False)
        is False
    )


@pytest.mark.unit
def test_hint_levels_are_capped_at_three() -> None:
    assert next_hint_level(MODE_GUIDE, 1) == 2
    assert next_hint_level(MODE_GUIDE, 2) == 3
    assert next_hint_level(MODE_GUIDE, 3) is None
    assert next_hint_level(MODE_FULL, 1) is None


@pytest.mark.unit
def test_prompt_values_include_all_tokens_without_requiring_model_calls() -> None:
    values = prompt_values(
        _context(),
        mode=MODE_GUIDE,
        strategy="method_hint",
        hint_level=2,
        attempted=True,
    )
    assert values["SUBJECT"] == "数学"
    assert values["CATEGORY"] == "一元一次方程"
    assert values["CONCEPTS"] == "移项"
    assert values["ERROR_CAUSE"] == "方法不会"
    assert values["STRATEGY"] == "给方法"
    assert values["CONTEXT_LABEL"] == "错题订正"
    assert values["HINT_LEVEL"] == "2"
    assert values["ATTEMPTED"] == "是"

    question = prompt_values(
        _context(entry=ENTRY_QUESTION, student_answer="", standard_answer=""),
        mode=MODE_FULL,
        strategy="general_solve",
        hint_level=1,
        attempted=False,
    )
    assert question["STUDENT_ANSWER"] == "（未提供）"
    assert question["STANDARD_ANSWER"] == "（未提供）"
    assert question["CONTEXT_LABEL"] == "拍照答疑"
    assert question["HINT_LEVEL"] == "0"


@pytest.mark.unit
def test_guide_gate_drops_answer_field() -> None:
    gated = quality_gate(
        _explanation(steps=("先看未知数在哪一边。",)),
        mode=MODE_GUIDE,
        standard_answer="x = 4",
    )
    assert gated.answer is None
    assert LEAK_ANSWER_FIELD_DROPPED in gated.leak_flags
    assert gated.focus
    assert gated.steps
    assert gated.consolidation


@pytest.mark.unit
def test_guide_gate_masks_known_standard_answer() -> None:
    gated = quality_gate(
        _explanation(steps=("直接得到 x = 4", "再检查一遍"), answer=None),
        mode=MODE_GUIDE,
        standard_answer="x = 4",
    )
    assert gated.steps[0] == SAFE_STEP
    assert LEAK_STANDARD_ANSWER_MASKED in gated.leak_flags


@pytest.mark.unit
def test_guide_gate_masks_answer_phrase_even_without_standard_answer() -> None:
    gated = quality_gate(
        _explanation(
            focus="答案：4",
            steps=("所以答案是 4", "再检查一遍"),
            answer=None,
        ),
        mode=MODE_GUIDE,
        standard_answer="",
    )
    assert gated.focus == SAFE_FOCUS
    assert gated.steps[0] == SAFE_STEP
    assert LEAK_ANSWER_PHRASE_MASKED in gated.leak_flags


@pytest.mark.unit
def test_full_gate_requires_multiple_steps_and_answer() -> None:
    gated = quality_gate(_explanation(), mode=MODE_FULL, standard_answer="x = 4")
    assert gated.answer == "x = 4"
    assert len(gated.steps) == 2
    assert gated.leak_flags == ()

    with pytest.raises(ExplanationQualityError) as error:
        quality_gate(
            _explanation(steps=("只有一步。",)),
            mode=MODE_FULL,
            standard_answer="x = 4",
        )
    assert "full_needs_multiple_steps" in error.value.reasons

    with pytest.raises(ExplanationQualityError) as error:
        quality_gate(_explanation(answer=None), mode=MODE_FULL)
    assert "answer_missing" in error.value.reasons


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"focus": ""}, "focus_empty"),
        ({"focus": "长" * 201}, "focus_too_long"),
        ({"steps": ()}, "steps_empty"),
        ({"steps": ("含 〔?〕 的提示", "第二步")}, "placeholder"),
        ({"steps": ("<b>加粗</b>", "第二步")}, "html"),
        ({"steps": ("带\x00控制字符", "第二步")}, "control_chars"),
        ({"consolidation": ""}, "consolidation_empty"),
        ({"consolidation": "长" * 301}, "consolidation_too_long"),
        ({"steps": ("一" * 601, "第二步")}, "step_too_long"),
        ({"answer": "答" * 501}, "answer_too_long"),
    ],
)
def test_quality_gate_rejects_bad_content(overrides: dict, reason: str) -> None:
    with pytest.raises(ExplanationQualityError) as error:
        quality_gate(_explanation(**overrides), mode=MODE_FULL)
    assert reason in error.value.reasons


@pytest.mark.unit
def test_context_key_is_stable() -> None:
    assert _context().key == "mistake:12"
    assert _context(kind="problem_extraction", context_id=5).key == "problem_extraction:5"
    assert _context(kind="ingestion_draft", context_id=3).key == "ingestion_draft:3"
