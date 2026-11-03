"""P2-1 运行时配置：daily_review_limit 默认值、非法回退与热加载。

P5-1a 增补：路径解析（env → data_dir → legacy 只读）、白名单校验、原子写。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.runtime_config import (
    DEFAULT_DAILY_RECITATION_LIMIT,
    DEFAULT_DAILY_REVIEW_LIMIT,
    DEFAULT_EXAM_DAY_LIMIT_FACTOR,
    DEFAULT_SETUP_COMPLETED,
    MAX_DAILY_RECITATION_LIMIT,
    MAX_DAILY_REVIEW_LIMIT,
    ConfigError,
    app_config_location,
    daily_recitation_limit,
    daily_review_limit,
    describe_config,
    exam_day_limit_factor,
    save_config,
    setup_completed,
)


def _write_config(path: Path, value: object) -> None:
    path.write_text(json.dumps({"daily_review_limit": value}), encoding="utf-8")


def _write_factor(path: Path, value: object) -> None:
    path.write_text(
        json.dumps({"exam_day_limit_factor": value}), encoding="utf-8"
    )


def _write_recitation_limit(path: Path, value: object) -> None:
    path.write_text(
        json.dumps({"daily_recitation_limit": value}), encoding="utf-8"
    )


def _write_completed(path: Path, value: object) -> None:
    path.write_text(json.dumps({"setup_completed": value}), encoding="utf-8")


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


def test_recitation_limit_defaults_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WENGU_APP_CONFIG", str(tmp_path / "missing.json"))

    assert daily_recitation_limit() == DEFAULT_DAILY_RECITATION_LIMIT


@pytest.mark.parametrize("raw", ["5", 0, -1, True, None, 2.5, [3]])
def test_recitation_limit_invalid_falls_back(tmp_path, monkeypatch, raw) -> None:
    path = tmp_path / "app-config.json"
    _write_recitation_limit(path, raw)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert daily_recitation_limit() == DEFAULT_DAILY_RECITATION_LIMIT


def test_recitation_limit_above_cap_is_clamped(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    _write_recitation_limit(path, MAX_DAILY_RECITATION_LIMIT + 1)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert daily_recitation_limit() == MAX_DAILY_RECITATION_LIMIT


def test_recitation_limit_hot_reload_picks_up_new_value(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    _write_recitation_limit(path, 3)
    assert daily_recitation_limit() == 3

    _write_recitation_limit(path, 1)
    assert daily_recitation_limit() == 1


def test_setup_completed_defaults_to_false_when_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WENGU_APP_CONFIG", str(tmp_path / "missing.json"))

    assert setup_completed() is DEFAULT_SETUP_COMPLETED
    assert setup_completed() is False


def test_setup_completed_reads_true_and_false(tmp_path, monkeypatch) -> None:
    path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    _write_completed(path, True)
    assert setup_completed() is True

    _write_completed(path, False)
    assert setup_completed() is False


@pytest.mark.parametrize("raw", ["true", 1, 0, "yes", None, [True]])
def test_setup_completed_invalid_falls_back_to_false(
    tmp_path, monkeypatch, raw
) -> None:
    path = tmp_path / "app-config.json"
    _write_completed(path, raw)
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    assert setup_completed() is False


async def test_setup_completed_is_written_and_reported(tmp_path) -> None:
    data_dir = tmp_path / "data"

    await save_config(
        _settings(data_dir),
        updates={"setup_completed": True},
        project_root=tmp_path / "repo",
        env={},
    )

    payload = json.loads((data_dir / "app-config.json").read_text(encoding="utf-8"))
    assert payload == {"setup_completed": True}
    assert setup_completed(_settings(data_dir)) is True
    description = describe_config(
        _settings(data_dir), project_root=tmp_path / "repo", env={}
    )
    assert description["values"]["setup_completed"] is True
    assert description["sources"]["setup_completed"] == "file"


def _settings(data_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(data_dir=data_dir)


def test_docker_layout_resolves_to_data_dir(tmp_path, monkeypatch) -> None:
    """API_DIR=/app → PROJECT_ROOT=/ 时，配置必须落 /app/data 而不是 /config。"""

    monkeypatch.delenv("WENGU_APP_CONFIG", raising=False)
    data_dir = tmp_path / "data"
    location = app_config_location(
        _settings(data_dir), project_root=Path("/"), env={}
    )

    assert location.source == "default"
    assert location.read_path == data_dir / "app-config.json"
    assert location.write_path == data_dir / "app-config.json"


def test_data_dir_file_wins_over_repo_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("WENGU_APP_CONFIG", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "app-config.json").write_text(
        json.dumps({"daily_review_limit": 4}), encoding="utf-8"
    )
    (data_dir / "app-config.json").write_text(
        json.dumps({"daily_review_limit": 7}), encoding="utf-8"
    )

    location = app_config_location(_settings(data_dir), project_root=repo, env={})
    assert location.source == "data"
    assert location.read_path == data_dir / "app-config.json"

    description = describe_config(_settings(data_dir), project_root=repo, env={})
    assert description["values"]["daily_review_limit"] == 7
    assert description["sources"]["daily_review_limit"] == "file"
    assert description["legacy"] is False
    assert description["hint"] is None


async def test_legacy_fallback_reads_only_and_saves_to_data_dir(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("WENGU_APP_CONFIG", raising=False)
    data_dir = tmp_path / "data"
    repo = tmp_path / "repo"
    legacy = repo / "config" / "app-config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {"daily_review_limit": 4, "exam_day_limit_factor": 2, "legacy_junk": "x"}
        ),
        encoding="utf-8",
    )
    before = legacy.read_bytes()

    location = app_config_location(_settings(data_dir), project_root=repo, env={})
    assert location.source == "legacy"
    assert location.read_path == legacy
    assert location.write_path == data_dir / "app-config.json"

    description = describe_config(_settings(data_dir), project_root=repo, env={})
    assert description["legacy"] is True
    assert description["file_source"] == "legacy"
    assert description["values"]["daily_review_limit"] == 4
    assert description["values"]["exam_day_limit_factor"] == 2.0
    assert description["hint"] and "建议" in description["hint"]

    await save_config(
        _settings(data_dir),
        updates={"daily_recitation_limit": 8},
        project_root=repo,
        env={},
    )

    assert legacy.read_bytes() == before, "老路径文件绝不能被改写"
    written = json.loads((data_dir / "app-config.json").read_text(encoding="utf-8"))
    assert written == {
        "daily_review_limit": 4,
        "exam_day_limit_factor": 2,
        "daily_recitation_limit": 8,
        "legacy_junk": "x",
    }, "保存时应基于生效值合并，未知键原样保留"


async def test_env_override_is_read_and_write_target(tmp_path, monkeypatch) -> None:
    path = tmp_path / "override.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(path))

    await save_config(updates={"daily_review_limit": 9})

    assert json.loads(path.read_text(encoding="utf-8"))["daily_review_limit"] == 9
    assert daily_review_limit() == 9


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {"unknown_key": 1},
        {"daily_review_limit": 0},
        {"daily_review_limit": 201},
        {"daily_review_limit": 2.5},
        {"daily_review_limit": True},
        {"daily_recitation_limit": 21},
        {"daily_recitation_limit": True},
        {"exam_day_limit_factor": 0.5},
        {"exam_day_limit_factor": 3.5},
        {"exam_day_limit_factor": True},
        {"setup_completed": "yes"},
        {"setup_completed": 1},
        {"setup_completed": 0},
        {"setup_completed": None},
    ],
)
async def test_invalid_updates_rejected_before_write(tmp_path, updates) -> None:
    data_dir = tmp_path / "data"
    with pytest.raises(ConfigError):
        await save_config(
            _settings(data_dir), updates=updates, project_root=tmp_path / "repo", env={}
        )
    assert not (data_dir / "app-config.json").exists()


async def test_concurrent_saves_leave_valid_json(tmp_path) -> None:
    data_dir = tmp_path / "data"

    await asyncio.gather(
        *(
            save_config(
                _settings(data_dir),
                updates={"daily_review_limit": (index % 200) + 1},
                project_root=tmp_path / "repo",
                env={},
            )
            for index in range(30)
        )
    )

    payload = json.loads((data_dir / "app-config.json").read_text(encoding="utf-8"))
    assert 1 <= payload["daily_review_limit"] <= MAX_DAILY_REVIEW_LIMIT
