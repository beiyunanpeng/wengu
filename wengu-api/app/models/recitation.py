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
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_recitation_items_status",
        ),
        UniqueConstraint(
            "subject", "prompt", name="uq_recitation_items_subject_prompt"
        ),
        CheckConstraint(
            "source IN ('seed','manual','candidate')",
            name="ck_recitation_items_source",
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


class DictationSheet(Base):
    """P3-4 默写卷：item_ids 为 JSON 有序快照（无逐词外键），status 只有 open→recorded。

    P3-4b：audio_ref 可空 TEXT 存 <data_dir>/audio/ 内纯文件名，一卷一音频，
    默写卷留空；音频本体不进 git/备份，本列只是文件名引用。
    """

    __tablename__ = "dictation_sheets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_on: Mapped[date_cls] = mapped_column(Date, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_ids: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="open",
        server_default=text("'open'"),
    )
    recorded_on: Mapped[date_cls | None] = mapped_column(Date, nullable=True)
    audio_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'recorded')",
            name="ck_dictation_sheets_status",
        ),
        CheckConstraint(
            "(status = 'open' AND recorded_on IS NULL)"
            " OR (status = 'recorded' AND recorded_on IS NOT NULL)",
            name="ck_dictation_sheets_recorded_on",
        ),
    )
