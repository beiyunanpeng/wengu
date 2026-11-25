"""P6-2：recitation_items 加 source 列（seed/manual/candidate 来源标记）

Revision ID: 0026_recitation_source
Revises: 0025_dictation_sheet_audio_ref
Create Date: 2026-11-25

- source TEXT NOT NULL DEFAULT 'manual' + CHECK source IN ('seed','manual','candidate')。
- 既有行经 server_default 自动回填 'manual'；本票只是标记列，不改任何服务逻辑
  （导入路径接 source 是 P6-4 的事），不产生用户可见行为变化。
- SQLite 加 CHECK 必须重建表：batch_alter_table(recreate="always") 反射重建，
  既有 ck_recitation_items_status / uq_recitation_items_subject_prompt 与
  recitation_reviews 两条 FK（CASCADE / RESTRICT）原样保留，迁移测试逐字核对。
- source 不进任何唯一键：一词一条记忆轨不变。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；删 source 列与该 CHECK，
既有行 subject/prompt/answer/unit/status 内容零变化，但 source 标记随列丢失、不可找回。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_recitation_source"
down_revision: str | None = "0025_dictation_sheet_audio_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_recitation_items_source"
CHECK_SQL = "source IN ('seed','manual','candidate')"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _check_names(table: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
    }


def upgrade() -> None:
    if "recitation_items" not in sa.inspect(op.get_bind()).get_table_names():
        return

    has_column = "source" in _columns("recitation_items")
    has_check = CHECK_NAME in _check_names("recitation_items")
    if has_column and has_check:
        return

    with op.batch_alter_table("recitation_items", recreate="always") as batch:
        if not has_column:
            batch.add_column(
                sa.Column(
                    "source",
                    sa.Text(),
                    nullable=False,
                    server_default=sa.text("'manual'"),
                )
            )
        if not has_check:
            batch.create_check_constraint(CHECK_NAME, CHECK_SQL)


def downgrade() -> None:
    if "recitation_items" not in sa.inspect(op.get_bind()).get_table_names():
        return

    has_column = "source" in _columns("recitation_items")
    has_check = CHECK_NAME in _check_names("recitation_items")
    if not has_column and not has_check:
        return

    with op.batch_alter_table("recitation_items", recreate="always") as batch:
        if has_check:
            batch.drop_constraint(CHECK_NAME, type_="check")
        if has_column:
            batch.drop_column("source")
