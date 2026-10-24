"""Alibaba Qwen-VL adapter — DashScope OpenAI-compatible endpoint."""

from __future__ import annotations

from app.providers.openai_vision import OpenAIVisionProvider


class QwenVLProvider(OpenAIVisionProvider):
    name = "qwen_vl"
    default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
