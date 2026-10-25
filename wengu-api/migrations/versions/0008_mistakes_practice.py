"""P1-6：mistakes 根表 + mistake_versions 概念标签 + practice_records 派生表

Revision ID: 0008_mistakes_practice
Revises: 0007_grading
Create Date: 2026-10-25

设计要点（对齐 TICKETS P1-6 / AGENTS §2.1、§5）：
- Phase 0 边界表未回填：不实现"判错即自动入本"。mistakes 唯一写入路径 = 用户
  确认/申诉 verdict=wrong；source_grading_id UNIQUE 保证同源重试不重复建。
- mistake_versions 继续只追加，并补 UPDATE/DELETE 触发器；新增概念标签 JSON 列，
  建议值与确认值分离，AI/规则建议永不覆盖确认值。
- practice_records 是变式/加练派生表：不写 learning_events、不进错题、不参与复习
  与掌握度，可整表清空。source_mistake_id 只做上下文引用，SET NULL 不级联删错题。
- review_schedules 保持原样：本迁移不生成任何排期，P1-7 闸门回填后再接。

备份/回退：升级前复制 wengu-api/data/wengu.db 到仓库外（migrations/README.md）；
downgrade 只删本迁移新增表/列/触发器，不动 uploads/、learning_events 或既有错题版本。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_mistakes_practice"
down_revision: str | None = "0007_grading"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_GUARD = """
CREATE TRIGGER {table}_{action}_guard BEFORE {action} ON {table}
BEGIN
    SELECT RAISE(ABORT, '{table} is append-only: {action} is forbidden');
END
"""


def upgrade() -> None:
    op.create_table(
        "mistakes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_grading_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_grading_id", name="uq_mistakes_source_grading_id"),
        sa.ForeignKeyConstraint(
            ["source_grading_id"],
            ["grading_results.id"],
            name="fk_mistakes_source_grading_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("status IN ('active', 'voided')", name="ck_mistakes_status"),
        sa.CheckConstraint("current_version >= 1", name="ck_mistakes_current_version"),
    )

    op.create_table(
        "practice_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_mistake_id", sa.Integer(), nullable=True),
        sa.Column("problem_bank_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("problem_text", sa.Text(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["source_mistake_id"],
            ["mistakes.id"],
            name="fk_practice_records_source_mistake_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["problem_bank_id"],
            ["problem_bank.id"],
            name="fk_practice_records_problem_bank_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "kind IN ('variant', 'extra')", name="ck_practice_records_kind"
        ),
    )
    op.create_index(
        "ix_practice_records_source_mistake_id",
        "practice_records",
        ["source_mistake_id"],
    )
    op.create_index(
        "ix_practice_records_created_at", "practice_records", ["created_at"]
    )

    op.add_column(
        "mistake_versions",
        sa.Column(
            "suggested_concept_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "mistake_versions",
        sa.Column(
            "confirmed_concept_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
    )

    for action in ("UPDATE", "DELETE"):
        op.execute(_APPEND_ONLY_GUARD.format(table="mistake_versions", action=action))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS mistake_versions_DELETE_guard")
    op.execute("DROP TRIGGER IF EXISTS mistake_versions_UPDATE_guard")
    op.drop_column("mistake_versions", "confirmed_concept_ids_json")
    op.drop_column("mistake_versions", "suggested_concept_ids_json")
    op.drop_index(
        "ix_practice_records_created_at", table_name="practice_records"
    )
    op.drop_index(
        "ix_practice_records_source_mistake_id", table_name="practice_records"
    )
    op.drop_table("practice_records")
    op.drop_table("mistakes")
