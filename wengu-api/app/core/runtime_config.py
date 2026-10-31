"""运行时非密钥配置：`config/app-config.json`，每次调用现读以支持热加载。

密钥与首启配置仍只走 `.env`（`app.core.config`）。本模块只读仓库根目录下的
JSON 文件，文件缺失或字段非法时退回内置默认值，绝不因配置错误阻断请求。
测试可用 `WENGU_APP_CONFIG` 指向临时文件。
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT

DEFAULT_DAILY_REVIEW_LIMIT = 10
MAX_DAILY_REVIEW_LIMIT = 200


def app_config_path() -> Path:
    override = os.environ.get("WENGU_APP_CONFIG")
    if override:
        return Path(override)
    return PROJECT_ROOT / "config" / "app-config.json"


def _load() -> Mapping[str, Any]:
    try:
        text = app_config_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, Mapping) else {}


def daily_review_limit() -> int:
    """每日到期复习上限；缺失/非法时用默认 10，超出硬上限按 200 收口。"""

    raw = _load().get("daily_review_limit")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return DEFAULT_DAILY_REVIEW_LIMIT
    return min(raw, MAX_DAILY_REVIEW_LIMIT)
