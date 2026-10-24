"""OpenAI-compatible text provider (DeepSeek / GLM / Kimi)."""

from __future__ import annotations

from typing import Any

from app.providers.base import CallMeta, TextProvider, TokenUsage
from app.providers.http import ChatResponse, chat_completions


class OpenAITextProvider(TextProvider):
    name = "openai_text"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        client: Any = None,
        temperature: float | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError(f"provider {self.name}: api_key is required")
        if not model or not model.strip():
            raise ValueError(f"provider {self.name}: model is required")
        if not base_url or not base_url.strip():
            raise ValueError(f"provider {self.name}: base_url is required")
        self._api_key = api_key
        self._model = model
        self.model = model  # 公开只读：缓存键/审计用
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._temperature = temperature
        self._timeout = timeout

    async def complete(self, prompt: str, *, temperature: float | None = None) -> tuple[str, CallMeta]:
        resp: ChatResponse = await chat_completions(
            provider=self.name,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            client=self._client,
            temperature=temperature if temperature is not None else self._temperature,
            timeout=self._timeout,
        )
        meta = CallMeta(
            provider=self.name,
            model=self._model,
            latency_ms=resp.latency_ms,
            usage=resp.usage or TokenUsage(),
            raw={"id": resp.raw.get("id"), "finish_reason": resp.raw.get("finish_reason")},
        )
        return resp.content, meta
