"""P3-1c：题库条目生命周期（编辑 + 软作废）

Revision ID: 0017_bank_item_lifecycle
Revises: 0016_bank_drafts
Create Date: 2026-10-31

- problem_bank.status：active|voided，NOT NULL、server_default 'active'；既有行回填 active。
- problem_bank.updated_at：家长编辑/作废/撤销时写入，便于审核页排序与追溯。
- **不做物理删除**（与错题本同一哲学）：作废题退出运行时检索池，但题目行、历史
  attempts / learning_events / review_schedules 一律不改写。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新增的两列与 CHECK，
不改既有 problem_bank 行内容。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_bank_item_lifecycle"
down_revision: str | None = "0016_bank_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_CHECK = "ck_problem_bank_status"


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _check_constraints(table: str) -> set[str]:
    return {
        constraint["name"] or ""
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table)
    }


def upgrade() -> None:
    existing = _columns("problem_bank")
    checks = _check_constraints("problem_bank")
    add_status = "status" not in existing
    add_updated = "updated_at" not in existing
    add_check = STATUS_CHECK not in checks
    if not (add_status or add_updated or add_check):
        return

    # SQLite 不支持直接 ADD CHECK / 带约束列；batch 重建保证既有行按 server_default 回填。
    with op.batch_alter_table("problem_bank", recreate="always") as batch:
        if add_status:
            batch.add_column(
                sa.Column(
                    "status",
                    sa.Text(),
                    nullable=False,
                    server_default="active",
                )
            )
        if add_updated:
            batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        if add_check:
            batch.create_check_constraint(
                STATUS_CHECK, "status IN ('active', 'voided')"
            )


def downgrade() -> None:
    if "problem_bank" not in sa.inspect(op.get_bind()).get_table_names():
        return
    existing = _columns("problem_bank")
    checks = _check_constraints("problem_bank")
    drop_status = "status" in existing
    drop_updated = "updated_at" in existing
    drop_check = STATUS_CHECK in checks
    if not (drop_status or drop_updated or drop_check):
        return

    with op.batch_alter_table("problem_bank", recreate="always") as batch:
        if drop_check:
            batch.drop_constraint(STATUS_CHECK, type_="check")
        if drop_updated:
            batch.drop_column("updated_at")
        if drop_status:
            batch.drop_column("status")
