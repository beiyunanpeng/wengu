"""ai_jobs（进程内队列，idempotency_key 防重）+ model_runs（审计，不落 PII/题目全文）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AiJob(Base):
    __tablename__ = "ai_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 水位
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ai_job_id: Mapped[int | None] = mapped_column(ForeignKey("ai_jobs.id"), nullable=True)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_model_runs_ai_job_id", "ai_job_id"),
        Index("ix_model_runs_attempt_group", "attempt_group"),
    )
