"""Deterministic offline provider for tests and local development."""

from __future__ import annotations

from app.providers.base import Explanation, ExtractedProblem, GradeResult, VisionProvider


class MockVisionProvider(VisionProvider):
    name = "mock"

    async def extract_problem(self, image_path: str) -> ExtractedProblem:
        return ExtractedProblem(
            problem_text=f"[mock] problem from {image_path}",
            student_answer=None,
            confidence=0.0,
            needs_human_review=True,
        )

    async def grade(self, problem_text: str, student_answer: str) -> GradeResult:
        return GradeResult(verdict="uncertain", confidence=0.0, source="ai")

    async def solve_explain(self, problem_text: str, hint_level: int = 0) -> Explanation:
        level = max(0, min(hint_level, 3))
        return Explanation(
            steps=(f"[mock] hint level {level} for: {problem_text}",),
            answer=None,
            hint_level=level,
        )
