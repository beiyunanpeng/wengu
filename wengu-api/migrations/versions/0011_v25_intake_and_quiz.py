"""v2.5 批次①：导入与考核的数据模型增量

Revision ID: 0011_v25_intake_and_quiz
Revises: 0010_model_run_attempts
Create Date: 2026-10-27

加法增量，不改旧视觉栈、不改判分/复习逻辑：
- attempts.source TEXT NOT NULL（server_default 'manual'）：student_self 原题重做
  自评 / system_quiz 系统判同类题考核 / manual 历史与手录，既有行回填 manual；
- attempts.problem_bank_id INTEGER NULL → problem_bank.id ON DELETE SET NULL + 索引
  （system_quiz 溯源题库题）；
- mistakes.primary_topic_id TEXT NULL → knowledge_seed.id ON DELETE SET NULL + 索引
  （检索同类题的主考点；多对多仍走 mistake_versions.confirmed_concept_ids_json）。
不新建 quiz_attempts——考核闭环记在 attempts，掌握度唯一事实源不被双读。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新增的列与索引，
不清业务数据。升级/回退都先 inspect，可重复执行。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_v25_intake_and_quiz"
down_revision: str | None = "0010_model_run_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTEMPT_BANK_INDEX = "ix_attempts_problem_bank_id"
_MISTAKE_TOPIC_INDEX = "ix_mistakes_primary_topic_id"

_ATTEMPT_COLUMNS = {
    "source": sa.Column(
        "source",
        sa.Text(),
        nullable=False,
        server_default=sa.text("'manual'"),
    ),
    "problem_bank_id": sa.Column(
        "problem_bank_id",
        sa.Integer(),
        sa.ForeignKey(
            "problem_bank.id", ondelete="SET NULL", name="fk_attempts_problem_bank_id"
        ),
        nullable=True,
    ),
}
_MISTAKE_COLUMNS = {
    "primary_topic_id": sa.Column(
        "primary_topic_id",
        sa.Text(),
        sa.ForeignKey(
            "knowledge_seed.id",
            ondelete="SET NULL",
            name="fk_mistakes_primary_topic_id",
        ),
        nullable=True,
    ),
}


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    missing = [c for name, c in _ATTEMPT_COLUMNS.items() if name not in _columns("attempts")]
    if missing:
        with op.batch_alter_table("attempts") as batch:
            for column in missing:
                batch.add_column(column)
    if _ATTEMPT_BANK_INDEX not in _indexes("attempts"):
        op.create_index(_ATTEMPT_BANK_INDEX, "attempts", ["problem_bank_id"])

    missing = [c for name, c in _MISTAKE_COLUMNS.items() if name not in _columns("mistakes")]
    if missing:
        with op.batch_alter_table("mistakes") as batch:
            for column in missing:
                batch.add_column(column)
    if _MISTAKE_TOPIC_INDEX not in _indexes("mistakes"):
        op.create_index(_MISTAKE_TOPIC_INDEX, "mistakes", ["primary_topic_id"])


def downgrade() -> None:
    if _MISTAKE_TOPIC_INDEX in _indexes("mistakes"):
        op.drop_index(_MISTAKE_TOPIC_INDEX, table_name="mistakes")
    existing = [name for name in _MISTAKE_COLUMNS if name in _columns("mistakes")]
    if existing:
        with op.batch_alter_table("mistakes") as batch:
            for name in existing:
                batch.drop_column(name)

    if _ATTEMPT_BANK_INDEX in _indexes("attempts"):
        op.drop_index(_ATTEMPT_BANK_INDEX, table_name="attempts")
    existing = [name for name in _ATTEMPT_COLUMNS if name in _columns("attempts")]
    if existing:
        with op.batch_alter_table("attempts") as batch:
            for name in existing:
                batch.drop_column(name)
