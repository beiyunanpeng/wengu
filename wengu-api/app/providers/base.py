"""Vision provider contract. Real vendor adapters arrive in P1-2; only mock exists now."""

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


class VisionProvider(ABC):
    """Exchangeable provider boundary; adding a vendor must not touch business code."""

    name: str

    @abstractmethod
    async def extract_problem(self, image_path: str) -> ExtractedProblem:
        """Read problem text and the student's answer from an image."""

    @abstractmethod
    async def grade(self, problem_text: str, student_answer: str) -> GradeResult:
        """Give a conservative hint for process questions; never judge objective ones."""

    @abstractmethod
    async def solve_explain(self, problem_text: str, hint_level: int = 0) -> Explanation:
        """Produce the staged explanation used by the tutoring engine."""
