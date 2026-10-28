"""learning_events：append-only 事实源 + attempts 作答明细。

learning_events 在数据库层有 UPDATE/DELETE 触发器守卫（见迁移 0002），
代码层也只提供 services/events.py 的写入入口，不提供任何更新/删除路径。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LearningEvent(Base):
    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    mistake_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    __table_args__ = (
        Index("ix_learning_events_mistake_id", "mistake_id"),
        Index("ix_learning_events_type", "type"),
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mistake_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    learning_event_id: Mapped[int] = mapped_column(
        ForeignKey("learning_events.id", ondelete="RESTRICT"), nullable=False
    )
    problem_bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("problem_bank.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'manual'")
    )
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("ix_attempts_problem_bank_id", "problem_bank_id"),)
