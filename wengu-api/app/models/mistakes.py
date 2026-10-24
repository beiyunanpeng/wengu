"""mistake_versions：错题内容版本，只追加（UNIQUE mistake_id+version）。

建议值（AI/模型）与确认值（孩子/家长）分离存储，带来源与置信度（AGENTS §5）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MistakeVersion(Base):
    __tablename__ = "mistake_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mistake_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem_images: Mapped[str | None] = mapped_column(Text, nullable=True)
    standard_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(
        nullable=True
    )  # NULL = 待确认（P0-1 保守档）
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    suggested_category_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_category_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_error_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_error_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("mistake_id", "version", name="uq_mistake_versions_mistake_version"),
        Index("ix_mistake_versions_mistake_id", "mistake_id"),
    )
