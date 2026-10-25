"""AiGateway：路由 → 护栏 → 缓存 → 调用 → 审计，业务代码只跟它打交道（AGENTS §4）。

纪律：
- prompt 一律从 llm_prompts/*.md 渲染后传入 adapter，本文件不留 prompt 正文；
- 缓存命中零模型调用、不进 model_runs（护栏只数真实调用）；
- 审计用独立 session 提交：业务事务回滚时 model_runs 仍完整（可重放诊断）；
- L3 原始响应落 data/ai-raw/{date}/（本地数据目录，非日志/审计表）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import RuntimeConfig, Settings, get_runtime_config, get_settings
from app.core.database import get_session_factory
from app.prompts.loader import Prompt, PromptError, load_prompts
from app.providers.base import CallMeta, Explanation, ExtractedProblem, GradeResult, TokenUsage
from app.providers.cache import ContentHashCache, hash_file, make_cache_key
from app.providers.registry import (
    create_text_provider,
    create_vision_provider,
    resolve_task_provider,
)
from app.services import model_audit


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
        self._prompts = (
            prompts if prompts is not None else load_prompts(self._settings.prompts_dir)
        )
        self._cache = cache or ContentHashCache(self._settings.data_dir / "ai-cache")
        self._session_factory = session_factory or get_session_factory()
        self._raw_dir = raw_dir or (self._settings.data_dir / "ai-raw")
        self._vision_providers: dict[str, Any] = {}
        self._text_providers: dict[str, Any] = {}

    # ---- prompt 渲染 -----------------------------------------------------

    def render_prompt(self, prompt_id: str, **values: str) -> tuple[Prompt, str]:
        prompt = self._prompts.get(prompt_id)
        if prompt is None:
            raise PromptError(
                f"prompt {prompt_id!r} 未装载：llm_prompts/*.md 是唯一真源（P1-4 起随 ticket 落盘）"
            )
        return prompt, prompt.render(**values)

    # ---- 供应商实例（按名缓存，避免重复构造） ----------------------------

    def _vision(self, name: str) -> Any:
        if name not in self._vision_providers:
            self._vision_providers[name] = create_vision_provider(
                name, settings=self._settings, runtime=self._runtime
            )
        return self._vision_providers[name]

    def _text(self, name: str) -> Any:
        if name not in self._text_providers:
            self._text_providers[name] = create_text_provider(name, settings=self._settings)
        return self._text_providers[name]

    # ---- 视觉三任务 --------------------------------------------------------

    async def extract_problem(
        self, image_path: str, *, prompt_id: str = "extract_problem"
    ) -> tuple[ExtractedProblem, CallMeta]:
        prompt, rendered = self.render_prompt(prompt_id)
        provider_name = resolve_task_provider("extract_problem", self._runtime)
        provider = self._vision(provider_name)
        key = make_cache_key(
            task="extract_problem",
            provider=provider.name,
            model=provider.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            payload={"image_sha256": hash_file(image_path)},
        )

        async def call() -> tuple[ExtractedProblem, CallMeta]:
            return await provider.extract_problem(image_path, prompt=rendered)

        envelope, cache_hit = await self._cached(
            key, task="extract_problem", prompt=prompt, provider=provider, call=call
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
        return result, self._meta(provider, envelope, cache_hit, prompt)

    async def grade(
        self,
        problem_text: str,
        student_answer: str,
        *,
        prompt_id: str = "grade",
    ) -> tuple[GradeResult, CallMeta]:
        prompt, rendered = self.render_prompt(
            prompt_id, PROBLEM_TEXT=problem_text, STUDENT_ANSWER=student_answer
        )
        provider_name = resolve_task_provider("grade", self._runtime)
        provider = self._vision(provider_name)
        key = make_cache_key(
            task="grade",
            provider=provider.name,
            model=provider.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            payload={"problem_text": problem_text, "student_answer": student_answer},
        )

        async def call() -> tuple[GradeResult, CallMeta]:
            return await provider.grade(problem_text, student_answer, prompt=rendered)

        envelope, cache_hit = await self._cached(
            key, task="grade", prompt=prompt, provider=provider, call=call
        )
        data = envelope["result"]
        result = GradeResult(
            verdict=data["verdict"],
            confidence=data.get("confidence"),
            source=data.get("source", "ai"),
            rationale=data.get("rationale"),
        )
        return result, self._meta(provider, envelope, cache_hit, prompt)

    async def solve_explain(
        self,
        problem_text: str,
        *,
        prompt_id: str = "solve_explain",
        hint_level: int = 0,
    ) -> tuple[Explanation, CallMeta]:
        level = max(0, min(int(hint_level), 3))
        prompt, rendered = self.render_prompt(
            prompt_id, PROBLEM_TEXT=problem_text, HINT_LEVEL=str(level)
        )
        provider_name = resolve_task_provider("solve_explain", self._runtime)
        provider = self._vision(provider_name)
        key = make_cache_key(
            task="solve_explain",
            provider=provider.name,
            model=provider.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            payload={"problem_text": problem_text, "hint_level": level},
        )

        async def call() -> tuple[Explanation, CallMeta]:
            return await provider.solve_explain(problem_text, prompt=rendered, hint_level=level)

        envelope, cache_hit = await self._cached(
            key, task="solve_explain", prompt=prompt, provider=provider, call=call
        )
        data = envelope["result"]
        result = Explanation(
            steps=tuple(data["steps"]),
            answer=data.get("answer"),
            hint_level=int(data.get("hint_level", level)),
        )
        return result, self._meta(provider, envelope, cache_hit, prompt)

    # ---- 文本侧 -------------------------------------------------------------

    async def complete_text(
        self, *, prompt_id: str, extra_values: dict[str, str] | None = None
    ) -> tuple[str, CallMeta]:
        prompt, rendered = self.render_prompt(prompt_id, **(extra_values or {}))
        provider_name = resolve_task_provider("text", self._runtime)
        provider = self._text(provider_name)
        key = make_cache_key(
            task="text",
            provider=provider.name,
            model=provider.model,
            prompt_id=prompt.id,
            prompt_version=prompt.version,
            payload={"prompt": rendered},
        )

        async def call() -> tuple[dict[str, Any], CallMeta]:
            text, meta = await provider.complete(rendered)
            return {"text": text}, meta

        envelope, cache_hit = await self._cached(
            key, task="text", prompt=prompt, provider=provider, call=call
        )
        return envelope["result"]["text"], self._meta(provider, envelope, cache_hit, prompt)

    # ---- 核心管线 -----------------------------------------------------------

    async def _cached(
        self,
        key: str,
        *,
        task: str,
        prompt: Prompt,
        provider: Any,
        call: Callable[[], Any],
    ) -> tuple[dict[str, Any], bool]:
        """命中→(envelope, True)；未命中→护栏→调用→L3→L2→审计（独立提交）→(envelope, False)。"""

        cached = self._cache.get(key)
        if cached is not None:
            return cached, True

        async with self._session_factory() as session, session.begin():
            await model_audit.check_daily_guard(session, runtime=self._runtime)
        try:
            result, meta = await call()
        except Exception as exc:
            async with self._session_factory() as session, session.begin():
                await model_audit.record_model_run(
                    session, task_type=task, prompt=prompt, status="error", error=str(exc)
                )
            raise

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
        async with self._session_factory() as session, session.begin():
            await model_audit.record_model_run(
                session, task_type=task, prompt=prompt, status="ok", meta=meta
            )
        return envelope, False

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
