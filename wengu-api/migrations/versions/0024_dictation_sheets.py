"""P3-4：英语默写卷（dictation_sheets）——卷面生成 + 页内勾选回录

Revision ID: 0024_dictation_sheets
Revises: 0023_learning_events_occurred_at
Create Date: 2026-11-20

默写卷只是"词序快照 + 回录状态机"：item_ids 存 JSON 有序数组（生成时按提交顺序
固化），不建逐词外键——条目之后停用/删除时卷面仍可回录，缺失/停用条目跳过并在
响应中报告。判分主体是家长卷面红笔，系统零判分代码；回录逐条写 recitation_reviews
并原样复用既有 decide() 二档调度，错词不进错题本。

- status 只有 open/recorded 两态；recorded 时 recorded_on 必填、open 时必须为空，
  状态机一致性由 CHECK 在库层兜底。同一天可生成多张卷，不设 UNIQUE。
- 不预留音频/时间戳字段：P3-4b 听写需要时由它自己的迁移加列。

备份/回退：升级前先在家长区「备份」页导出（或 `POST /api/backup/export`）拿到整库
一致性快照，或按 `migrations/README.md` 把 `wengu-api/data/wengu.db` 复制到仓库外。
回退 `alembic downgrade -1` 只删本迁移新建的一张表；新增结构，不含历史回填。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_dictation_sheets"
down_revision: str | None = "0023_learning_events_occurred_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_sheets() -> None:
    op.create_table(
        "dictation_sheets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_on", sa.Date(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("item_ids", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("recorded_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'recorded')",
            name="ck_dictation_sheets_status",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND recorded_on IS NULL)"
            " OR (status = 'recorded' AND recorded_on IS NOT NULL)",
            name="ck_dictation_sheets_recorded_on",
        ),
    )


def upgrade() -> None:
    if "dictation_sheets" not in _tables():
        _create_sheets()


def downgrade() -> None:
    if "dictation_sheets" in _tables():
        op.drop_table("dictation_sheets")
