"""Volcano Engine Doubao (Ark) vision adapter — OpenAI-compatible endpoint."""

from __future__ import annotations

from app.providers.openai_vision import OpenAIVisionProvider


class DoubaoVisionProvider(OpenAIVisionProvider):
    name = "doubao"
    default_base_url = "https://ark.cn-beijing.volces.com/api/v3"
