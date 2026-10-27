"""Alibaba Qwen-VL adapter — DashScope OpenAI-compatible endpoint."""

from __future__ import annotations

from app.providers.openai_vision import OpenAIVisionProvider


class QwenVLProvider(OpenAIVisionProvider):
    name = "qwen_vl"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def _extra_chat_kwargs(self) -> dict[str, object]:
        # 默认思考模式下整页提取实测 176s（超 120s 超时）；关闭后同图 16s 返回合法 JSON。
        # 质量影响待 P0-2 黄金集复测，若确认思考必要再按任务重新开启。
        return {"extra_payload": {"enable_thinking": False}}
