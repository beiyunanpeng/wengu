"""P3-2d：加练提交幂等（topic_id / seed / dedup_key）

Revision ID: 0018_practice_dedup
Revises: 0017_bank_item_lifecycle
Create Date: 2026-10-31

- practice_records.topic_id TEXT NULL / seed INTEGER NULL：回看按"同一组练习"分组。
- practice_records.dedup_key TEXT NULL：`variant:{topic_id}:{seed}:{question_id}`。
- 部分唯一索引 `uq_practice_records_dedup_key`（WHERE dedup_key IS NOT NULL）：
  多 NULL 不冲突，既有历史行不受影响；同题重复提交只回看已有行。
- 仍然只写 practice_records：不写 attempts / learning_events，不影响掌握度与排期。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新增的三列与唯一索引，
不改既有 practice_records 行内容。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_practice_dedup"
down_revision: str | None = "0017_bank_item_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "uq_practice_records_dedup_key"
NEW_COLUMNS = {
    "topic_id": sa.Text(),
    "seed": sa.Integer(),
    "dedup_key": sa.Text(),
}


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "practice_records" not in sa.inspect(op.get_bind()).get_table_names():
        return

    existing = _columns("practice_records")
    missing = [name for name in NEW_COLUMNS if name not in existing]
    if missing:
        with op.batch_alter_table("practice_records", recreate="always") as batch:
            for name in missing:
                batch.add_column(sa.Column(name, NEW_COLUMNS[name], nullable=True))

    if INDEX_NAME not in _indexes("practice_records"):
        op.create_index(
            INDEX_NAME,
            "practice_records",
            ["dedup_key"],
            unique=True,
            sqlite_where=sa.text("dedup_key IS NOT NULL"),
        )


def downgrade() -> None:
    if "practice_records" not in sa.inspect(op.get_bind()).get_table_names():
        return

    existing = _columns("practice_records")
    drop_columns = [name for name in NEW_COLUMNS if name in existing]
    if not drop_columns and INDEX_NAME not in _indexes("practice_records"):
        return

    if INDEX_NAME in _indexes("practice_records"):
        op.drop_index(INDEX_NAME, table_name="practice_records")
    if drop_columns:
        with op.batch_alter_table("practice_records", recreate="always") as batch:
            for name in drop_columns:
                batch.drop_column(name)
