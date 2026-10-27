"""model_runs 自计 + 每日成本护栏（临时库 create_all，零网络）。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core.database import Base, create_sqlite_engine
from app.models import ModelRun
from app.prompts.loader import Prompt
from app.providers.base import CallMeta, TokenUsage
from app.services.model_audit import (
    DailyLimitExceeded,
    check_daily_guard,
    record_model_run,
    today_call_count,
    today_estimated_cost_cny,
)
from sqlalchemy.ext.asyncio import async_sessionmaker


def _runtime(daily_call_limit: int, budget: float = 0.0, model_prices=None):
    from app.core.config import RuntimeConfig

    return RuntimeConfig(
        model_tier_default="value",
        daily_call_budget_cny=budget,
        daily_call_limit=daily_call_limit,
        variant_on_demand=True,
        provider_routing={},
        model_prices=model_prices or {},
    )


def _prompt() -> Prompt:
    return Prompt(id="grade", version=3, path=Path("grade.md"), template="t")


@pytest.fixture
async def session(tmp_path):
    engine = create_sqlite_engine(tmp_path / "audit.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _meta(model: str = "m", input_tokens: int = 1_000_000, output_tokens: int = 0) -> CallMeta:
    return CallMeta(
        provider="doubao",
        model=model,
        latency_ms=12,
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


@pytest.mark.unit
async def test_record_model_run_stores_metadata_only(session) -> None:
    run = await record_model_run(
        session, task_type="grade", prompt=_prompt(), status="ok", meta=_meta()
    )
    await session.commit()

    assert run.prompt_id == "grade"
    assert run.prompt_version == "3"
    assert run.status == "ok"
    assert run.latency_ms == 12
    assert "input_tokens" in run.usage_json
    assert "1_000_000" not in run.usage_json  # 纯 JSON 数字，无题目内容


@pytest.mark.unit
async def test_daily_guard_blocks_on_call_count(session) -> None:
    runtime = _runtime(daily_call_limit=2)
    await check_daily_guard(session, runtime=runtime)  # 0/2 通过
    for _ in range(2):
        await record_model_run(session, task_type="grade", prompt=_prompt(), status="ok", meta=_meta())
    await session.commit()

    assert await today_call_count(session) == 2
    with pytest.raises(DailyLimitExceeded, match="上限"):
        await check_daily_guard(session, runtime=runtime)


@pytest.mark.unit
async def test_daily_guard_blocks_on_estimated_cost(session) -> None:
    prices = {"expensive-model": {"input": 4.0, "output": 10.0}}  # CNY / 1M tokens
    runtime = _runtime(daily_call_limit=10_000, budget=5.0, model_prices=prices)

    await record_model_run(
        session, task_type="grade", prompt=_prompt(), status="ok",
        meta=_meta(model="expensive-model", input_tokens=1_000_000, output_tokens=500_000),
    )
    await session.commit()

    # 1M*4 + 0.5M*10 = 9 元 > 5 元预算
    assert await today_estimated_cost_cny(session, prices) == pytest.approx(9.0)
    with pytest.raises(DailyLimitExceeded, match="成本"):
        await check_daily_guard(session, runtime=runtime)

    # 未知模型不在价目表 → 不参与估算
    assert await today_estimated_cost_cny(session, {"other": {"input": 1}}) == 0.0


@pytest.mark.unit
async def test_count_only_today(session) -> None:
    runtime = _runtime(daily_call_limit=1)
    stale = ModelRun(
        task_type="grade", provider="p", model="m", prompt_id="grade", prompt_version="1",
        status="ok", created_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    session.add(stale)
    await session.commit()

    assert await today_call_count(session) == 0  # 历史记录不计入今日
    await check_daily_guard(session, runtime=runtime)


@pytest.mark.unit
async def test_attempt_chain_fields_and_config_error_not_counted(session) -> None:
    runtime = _runtime(daily_call_limit=1)
    run = await record_model_run(
        session,
        task_type="extract_problem",
        prompt=_prompt(),
        status="config_error",
        error="缺少 WENGU_DOUBAO_API_KEY",
        attempt_group="group-1",
        attempt_index=0,
        error_kind="config",
    )
    await session.commit()

    assert (run.attempt_group, run.attempt_index, run.error_kind) == (
        "group-1",
        0,
        "config",
    )
    assert await today_call_count(session) == 0  # 配置缺失没有真实调用
    await check_daily_guard(session, runtime=runtime)

    await record_model_run(
        session,
        task_type="extract_problem",
        prompt=_prompt(),
        status="error",
        meta=_meta(),
        error="status=403 AccountOverdueError",
        attempt_group="group-1",
        attempt_index=1,
        error_kind="account",
    )
    await session.commit()
    assert await today_call_count(session) == 1  # 真实失败照常计数
    with pytest.raises(DailyLimitExceeded, match="上限"):
        await check_daily_guard(session, runtime=runtime)
