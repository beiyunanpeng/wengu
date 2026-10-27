"""model_runs 自计 + 每日成本护栏（AGENTS §4：性价比分档/每日上限/自计审计）。

只落元数据（供应商/模型/prompt 版本/token 用量/延迟/状态），绝不落题目全文、
答案、文件 URL。护栏 = 当日真实调用次数上限 + 按 model_prices 的 token 成本估算上限。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RuntimeConfig
from app.models import ModelRun
from app.prompts.loader import Prompt
from app.providers.base import CallMeta


class DailyLimitExceeded(RuntimeError):
    """当日调用次数或估算成本触顶；调用方应熔断，而不是排队重试。"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def record_model_run(
    session: AsyncSession,
    *,
    task_type: str,
    prompt: Prompt,
    status: str,
    meta: CallMeta | None = None,
    error: str | None = None,
    ai_job_id: int | None = None,
    attempt_group: str | None = None,
    attempt_index: int | None = None,
    error_kind: str | None = None,
) -> ModelRun:
    run = ModelRun(
        ai_job_id=ai_job_id,
        task_type=task_type,
        provider=meta.provider if meta else "unknown",
        model=meta.model if meta else "unknown",
        prompt_id=prompt.id,
        prompt_version=str(prompt.version),
        latency_ms=meta.latency_ms if meta else None,
        usage_json=json.dumps(asdict(meta.usage), ensure_ascii=False) if meta else None,
        status=status,
        error=error[:200] if error else None,
        attempt_group=attempt_group,
        attempt_index=attempt_index,
        error_kind=error_kind,
        created_at=_utcnow(),
    )
    session.add(run)
    await session.flush()
    return run


async def today_call_count(session: AsyncSession, *, now: datetime | None = None) -> int:
    start = _day_start(now or _utcnow())
    total = await session.scalar(
        select(func.count(ModelRun.id)).where(
            ModelRun.created_at >= start,
            ModelRun.status != "config_error",  # 配置缺失没有真实调用，不占每日次数
        )
    )
    return int(total or 0)


async def today_estimated_cost_cny(
    session: AsyncSession,
    model_prices: dict[str, dict[str, float]],
    *,
    now: datetime | None = None,
) -> float:
    """按当日 model_runs 的 token 用量 × model_prices（CNY/1M tokens）估算。"""

    if not model_prices:
        return 0.0
    start = _day_start(now or _utcnow())
    rows = await session.execute(
        select(ModelRun.model, ModelRun.usage_json).where(ModelRun.created_at >= start)
    )
    total = 0.0
    for model, usage_json in rows.all():
        if not usage_json:
            continue
        prices = model_prices.get(model)
        if not prices:
            continue
        try:
            usage = json.loads(usage_json)
        except ValueError:
            continue
        total += usage.get("input_tokens", 0) / 1_000_000 * prices.get("input", 0.0)
        total += usage.get("output_tokens", 0) / 1_000_000 * prices.get("output", 0.0)
    return total


async def check_daily_guard(session: AsyncSession, *, runtime: RuntimeConfig) -> None:
    """真实调用前检查：次数上限硬闸 + 成本估算软闸（预算=0 表示不启用成本闸）。"""

    count = await today_call_count(session)
    if count >= runtime.daily_call_limit:
        raise DailyLimitExceeded(
            f"当日模型调用已达上限 {runtime.daily_call_limit} 次（model_runs 计数），明日再试"
        )
    if runtime.daily_call_budget_cny > 0:
        cost = await today_estimated_cost_cny(session, runtime.model_prices)
        if cost >= runtime.daily_call_budget_cny:
            raise DailyLimitExceeded(
                f"当日模型估算成本 ¥{cost:.4f} 已达预算 ¥{runtime.daily_call_budget_cny:.2f}"
            )
