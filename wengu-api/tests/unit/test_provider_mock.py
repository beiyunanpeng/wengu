from __future__ import annotations

import pytest
from app.providers.base import Explanation, GradeResult, VisionProvider
from app.providers.mock import MockVisionProvider


@pytest.mark.unit
async def test_mock_provider_is_deterministic_and_conservative() -> None:
    provider = MockVisionProvider()

    assert isinstance(provider, VisionProvider)
    assert provider.name == "mock"

    first = await provider.extract_problem("uploads/page-1.jpg")
    second = await provider.extract_problem("uploads/page-1.jpg")
    assert first == second
    assert first.problem_text == "[mock] problem from uploads/page-1.jpg"
    assert first.student_answer is None
    assert first.needs_human_review is True

    graded = await provider.grade("1 + 1 = ?", "2")
    assert graded == GradeResult(verdict="uncertain", confidence=0.0, source="ai")


@pytest.mark.unit
async def test_mock_provider_hint_levels_are_bounded() -> None:
    provider = MockVisionProvider()
    explanation = await provider.solve_explain("solve x", hint_level=9)

    assert isinstance(explanation, Explanation)
    assert explanation.hint_level == 3
    assert explanation.answer is None
    assert await provider.solve_explain("solve x", hint_level=-2) == Explanation(
        steps=("[mock] hint level 0 for: solve x",),
        answer=None,
        hint_level=0,
    )
