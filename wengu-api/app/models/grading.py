"""批改分级闸的事实表（P1-5）。

grading_results 是逻辑批改单（同源 UNIQUE），grading_versions 只追加版本：
首版建议值（code/ai）+ 后续确认/申诉（student/parent）。题目/作答存快照，
与提取结果的生灭解耦；不存图片路径/URL。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SOURCE_INGESTION_DRAFT = "ingestion_draft"

QUESTION_OBJECTIVE = "objective"
QUESTION_PROCESS = "process"

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_APPEALED = "appealed"


class ProblemBankItem(Base):
    __tablename__ = "problem_bank"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    acceptable_answers_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    unordered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verify: Mapped[str] = mapped_column(Text, nullable=False)
    verify_vars_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    verify_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="verified"
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, default="import")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class GradingResult(Base):
    __tablename__ = "grading_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("problem_bank.id", ondelete="SET NULL"), nullable=True
    )
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    standard_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptable_answers_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    unordered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=STATUS_PENDING)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("source_kind", "source_id", name="uq_grading_results_source"),
        CheckConstraint(
            "source_kind IN ('problem_extraction', 'ingestion_draft')",
            name="ck_grading_results_source_kind",
        ),
        CheckConstraint(
            "question_type IN ('objective', 'process')",
            name="ck_grading_results_question_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'appealed')",
            name="ck_grading_results_status",
        ),
        Index("ix_grading_results_problem_bank_id", "problem_bank_id"),
    )


class GradingVersion(Base):
    __tablename__ = "grading_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grading_id: Mapped[int] = mapped_column(
        ForeignKey("grading_results.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_verdicts_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "grading_id", "version", name="uq_grading_versions_grading_version"
        ),
        CheckConstraint(
            "action IN ('suggested', 'confirmed', 'appealed')",
            name="ck_grading_versions_action",
        ),
        CheckConstraint(
            "verdict IN ('correct', 'wrong', 'uncertain')",
            name="ck_grading_versions_verdict",
        ),
        CheckConstraint(
            "source IN ('code', 'ai', 'student', 'parent')",
            name="ck_grading_versions_source",
        ),
    )
