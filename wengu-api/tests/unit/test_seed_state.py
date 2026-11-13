"""P4-4：seed 装载状态单例 + 安全错误分类。

钉死的口径（AGENTS §5/§9）：
- classify_seed_error 只回固定类别常量（format/json/io/unknown），
  绝不回传 str(exc)/绝对路径/题目文本/堆栈；
- 进程内状态可写可读可重置，默认"尚未装载"（loaded=False, error=None）。
"""

from __future__ import annotations

import json

import pytest
from app.seed.loader import SeedFormatError, classify_seed_error
from app.seed.state import get_seed_status, reset_seed_status, set_seed_status

pytestmark = pytest.mark.unit

_ALLOWED = {"format", "json", "io", "unknown"}


def test_classify_maps_each_exception_to_a_safe_category() -> None:
    assert classify_seed_error(SeedFormatError("结构非法")) == "format"
    assert classify_seed_error(json.JSONDecodeError("Expecting value", "doc", 0)) == "json"
    assert classify_seed_error(IsADirectoryError("topics.json")) == "io"
    assert classify_seed_error(PermissionError("denied")) == "io"
    assert classify_seed_error(FileNotFoundError("missing")) == "io"
    # ValueError 兜底（SeedFormatError / JSONDecodeError 都是其子类，须先被上面接住）
    assert classify_seed_error(ValueError("其他")) == "unknown"
    assert classify_seed_error(RuntimeError("boom")) == "unknown"


def test_classify_never_leaks_message_path_or_pii() -> None:
    marker = "机密题目文本PII_MARKER"
    abs_path = "/home/roc/seeds/data/topics.json"
    cases = [
        SeedFormatError(f"知识点缺少字符串 id: {{'name': '{marker}'}}"),
        json.JSONDecodeError(f"Expecting value {marker}", abs_path, 0),
        IsADirectoryError(abs_path),
        RuntimeError(f"{marker} {abs_path}"),
    ]
    for exc in cases:
        category = classify_seed_error(exc)
        assert category in _ALLOWED
        assert marker not in category
        assert abs_path not in category


def test_seed_status_singleton_roundtrip_and_reset() -> None:
    reset_seed_status()
    default = get_seed_status()
    assert default.loaded is False
    assert default.error is None

    set_seed_status(loaded=True, error=None)
    loaded = get_seed_status()
    assert loaded.loaded is True
    assert loaded.error is None

    set_seed_status(loaded=False, error="json")
    failed = get_seed_status()
    assert failed.loaded is False
    assert failed.error == "json"

    reset_seed_status()
    again = get_seed_status()
    assert again.loaded is False
    assert again.error is None
