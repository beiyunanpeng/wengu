"""Deterministic judging primitives: runtime answer normalization + ingestion sandbox."""

from app.judge.normalize import JudgeOutcome, judge_answer

__all__ = ["JudgeOutcome", "judge_answer"]
