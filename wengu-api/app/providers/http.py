"""共享 OpenAI-compat chat/completions 客户端：零厂商 SDK，httpx 直连。

错误处理：HTTP/网络错误归一化为 ProviderHttpError（含状态码与上游 error 摘要，
绝不回显请求体——请求体里可能有题目图片/文本）。原始响应由调用方决定是否落 ai-raw/。
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.base import TokenUsage


class ProviderHttpError(RuntimeError):
    def __init__(self, provider: str, status: int | None, message: str) -> None:
        self.status = status
        super().__init__(f"{provider} 调用失败: status={status} {message}")


class ProviderResponseError(RuntimeError):
    """上游返回了 200 但结构不可解析（先救 JSON 抖动，再由 Schema 层兜底）。"""


@dataclass(frozen=True)
class ChatResponse:
    content: str
    usage: TokenUsage
    latency_ms: int
    raw: dict[str, Any]


async def chat_completions(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    client: httpx.AsyncClient | None = None,
    temperature: float | None = None,
    timeout: float = 60.0,
) -> ChatResponse:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    except httpx.HTTPError as exc:
        raise ProviderHttpError(provider, None, type(exc).__name__) from exc
    finally:
        if owns_client:
            await client.aclose()

    latency_ms = int((time.perf_counter() - started) * 1000)

    if response.status_code != 200:
        code, message = _extract_error(response)
        raise ProviderHttpError(provider, response.status_code, f"{code}: {message}")

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage_raw = body.get("usage") or {}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ProviderResponseError(f"{provider} 响应结构异常: {type(exc).__name__}") from exc

    return ChatResponse(
        content=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        usage=TokenUsage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        ),
        latency_ms=latency_ms,
        raw=body,
    )


def _extract_error(response: httpx.Response) -> tuple[str | None, str]:
    """只取上游 error.code/message 摘要，不回显请求内容。"""

    try:
        body = response.json()
        error = body.get("error") or {}
        return (
            str(error.get("code")) if error.get("code") else None,
            str(error.get("message"))[:200] if error.get("message") else response.text[:120],
        )
    except ValueError:
        return None, response.text[:120]


def extract_json_object(text: str, *, provider: str = "provider", task: str = "") -> dict[str, Any]:
    """从模型输出中抢救第一个 JSON 对象（宽松解析层；严格校验归 Schema 层）。"""

    where = f"{provider}/{task}" if task else provider
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ProviderResponseError(f"{where}: 模型输出中没有 JSON 对象")
    try:
        value = json.loads(text[start : end + 1])
    except ValueError as exc:
        raise ProviderResponseError(f"{where}: 模型输出 JSON 解析失败: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ProviderResponseError("模型输出 JSON 不是对象")
    return value


def image_to_data_url(image_path: str, *, default_mime: str = "image/png") -> str:
    path = image_path.lower()
    mime = (
        "image/jpeg"
        if path.endswith((".jpg", ".jpeg"))
        else "image/png"
        if path.endswith(".png")
        else "image/webp"
        if path.endswith(".webp")
        else default_mime
    )
    with open(image_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
