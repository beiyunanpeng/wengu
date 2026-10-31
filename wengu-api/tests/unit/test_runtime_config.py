"""P2-1 运行时配置：daily_review_limit 默认值、非法回退与热加载。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.core.runtime_config import (
    DEFAULT_DAILY_REVIEW_LIMIT,
    DEFAULT_EXAM_DAY_LIMIT_FACTOR,
    MAX_DAILY_REVIEW_LIMIT,
    daily_review_limit,
    exam_day_limit_factor,
)


def _write_config(path: Path, value: object) -> None:
    path.write_text(json.dumps({"daily_review_limit": value}), encoding="utf-8")


def _write_factor(path: Path, value: object) -> None:
    path.write_text(
        json.dumps({"exam_day_limit_factor": value}), encoding="utf-8"
    )


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


def test_exam_day_factor_defaults_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WENGU_APP_CONFIG", str(tmp_path / "missing.json"))

    assert exam_day_limit_factor() == DEFAULT_EXAM_DAY_LIMIT_FACTOR


def test_exam_day_factor_reads_and_hot_reloads(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    _write_factor(path, 1.5)
    assert exam_day_limit_factor() == 1.5

    _write_factor(path, 2)  # 整数也合法，按 2.0 使用
    assert exam_day_limit_factor() == 2.0

    _write_factor(path, 2.5)
    assert exam_day_limit_factor() == 2.5


@pytest.mark.parametrize(
    "raw", ["2.0", 0, 0.5, -1.5, True, None, [2.0], {"factor": 2}]
)
def test_exam_day_factor_invalid_falls_back(tmp_path, monkeypatch, raw) -> None:
    path = tmp_path / "app-config.json"
    _write_factor(path, raw)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert exam_day_limit_factor() == DEFAULT_EXAM_DAY_LIMIT_FACTOR
