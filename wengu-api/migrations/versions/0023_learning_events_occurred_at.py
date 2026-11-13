"""P4-4：给 learning_events.occurred_at 建索引（v2.8 §19-E）

Revision ID: 0023_learning_events_occurred_at
Revises: 0022_correction_notes
Create Date: 2026-11-13

learning_events 此前只有 ix_learning_events_mistake_id / ix_learning_events_type
两个索引，occurred_at 无索引。看板掌握度曲线按 occurred_at 做时间维度的过滤/排序，
本迁移补 ix_learning_events_occurred_at 为其提供索引支撑。

纯加索引：不改表结构、不回填数据、不触碰 0002 钉死的 append-only UPDATE/DELETE
触发器（本迁移只 CREATE/DROP INDEX，绝不 batch 重建表）。不改 dashboard 查询逻辑。

备份/回退：升级前先在家长区「备份」页导出整库一致性快照，或按 migrations/README.md
把 wengu-api/data/wengu.db 复制到仓库外。downgrade 只删本索引，表数据、其余索引与
append-only 触发器原样保留——可逆、无数据损失（与 0013/0019 的"数据不可回退"不同）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_learning_events_occurred_at"
down_revision: str | None = "0022_correction_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("learning_events")
    }


def upgrade() -> None:
    if "ix_learning_events_occurred_at" not in _indexes():
        op.create_index(
            "ix_learning_events_occurred_at", "learning_events", ["occurred_at"]
        )


def downgrade() -> None:
    if "ix_learning_events_occurred_at" in _indexes():
        op.drop_index("ix_learning_events_occurred_at", table_name="learning_events")
