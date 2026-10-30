"""Runtime configuration: secrets/bootstrap live in .env (v2.5 zero-model)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
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
    inbox_dir: Path | None = Field(default=None, validation_alias="WENGU_INBOX_DIR")
    db_path: Path | None = Field(default=None, validation_alias="WENGU_DB_PATH")
    seeds_dir: Path = Field(
        default=PROJECT_ROOT / "seeds", validation_alias="WENGU_SEEDS_DIR"
    )
    log_level: str = Field(default="info", validation_alias="WENGU_LOG_LEVEL")
    session_secret: str | None = Field(
        default=None, validation_alias="WENGU_SESSION_SECRET"
    )

    @model_validator(mode="after")
    def _normalize_paths(self) -> Settings:
        self.data_dir = _resolve(self.data_dir)
        if self.inbox_dir is not None:
            self.inbox_dir = _resolve(self.inbox_dir)
        self.db_path = self.data_dir / "wengu.db" if self.db_path is None else _resolve(self.db_path)
        self.seeds_dir = _resolve(self.seeds_dir)
        return self

    @property
    def inbox_path(self) -> Path:
        """外部 agent 转录报文的监听目录（v2.5 主入本通道）。"""
        return self.inbox_dir if self.inbox_dir is not None else self.data_dir / "inbox"

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
