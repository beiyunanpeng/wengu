"""P3-1：空白真题录题草稿 + problem_bank 动态字段

Revision ID: 0016_bank_drafts
Revises: 0015_timetable_calendar
Create Date: 2026-10-31

- bank_drafts：外部 agent 转录的空白真题先停这里，家长审核才写 problem_bank；
  UNIQUE(import_batch_id, seq) 与 ingestion_drafts 同构，sha256 去重复用 import_batches。
- problem_bank 加列：topic_id（FK knowledge_seed.id, ON DELETE SET NULL）、题型/难度/
  选项/配图/百分比等；**既有行保持 NULL**，不影响 P1-5 既有导入行。
- 固定 unaudited=1 / blind_verified=0 的标签列：家长/外部转录题未经教师审核与二遍盲解。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新建的 bank_drafts
与新增列，不动既有 problem_bank 行内容。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_bank_drafts"
down_revision: str | None = "0015_timetable_calendar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BANK_COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    (
        "topic_id",
        sa.Column(
            "topic_id",
            sa.Text(),
            sa.ForeignKey(
                "knowledge_seed.id",
                ondelete="SET NULL",
                name="fk_problem_bank_topic_id",
            ),
            nullable=True,
        ),
    ),
    ("question_type", sa.Column("question_type", sa.Text(), nullable=True)),
    ("difficulty", sa.Column("difficulty", sa.Text(), nullable=True)),
    ("choices_json", sa.Column("choices_json", sa.Text(), nullable=True)),
    ("figure", sa.Column("figure", sa.Text(), nullable=True)),
    ("hide_choice_text", sa.Column("hide_choice_text", sa.Boolean(), nullable=True)),
    ("percent", sa.Column("percent", sa.Boolean(), nullable=True)),
    ("unaudited", sa.Column("unaudited", sa.Boolean(), nullable=True)),
    ("blind_verified", sa.Column("blind_verified", sa.Boolean(), nullable=True)),
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if "bank_drafts" not in _tables():
        op.create_table(
            "bank_drafts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "import_batch_id",
                sa.Integer(),
                sa.ForeignKey("import_batches.id"),
                nullable=False,
            ),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("normalized_json", sa.Text(), nullable=False),
            sa.Column("has_placeholder", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.CheckConstraint(
                "status IN ('draft', 'approved', 'rejected')",
                name="ck_bank_drafts_status",
            ),
            sa.UniqueConstraint(
                "import_batch_id", "seq", name="uq_bank_drafts_batch_seq"
            ),
        )
        op.create_index("ix_bank_drafts_status", "bank_drafts", ["status"])

    existing = _columns("problem_bank")
    missing = [(name, column) for name, column in BANK_COLUMNS if name not in existing]
    if missing:
        # SQLite 不支持 ALTER ADD CONSTRAINT；含 FK 的新列必须走 batch 重建
        with op.batch_alter_table("problem_bank", recreate="always") as batch:
            for _name, column in missing:
                batch.add_column(column)
    if "ix_problem_bank_topic_id" not in _indexes("problem_bank"):
        op.create_index(
            "ix_problem_bank_topic_id", "problem_bank", ["topic_id"]
        )


def downgrade() -> None:
    if "problem_bank" in _tables():
        if "ix_problem_bank_topic_id" in _indexes("problem_bank"):
            op.drop_index("ix_problem_bank_topic_id", table_name="problem_bank")
        existing = _columns("problem_bank")
        present = [name for name, _column in BANK_COLUMNS if name in existing]
        if present:
            # FK 列无法直接 DROP COLUMN，同样走 batch 重建
            with op.batch_alter_table("problem_bank", recreate="always") as batch:
                for name in reversed(present):
                    batch.drop_column(name)

    if "bank_drafts" in _tables():
        op.drop_index("ix_bank_drafts_status", table_name="bank_drafts")
        op.drop_table("bank_drafts")
