"""Provider registry: 任务 → 供应商。加一家 = adapter 文件 + 这里一行 + .env，业务零改动。

路由表配置化（app-config.json 的 provider_routing 热覆盖 DEFAULT_ROUTING）；
模型名/密钥只从 .env 来，缺失即 fail-fast（ProviderConfigError），绝不猜。
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


DEFAULT_ROUTING: dict[str, str] = {
    "extract_problem": "doubao",  # 拍照提取：多模态主链路（含按题型路由的默认落点）
    "grade": "doubao",  # 过程题初判：保守建议值，客观题根本不进这条路
    "solve_explain": "doubao",  # 三段式讲解
    "dictation_extract": "qwen_vl",  # 英语字形默写：Phase 0 实测 Qwen 占优
    "text": "deepseek",  # 文本侧：错因预填/标签等
}

VISION_TASKS = frozenset({"extract_problem", "grade", "solve_explain", "dictation_extract"})


def resolve_task_provider(task: str, runtime: RuntimeConfig) -> str:
    routing = {**DEFAULT_ROUTING, **runtime.provider_routing}
    name = routing.get(task)
    if not name:
        raise ProviderConfigError(
            f"任务 {task!r} 没有路由落点（可用任务: {sorted(DEFAULT_ROUTING)}）"
        )
    return name


def _required(value: str | None, what: str) -> str:
    if not value or not value.strip():
        raise ProviderConfigError(f"缺少 {what}（.env 配置后才允许路由到该供应商）")
    return value


def create_vision_provider(
    name: str, *, settings: Settings, runtime: RuntimeConfig
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
        model = _required(getattr(settings, attr), f"WENGU_{attr.upper()}")
        return DoubaoVisionProvider(
            api_key=api_key, model=model, base_url=settings.doubao_base_url
        )
    if name == "qwen_vl":
        api_key = _required(settings.qwen_api_key, "WENGU_QWEN_API_KEY / DASHSCOPE_API_KEY")
        attr = (
            "qwen_model_flagship" if runtime.model_tier_default == "flagship" else "qwen_model_value"
        )
        model = _required(getattr(settings, attr), f"WENGU_{attr.upper()}")
        return QwenVLProvider(api_key=api_key, model=model, base_url=settings.qwen_base_url)
    if name == "tencent":
        return TencentVisionProvider()  # 占位：调用时抛 NotImplementedError
    raise ProviderConfigError(f"未知视觉供应商: {name!r}")


def create_text_provider(name: str, *, settings: Settings) -> TextProvider:
    if name in ("mock", "mock_text"):
        return MockTextProvider()
    if name == "deepseek":
        api_key = _required(settings.deepseek_api_key, "WENGU_DEEPSEEK_API_KEY")
        return OpenAITextProvider(
            api_key=api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
        )
    raise ProviderConfigError(f"未知文本供应商: {name!r}")
