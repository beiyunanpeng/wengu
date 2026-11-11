"""P2-2b：番茄钟进行中轮次（pomodoro_sessions）

Revision ID: 0021_pomodoro_sessions
Revises: 0020_recitation
Create Date: 2026-11-11

计时器运行态，不是学习事实：本表只记"这一轮从什么时候开始、计划多少分钟、
现在是什么状态"，供刷新/切页/换设备续走。专注时长的事实源仍是
`learning_events(type='pomodoro_completed')`，看板统计一字不改地继续从事件现算；
本表不参与掌握度 / streak / 排期 / 错题本任何链路。

- status 只有 active / completed / abandoned 三态，放弃不写事件；
- mistake_id 与 learning_events 同惯例：可空整数、不挂外键（自由专注无错题）；
- 不存 remaining / elapsed 之类易变字段：剩余时间由 started_at + planned_minutes
  与服务端当前时间确定性推导。

备份/回退：升级前先在家长区「备份」页导出（或 `POST /api/backup/export`）拿到整库
一致性快照，或按 `migrations/README.md` 把 `wengu-api/data/wengu.db` 复制到仓库外。
回退 `alembic downgrade -1` 只删本迁移新建的这一张表；新增结构、不含历史回填，
回退后旧的"完成打点"端点与看板统计照常工作（进行中的轮次会丢，与升级前行为一致）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_pomodoro_sessions"
down_revision: str | None = "0020_recitation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_sessions() -> None:
    op.create_table(
        "pomodoro_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("planned_minutes", sa.Integer(), nullable=False),
        sa.Column("mistake_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'abandoned')",
            name="ck_pomodoro_sessions_status",
        ),
        sa.CheckConstraint(
            "planned_minutes >= 5 AND planned_minutes <= 120",
            name="ck_pomodoro_sessions_planned_minutes",
        ),
    )
    op.create_index(
        "ix_pomodoro_sessions_status",
        "pomodoro_sessions",
        ["status"],
    )


def upgrade() -> None:
    if "pomodoro_sessions" not in _tables():
        _create_sessions()


def downgrade() -> None:
    if "pomodoro_sessions" in _tables():
        op.drop_index("ix_pomodoro_sessions_status", table_name="pomodoro_sessions")
        op.drop_table("pomodoro_sessions")
