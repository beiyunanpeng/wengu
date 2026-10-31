"""P2-1 运行时配置：daily_review_limit 默认值、非法回退与热加载。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.runtime_config import (
    DEFAULT_DAILY_REVIEW_LIMIT,
    MAX_DAILY_REVIEW_LIMIT,
    daily_review_limit,
)


def _write_config(path: Path, value: object) -> None:
    path.write_text(json.dumps({"daily_review_limit": value}), encoding="utf-8")


def test_missing_file_falls_back_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WENGU_APP_CONFIG", str(tmp_path / "missing.json"))

    assert daily_review_limit() == DEFAULT_DAILY_REVIEW_LIMIT


def test_reads_limit_from_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    _write_config(path, 4)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert daily_review_limit() == 4


@pytest.mark.parametrize("raw", ["10", 0, -3, True, None, 2.5, [10]])
def test_invalid_values_fall_back_to_default(tmp_path, monkeypatch, raw) -> None:
    path = tmp_path / "app-config.json"
    _write_config(path, raw)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert daily_review_limit() == DEFAULT_DAILY_REVIEW_LIMIT


def test_limit_above_cap_is_clamped(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    _write_config(path, MAX_DAILY_REVIEW_LIMIT + 50)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert daily_review_limit() == MAX_DAILY_REVIEW_LIMIT


def test_hot_reload_picks_up_new_value_without_restart(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    _write_config(path, 5)
    assert daily_review_limit() == 5

    _write_config(path, 2)
    assert daily_review_limit() == 2

    path.write_text("{ broken json", encoding="utf-8")
    assert daily_review_limit() == DEFAULT_DAILY_REVIEW_LIMIT
