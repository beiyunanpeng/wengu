"""采集双通道：photo_captures（主·拍照落库）+ import_batches/ingestion_drafts（兜底·JSON 导入）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PhotoCapture(Base):
    """主通道事实表：手机拍照经 HTTP 秒传落本地存储（P1-3）。

    sha256 UNIQUE 保证重传/重试/重启幂等；stored_path 为 uploads_dir 相对路径
    （哈希改名，不携带原文件名信息）。status='pending' 等待 P1-3b/4 消费，
    本表不含识别结果——Phase 0 闸门内"触发"只到落库为止。
    """

    __tablename__ = "photo_captures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="phone")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class PhotoCaptureItem(Base):
    """切题子图：母 photo_capture 经本地 OCR 聚类裁出的单题图片（P1-3b）。

    不含识别结果——题目内容等 P1-4 由 VLM 精读子图产出；anchor_label 只是
    命中的题号短文本（如 "12"），便于回显与申诉定位。
    """

    __tablename__ = "photo_capture_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_capture_id: Mapped[int] = mapped_column(
        ForeignKey("photo_captures.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    bbox_json: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "photo_capture_id", "seq", name="uq_photo_capture_items_capture_seq"
        ),
    )


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
