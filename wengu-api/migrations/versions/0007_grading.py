"""P1-5：problem_bank + grading_results + grading_versions（批改分级闸事实）

Revision ID: 0007_grading
Revises: 0006_problem_extractions
Create Date: 2026-10-25

设计要点（对齐 TICKETS P1-5 / AGENTS §5）：
- problem_bank 只收 verify 表达式在 AST 沙箱跑通且 mismatch=0 的题；external_id
  UNIQUE 保证重复导入不叠加，verify_status 留审计。
- grading_results 是逻辑批改单：UNIQUE(source_kind, source_id) 保证同源幂等；
  题目/作答/标准答案全部存快照，P1-4 force 重切删除 extraction 后仍可审阅，
  且不落图片路径/URL。
- grading_versions 只追加：UNIQUE(grading_id, version)，UPDATE/DELETE 触发器守卫。
  首版是建议值（source=code/ai），确认/申诉追加确认值（source=student/parent），
  建议值永不被覆盖。
- Phase 0 边界表未回填：所有批改单初始 status=pending，不自动建错题/排复习。

备份/回退：SQLite 单文件，升级前按 migrations/README.md 备份整库；
downgrade 只删表，不动 uploads/ 与既有 learning_events。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_grading"
down_revision: str | None = "0006_problem_extractions"
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
        "problem_bank",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("problem_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "acceptable_answers_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("unordered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verify", sa.Text(), nullable=False),
        sa.Column("verify_vars_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("verify_status", sa.Text(), nullable=False, server_default="verified"),
        sa.Column("source", sa.Text(), nullable=False, server_default="import"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("external_id", name="uq_problem_bank_external_id"),
    )

    op.create_table(
        "grading_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("problem_bank_id", sa.Integer(), nullable=True),
        sa.Column("question_type", sa.Text(), nullable=False),
        sa.Column("problem_text", sa.Text(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("standard_answer", sa.Text(), nullable=True),
        sa.Column(
            "acceptable_answers_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("unordered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "source_kind", "source_id", name="uq_grading_results_source"
        ),
        sa.ForeignKeyConstraint(
            ["problem_bank_id"],
            ["problem_bank.id"],
            name="fk_grading_results_problem_bank_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "source_kind IN ('problem_extraction', 'ingestion_draft')",
            name="ck_grading_results_source_kind",
        ),
        sa.CheckConstraint(
            "question_type IN ('objective', 'process')",
            name="ck_grading_results_question_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'appealed')",
            name="ck_grading_results_status",
        ),
    )
    op.create_index(
        "ix_grading_results_problem_bank_id", "grading_results", ["problem_bank_id"]
    )

    op.create_table(
        "grading_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grading_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_id", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column(
            "sample_verdicts_json", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "grading_id", "version", name="uq_grading_versions_grading_version"
        ),
        sa.ForeignKeyConstraint(
            ["grading_id"],
            ["grading_results.id"],
            name="fk_grading_versions_grading_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action IN ('suggested', 'confirmed', 'appealed')",
            name="ck_grading_versions_action",
        ),
        sa.CheckConstraint(
            "verdict IN ('correct', 'wrong', 'uncertain')",
            name="ck_grading_versions_verdict",
        ),
        sa.CheckConstraint(
            "source IN ('code', 'ai', 'student', 'parent')",
            name="ck_grading_versions_source",
        ),
    )

    for action in ("UPDATE", "DELETE"):
        op.execute(_APPEND_ONLY_GUARD.format(table="grading_versions", action=action))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS grading_versions_DELETE_guard")
    op.execute("DROP TRIGGER IF EXISTS grading_versions_UPDATE_guard")
    op.drop_table("grading_versions")
    op.drop_index(
        "ix_grading_results_problem_bank_id", table_name="grading_results"
    )
    op.drop_table("grading_results")
    op.drop_table("problem_bank")
