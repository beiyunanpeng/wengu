"""Provider contracts. 适配层唯一边界：加一家 = 一个文件 + 配置，业务零改动。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

Source = Literal["vlm", "ai", "student", "parent"]
Verdict = Literal["correct", "wrong", "uncertain"]


@dataclass(frozen=True)
class ExtractedProblem:
    """A single problem read from a photo; never treated as trusted input."""

    problem_text: str
    student_answer: str | None
    confidence: float | None = None
    problem_complete: bool | None = None
    needs_human_review: bool = True
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GradeResult:
    """A provider hint only; objective answers are judged by app.judge, not by a model."""

    verdict: Verdict
    confidence: float | None = None
    source: Source = "ai"
    rationale: str | None = None


@dataclass(frozen=True)
class Explanation:
    steps: tuple[str, ...]
    answer: str | None = None
    hint_level: int = 0
    focus: str = ""
    consolidation: str = ""


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class CallMeta:
    """每次调用的可审计元数据（进 model_runs / ai-raw，绝不进日志正文）。"""

    provider: str
    model: str
    latency_ms: int
    prompt_id: str = ""
    prompt_version: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    raw: dict[str, object] = field(default_factory=dict)


class VisionProvider(ABC):
    """Exchangeable provider boundary; adding a vendor must not touch business code.

    prompt 一律由调用方（gateway）从 llm_prompts 真源渲染后传入——代码不留 prompt 正文。
    """

    name: str

    @abstractmethod
    async def extract_problem(
        self, image_path: str, *, prompt: str
    ) -> tuple[ExtractedProblem, CallMeta]:
        """Read problem text and the student's answer from an image."""

    @abstractmethod
    async def grade(
        self, problem_text: str, student_answer: str, *, prompt: str
    ) -> tuple[GradeResult, CallMeta]:
        """Give a conservative hint for process questions; never judge objective ones."""

    @abstractmethod
    async def solve_explain(
        self, problem_text: str, *, prompt: str, hint_level: int = 0
    ) -> tuple[Explanation, CallMeta]:
        """Produce the staged explanation used by the tutoring engine."""


class TextProvider(ABC):
    """OpenAI-compat 文本侧（DeepSeek/GLM/Kimi）：讲解、判分辅助、标签预填等。"""

    name: str

    @abstractmethod
    async def complete(
        self, prompt: str, *, temperature: float | None = None
    ) -> tuple[str, CallMeta]:
        """Run a single-turn completion and return (text, call metadata)."""
