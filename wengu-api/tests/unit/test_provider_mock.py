from __future__ import annotations

import pytest
from app.providers.base import CallMeta, Explanation, GradeResult, VisionProvider
from app.providers.mock import MockTextProvider, MockVisionProvider


@pytest.mark.unit
async def test_mock_provider_is_deterministic_and_conservative() -> None:
    provider = MockVisionProvider()

    assert isinstance(provider, VisionProvider)
    assert provider.name == "mock"
    assert provider.model == "mock-vision"

    first, meta_first = await provider.extract_problem("uploads/page-1.jpg", prompt="p")
    second, meta_second = await provider.extract_problem("uploads/page-1.jpg", prompt="p")
    assert (first, meta_first) == (second, meta_second)
    assert first.problem_text == "[mock] problem from uploads/page-1.jpg"
    assert first.student_answer is None
    assert first.needs_human_review is True
    assert isinstance(meta_first, CallMeta)
    assert meta_first.provider == "mock"

    graded, grade_meta = await provider.grade("1 + 1 = ?", "2", prompt="p")
    assert graded == GradeResult(verdict="uncertain", confidence=0.0, source="ai")
    assert grade_meta.provider == "mock"


@pytest.mark.unit
async def test_mock_provider_hint_levels_are_bounded() -> None:
    provider = MockVisionProvider()
    explanation, _ = await provider.solve_explain("solve x", prompt="p", hint_level=9)

    assert isinstance(explanation, Explanation)
    assert explanation.hint_level == 3
    assert explanation.answer is None
    explanation0, _ = await provider.solve_explain("solve x", prompt="p", hint_level=-2)
    assert explanation0 == Explanation(
        steps=("[mock] hint level 0 for: solve x",),
        answer=None,
        hint_level=0,
    )


@pytest.mark.unit
async def test_mock_text_provider() -> None:
    provider = MockTextProvider()
    assert provider.name == "mock_text"
    text, meta = await provider.complete("hello", temperature=0.1)
    assert text == "[mock] text completion for: hello"
    assert meta.provider == "mock_text"
    assert meta.latency_ms == 0
