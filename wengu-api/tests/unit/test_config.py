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
    "WENGU_PROVIDER_ROUTING",
    "WENGU_TASK_MODELS",
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


def test_provider_routing_env_and_app_config_precedence(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'WENGU_PROVIDER_ROUTING={"extract_problem":["qwen_vl","doubao"],"grade":"qwen_vl"}\n',
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.provider_routing == {
        "extract_problem": ["qwen_vl", "doubao"],
        "grade": "qwen_vl",
    }

    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    path = tmp_path / "app-config.json"
    path.write_text(
        json.dumps(
            {
                "provider_routing": {
                    "extract_problem": ["doubao"],
                    "text": ["mock"],
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = get_runtime_config(path)
    assert runtime.provider_routing["extract_problem"] == ["doubao"]  # app-config 整条覆盖
    assert runtime.provider_routing["grade"] == "qwen_vl"  # 未覆盖的沿用 .env
    assert runtime.provider_routing["text"] == ["mock"]


def test_task_models_env_and_app_config_precedence(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'WENGU_TASK_MODELS={"extract_problem":{"qwen_vl":"qwen3.8-max"},'
        '"dictation_extract":{"qwen_vl":"qwen3.5-ocr"}}\n',
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.task_models == {
        "extract_problem": {"qwen_vl": "qwen3.8-max"},
        "dictation_extract": {"qwen_vl": "qwen3.5-ocr"},
    }

    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    path = tmp_path / "app-config.json"
    path.write_text(
        json.dumps(
            {"task_models": {"extract_problem": {"qwen_vl": "qwen3.8-max-2026"}}}
        ),
        encoding="utf-8",
    )
    runtime = get_runtime_config(path)
    # app-config 按 task 整条覆盖；未覆盖的 task 沿用 .env
    assert runtime.task_models["extract_problem"] == {"qwen_vl": "qwen3.8-max-2026"}
    assert runtime.task_models["dictation_extract"] == {"qwen_vl": "qwen3.5-ocr"}

    missing = get_runtime_config(tmp_path / "missing.json")
    assert missing.task_models == settings.task_models
