"""兜底通道确定性校验/归一化的单测（导入不调模型，AGENTS §5 宽松解析层）。"""

from __future__ import annotations

import json

import pytest
from app.services.ingestion import (
    MAX_ITEMS_PER_BATCH,
    clean_text,
    dumps_draft,
    validate_and_normalize,
    validate_envelope,
)


def test_clean_text_strips_control_chars_keeps_newline_tab() -> None:
    assert clean_text("a\x00b\x07c\nd\te ") == "abc\nd\te"


def test_envelope_requires_object() -> None:
    with pytest.raises(ValueError, match="JSON 对象"):
        validate_envelope([{"problem_text": "x"}])


def test_envelope_channel_whitelist() -> None:
    with pytest.raises(ValueError, match="channel"):
        validate_envelope({"channel": "wechat", "items": [{"problem_text": "x"}]})


def test_envelope_items_list_nonempty_and_capped() -> None:
    with pytest.raises(ValueError, match="数组"):
        validate_envelope({"channel": "doubao_json", "items": "oops"})
    with pytest.raises(ValueError, match="为空"):
        validate_envelope({"channel": "doubao_json", "items": []})
    too_many = [{"problem_text": "x"}] * (MAX_ITEMS_PER_BATCH + 1)
    with pytest.raises(ValueError, match="上限"):
        validate_envelope({"channel": "doubao_json", "items": too_many})
    channel, items = validate_envelope(
        {"channel": "doubao_json", "items": [{"problem_text": "x"}]}
    )
    assert channel == "doubao_json" and len(items) == 1


def test_normalize_happy_path_full_fields() -> None:
    result = validate_and_normalize(
        [
            {
                "subject": "数学",
                "problem_text": "计算 1+1",
                "student_answer": "3",
                "source_ref": "校本练习 P5",
                "captured_at": "2026-10-24",
                "unknown_extra": "丢弃并计数",
            }
        ]
    )
    assert not result.errors
    assert result.dropped_unknown_fields == 1
    draft = result.drafts[0]
    assert draft["seq"] == 0
    assert draft["normalized"]["subject"] == "数学"
    assert not draft["has_placeholder"]
    assert not draft["is_incomplete"]


def test_normalize_placeholder_and_incomplete_flags() -> None:
    result = validate_and_normalize(
        [
            {"problem_text": "求解 〔?〕", "student_answer": "42"},
            {"problem_text": "默写单词 apple", "student_answer": ""},
        ]
    )
    assert not result.errors
    first, second = result.drafts
    assert first["has_placeholder"] and not first["is_incomplete"]
    assert not second["has_placeholder"] and second["is_incomplete"]


def test_normalize_rejects_bad_items_without_truncation() -> None:
    overlong = "x" * 2001
    result = validate_and_normalize(
        [
            "not-a-dict",
            {"problem_text": 123},
            {"problem_text": ""},
            {"problem_text": overlong},
            {"problem_text": "合法题"},
        ]
    )
    assert len(result.drafts) == 1
    assert result.drafts[0]["seq"] == 4
    fields = {(e.index, e.field) for e in result.errors}
    assert (0, "item") in fields
    assert (1, "problem_text") in fields
    assert (2, "problem_text") in fields
    assert (3, "problem_text") in fields
    # 超长被跳过而非截断：错误理由里明示未导入
    assert any("未导入" in e.reason for e in result.errors if e.index == 3)


def test_normalize_cleans_control_chars() -> None:
    result = validate_and_normalize([{"problem_text": "题目\x0b文本"}])
    assert not result.errors
    assert result.drafts[0]["normalized"]["problem_text"] == "题目文本"


def test_dumps_draft_stable_key_order() -> None:
    a = dumps_draft({"problem_text": "x", "subject": "数学"})
    b = dumps_draft({"subject": "数学", "problem_text": "x"})
    assert a == b
    assert list(json.loads(a)) == sorted(json.loads(a))
