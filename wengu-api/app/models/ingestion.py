"""导入通道：import_batches（sha256 去重）+ ingestion_drafts（草稿，导入不调模型）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
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
