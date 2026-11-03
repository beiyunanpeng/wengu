"""运行时非密钥配置：JSON 文件真源，每次调用现读以支持热加载。

密钥与首启配置仍只走 `.env`（`app.core.config`）。本模块只读 JSON 文件，
文件缺失或字段非法时退回内置默认值，绝不因配置错误阻断请求。

路径解析顺序（P5-1a）：
1. `WENGU_APP_CONFIG`（测试 / 显式覆盖）
2. `<data_dir>/app-config.json`（Docker 与原生都持久）
3. 仓库根 `config/app-config.json`（原生老用户兼容；**只读**）

写入一律落 `<data_dir>/app-config.json`（`WENGU_APP_CONFIG` 覆盖时落覆盖路径）；
绝不自动搬运、删除或覆盖仓库根老路径文件——那是用户的文件。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.config import PROJECT_ROOT, Settings, get_settings

CONFIG_FILENAME = "app-config.json"

DEFAULT_DAILY_REVIEW_LIMIT = 10
MAX_DAILY_REVIEW_LIMIT = 200
DEFAULT_EXAM_DAY_LIMIT_FACTOR = 1.5
MIN_EXAM_DAY_LIMIT_FACTOR = 1.0
MAX_EXAM_DAY_LIMIT_FACTOR = 3.0
DEFAULT_DAILY_RECITATION_LIMIT = 5
MAX_DAILY_RECITATION_LIMIT = 20
DEFAULT_SETUP_COMPLETED = False

ConfigSource = Literal["env", "data", "legacy", "default"]
ValueSource = Literal["file", "default"]

_FILE_LOCK = asyncio.Lock()


class ConfigError(ValueError):
    """配置值非法（API 映射 422）。"""


@dataclass(frozen=True)
class AppConfigLocation:
    """一次解析的结果：读哪个文件、写哪个文件、为什么。"""

    read_path: Path
    write_path: Path
    source: ConfigSource

    @property
    def legacy(self) -> bool:
        return self.source == "legacy"


def app_config_location(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfigLocation:
    """解析生效配置路径；`project_root` / `env` 仅供测试注入。"""

    resolved = get_settings() if settings is None else settings
    root = PROJECT_ROOT if project_root is None else project_root
    environment = os.environ if env is None else env
    data_path = Path(resolved.data_dir) / CONFIG_FILENAME

    override = environment.get("WENGU_APP_CONFIG")
    if override:
        path = Path(override)
        return AppConfigLocation(read_path=path, write_path=path, source="env")
    if data_path.is_file():
        return AppConfigLocation(read_path=data_path, write_path=data_path, source="data")
    legacy = root / "config" / CONFIG_FILENAME
    if legacy.is_file():
        return AppConfigLocation(read_path=legacy, write_path=data_path, source="legacy")
    return AppConfigLocation(read_path=data_path, write_path=data_path, source="default")


def app_config_path() -> Path:
    """当前生效的读取路径（保留给既有调用方）。"""

    return app_config_location().read_path


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _load(settings: Settings | None = None) -> Mapping[str, Any]:
    return _read_mapping(app_config_location(settings).read_path)


def _effective_int(
    data: Mapping[str, Any], key: str, default: int, cap: int
) -> tuple[int, ValueSource]:
    raw = data.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return default, "default"
    return min(raw, cap), "file"


def _effective_factor(data: Mapping[str, Any]) -> tuple[float, ValueSource]:
    raw = data.get("exam_day_limit_factor")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return DEFAULT_EXAM_DAY_LIMIT_FACTOR, "default"
    value = float(raw)
    if not math.isfinite(value) or value < MIN_EXAM_DAY_LIMIT_FACTOR:
        return DEFAULT_EXAM_DAY_LIMIT_FACTOR, "default"
    return value, "file"


def _effective_bool(data: Mapping[str, Any]) -> tuple[bool, ValueSource]:
    raw = data.get("setup_completed")
    if isinstance(raw, bool):
        return raw, "file"
    return DEFAULT_SETUP_COMPLETED, "default"


def describe_config(
    settings: Settings | None = None,
    *,
    project_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """生效值 + 每项来源 + 读/写路径 + 兼容提示（GET /api/config 的载荷）。"""

    location = app_config_location(settings, project_root=project_root, env=env)
    data = _read_mapping(location.read_path)
    review_limit, review_source = _effective_int(
        data, "daily_review_limit", DEFAULT_DAILY_REVIEW_LIMIT, MAX_DAILY_REVIEW_LIMIT
    )
    recitation_limit, recitation_source = _effective_int(
        data,
        "daily_recitation_limit",
        DEFAULT_DAILY_RECITATION_LIMIT,
        MAX_DAILY_RECITATION_LIMIT,
    )
    factor, factor_source = _effective_factor(data)
    completed, completed_source = _effective_bool(data)

    hint = None
    if location.legacy:
        hint = (
            "当前仍在读取仓库根 config/app-config.json（兼容模式，只读）。"
            f"建议复制到 {location.write_path}；系统不会自动搬运或删除旧文件。"
        )

    return {
        "values": {
            "daily_review_limit": review_limit,
            "daily_recitation_limit": recitation_limit,
            "exam_day_limit_factor": factor,
            "setup_completed": completed,
        },
        "sources": {
            "daily_review_limit": review_source,
            "daily_recitation_limit": recitation_source,
            "exam_day_limit_factor": factor_source,
            "setup_completed": completed_source,
        },
        "read_path": str(location.read_path),
        "write_path": str(location.write_path),
        "file_source": location.source,
        "legacy": location.legacy,
        "hint": hint,
    }


def validate_updates(updates: Mapping[str, Any]) -> dict[str, int | float]:
    """白名单 + 区间校验；任何非法值在写文件前抛 `ConfigError`。"""

    if not updates:
        raise ConfigError("至少提供一个配置项")
    unknown = sorted(set(updates) - _ALLOWED_KEYS)
    if unknown:
        raise ConfigError(f"不支持的配置键：{', '.join(unknown)}")

    validated: dict[str, int | float | bool] = {}
    for key, raw in updates.items():
        if key == "setup_completed":
            if not isinstance(raw, bool):
                raise ConfigError("setup_completed 必须是布尔值")
            validated[key] = raw
            continue
        if key == "exam_day_limit_factor":
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                raise ConfigError("exam_day_limit_factor 必须是数字")
            value = float(raw)
            if not math.isfinite(value) or not (
                MIN_EXAM_DAY_LIMIT_FACTOR <= value <= MAX_EXAM_DAY_LIMIT_FACTOR
            ):
                raise ConfigError("exam_day_limit_factor 必须在 1..3 之间")
            validated[key] = value
            continue
        low, high = _RULES[key]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ConfigError(f"{key} 必须是整数")
        if not low <= raw <= high:
            raise ConfigError(f"{key} 必须在 {low}..{high} 之间")
        validated[key] = raw
    return validated


_RULES: dict[str, tuple[int, int]] = {
    "daily_review_limit": (1, MAX_DAILY_REVIEW_LIMIT),
    "daily_recitation_limit": (1, MAX_DAILY_RECITATION_LIMIT),
}
_ALLOWED_KEYS = frozenset({*_RULES, "exam_day_limit_factor", "setup_completed"})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """同目录 tmp + fsync + os.replace（参照 services/local_seed.py）。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(dict(sorted(payload.items())), ensure_ascii=False, indent=2) + "\n"
    )
    fd, tmp_name = tempfile.mkstemp(
        prefix="._app-config-", suffix=".tmp", dir=path.parent
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def save_config(
    settings: Settings | None = None,
    *,
    updates: Mapping[str, Any],
    project_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """校验后原子落盘；保留文件里既有的未知键，只覆盖白名单键。"""

    validated = validate_updates(updates)
    async with _FILE_LOCK:
        location = app_config_location(settings, project_root=project_root, env=env)
        merged = _read_mapping(location.read_path)
        merged.update(validated)
        _write_json(location.write_path, merged)
    return describe_config(settings, project_root=project_root, env=env)


def daily_review_limit(settings: Settings | None = None) -> int:
    """每日到期复习上限；缺失/非法时用默认 10，超出硬上限按 200 收口。"""

    value, _ = _effective_int(
        _load(settings),
        "daily_review_limit",
        DEFAULT_DAILY_REVIEW_LIMIT,
        MAX_DAILY_REVIEW_LIMIT,
    )
    return value


def daily_recitation_limit(settings: Settings | None = None) -> int:
    """每日到期背诵铺底条数；缺失/非法时用默认 5，超出硬上限按 20 收口。"""

    value, _ = _effective_int(
        _load(settings),
        "daily_recitation_limit",
        DEFAULT_DAILY_RECITATION_LIMIT,
        MAX_DAILY_RECITATION_LIMIT,
    )
    return value


def exam_day_limit_factor(settings: Settings | None = None) -> float:
    """考试日复习上限放大系数；缺失/非法/小于 1 时回退默认 1.5。

    只放大、不缩小：`factor < 1` 视为配置错误，避免 "考试日反而少做"。
    最终上限仍由 `MAX_DAILY_REVIEW_LIMIT` 收口。
    """

    value, _ = _effective_factor(_load(settings))
    return value


def setup_completed(settings: Settings | None = None) -> bool:
    """首次运行向导是否已标记完成；缺失或非布尔时视为未完成。"""

    value, _ = _effective_bool(_load(settings))
    return value
