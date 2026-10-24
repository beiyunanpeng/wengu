"""供应商连通性冒烟（开发者手动跑，不进 CI）：

    python -m scripts.smoke_providers            # 每家一次最小 chat 调用
    python -m scripts.smoke_providers --list     # 只列各家 /models 可用模型 ID
    python -m scripts.smoke_providers --prefer-dotenv
        # 本地验证专用：wengu-api/.env 优先于进程环境变量。
        # 用途：进程环境里残留旧密钥/旧 base_url 时（如 Qoder 会话快照不刷新、
        # 密钥刚重置），仍能用 .env 里的新值验证连通性。应用运行时行为不变
        # （pydantic-settings 规定进程环境变量优先于 .env）。

密钥从环境变量 / wengu-api/.env 读取（WENGU_DOUBAO_API_KEY 或 ARK_API_KEY、
WENGU_QWEN_API_KEY 或 DASHSCOPE_API_KEY）；本脚本绝不打印密钥。
模型名未配置时按 /models 列表自动挑选（豆包优先含 "vision"，Qwen 优先含 "qwen-vl"），
并把挑选结果打印出来供写入 .env。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from app.core.config import get_settings
from app.providers.http import ProviderHttpError, chat_completions

API_DIR = Path(__file__).resolve().parents[1]

_PREFER_KEYWORDS = {"doubao": "vision", "qwen_vl": "qwen-vl"}


def _pick_model(ids: list[str], keyword: str) -> str | None:
    for model_id in ids:
        if keyword.lower() in model_id.lower():
            return model_id
    return ids[0] if ids else None


async def _list_models(
    *, provider: str, base_url: str, api_key: str, client: httpx.AsyncClient
) -> list[str]:
    resp = await client.get(
        f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}
    )
    if resp.status_code != 200:
        code, message = _error_summary(resp)
        raise ProviderHttpError(provider, resp.status_code, f"{code}: {message}")
    data = resp.json()
    return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]


def _error_summary(resp: httpx.Response) -> tuple[str | None, str]:
    try:
        error = (resp.json().get("error")) or {}
        return (
            str(error.get("code")) if error.get("code") else None,
            str(error.get("message"))[:200] if error.get("message") else resp.text[:120],
        )
    except ValueError:
        return None, resp.text[:120]


async def _smoke_one(
    provider: str,
    *,
    base_url: str,
    api_key: str | None,
    model: str | None,
    list_only: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"provider": provider, "base_url": base_url}
    if not api_key:
        result["status"] = "skipped: 未配置密钥（ARK_API_KEY / DASHSCOPE_API_KEY 或 WENGU_ 前缀）"
        return result
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            ids = await _list_models(provider=provider, base_url=base_url, api_key=api_key, client=client)
        except ProviderHttpError as exc:
            result["status"] = f"models 列表失败: {exc}"
            return result
        result["available_models"] = ids
        if list_only:
            result["status"] = "ok"
            return result
        if not model:
            model = _pick_model(ids, _PREFER_KEYWORDS.get(provider, ""))
            result["auto_picked_model"] = model
        if not model:
            result["status"] = "skipped: /models 为空，无法自动挑选，请配置模型名"
            return result
        try:
            resp = await chat_completions(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                client=client,
                temperature=0,
            )
        except ProviderHttpError as exc:
            result["status"] = f"调用失败: {exc}"
            return result
        result.update(
            status="ok",
            model=model,
            latency_ms=resp.latency_ms,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
            reply_head=resp.content[:40],
        )
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="供应商连通性冒烟")
    parser.add_argument("--list", action="store_true", help="只列可用模型 ID，不发 chat 调用")
    parser.add_argument(
        "--prefer-dotenv",
        action="store_true",
        help="wengu-api/.env 优先于进程环境变量（仅本地验证用，不改变应用运行时行为）",
    )
    args = parser.parse_args()

    settings = get_settings()
    dotenv_vars: dict[str, str] = {}
    if args.prefer_dotenv:
        from dotenv import dotenv_values

        dotenv_vars = {
            k: v for k, v in dotenv_values(API_DIR / ".env").items() if v is not None
        }

    def pick(field: str, *names: str) -> Any:
        """--prefer-dotenv 时 .env 同名变量优先；否则用 Settings（env > .env）。"""
        if args.prefer_dotenv:
            for name in names:
                if dotenv_vars.get(name):
                    return dotenv_vars[name]
        return getattr(settings, field)

    checks = [
        _smoke_one(
            "doubao",
            base_url=pick("doubao_base_url", "WENGU_DOUBAO_BASE_URL", "ARK_BASE_URL"),
            api_key=pick("doubao_api_key", "WENGU_DOUBAO_API_KEY", "ARK_API_KEY"),
            model=pick("doubao_model_value", "WENGU_DOUBAO_MODEL_VALUE"),
            list_only=args.list,
        ),
        _smoke_one(
            "qwen_vl",
            base_url=pick("qwen_base_url", "WENGU_QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
            api_key=pick("qwen_api_key", "WENGU_QWEN_API_KEY", "DASHSCOPE_API_KEY"),
            model=pick("qwen_model_value", "WENGU_QWEN_MODEL_VALUE"),
            list_only=args.list,
        ),
    ]
    for check in await asyncio.gather(*checks):
        print(json.dumps(check, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
