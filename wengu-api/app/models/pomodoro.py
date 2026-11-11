"""P2-2b 番茄钟进行中轮次：计时器运行态，不是学习事实。

专注时长的事实源仍是 `learning_events(type='pomodoro_completed')`；本表只承载
"这一轮何时开始、计划多少分钟、现在什么状态"，让刷新/切页/换设备能续走。
剩余时间不入库，由 started_at + planned_minutes 与服务端当前时间推导。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SESSION_ACTIVE = "active"
SESSION_COMPLETED = "completed"
SESSION_ABANDONED = "abandoned"


class PomodoroSession(Base):
    __tablename__ = "pomodoro_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    mistake_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=SESSION_ACTIVE,
        server_default=text("'active'"),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'abandoned')",
            name="ck_pomodoro_sessions_status",
        ),
        CheckConstraint(
            "planned_minutes >= 5 AND planned_minutes <= 120",
            name="ck_pomodoro_sessions_planned_minutes",
        ),
        Index("ix_pomodoro_sessions_status", "status"),
    )
