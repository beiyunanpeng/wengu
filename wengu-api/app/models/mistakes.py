"""错题根表 + 内容版本 + 派生练习记录。

mistakes 是错题生命周期锚点（唯一来源 = 用户确认/申诉 wrong）；
mistake_versions 只追加内容/标签版本，建议值与确认值分离存储；
practice_records 承接变式/加练，绝不进入错题本或复习排期。
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MISTAKE_ACTIVE = "active"
MISTAKE_VOIDED = "voided"


class Mistake(Base):
    __tablename__ = "mistakes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_grading_id: Mapped[int] = mapped_column(
        ForeignKey("grading_results.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default=MISTAKE_ACTIVE)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    primary_topic_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_seed.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('active', 'voided')", name="ck_mistakes_status"),
        CheckConstraint("current_version >= 1", name="ck_mistakes_current_version"),
        Index("ix_mistakes_primary_topic_id", "primary_topic_id"),
    )


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
    suggested_concept_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    confirmed_category_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_concept_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    confirmed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_error_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_error_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("mistake_id", "version", name="uq_mistake_versions_mistake_version"),
        Index("ix_mistake_versions_mistake_id", "mistake_id"),
    )


class PracticeRecord(Base):
    """变式/加练作答：派生表，不写事件、不进错题、不参与复习/掌握度。"""

    __tablename__ = "practice_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_mistake_id: Mapped[int | None] = mapped_column(
        ForeignKey("mistakes.id", ondelete="SET NULL"), nullable=True
    )
    problem_bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("problem_bank.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 加练分组信息；历史行保持 NULL，不参与幂等判定。
    topic_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('variant', 'extra')", name="ck_practice_records_kind"),
        Index("ix_practice_records_source_mistake_id", "source_mistake_id"),
        Index("ix_practice_records_created_at", "created_at"),
        Index(
            "uq_practice_records_dedup_key",
            "dedup_key",
            unique=True,
            sqlite_where=text("dedup_key IS NOT NULL"),
        ),
    )
