"""Shared OpenAI-compatible vision adapter; concrete vendors subclass with name/base_url."""

from __future__ import annotations

from typing import Any

from app.providers.base import (
    CallMeta,
    Explanation,
    ExtractedProblem,
    GradeResult,
    TokenUsage,
    Verdict,
    VisionProvider,
)
from app.providers.http import (
    ChatResponse,
    ProviderResponseError,
    chat_completions,
    extract_json_object,
    image_to_data_url,
)

# 豆包 value 档对极小裁图偶发 50s+ 长推理（实测 51.9s/3496 output tokens），
# 60s 会在容器/网关开销下误杀；120s 留出余量，仍由调用方逐条计时审计。
_TIMEOUT = 120.0


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _coerce_extract_text(value: Any, *, field_name: str, provider: str) -> str:
    """严格层：题目文本只接受字符串（或字符串数组，join 救回）。"""

    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(item for item in value if item.strip())
    raise ProviderResponseError(
        f"{provider}: extract_problem.{field_name} 类型非法（期望字符串）"
    )


def _coerce_extract_answer(value: Any, *, provider: str) -> str | None:
    """作答允许字符串/数字/null；列表按行拼接；其余类型视为结构错误。"""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(item for item in value if item.strip())
    raise ProviderResponseError(
        f"{provider}: extract_problem.student_answer 类型非法（期望字符串/数字/null）"
    )


def _coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return None


def _coerce_confidence(value: Any) -> float | None:
    """置信度只在 [0,1] 内可信；越界视为未知，不制造虚假精确。"""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if 0.0 <= number <= 1.0:
        return number
    return None


class OpenAIVisionProvider(VisionProvider):
    """Generic `chat.completions` vision caller. Vendors only set name/base_url."""

    name = "openai_vision"
    default_base_url = "https://api.openai.com/v1"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        client: Any = None,
        temperature: float | None = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError(f"provider {self.name}: api_key is required")
        if not model or not model.strip():
            raise ValueError(f"provider {self.name}: model is required")
        self._api_key = api_key
        self._model = model
        self.model = model  # 公开只读：缓存键/审计用，业务不可改
        self._base_url = (base_url or self.default_base_url).rstrip("/")
        self._client = client
        self._temperature = temperature
        self._timeout = timeout

    # ---- vendor hooks -------------------------------------------------

    def _extra_chat_kwargs(self) -> dict[str, Any]:
        return {}

    # ---- message builders (override per task if a vendor needs tweaks) -

    def _build_extract_messages(self, image_path: str, prompt: str) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ],
            }
        ]

    def _build_grade_messages(self, problem_text: str, student_answer: str, prompt: str) -> list[dict[str, Any]]:
        return [{"role": "user", "content": prompt}]

    def _build_solve_messages(self, problem_text: str, prompt: str) -> list[dict[str, Any]]:
        return [{"role": "user", "content": prompt}]

    # ---- VisionProvider ------------------------------------------------

    async def extract_problem(self, image_path: str, *, prompt: str) -> tuple[ExtractedProblem, CallMeta]:
        resp = await self._chat(self._build_extract_messages(image_path, prompt))
        data = self._json_object(resp, task="extract_problem")
        extracted = ExtractedProblem(
            problem_text=_coerce_extract_text(
                data.get("problem_text"), field_name="problem_text", provider=self.name
            ),
            student_answer=_coerce_extract_answer(
                data.get("student_answer"), provider=self.name
            ),
            confidence=_coerce_confidence(data.get("confidence")),
            problem_complete=_coerce_optional_bool(data.get("problem_complete")),
            needs_human_review=True,
            raw=data,
        )
        return extracted, self._meta(resp)

    async def grade(self, problem_text: str, student_answer: str, *, prompt: str) -> tuple[GradeResult, CallMeta]:
        resp = await self._chat(self._build_grade_messages(problem_text, student_answer, prompt))
        data = self._json_object(resp, task="grade")
        verdict_raw = str(data.get("verdict") or "uncertain").lower()
        verdict: Verdict = verdict_raw if verdict_raw in ("correct", "wrong", "uncertain") else "uncertain"
        result = GradeResult(
            verdict=verdict,
            confidence=_coerce_optional_float(data.get("confidence")),
            source="ai",
            rationale=_coerce_optional_str(data.get("rationale")),
        )
        return result, self._meta(resp)

    async def solve_explain(
        self, problem_text: str, *, prompt: str, hint_level: int = 0
    ) -> tuple[Explanation, CallMeta]:
        level = max(0, min(int(hint_level), 3))
        resp = await self._chat(self._build_solve_messages(problem_text, prompt))
        try:
            data = self._json_object(resp, task="solve_explain")
        except ProviderResponseError:
            # 讲解允许纯文本降级：模型没按 JSON 输出时整段保留，交给上层 Schema 层处置
            data = {}
        steps_raw = data.get("steps")
        steps: tuple[str, ...]
        if isinstance(steps_raw, list) and steps_raw:
            steps = tuple(str(s) for s in steps_raw if str(s).strip())
        else:
            fallback = resp.content.strip()
            if not fallback:
                raise ProviderResponseError(f"{self.name}: solve_explain 模型输出为空")
            steps = (fallback,)
        explanation = Explanation(
            steps=steps,
            answer=_coerce_optional_str(data.get("answer")),
            hint_level=level,
            focus=_coerce_optional_str(data.get("focus")) or "",
            consolidation=_coerce_optional_str(data.get("consolidation")) or "",
        )
        return explanation, self._meta(resp)

    # ---- internals ------------------------------------------------------

    async def _chat(self, messages: list[dict[str, Any]]) -> ChatResponse:
        kwargs: dict[str, Any] = {
            "provider": self.name,
            "base_url": self._base_url,
            "api_key": self._api_key,
            "model": self._model,
            "messages": messages,
            "client": self._client,
            "temperature": self._temperature,
            "timeout": self._timeout,
        }
        kwargs.update(self._extra_chat_kwargs())
        return await chat_completions(**kwargs)

    def _json_object(self, resp: ChatResponse, *, task: str) -> dict[str, Any]:
        return extract_json_object(resp.content, provider=self.name, task=task)

    def _meta(self, resp: ChatResponse) -> CallMeta:
        return CallMeta(
            provider=self.name,
            model=self._model,
            latency_ms=resp.latency_ms,
            usage=resp.usage or TokenUsage(),
            raw={"id": resp.raw.get("id"), "finish_reason": resp.raw.get("finish_reason")},
        )
