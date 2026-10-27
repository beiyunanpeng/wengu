"""共享 httpx 客户端与解析工具的契约测试（MockTransport，零网络）。"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from app.providers.http import (
    ProviderHttpError,
    ProviderResponseError,
    chat_completions,
    extract_json_object,
    image_to_data_url,
)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    assert request.method == "POST"
    assert str(request.url).endswith("/v1/chat/completions")
    assert request.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(request.content)
    assert body["model"] == "m1"
    assert body["messages"][0]["role"] == "user"
    return httpx.Response(
        200,
        json={
            "id": "chat-1",
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        },
    )


@pytest.mark.unit
async def test_chat_completions_posts_and_parses() -> None:
    async with httpx.AsyncClient(
        transport=_transport(_ok_handler), base_url="https://example.com"
    ) as client:
        resp = await chat_completions(
            provider="doubao",
            base_url="https://example.com/v1",
            api_key="sk-test",
            model="m1",
            messages=[{"role": "user", "content": "hi"}],
            client=client,
        )
    assert resp.content == "hi"
    assert resp.usage.input_tokens == 11
    assert resp.usage.output_tokens == 7
    assert resp.latency_ms >= 0
    assert resp.raw["id"] == "chat-1"


@pytest.mark.unit
async def test_chat_completions_error_status_carries_no_request_echo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "InvalidApiKey", "message": "bad key"}},
        )

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        with pytest.raises(ProviderHttpError) as excinfo:
            await chat_completions(
                provider="qwen_vl",
                base_url="https://example.com/v1",
                api_key="sk-test",
                model="m1",
                messages=[{"role": "user", "content": "secret-content"}],
                client=client,
            )
    message = str(excinfo.value)
    assert "401" in message
    assert "InvalidApiKey" in message
    assert "secret-content" not in message  # 错误绝不回显请求体


@pytest.mark.unit
async def test_chat_completions_merges_extra_payload() -> None:
    sent: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        await chat_completions(
            provider="qwen_vl",
            base_url="https://example.com/v1",
            api_key="sk-test",
            model="m1",
            messages=[{"role": "user", "content": "hi"}],
            client=client,
            extra_payload={"enable_thinking": False},
        )
    assert sent["model"] == "m1"
    assert sent["enable_thinking"] is False


@pytest.mark.unit
async def test_chat_completions_broken_200_is_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async with httpx.AsyncClient(transport=_transport(handler)) as client:
        with pytest.raises(ProviderResponseError):
            await chat_completions(
                provider="doubao",
                base_url="https://example.com/v1",
                api_key="sk-test",
                model="m1",
                messages=[{"role": "user", "content": "x"}],
                client=client,
            )


@pytest.mark.unit
def test_extract_json_object_salvages_from_prose() -> None:
    text = '前言\n{"a": 1, "b": [2, 3]}\n后记'
    assert extract_json_object(text, provider="doubao", task="grade") == {"a": 1, "b": [2, 3]}

    with pytest.raises(ProviderResponseError):
        extract_json_object("没有对象", provider="doubao", task="grade")

    with pytest.raises(ProviderResponseError):
        extract_json_object("{broken", provider="doubao", task="grade")


@pytest.mark.unit
def test_extract_json_object_repairs_latex_backslashes() -> None:
    raw = '{"problem_text": "$\\sqrt{2}$", "note": "a\\nb"}'
    assert extract_json_object(raw) == {
        "problem_text": "$\\sqrt{2}$",
        "note": "a\nb",
    }

    assert extract_json_object('{"x": "\\u12"}') == {"x": "\\u12"}


@pytest.mark.unit
def test_image_to_data_url_detects_mime(tmp_path) -> None:
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG")
    url = image_to_data_url(str(png))
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == b"\x89PNG"

    jpg = tmp_path / "b.jpg"
    jpg.write_bytes(b"\xff\xd8")
    assert image_to_data_url(str(jpg)).startswith("data:image/jpeg;base64,")

    webp = tmp_path / "c.webp"
    webp.write_bytes(b"RIFF")
    assert image_to_data_url(str(webp)).startswith("data:image/webp;base64,")
