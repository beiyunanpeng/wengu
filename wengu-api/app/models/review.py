"""review_schedules：复习排期=调度决策事实。

只存"何时排了什么、何时完成"，不存掌握度/毕业等易变字段（由 recompute 推导）。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReviewSchedule(Base):
    __tablename__ = "review_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mistake_id: Mapped[int] = mapped_column(Integer, nullable=False)
    rung: Mapped[int] = mapped_column(Integer, nullable=False)
    base_interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_event_id: Mapped[int] = mapped_column(
        ForeignKey("learning_events.id", ondelete="RESTRICT"), nullable=False
    )
    completed_attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("attempts.id"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_review_schedules_mistake_id", "mistake_id"),
        Index("ix_review_schedules_due_date", "due_date"),
    )
