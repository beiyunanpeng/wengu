"""P3-3a 英语背诵：条目 + 记忆阶梯自评（与错题/作答链路完全隔离）。

recitation_items 是家长手填的背诵内容；recitation_reviews 是孩子"记得/没记住"
的自评事实。两者都不写 mistakes / mistake_versions / attempts，掌握度因此不受影响。
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RecitationItem(Base):
    __tablename__ = "recitation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_recitation_items_status",
        ),
        UniqueConstraint(
            "subject", "prompt", name="uq_recitation_items_subject_prompt"
        ),
    )


class RecitationReview(Base):
    __tablename__ = "recitation_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey(
            "recitation_items.id",
            ondelete="CASCADE",
            name="fk_recitation_reviews_item_id",
        ),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    rung: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_on: Mapped[date_cls] = mapped_column(Date, nullable=False)
    scheduled_next: Mapped[date_cls | None] = mapped_column(Date, nullable=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey(
            "learning_events.id",
            ondelete="RESTRICT",
            name="fk_recitation_reviews_event_id",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "verdict IN ('remembered', 'forgot')",
            name="ck_recitation_reviews_verdict",
        ),
        UniqueConstraint(
            "item_id",
            "reviewed_on",
            name="uq_recitation_reviews_item_reviewed_on",
        ),
    )
