"""Deterministic judging primitives: runtime answer normalization + ingestion sandbox."""

from app.judge.normalize import JudgeOutcome, formula_equivalent, judge_answer

__all__ = ["JudgeOutcome", "formula_equivalent", "judge_answer"]
