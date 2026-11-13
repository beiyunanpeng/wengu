"""P5-1a 家长运行时配置：读取生效值 / 白名单写回（均挂 require_parent）。

配置真源是 `<data_dir>/app-config.json`；仓库根 `config/app-config.json` 只作
原生老用户的兼容回退（只读）。密钥仍只走 `.env`，本端点不接受也不写任何凭据。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.session import require_parent
from app.core.config import Settings, get_settings
from app.core.runtime_config import (
    ConfigError,
    describe_config,
    save_config,
    setup_completed,
)
from app.seed.state import get_seed_status

router = APIRouter(tags=["config"], dependencies=[Depends(require_parent)])

# 横幅需要对未解锁的孩子也可见，因此单独开一个只返回布尔的公开只读端点。
public_router = APIRouter(tags=["config"])


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_review_limit: int | None = Field(default=None, ge=1, le=200)
    daily_recitation_limit: int | None = Field(default=None, ge=1, le=20)
    exam_day_limit_factor: float | None = Field(default=None, ge=1, le=3)
    setup_completed: bool | None = Field(default=None, strict=True)

    @field_validator(
        "daily_review_limit", "daily_recitation_limit", "exam_day_limit_factor",
        mode="before",
    )
    @classmethod
    def _reject_bool(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("布尔值不是合法配置值")
        return value


class ConfigResponse(BaseModel):
    values: dict[str, int | float | bool]
    sources: dict[str, str]
    read_path: str
    write_path: str
    file_source: str
    legacy: bool
    hint: str | None


class SetupStatus(BaseModel):
    setup_completed: bool
    seed_loaded: bool
    seed_error: str | None


def _view(payload: dict[str, Any]) -> ConfigResponse:
    return ConfigResponse(**payload)


@router.get("/api/config", response_model=ConfigResponse)
async def get_config(
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    return _view(describe_config(settings))


@public_router.get("/api/setup/status", response_model=SetupStatus)
async def get_setup_status(
    settings: Settings = Depends(get_settings),
) -> SetupStatus:
    seed = get_seed_status()
    return SetupStatus(
        setup_completed=setup_completed(settings),
        seed_loaded=seed.loaded,
        seed_error=seed.error,
    )


@router.put("/api/config", response_model=ConfigResponse)
async def put_config(
    payload: ConfigUpdate,
    settings: Settings = Depends(get_settings),
) -> ConfigResponse:
    updates = payload.model_dump(exclude_unset=True)
    try:
        return _view(await save_config(settings, updates=updates))
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
