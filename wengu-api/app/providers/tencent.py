"""Tencent education-grading adapter — placeholder (P1-2 ships no Tencent integration)."""

from __future__ import annotations

from app.providers.base import CallMeta, Explanation, ExtractedProblem, GradeResult, VisionProvider


class TencentVisionProvider(VisionProvider):
    name = "tencent"
    model = "unconfigured"

    def __init__(self, **kwargs: object) -> None:
        self._config = kwargs

    async def extract_problem(self, image_path: str, *, prompt: str) -> tuple[ExtractedProblem, CallMeta]:
        raise NotImplementedError("tencent adapter is a stub; configure doubao or qwen_vl")

    async def grade(self, problem_text: str, student_answer: str, *, prompt: str) -> tuple[GradeResult, CallMeta]:
        raise NotImplementedError("tencent adapter is a stub; configure doubao or qwen_vl")

    async def solve_explain(
        self, problem_text: str, *, prompt: str, hint_level: int = 0
    ) -> tuple[Explanation, CallMeta]:
        raise NotImplementedError("tencent adapter is a stub; configure doubao or qwen_vl")
