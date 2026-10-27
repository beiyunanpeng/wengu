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
from app.providers.base import CallMeta, ExtractedProblem
from app.providers.cache import ContentHashCache
from app.providers.failover import AllProvidersFailed
from app.providers.http import ProviderHttpError, ProviderResponseError
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


def _runtime(
    daily_call_limit: int = 50,
    routing: dict[str, str | list[str]] | None = None,
    task_models: dict[str, dict[str, str]] | None = None,
) -> RuntimeConfig:
    return RuntimeConfig(
        model_tier_default="value",
        daily_call_budget_cny=10.0,
        daily_call_limit=daily_call_limit,
        variant_on_demand=True,
        provider_routing=routing or {},
        task_models=task_models or {},
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
        qwen_model_value="qwen3.5-ocr",
        qwen_model_flagship="qwen3.8-max",
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


async def _runs(factory) -> list[ModelRun]:
    async with factory() as session:
        return list(
            (await session.scalars(select(ModelRun).order_by(ModelRun.attempt_index))).all()
        )


class _StubVisionProvider:
    def __init__(
        self,
        name: str,
        *,
        exc: Exception | None = None,
        result: ExtractedProblem | None = None,
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.exc = exc
        self.result = result
        self.calls = 0

    async def extract_problem(
        self, image_path: str, *, prompt: str
    ) -> tuple[ExtractedProblem, CallMeta]:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return (
            self.result
            or ExtractedProblem(
                problem_text=f"[{self.name}]题",
                student_answer="1",
                problem_complete=True,
            ),
            CallMeta(
                provider=self.name,
                model=self.model,
                latency_ms=3,
                prompt_id="extract_problem",
                prompt_version=1,
            ),
        )


@pytest.fixture
def stubs(gateway, monkeypatch):
    gw, factory, tmp_path = gateway
    providers: dict[str, _StubVisionProvider] = {}

    def fake_create(name: str, *, settings, runtime, model=None):
        provider = providers[name]
        provider.requested_model = model
        provider.model = model or f"{name}-model"
        return provider

    monkeypatch.setattr(
        "app.services.ai_gateway.create_vision_provider", fake_create
    )
    yield gw, factory, tmp_path, providers


def _use_routing(
    gw,
    route: str | list[str],
    *,
    task_models: dict[str, dict[str, str]] | None = None,
) -> None:
    gw._runtime = _runtime(
        routing={"extract_problem": route}, task_models=task_models
    )
    gw._vision_providers.clear()


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
async def test_complete_text_uses_task_model(gateway, monkeypatch) -> None:
    gw, _, _ = gateway
    captured: dict[str, str | None] = {}

    class _StubTextProvider:
        name = "stub_text"
        model = "default-text"

        async def complete(self, prompt: str, *, temperature: float | None = None):
            return "ok", CallMeta(provider=self.name, model=self.model, latency_ms=1)

    def fake_create_text(name: str, *, settings, model=None):
        captured["model"] = model
        provider = _StubTextProvider()
        provider.model = model or "default-text"
        return provider

    monkeypatch.setattr(
        "app.services.ai_gateway.create_text_provider", fake_create_text
    )
    gw._runtime = _runtime(
        routing={"text": "stub_text"},
        task_models={"text": {"stub_text": "deepseek-reasoner"}},
    )
    gw._text_providers.clear()

    text, meta = await gw.complete_text(
        prompt_id="label_suggest", extra_values={"PROBLEM_TEXT": "某错题"}
    )

    assert text == "ok"
    assert captured["model"] == "deepseek-reasoner"
    assert meta.model == "deepseek-reasoner"


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


@pytest.mark.integration
async def test_failover_primary_403_uses_backup(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    primary = _StubVisionProvider(
        "fake_primary",
        exc=ProviderHttpError("fake_primary", 403, "AccountOverdueError"),
    )
    backup = _StubVisionProvider("fake_backup")
    providers.update(fake_primary=primary, fake_backup=backup)
    _use_routing(gw, ["fake_primary", "fake_backup"])
    image = tmp_path / "failover.png"
    image.write_bytes(b"bytes")

    result, meta = await gw.extract_problem(str(image))

    assert result.problem_text == "[fake_backup]题"
    assert meta.provider == "fake_backup"
    assert (primary.calls, backup.calls) == (1, 1)
    runs = await _runs(factory)
    assert [(r.provider, r.status, r.error_kind, r.attempt_index) for r in runs] == [
        ("fake_primary", "error", "account", 0),
        ("fake_backup", "ok", None, 1),
    ]
    assert runs[0].attempt_group
    assert runs[0].attempt_group == runs[1].attempt_group


@pytest.mark.integration
async def test_failover_all_fail_aggregates_kind_and_chain(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    primary = _StubVisionProvider(
        "fake_primary", exc=ProviderHttpError("fake_primary", 403, "AccountOverdueError")
    )
    backup = _StubVisionProvider(
        "fake_backup", exc=ProviderHttpError("fake_backup", None, "ConnectTimeout")
    )
    providers.update(fake_primary=primary, fake_backup=backup)
    _use_routing(gw, ["fake_primary", "fake_backup"])
    image = tmp_path / "all-fail.png"
    image.write_bytes(b"bytes")

    with pytest.raises(AllProvidersFailed, match="全部 provider 失败") as excinfo:
        await gw.extract_problem(str(image))

    error = excinfo.value
    assert error.kind == "account"
    assert error.config_only is False
    assert error.attempt_group
    assert [(a.provider, a.error_kind, a.attempt_index) for a in error.attempts] == [
        ("fake_primary", "account", 0),
        ("fake_backup", "network", 1),
    ]
    runs = await _runs(factory)
    assert [r.status for r in runs] == ["error", "error"]
    assert [r.error_kind for r in runs] == ["account", "network"]
    assert {r.attempt_group for r in runs} == {error.attempt_group}


@pytest.mark.integration
async def test_quality_failure_does_not_failover(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    primary = _StubVisionProvider(
        "fake_primary", exc=ProviderResponseError("模型输出 JSON 解析失败")
    )
    backup = _StubVisionProvider("fake_backup")
    providers.update(fake_primary=primary, fake_backup=backup)
    _use_routing(gw, ["fake_primary", "fake_backup"])
    image = tmp_path / "quality.png"
    image.write_bytes(b"bytes")

    with pytest.raises(ProviderResponseError, match="JSON"):
        await gw.extract_problem(str(image))

    assert primary.calls == 1
    assert backup.calls == 0  # 质量错误不切备，不浪费第二次调用
    runs = await _runs(factory)
    assert len(runs) == 1
    assert runs[0].error_kind == "quality"


@pytest.mark.integration
async def test_poor_extraction_content_passes_without_failover(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    primary = _StubVisionProvider(
        "fake_primary",
        result=ExtractedProblem(
            problem_text="2. 已知〔?〕，求 x",
            student_answer=None,
            problem_complete=False,
        ),
    )
    backup = _StubVisionProvider("fake_backup")
    providers.update(fake_primary=primary, fake_backup=backup)
    _use_routing(gw, ["fake_primary", "fake_backup"])
    image = tmp_path / "poor.png"
    image.write_bytes(b"bytes")

    result, meta = await gw.extract_problem(str(image))

    assert result.problem_complete is False  # 质量交给提取闸门，不在 gateway 切备
    assert meta.provider == "fake_primary"
    assert backup.calls == 0


@pytest.mark.integration
async def test_failover_attempts_capped_by_deduped_list(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    for name in ("fake_a", "fake_b", "fake_c"):
        providers[name] = _StubVisionProvider(
            name, exc=ProviderHttpError(name, 503, "ServiceUnavailable")
        )
    _use_routing(gw, ["fake_a", "fake_a", "fake_b", "fake_c"])
    image = tmp_path / "capped.png"
    image.write_bytes(b"bytes")

    with pytest.raises(AllProvidersFailed) as excinfo:
        await gw.extract_problem(str(image))

    assert [providers[name].calls for name in ("fake_a", "fake_b", "fake_c")] == [1, 1, 1]
    assert len(excinfo.value.attempts) == 3


@pytest.mark.integration
async def test_missing_primary_config_falls_back_to_backup(gateway) -> None:
    gw, factory, tmp_path = gateway
    gw._runtime = _runtime(routing={"extract_problem": ["doubao", "mock"]})
    gw._vision_providers.clear()
    image = tmp_path / "config-fallback.png"
    image.write_bytes(b"bytes")

    result, meta = await gw.extract_problem(str(image))

    assert meta.provider == "mock"
    assert result.problem_text.startswith("[mock]")
    runs = await _runs(factory)
    assert [(r.provider, r.status, r.error_kind, r.attempt_index) for r in runs] == [
        ("doubao", "config_error", "config", 0),
        ("mock", "ok", None, 1),
    ]


@pytest.mark.integration
async def test_failover_uses_task_default_vlm_model(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    primary = _StubVisionProvider(
        "doubao", exc=ProviderHttpError("doubao", 403, "AccountOverdueError")
    )
    backup = _StubVisionProvider("qwen_vl")
    providers.update(doubao=primary, qwen_vl=backup)
    _use_routing(gw, ["doubao", "qwen_vl"])
    image = tmp_path / "vlm.png"
    image.write_bytes(b"bytes")

    result, meta = await gw.extract_problem(str(image))

    assert result.problem_text == "[qwen_vl]题"
    assert meta.provider == "qwen_vl"
    # 备用 qwen 必须拿 VLM 档，而不是 dictation 用的 OCR 档
    assert backup.requested_model == "qwen3.8-max"
    assert meta.model == "qwen3.8-max"
    runs = await _runs(factory)
    assert [(r.provider, r.status, r.model) for r in runs] == [
        ("doubao", "error", "doubao-model"),
        ("qwen_vl", "ok", "qwen3.8-max"),
    ]


@pytest.mark.integration
async def test_task_models_override_backup_model(stubs) -> None:
    gw, factory, tmp_path, providers = stubs
    primary = _StubVisionProvider(
        "doubao", exc=ProviderHttpError("doubao", 403, "AccountOverdueError")
    )
    backup = _StubVisionProvider("qwen_vl")
    providers.update(doubao=primary, qwen_vl=backup)
    _use_routing(
        gw,
        ["doubao", "qwen_vl"],
        task_models={"extract_problem": {"qwen_vl": "qwen3.8-max-2026"}},
    )
    image = tmp_path / "override.png"
    image.write_bytes(b"bytes")

    _, meta = await gw.extract_problem(str(image))

    assert backup.requested_model == "qwen3.8-max-2026"
    assert meta.model == "qwen3.8-max-2026"
