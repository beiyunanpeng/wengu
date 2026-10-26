"""Deterministic offline providers for tests and local development."""

from __future__ import annotations

from app.providers.base import CallMeta, Explanation, ExtractedProblem, GradeResult, TextProvider, VisionProvider


class MockVisionProvider(VisionProvider):
    name = "mock"
    model = "mock-vision"

    async def extract_problem(self, image_path: str, *, prompt: str) -> tuple[ExtractedProblem, CallMeta]:
        return (
            ExtractedProblem(
                problem_text=f"[mock] problem from {image_path}",
                student_answer=None,
                confidence=0.0,
                problem_complete=True,
                needs_human_review=True,
            ),
            CallMeta(provider=self.name, model="mock-vision", latency_ms=0),
        )

    async def grade(self, problem_text: str, student_answer: str, *, prompt: str) -> tuple[GradeResult, CallMeta]:
        return (
            GradeResult(verdict="uncertain", confidence=0.0, source="ai"),
            CallMeta(provider=self.name, model="mock-vision", latency_ms=0),
        )

    async def solve_explain(
        self, problem_text: str, *, prompt: str, hint_level: int = 0
    ) -> tuple[Explanation, CallMeta]:
        level = max(0, min(int(hint_level), 3))
        return (
            Explanation(
                steps=(
                    f"[mock] hint level {level} for: {problem_text}",
                    "[mock] next step without revealing the final answer",
                ),
                answer="[mock] answer",
                hint_level=level,
                focus="[mock] locate what the problem asks",
                consolidation="[mock] redo the last step and check it yourself",
            ),
            CallMeta(provider=self.name, model="mock-vision", latency_ms=0),
        )


class MockTextProvider(TextProvider):
    name = "mock_text"
    model = "mock-text"

    async def complete(self, prompt: str, *, temperature: float | None = None) -> tuple[str, CallMeta]:
        return (
            f"[mock] text completion for: {prompt}",
            CallMeta(provider=self.name, model="mock-text", latency_ms=0),
        )
