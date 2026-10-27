"""P1-2b：model_runs 记录 provider 尝试链

Revision ID: 0010_model_run_attempts
Revises: 0009_review_schedules
Create Date: 2026-10-27

新增三列 + 一个索引，支持按 attempt_group 查询一次 gateway 调用依次试过哪些
provider 及各自结果：
- attempt_group: 一次调用的 uuid（旧行 NULL）；
- attempt_index: 0 基尝试序号（旧行 NULL）；
- error_kind: account/quota/rate_limit/network/config/quality/unknown。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新增的列与索引，
不清审计数据。升级/回退都先 inspect，可重复执行。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_model_run_attempts"
down_revision: str | None = "0009_review_schedules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTEMPT_INDEX = "ix_model_runs_attempt_group"
_COLUMNS = {
    "attempt_group": sa.Column("attempt_group", sa.Text(), nullable=True),
    "attempt_index": sa.Column("attempt_index", sa.Integer(), nullable=True),
    "error_kind": sa.Column("error_kind", sa.Text(), nullable=True),
}


def _column_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("model_runs")}


def _index_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes("model_runs")}


def upgrade() -> None:
    columns = _column_names()
    missing = [column for name, column in _COLUMNS.items() if name not in columns]
    if missing:
        with op.batch_alter_table("model_runs") as batch:
            for column in missing:
                batch.add_column(column)
    if _ATTEMPT_INDEX not in _index_names():
        op.create_index(_ATTEMPT_INDEX, "model_runs", ["attempt_group"])


def downgrade() -> None:
    if _ATTEMPT_INDEX in _index_names():
        op.drop_index(_ATTEMPT_INDEX, table_name="model_runs")
    columns = _column_names()
    existing = [name for name in _COLUMNS if name in columns]
    if existing:
        with op.batch_alter_table("model_runs") as batch:
            for name in existing:
                batch.drop_column(name)
