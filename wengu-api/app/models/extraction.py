"""problem_extractions：VLM 结构化提取结果 + 提取质量前置闸门结论（P1-4）。

一条记录 = 一次针对单题裁图（source_kind='slice'）或整页兜底（'whole_page'）的
提取结果。gate_status 三态：ready_for_grading / manual_review / figure_dependent；
figure_dependent 不阻断回显，但不参与自动判分与复习（AGENTS §5）。

FK 均 ON DELETE CASCADE：force 重切会删旧 photo_capture_items，旧提取随之失效，
不允许残留指向已删除裁图的结果。本表只存模型建议值，用户确认值归 P1-5 的
mistake_versions，不在此表覆盖。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class ProblemExtraction(Base):
    __tablename__ = "problem_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_capture_id: Mapped[int] = mapped_column(
        ForeignKey("photo_captures.id", ondelete="CASCADE"), nullable=False
    )
    photo_capture_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("photo_capture_items.id", ondelete="CASCADE"), nullable=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    problem_complete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gate_status: Mapped[str] = mapped_column(Text, nullable=False)
    review_reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    figure_keywords_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "photo_capture_id",
            "source_kind",
            "seq",
            name="uq_problem_extractions_capture_source_seq",
        ),
        Index("ix_problem_extractions_capture_id", "photo_capture_id"),
        Index("ix_problem_extractions_item_id", "photo_capture_item_id"),
    )
