"""AiGateway 端到端：临时 prompt 库 + mock 供应商 + 真实迁移库（审计落库验证）。

覆盖管线纪律：路由→护栏→缓存→调用→审计；缓存命中零调用；审计独立提交；
错误路径也留痕；prompt 版本进 model_runs。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import RuntimeConfig, Settings
from app.core.database import create_sqlite_engine
from app.models import ModelRun
from app.prompts.loader import load_prompts
from app.providers.cache import ContentHashCache
from app.services.ai_gateway import AiGateway
from app.services.model_audit import DailyLimitExceeded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

PROMPTS = {
    "extract_problem.md": (
        "---\nid: extract_problem\nversion: 1\n---\n提取题目与作答，输出 JSON。"
    ),
    "grade.md": (
        "---\nid: grade\nversion: 2\n---\n判题：{{PROBLEM_TEXT}} 学生答：{{STUDENT_ANSWER}}"
    ),
    "explain_guide.md": (
        "---\nid: explain_guide\nversion: 1\n---\n讲解 {{PROBLEM_TEXT}}（档位 {{HINT_LEVEL}}）"
    ),
    "label_suggest.md": (
        "---\nid: label_suggest\nversion: 1\n---\n给错题建议标签：{{PROBLEM_TEXT}}"
    ),
}


def _runtime(daily_call_limit: int = 50, routing: dict[str, str] | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        model_tier_default="value",
        daily_call_budget_cny=10.0,
        daily_call_limit=daily_call_limit,
        variant_on_demand=True,
        provider_routing=routing or {},
        model_prices={},
    )


@pytest.fixture
async def gateway(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    for name, body in PROMPTS.items():
        (prompts_dir / name).write_text(body, encoding="utf-8")

    db_path = tmp_path / "gw.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")

    engine = create_sqlite_engine(db_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path / "data",
    )
    gw = AiGateway(
        settings=settings,
        runtime=_runtime(routing={
            "extract_problem": "mock",
            "grade": "mock",
            "solve_explain": "mock",
            "text": "mock",
        }),
        prompts=load_prompts(prompts_dir),
        cache=ContentHashCache(tmp_path / "ai-cache"),
        session_factory=factory,
        raw_dir=tmp_path / "ai-raw",
    )
    yield gw, factory, tmp_path
    await engine.dispose()


async def _run_count(factory) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count(ModelRun.id))))


@pytest.mark.integration
async def test_extract_problem_full_pipeline_and_cache_hit(gateway) -> None:
    gw, factory, tmp_path = gateway
    image = tmp_path / "page.png"
    image.write_bytes(b"fake-png-bytes")

    result1, meta1 = await gw.extract_problem(str(image))
    assert result1.problem_text == f"[mock] problem from {image}"
    assert meta1.raw["cache_hit"] is False
    assert await _run_count(factory) == 1

    # 第二次：缓存命中，零新增调用、零审计行
    result2, meta2 = await gw.extract_problem(str(image))
    assert result2 == result1
    assert meta2.raw["cache_hit"] is True
    assert await _run_count(factory) == 1

    # L2 缓存文件一份；mock 无 raw 上游响应，L3 不落盘（真实 adapter 才有）
    assert len(list((tmp_path / "ai-cache").glob("*.json"))) == 1
    assert len(list((tmp_path / "ai-raw").rglob("*.json"))) == 0

    # 审计行元数据完整（prompt 版本进库，零题目内容）
    async with factory() as session:
        run = (await session.scalars(select(ModelRun))).one()
    assert run.task_type == "extract_problem"
    assert run.prompt_id == "extract_problem"
    assert run.prompt_version == "1"
    assert run.status == "ok"
    assert run.provider == "mock"
    assert "page.png" not in (run.error or "")


@pytest.mark.integration
async def test_grade_and_solve_explain_render_prompt_tokens(gateway) -> None:
    gw, factory, _ = gateway
    graded, _ = await gw.grade("1+1=?", "2")
    assert graded.verdict == "uncertain"

    explanation, _ = await gw.solve_explain("解方程 2x=4", hint_level=9)
    assert explanation.hint_level == 3
    assert "解方程 2x=4" in explanation.steps[0]

    async with factory() as session:
        runs = (await session.scalars(select(ModelRun))).all()
    assert {r.prompt_id for r in runs} == {"grade", "explain_guide"}
    assert all(r.prompt_version for r in runs)


@pytest.mark.integration
async def test_solve_explain_extra_values_invalidate_cache(gateway) -> None:
    gw, factory, _ = gateway
    await gw.solve_explain("题A", extra_values={"STRATEGY": "method_hint"})
    await gw.solve_explain("题A", extra_values={"STRATEGY": "calculation_check"})
    _, repeat = await gw.solve_explain("题A", extra_values={"STRATEGY": "method_hint"})

    assert repeat.raw["cache_hit"] is True
    assert await _run_count(factory) == 2


@pytest.mark.integration
async def test_grade_sample_index_bypasses_cache(gateway) -> None:
    gw, factory, _ = gateway
    _, first = await gw.grade("题", "答", sample_index=0)
    _, repeat = await gw.grade("题", "答", sample_index=0)
    _, second = await gw.grade("题", "答", sample_index=1)

    assert first.raw["cache_hit"] is False
    assert repeat.raw["cache_hit"] is True
    assert second.raw["cache_hit"] is False  # 多采样不能被缓存折叠成一次
    assert await _run_count(factory) == 2


@pytest.mark.integration
async def test_complete_text_routes_to_text_provider(gateway) -> None:
    gw, factory, _ = gateway
    text, meta = await gw.complete_text(
        prompt_id="label_suggest", extra_values={"PROBLEM_TEXT": "某错题"}
    )
    assert text == "[mock] text completion for: 给错题建议标签：某错题"
    assert meta.provider == "mock_text"

    async with factory() as session:
        run = (await session.scalars(select(ModelRun))).one()
    assert run.task_type == "text"


@pytest.mark.integration
async def test_error_path_records_audit_and_raises(gateway) -> None:
    gw, factory, tmp_path = gateway
    image = tmp_path / "real.png"
    image.write_bytes(b"bytes")
    runtime = _runtime(routing={
        "extract_problem": "tencent",  # 占位供应商：调用即 NotImplementedError
    })
    gw._runtime = runtime
    gw._vision_providers.clear()

    with pytest.raises(NotImplementedError):
        await gw.extract_problem(str(image))
    assert await _run_count(factory) == 1
    async with factory() as session:
        run = (await session.scalars(select(ModelRun))).one()
    assert run.status == "error"
    assert "stub" in run.error


@pytest.mark.integration
async def test_daily_guard_blocks_new_calls(gateway) -> None:
    gw, factory, _ = gateway
    # 把上限压到 1：第一次调用成功，第二次（不同输入）被闸住
    gw._runtime = _runtime(daily_call_limit=1, routing={
        "extract_problem": "mock", "solve_explain": "mock",
    })

    await gw.solve_explain("题A")
    with pytest.raises(DailyLimitExceeded, match="上限"):
        await gw.solve_explain("题B")

    async with factory() as session:
        runs = (await session.scalars(select(ModelRun))).all()
    assert len(runs) == 1  # 被闸住的调用没有产生新审计行


@pytest.mark.integration
async def test_prompt_version_bump_invalidates_cache(gateway) -> None:
    gw, factory, tmp_path = gateway
    image = tmp_path / "p.png"
    image.write_bytes(b"bytes-v1")

    await gw.extract_problem(str(image))
    assert await _run_count(factory) == 1

    # 模拟"改语义递增版本"：重写 prompt 文件并重建 gateway 的 prompt 表
    (tmp_path / "prompts" / "extract_problem.md").write_text(
        "---\nid: extract_problem\nversion: 2\n---\n新提示词。", encoding="utf-8"
    )
    gw._prompts = load_prompts(tmp_path / "prompts")

    await gw.extract_problem(str(image))  # prompt_version 变了 → 缓存 miss → 真实调用
    assert await _run_count(factory) == 2
