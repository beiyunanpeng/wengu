"""P1-4 评测 fixture 完整性：truth 与 PNG 随仓库分发，CI 不依赖字体/网络。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.services.extraction import (
    GATE_FIGURE,
    GATE_MANUAL,
    GATE_READY,
    REASON_ANSWER_EMPTY,
    REASON_COMPLETENESS_UNKNOWN,
    REASON_FIGURE,
    REASON_PLACEHOLDER,
    REASON_PROBLEM_EMPTY,
    REASON_PROBLEM_INCOMPLETE,
    REASON_WHOLE_PAGE,
    SOURCE_SLICE,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "extraction"
KNOWN_GATES = {GATE_READY, GATE_MANUAL, GATE_FIGURE}
KNOWN_REASONS = {
    REASON_PROBLEM_EMPTY,
    REASON_PROBLEM_INCOMPLETE,
    REASON_COMPLETENESS_UNKNOWN,
    REASON_PLACEHOLDER,
    REASON_ANSWER_EMPTY,
    REASON_FIGURE,
    REASON_WHOLE_PAGE,
}


@pytest.mark.unit
def test_extraction_fixtures_match_truth() -> None:
    truth = json.loads((FIXTURES / "truth.json").read_text(encoding="utf-8"))
    questions = truth["questions"]

    assert truth["source_kind"] == SOURCE_SLICE
    assert len(questions) >= 8
    assert len({q["file"] for q in questions}) == len(questions)

    for question in questions:
        image = FIXTURES / question["file"]
        assert image.is_file(), question["file"]
        assert image.read_bytes().startswith(b"\x89PNG"), question["file"]

        assert question["problem_text"].strip()
        assert question["student_answer"] is None or isinstance(
            question["student_answer"], str
        )
        assert question["expected_gate"] in KNOWN_GATES
        assert set(question.get("expected_reasons") or ()) <= KNOWN_REASONS
        assert isinstance(question.get("exploratory", False), bool)
        assert question.get("problem_text_scope", "similarity") in {
            "similarity",
            "contains",
        }

    gates = [q["expected_gate"] for q in questions]
    assert GATE_READY in gates and GATE_MANUAL in gates and GATE_FIGURE in gates
    assert [q["file"] for q in questions if q.get("exploratory")] == ["q09_smudge.png"]
