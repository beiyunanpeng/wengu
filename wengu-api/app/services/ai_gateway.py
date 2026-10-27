"""AiGateway：路由 → 护栏 → 缓存 → 调用 → 审计，业务代码只跟它打交道（AGENTS §4）。

纪律：
- prompt 一律从 llm_prompts/*.md 渲染后传入 adapter，本文件不留 prompt 正文；
- 缓存命中零模型调用、不进 model_runs（护栏只数真实调用）；
- 审计用独立 session 提交：业务事务回滚时 model_runs 仍完整（可重放诊断）；
- L3 原始响应落 data/ai-raw/{date}/（本地数据目录，非日志/审计表）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import RuntimeConfig, Settings, get_runtime_config, get_settings
from app.core.database import get_session_factory
from app.prompts.loader import Prompt, PromptError, load_prompts
from app.providers.base import CallMeta, Explanation, ExtractedProblem, GradeResult, TokenUsage
from app.providers.cache import ContentHashCache, hash_file, make_cache_key
from app.providers.failover import (
    CONFIG,
    AllProvidersFailed,
    ProviderAttempt,
    classify_provider_error,
    is_transferable,
)
from app.providers.registry import (
    ProviderConfigError,
    create_text_provider,
    create_vision_provider,
    resolve_task_model,
    resolve_task_providers,
)
from app.services import model_audit


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


class AiGateway:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        runtime: RuntimeConfig | None = None,
        prompts: dict[str, Prompt] | None = None,
        cache: ContentHashCache | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        raw_dir: Path | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._runtime = runtime or get_runtime_config()
        self._runtime_injected = runtime is not None
        self._prompts = (
            prompts if prompts is not None else load_prompts(self._settings.prompts_dir)
        )
        self._cache = cache or ContentHashCache(self._settings.data_dir / "ai-cache")
        self._session_factory = session_factory or get_session_factory()
        self._raw_dir = raw_dir or (self._settings.data_dir / "ai-raw")
        self._vision_providers: dict[tuple[str, str | None], Any] = {}
        self._text_providers: dict[tuple[str, str | None], Any] = {}

    # ---- prompt 渲染 -----------------------------------------------------

    def render_prompt(self, prompt_id: str, **values: str) -> tuple[Prompt, str]:
        prompt = self._prompts.get(prompt_id)
        if prompt is None:
            raise PromptError(
                f"prompt {prompt_id!r} 未装载：llm_prompts/*.md 是唯一真源（P1-4 起随 ticket 落盘）"
            )
        return prompt, prompt.render(**values)

    # ---- 供应商实例（按名缓存，避免重复构造） ----------------------------

    def _current_runtime(self) -> RuntimeConfig:
        """生产单例随 app-config 热刷新；测试注入的 runtime 保持稳定。"""

        if self._runtime_injected:
            return self._runtime
        runtime = get_runtime_config()
        if (
            runtime.model_tier_default != self._runtime.model_tier_default
            or runtime.task_models != self._runtime.task_models
        ):
            self._vision_providers.clear()
            self._text_providers.clear()
        self._runtime = runtime
        return runtime

    def _vision(self, name: str, model: str | None = None) -> Any:
        key = (name, model)
        if key not in self._vision_providers:
            self._vision_providers[key] = create_vision_provider(
                name, settings=self._settings, runtime=self._runtime, model=model
            )
        return self._vision_providers[key]

    def _text(self, name: str, model: str | None = None) -> Any:
        key = (name, model)
        if key not in self._text_providers:
            self._text_providers[key] = create_text_provider(
                name, settings=self._settings, model=model
            )
        return self._text_providers[key]

    # ---- 视觉三任务 --------------------------------------------------------

    async def extract_problem(
        self, image_path: str, *, prompt_id: str = "extract_problem"
    ) -> tuple[ExtractedProblem, CallMeta]:
        prompt, rendered = self.render_prompt(prompt_id)
        image_hash = hash_file(image_path)

        async def call_for(provider: Any) -> tuple[ExtractedProblem, CallMeta]:
            return await provider.extract_problem(image_path, prompt=rendered)

        envelope, meta = await self._run_with_failover(
            task="extract_problem",
            prompt=prompt,
            provider_for=self._vision,
            cache_key=lambda provider: make_cache_key(
                task="extract_problem",
                provider=provider.name,
                model=provider.model,
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                payload={"image_sha256": image_hash},
            ),
            call_for=call_for,
        )
        data = envelope["result"]
        result = ExtractedProblem(
            problem_text=data["problem_text"],
            student_answer=data.get("student_answer"),
            confidence=data.get("confidence"),
            problem_complete=data.get("problem_complete"),
            needs_human_review=bool(data.get("needs_human_review", True)),
            raw=data.get("raw") or {},
        )
        return result, meta

    async def grade(
        self,
        problem_text: str,
        student_answer: str,
        *,
        prompt_id: str = "grade",
        standard_answer: str = "",
        sample_index: int = 0,
    ) -> tuple[GradeResult, CallMeta]:
        prompt, rendered = self.render_prompt(
            prompt_id,
            PROBLEM_TEXT=problem_text,
            STANDARD_ANSWER=standard_answer,
            STUDENT_ANSWER=student_answer,
        )

        async def call_for(provider: Any) -> tuple[GradeResult, CallMeta]:
            return await provider.grade(problem_text, student_answer, prompt=rendered)

        envelope, meta = await self._run_with_failover(
            task="grade",
            prompt=prompt,
            provider_for=self._vision,
            cache_key=lambda provider: make_cache_key(
                task="grade",
                provider=provider.name,
                model=provider.model,
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                # sample_index 进缓存键：多次采样必须各自真实调用
                payload={
                    "problem_text": problem_text,
                    "student_answer": student_answer,
                    "standard_answer": standard_answer,
                    "sample_index": sample_index,
                },
            ),
            call_for=call_for,
        )
        data = envelope["result"]
        result = GradeResult(
            verdict=data["verdict"],
            confidence=data.get("confidence"),
            source=data.get("source", "ai"),
            rationale=data.get("rationale"),
        )
        return result, meta

    async def solve_explain(
        self,
        problem_text: str,
        *,
        prompt_id: str = "explain_guide",
        hint_level: int = 0,
        extra_values: dict[str, str] | None = None,
    ) -> tuple[Explanation, CallMeta]:
        level = max(0, min(int(hint_level), 3))
        values = dict(extra_values or {})
        values["PROBLEM_TEXT"] = problem_text
        values["HINT_LEVEL"] = str(level)
        prompt, rendered = self.render_prompt(prompt_id, **values)

        async def call_for(provider: Any) -> tuple[Explanation, CallMeta]:
            return await provider.solve_explain(
                problem_text, prompt=rendered, hint_level=level
            )

        envelope, meta = await self._run_with_failover(
            task="solve_explain",
            prompt=prompt,
            provider_for=self._vision,
            cache_key=lambda provider: make_cache_key(
                task="solve_explain",
                provider=provider.name,
                model=provider.model,
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                payload={
                    "problem_text": problem_text,
                    "hint_level": level,
                    "extra_values": sorted((extra_values or {}).items()),
                },
            ),
            call_for=call_for,
        )
        data = envelope["result"]
        result = Explanation(
            steps=tuple(data["steps"]),
            answer=data.get("answer"),
            hint_level=int(data.get("hint_level", level)),
            focus=str(data.get("focus") or ""),
            consolidation=str(data.get("consolidation") or ""),
        )
        return result, meta

    # ---- 文本侧 -------------------------------------------------------------

    async def complete_text(
        self, *, prompt_id: str, extra_values: dict[str, str] | None = None
    ) -> tuple[str, CallMeta]:
        prompt, rendered = self.render_prompt(prompt_id, **(extra_values or {}))

        async def call_for(provider: Any) -> tuple[dict[str, Any], CallMeta]:
            text, meta = await provider.complete(rendered)
            return {"text": text}, meta

        envelope, meta = await self._run_with_failover(
            task="text",
            prompt=prompt,
            provider_for=self._text,
            cache_key=lambda provider: make_cache_key(
                task="text",
                provider=provider.name,
                model=provider.model,
                prompt_id=prompt.id,
                prompt_version=prompt.version,
                payload={"prompt": rendered},
            ),
            call_for=call_for,
        )
        return envelope["result"]["text"], meta

    # ---- 核心管线 -----------------------------------------------------------

    async def _run_with_failover(
        self,
        *,
        task: str,
        prompt: Prompt,
        provider_for: Callable[[str, str | None], Any],
        cache_key: Callable[[Any], str],
        call_for: Callable[[Any], Awaitable[tuple[Any, CallMeta]]],
    ) -> tuple[dict[str, Any], CallMeta]:
        """按有序列表逐家尝试；每家最多 1 次，全部失败才聚合报错。"""

        runtime = self._current_runtime()
        attempt_group = uuid4().hex
        attempts: list[ProviderAttempt] = []

        for index, name in enumerate(resolve_task_providers(task, runtime)):
            started = time.monotonic()
            model: str | None = None
            try:
                model = resolve_task_model(task, name, runtime, self._settings)
                provider = provider_for(name, model)
            except ProviderConfigError as exc:
                latency = _elapsed_ms(started)
                await self._record_attempt(
                    task=task,
                    prompt=prompt,
                    attempt_group=attempt_group,
                    attempt_index=index,
                    provider=name,
                    model=model or "unknown",
                    status="config_error",
                    error_kind=CONFIG,
                    latency_ms=latency,
                    error=str(exc),
                )
                attempts.append(
                    ProviderAttempt(name, "config_error", CONFIG, latency, index)
                )
                continue

            key = cache_key(provider)
            cached = self._cache.get(key)
            if cached is not None:
                return cached, self._meta(provider, cached, True, prompt)

            async with self._session_factory() as session, session.begin():
                await model_audit.check_daily_guard(session, runtime=runtime)

            started = time.monotonic()
            try:
                result, meta = await call_for(provider)
            except Exception as exc:
                latency = _elapsed_ms(started)
                kind = classify_provider_error(exc)
                await self._record_attempt(
                    task=task,
                    prompt=prompt,
                    attempt_group=attempt_group,
                    attempt_index=index,
                    provider=provider.name,
                    model=provider.model,
                    status="error",
                    error_kind=kind,
                    latency_ms=latency,
                    error=str(exc),
                )
                attempts.append(
                    ProviderAttempt(provider.name, "error", kind, latency, index)
                )
                if not is_transferable(kind):
                    raise
                continue

            envelope = self._cache.set(
                key,
                model=provider.model,
                prompt_version=prompt.version,
                result=result,
                usage=asdict(meta.usage),
            )
            envelope["latency_ms"] = meta.latency_ms
            if meta.raw:
                self._write_raw(key, envelope, meta)
            await self._record_attempt(
                task=task,
                prompt=prompt,
                attempt_group=attempt_group,
                attempt_index=index,
                provider=provider.name,
                model=provider.model,
                status="ok",
                meta=meta,
            )
            return envelope, self._meta(provider, envelope, False, prompt)

        raise AllProvidersFailed(task, attempts=attempts, attempt_group=attempt_group)

    async def _record_attempt(
        self,
        *,
        task: str,
        prompt: Prompt,
        attempt_group: str,
        attempt_index: int,
        provider: str,
        model: str,
        status: str,
        latency_ms: int = 0,
        meta: CallMeta | None = None,
        error: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        audit_meta = meta or CallMeta(
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
        )
        async with self._session_factory() as session, session.begin():
            await model_audit.record_model_run(
                session,
                task_type=task,
                prompt=prompt,
                status=status,
                meta=audit_meta,
                error=error,
                attempt_group=attempt_group,
                attempt_index=attempt_index,
                error_kind=error_kind,
            )

    def _write_raw(self, key: str, envelope: dict[str, Any], meta: CallMeta) -> None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        path = self._raw_dir / day / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({**envelope, "raw": meta.raw}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _meta(
        provider: Any, envelope: dict[str, Any], cache_hit: bool, prompt: Prompt
    ) -> CallMeta:
        usage = envelope.get("usage") or {}
        return CallMeta(
            provider=provider.name,
            model=envelope.get("model", provider.model),
            latency_ms=int(envelope.get("latency_ms", 0)),
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            usage=TokenUsage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
            raw={"cache_hit": cache_hit},
        )


@lru_cache
def get_ai_gateway() -> AiGateway:
    """进程内单例：prompt 装载/缓存/护栏共用，测试用 dependency_overrides 替换。"""

    return AiGateway()
