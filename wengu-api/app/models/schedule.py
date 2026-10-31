"""P2-3 课表/日历约束层：只记录"什么时候有课/有硬事件"，不生成任务。

timetable_slots = 周内固定节次（一节一科，无 A/B 周）；calendar_events = 具体
日期的硬事件（考试/竞赛/请假/其它）。两者都只作为展示与"考试日放宽复习上限"
的确定性输入，绝不作为任务源主体、不做时间块排课。
"""

from __future__ import annotations

from datetime import date as date_cls

from sqlalchemy import CheckConstraint, Date, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CALENDAR_KINDS = ("exam", "competition", "leave", "other")


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 周一=1 … 周日=7
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "weekday BETWEEN 1 AND 7", name="ck_timetable_slots_weekday"
        ),
        CheckConstraint(
            "period BETWEEN 1 AND 12", name="ck_timetable_slots_period"
        ),
        UniqueConstraint(
            "weekday", "period", name="uq_timetable_slots_weekday_period"
        ),
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date_cls] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('exam', 'competition', 'leave', 'other')",
            name="ck_calendar_events_kind",
        ),
        Index("ix_calendar_events_date", "date"),
    )
