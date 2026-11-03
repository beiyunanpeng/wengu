"""采集通道：import_batches/ingestion_drafts（外部转录错题草稿）+ bank_drafts（空白真题草稿）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="received")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class IngestionDraft(Base):
    __tablename__ = "ingestion_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_json: Mapped[str] = mapped_column(Text, nullable=False)
    has_placeholder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_incomplete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("import_batch_id", "seq", name="uq_ingestion_drafts_batch_seq"),
    )


class BankDraft(Base):
    """P3-1 空白真题录题草稿：外部 agent 转录后停在这里，家长审核才入 problem_bank。

    与错题草稿分表：录题不建错题、不排复习；`status` 只允许 draft/approved/rejected。
    `normalized_json` 是归一化后的题目字段（含可空 answer，等家长补填）。
    """

    __tablename__ = "bank_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_batch_id: Mapped[int] = mapped_column(
        ForeignKey("import_batches.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_json: Mapped[str] = mapped_column(Text, nullable=False)
    has_placeholder: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("import_batch_id", "seq", name="uq_bank_drafts_batch_seq"),
        Index("ix_bank_drafts_status", "status"),
    )
