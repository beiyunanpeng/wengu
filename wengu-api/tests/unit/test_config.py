from __future__ import annotations

import json
import os

from app.core import config as config_module
from app.core.config import Settings, get_runtime_config

_WENGU_KEYS = (
    "WENGU_ENV",
    "WENGU_MODEL_TIER_DEFAULT",
    "WENGU_DAILY_CALL_BUDGET_CNY",
    "WENGU_VARIANT_ON_DEMAND",
    "WENGU_DATA_DIR",
    "WENGU_DB_PATH",
    "WENGU_UPLOADS_DIR",
    "WENGU_PROMPTS_DIR",
    "WENGU_APP_CONFIG_PATH",
)


def _clear_env(monkeypatch) -> None:
    for key in _WENGU_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_read_env_file(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WENGU_ENV=prod\n"
        "WENGU_DB_PATH=./custom/wengu.db\n"
        "WENGU_MODEL_TIER_DEFAULT=flagship\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.env == "prod"
    assert settings.model_tier_default == "flagship"
    assert settings.db_path is not None
    assert settings.db_path.is_absolute()
    assert settings.db_path.parent.name == "custom"
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert settings.database_url.endswith("custom/wengu.db")


def test_runtime_config_hot_reload(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    base_settings = Settings(
        _env_file=None,
        model_tier_default="value",
        daily_call_budget_cny=10.0,
        variant_on_demand=True,
    )
    monkeypatch.setattr(config_module, "get_settings", lambda: base_settings)

    path = tmp_path / "app-config.json"
    path.write_text(
        json.dumps({"model_tier_default": "flagship", "variant_on_demand": False}),
        encoding="utf-8",
    )
    first = get_runtime_config(path)
    assert first.model_tier_default == "flagship"
    assert first.variant_on_demand is False

    path.write_text(json.dumps({"model_tier_default": "value"}), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    second = get_runtime_config(path)
    assert second.model_tier_default == "value"
    assert second.variant_on_demand is True

    missing = get_runtime_config(tmp_path / "missing.json")
    assert missing.model_tier_default == "value"
