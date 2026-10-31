"""P3-1 录题通道确定性闸门单测：封套/归一/审核必填/verify 沙箱分类。

红线：录题不调模型、不生成答案；verify 只走 AST 白名单，非法表达式与数值矛盾拒绝。
"""

from __future__ import annotations

import pytest
from app.services.bank_import import (
    BANK_CHANNEL,
    BankVerifyError,
    check_approvable,
    classify_verify,
    dumps_bank_draft,
    normalize_bank_item,
    normalize_bank_items,
    validate_bank_envelope,
)

TOPICS = {"cnm_001": "数学", "cnm_002": "英语"}


def _item(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "subject": "数学",
        "topic_id": "cnm_001",
        "type": "numeric",
        "prompt": "计算 1+1",
        "answer": "2",
        "verify": "1+1",
    }
    payload.update(overrides)
    return payload


def test_envelope_requires_bank_channel_and_single_batch() -> None:
    with pytest.raises(ValueError, match="channel"):
        validate_bank_envelope({"channel": "agent_transcribe_v1", "items": [{}]})
    with pytest.raises(ValueError, match="数组"):
        validate_bank_envelope({"channel": BANK_CHANNEL, "items": "oops"})
    with pytest.raises(ValueError, match="为空"):
        validate_bank_envelope({"channel": BANK_CHANNEL, "items": []})
    items = validate_bank_envelope({"channel": BANK_CHANNEL, "items": [_item()]})
    assert items == [_item()]


def test_normalize_derives_subject_from_seed_and_counts_unknown_fields() -> None:
    result = normalize_bank_items(
        [_item(subject="物理", unknown_extra="drop")], TOPICS
    )
    assert not result.errors
    assert result.dropped_unknown_fields == 1
    draft = result.drafts[0]
    assert draft["seq"] == 0
    assert draft["normalized"]["subject"] == "数学"  # seed 为权威
    assert not draft["has_placeholder"]
    assert dumps_bank_draft(draft["normalized"]).startswith("{")


def test_normalize_rejects_unknown_topic_bad_type_and_long_prompt() -> None:
    _, errors = normalize_bank_item(
        3,
        _item(topic_id="cnm_404", type="essay", prompt="x" * 2001),
        TOPICS,
    )
    fields = {error.field for error in errors}
    assert {"topic_id", "type", "prompt"} <= fields
    assert all(error.index == 3 for error in errors)


def test_normalize_choice_requires_answer_key() -> None:
    raw = _item(
        type="choice",
        choices=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
        answer="C",
    )
    normalized, errors = normalize_bank_item(0, raw, TOPICS)
    assert normalized is None
    assert any(error.field == "answer" for error in errors)
    assert any("answer_not_in_choices" in error.reason for error in errors)


def test_normalize_choice_dedupes_keys_and_sanitizes_figure() -> None:
    raw = _item(
        type="choice",
        answer="A",
        choices=[
            {"key": "A", "text": "1"},
            {"key": "A", "text": "2"},
        ],
        figure='<svg viewBox="0 0 1 1"><script>alert(1)</script><rect width="1" height="1"/></svg>',
    )
    _, errors = normalize_bank_item(0, raw, TOPICS)
    assert any(error.field == "choices" for error in errors)

    ok, errors = normalize_bank_item(
        0,
        _item(
            type="choice",
            answer="A",
            choices=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
            figure='<svg viewBox="0 0 1 1"><script>alert(1)</script><rect width="1" height="1"/></svg>',
        ),
        TOPICS,
    )
    assert not errors
    assert ok is not None
    assert ok["figure"] is not None and "script" not in ok["figure"]


def test_placeholder_is_flagged_not_silently_accepted() -> None:
    result = normalize_bank_items([_item(prompt="计算 〔?〕 + 1", answer="")], TOPICS)
    assert not result.errors
    assert result.drafts[0]["has_placeholder"]


def test_approve_gate_requires_answer_and_clean_prompt() -> None:
    normalized, errors = normalize_bank_item(0, _item(answer="", verify=""), TOPICS)
    assert not errors and normalized is not None
    gate = check_approvable(normalized)
    assert any(error.field == "answer" and "missing_answer" in error.reason for error in gate)

    tagged, _ = normalize_bank_item(0, _item(prompt="计算 〔?〕"), TOPICS)
    assert any("placeholder" in error.reason for error in check_approvable(tagged))


def test_verify_classification_verified_and_unverifiable() -> None:
    verified, _ = normalize_bank_item(0, _item(verify="1+1"), TOPICS)
    status, reason = classify_verify(verified)
    assert (status, reason) == ("verified", None)

    no_verify, _ = normalize_bank_item(0, _item(verify=""), TOPICS)
    assert classify_verify(no_verify) == ("unverifiable", "no_verify")

    uncertain, _ = normalize_bank_item(0, _item(verify="''"), TOPICS)
    status, reason = classify_verify(uncertain)
    assert status == "unverifiable"
    assert reason == "empty_answer"


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "x = 1", "(1).__class__"],
)
def test_verify_sandbox_rejects_import_assignment_attribute(expression: str) -> None:
    normalized, errors = normalize_bank_item(0, _item(verify=expression), TOPICS)
    assert not errors and normalized is not None
    with pytest.raises(BankVerifyError) as caught:
        classify_verify(normalized)
    assert caught.value.reason.startswith("verify_error:")


def test_verify_numeric_mismatch_is_rejected() -> None:
    normalized, _ = normalize_bank_item(0, _item(verify="2+2", answer="5"), TOPICS)
    with pytest.raises(BankVerifyError) as caught:
        classify_verify(normalized)
    assert caught.value.reason == "verify_mismatch"


def test_choice_text_mismatch_is_unverifiable_not_blocking() -> None:
    normalized, _ = normalize_bank_item(
        0,
        _item(
            type="choice",
            answer="A",
            choices=[{"key": "A", "text": "3"}, {"key": "B", "text": "2"}],
            verify="1+1",
        ),
        TOPICS,
    )
    status, reason = classify_verify(normalized)
    assert (status, reason) == ("unverifiable", "choice_text_mismatch")
