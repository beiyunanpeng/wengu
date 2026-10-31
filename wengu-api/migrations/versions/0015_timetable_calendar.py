"""P2-3：课表/日历约束层（timetable_slots + calendar_events）

Revision ID: 0015_timetable_calendar
Revises: 0014_parent_pin
Create Date: 2026-10-31

只做"录入 + 展示 + 考试日放宽复习上限"三件事的数据底座：
- timetable_slots：周内固定节次，UNIQUE(weekday, period) 保证一节一科（无 A/B 周）；
- calendar_events：具体日期的硬事件，kind 受 CHECK 约束，date 建索引供窗口查询。
不建任务、不做时间块、不存"考试科目↔知识点"映射。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新建的两张表。
升级/回退都先 inspect 表名，可重复执行。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_timetable_calendar"
down_revision: str | None = "0014_parent_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "timetable_slots" not in tables:
        op.create_table(
            "timetable_slots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("weekday", sa.Integer(), nullable=False),
            sa.Column("period", sa.Integer(), nullable=False),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "weekday BETWEEN 1 AND 7",
                name="ck_timetable_slots_weekday",
            ),
            sa.CheckConstraint(
                "period BETWEEN 1 AND 12",
                name="ck_timetable_slots_period",
            ),
            sa.UniqueConstraint(
                "weekday", "period", name="uq_timetable_slots_weekday_period"
            ),
        )
    if "calendar_events" not in tables:
        op.create_table(
            "calendar_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("subject", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "kind IN ('exam', 'competition', 'leave', 'other')",
                name="ck_calendar_events_kind",
            ),
        )
        op.create_index(
            "ix_calendar_events_date", "calendar_events", ["date"]
        )


def downgrade() -> None:
    tables = _tables()
    if "calendar_events" in tables:
        op.drop_index("ix_calendar_events_date", table_name="calendar_events")
        op.drop_table("calendar_events")
    if "timetable_slots" in tables:
        op.drop_table("timetable_slots")
