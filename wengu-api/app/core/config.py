"""Runtime configuration: .env for secrets/bootstrap, app-config.json for hot runtime params."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = API_DIR.parent


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (API_DIR / path).resolve()


class Settings(BaseSettings):
    """Environment-backed settings; relative paths are resolved against wengu-api/."""

    model_config = SettingsConfigDict(
        env_file=API_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    env: Literal["dev", "prod"] = Field(default="dev", validation_alias="WENGU_ENV")
    port: int = Field(default=8000, validation_alias="WENGU_PORT")
    data_dir: Path = Field(default=API_DIR / "data", validation_alias="WENGU_DATA_DIR")
    uploads_dir: Path | None = Field(default=None, validation_alias="WENGU_UPLOADS_DIR")
    db_path: Path | None = Field(default=None, validation_alias="WENGU_DB_PATH")
    prompts_dir: Path = Field(
        default=PROJECT_ROOT / "llm_prompts", validation_alias="WENGU_PROMPTS_DIR"
    )
    seeds_dir: Path = Field(
        default=PROJECT_ROOT / "seeds", validation_alias="WENGU_SEEDS_DIR"
    )
    app_config_path: Path = Field(
        default=PROJECT_ROOT / "config" / "app-config.json",
        validation_alias="WENGU_APP_CONFIG_PATH",
    )
    log_level: str = Field(default="info", validation_alias="WENGU_LOG_LEVEL")
    model_tier_default: Literal["value", "flagship"] = Field(
        default="value", validation_alias="WENGU_MODEL_TIER_DEFAULT"
    )
    daily_call_budget_cny: float = Field(
        default=10.0, ge=0, validation_alias="WENGU_DAILY_CALL_BUDGET_CNY"
    )
    daily_call_limit: int = Field(default=200, ge=1, validation_alias="WENGU_DAILY_CALL_LIMIT")
    variant_on_demand: bool = Field(default=True, validation_alias="WENGU_VARIANT_ON_DEMAND")
    provider_routing: dict[str, str | list[str]] | None = Field(
        default=None, validation_alias="WENGU_PROVIDER_ROUTING"
    )
    task_models: dict[str, dict[str, str]] | None = Field(
        default=None, validation_alias="WENGU_TASK_MODELS"
    )
    # Provider keys/models：模型名绝不猜——缺了在注册时 fail-fast（ProviderConfigError）。
    # 密钥别名同时接受 wengu 前缀与上游标准名（ARK_*/DASHSCOPE_*），方便复用本机已有配置。
    doubao_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WENGU_DOUBAO_API_KEY", "ARK_API_KEY"),
    )
    doubao_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        validation_alias=AliasChoices("WENGU_DOUBAO_BASE_URL", "ARK_BASE_URL"),
    )
    doubao_model_value: str | None = Field(default=None, validation_alias="WENGU_DOUBAO_MODEL_VALUE")
    doubao_model_flagship: str | None = Field(
        default=None, validation_alias="WENGU_DOUBAO_MODEL_FLAGSHIP"
    )
    qwen_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WENGU_QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    )
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("WENGU_QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
    )
    qwen_model_value: str | None = Field(default=None, validation_alias="WENGU_QWEN_MODEL_VALUE")
    qwen_model_flagship: str | None = Field(default=None, validation_alias="WENGU_QWEN_MODEL_FLAGSHIP")
    deepseek_api_key: str | None = Field(default=None, validation_alias="WENGU_DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", validation_alias="WENGU_DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field(default="deepseek-chat", validation_alias="WENGU_DEEPSEEK_MODEL")

    @model_validator(mode="after")
    def _normalize_paths(self) -> Settings:
        self.data_dir = _resolve(self.data_dir)
        self.uploads_dir = (
            self.data_dir / "uploads" if self.uploads_dir is None else _resolve(self.uploads_dir)
        )
        self.db_path = self.data_dir / "wengu.db" if self.db_path is None else _resolve(self.db_path)
        self.prompts_dir = _resolve(self.prompts_dir)
        self.seeds_dir = _resolve(self.seeds_dir)
        self.app_config_path = _resolve(self.app_config_path)
        return self

    @property
    def database_url(self) -> str:
        assert self.db_path is not None
        return f"sqlite+aiosqlite:///{self.db_path.as_posix()}"

    @property
    def sync_database_url(self) -> str:
        assert self.db_path is not None
        return f"sqlite:///{self.db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


class AppConfigFile(BaseModel):
    """Hot-reloadable runtime parameters; secrets stay in .env."""

    model_config = ConfigDict(extra="forbid")

    model_tier_default: Literal["value", "flagship"] | None = None
    daily_call_budget_cny: float | None = Field(default=None, ge=0)
    daily_call_limit: int | None = Field(default=None, ge=1)
    variant_on_demand: bool | None = None
    provider_routing: dict[str, str | list[str]] | None = None
    task_models: dict[str, dict[str, str]] | None = None
    model_prices: dict[str, dict[str, float]] | None = None


class RuntimeConfig(BaseModel):
    model_tier_default: Literal["value", "flagship"]
    daily_call_budget_cny: float
    daily_call_limit: int
    variant_on_demand: bool
    provider_routing: dict[str, str | list[str]]
    task_models: dict[str, dict[str, str]] = Field(default_factory=dict)
    model_prices: dict[str, dict[str, float]]


_app_config_cache: dict[Path, tuple[int, AppConfigFile]] = {}


def _load_app_config(path: Path) -> AppConfigFile:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except FileNotFoundError:
        _app_config_cache.pop(path, None)
        return AppConfigFile()
    cached = _app_config_cache.get(path)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]
    parsed = AppConfigFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    _app_config_cache[path] = (mtime_ns, parsed)
    return parsed


def get_runtime_config(path: Path | None = None) -> RuntimeConfig:
    """Load app-config.json on demand; mtime cache makes hot reload cheap."""

    settings = get_settings()
    overrides = _load_app_config(path or settings.app_config_path)
    return RuntimeConfig(
        model_tier_default=(
            overrides.model_tier_default
            if overrides.model_tier_default is not None
            else settings.model_tier_default
        ),
        daily_call_budget_cny=(
            overrides.daily_call_budget_cny
            if overrides.daily_call_budget_cny is not None
            else settings.daily_call_budget_cny
        ),
        daily_call_limit=(
            overrides.daily_call_limit
            if overrides.daily_call_limit is not None
            else settings.daily_call_limit
        ),
        variant_on_demand=(
            overrides.variant_on_demand
            if overrides.variant_on_demand is not None
            else settings.variant_on_demand
        ),
        provider_routing={
            **(settings.provider_routing or {}),
            **(overrides.provider_routing or {}),
        },
        task_models={
            **(settings.task_models or {}),
            **(overrides.task_models or {}),
        },
        model_prices=overrides.model_prices or {},
    )
