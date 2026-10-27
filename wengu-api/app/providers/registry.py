"""Provider registry: 任务 → 有序供应商列表 + 任务级模型覆盖。

路由表配置化（app-config.json 的 provider_routing 按任务覆盖 DEFAULT_ROUTING）；
单值字符串等价于单元素列表，兼容旧配置。密钥/默认模型只从 .env 来，缺失即
fail-fast（ProviderConfigError），绝不猜；按 task 的模型覆盖走热配置 task_models。
"""

from __future__ import annotations

from app.core.config import RuntimeConfig, Settings
from app.providers.base import TextProvider, VisionProvider
from app.providers.doubao import DoubaoVisionProvider
from app.providers.mock import MockTextProvider, MockVisionProvider
from app.providers.qwen_vl import QwenVLProvider
from app.providers.tencent import TencentVisionProvider
from app.providers.text import OpenAITextProvider


class ProviderConfigError(RuntimeError):
    """供应商配置缺失（密钥/模型名）或路由指向未知供应商。"""


ProviderRoute = str | list[str]

DEFAULT_ROUTING: dict[str, list[str]] = {
    "extract_problem": ["doubao", "qwen_vl"],  # 拍照提取：豆包不可用时切 Qwen
    "grade": ["doubao", "qwen_vl"],  # 过程题初判：客观题根本不进这条路
    "solve_explain": ["doubao", "qwen_vl"],  # 三段式讲解
    "dictation_extract": ["qwen_vl", "doubao"],  # 英语字形默写：Phase 0 实测 Qwen 占优
    "text": ["deepseek"],  # 文本侧暂无第二家
}

VISION_TASKS = frozenset({"extract_problem", "grade", "solve_explain", "dictation_extract"})

# 任务级默认模型：只列模型类型会踩坑的项，值是 provider 的档位后缀。
# qwen 的 value 档是 OCR（qwen3.5-ocr），VLM 任务必须走旗舰档（qwen3.8-max）；
# 字形默写反过来才用 OCR 档。其余 provider/任务沿用 model_tier_default。
DEFAULT_TASK_MODEL_SLOTS: dict[str, dict[str, str]] = {
    "extract_problem": {"qwen_vl": "flagship"},
    "grade": {"qwen_vl": "flagship"},
    "solve_explain": {"qwen_vl": "flagship"},
    "dictation_extract": {"qwen_vl": "value"},
}

# provider 名 → .env 字段前缀（qwen_vl 的模型字段是 WENGU_QWEN_MODEL_*）。
SETTINGS_PREFIX = {"qwen_vl": "qwen", "doubao": "doubao", "deepseek": "deepseek"}


def resolve_task_providers(task: str, runtime: RuntimeConfig) -> tuple[str, ...]:
    routing = {**DEFAULT_ROUTING, **runtime.provider_routing}
    route = routing.get(task)
    if route is None:
        raise ProviderConfigError(
            f"任务 {task!r} 没有路由落点（可用任务: {sorted(DEFAULT_ROUTING)}）"
        )
    raw = [route] if isinstance(route, str) else list(route)
    names = tuple(dict.fromkeys(name.strip() for name in raw if name and name.strip()))
    if not names:
        raise ProviderConfigError(f"任务 {task!r} 的路由为空（至少配置一家供应商）")
    return names


def resolve_task_model(
    task: str, provider: str, runtime: RuntimeConfig, settings: Settings
) -> str | None:
    """按 task 选模型：显式 task_models → 内置默认档 → None（沿用档位默认）。"""

    overrides = runtime.task_models.get(task) or {}
    if provider in overrides:
        return _required(overrides[provider], f"task_models.{task}.{provider}")

    slot = DEFAULT_TASK_MODEL_SLOTS.get(task, {}).get(provider)
    if slot is None:
        return None
    prefix = SETTINGS_PREFIX.get(provider, provider)
    attr = f"{prefix}_model_{slot}"
    value = getattr(settings, attr, None)
    return _required(
        value if isinstance(value, str) else None,
        f"WENGU_{attr.upper()}（{task} 默认走 {provider} 的 {slot} 档）",
    )


def _required(value: str | None, what: str) -> str:
    if not value or not value.strip():
        raise ProviderConfigError(f"缺少 {what}（.env 配置后才允许路由到该供应商）")
    return value


def create_vision_provider(
    name: str,
    *,
    settings: Settings,
    runtime: RuntimeConfig,
    model: str | None = None,
) -> VisionProvider:
    if name == "mock":
        return MockVisionProvider()
    if name == "doubao":
        api_key = _required(settings.doubao_api_key, "WENGU_DOUBAO_API_KEY / ARK_API_KEY")
        attr = (
            "doubao_model_flagship"
            if runtime.model_tier_default == "flagship"
            else "doubao_model_value"
        )
        chosen = (
            _required(model, "task_models 指定的模型")
            if model is not None
            else _required(getattr(settings, attr), f"WENGU_{attr.upper()}")
        )
        return DoubaoVisionProvider(
            api_key=api_key, model=chosen, base_url=settings.doubao_base_url
        )
    if name == "qwen_vl":
        api_key = _required(settings.qwen_api_key, "WENGU_QWEN_API_KEY / DASHSCOPE_API_KEY")
        attr = (
            "qwen_model_flagship" if runtime.model_tier_default == "flagship" else "qwen_model_value"
        )
        chosen = (
            _required(model, "task_models 指定的模型")
            if model is not None
            else _required(getattr(settings, attr), f"WENGU_{attr.upper()}")
        )
        return QwenVLProvider(api_key=api_key, model=chosen, base_url=settings.qwen_base_url)
    if name == "tencent":
        return TencentVisionProvider()  # 占位：调用时抛 NotImplementedError
    raise ProviderConfigError(f"未知视觉供应商: {name!r}")


def create_text_provider(
    name: str, *, settings: Settings, model: str | None = None
) -> TextProvider:
    if name in ("mock", "mock_text"):
        return MockTextProvider()
    if name == "deepseek":
        api_key = _required(settings.deepseek_api_key, "WENGU_DEEPSEEK_API_KEY")
        chosen = (
            _required(model, "task_models 指定的模型")
            if model is not None
            else settings.deepseek_model
        )
        return OpenAITextProvider(
            api_key=api_key,
            model=chosen,
            base_url=settings.deepseek_base_url,
        )
    raise ProviderConfigError(f"未知文本供应商: {name!r}")
