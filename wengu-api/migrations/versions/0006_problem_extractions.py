"""P1-4：problem_extractions（VLM 结构化提取结果 + 提取质量前置闸门结论）

Revision ID: 0006_problem_extractions
Revises: 0005_photo_capture_items
Create Date: 2026-10-25

设计要点（对齐 TICKETS P1-4 / AGENTS §5）：
- 一题一条：UNIQUE(photo_capture_id, source_kind, seq)；source_kind 区分
  单题裁图（slice）与整页兜底（whole_page），两者可共存但 API 按当前来源回显。
- FK ON DELETE CASCADE：force 重切删除旧 photo_capture_items 时，旧提取结果
  自动失效，不残留指向已删除裁图的记录。
- gate_status 三态：ready_for_grading / manual_review / figure_dependent；
  提取质量前置闸门结论在此固化，P1-5 只消费 ready_for_grading 进判分链路。
- 只存模型建议值与回显原文；用户确认值归 P1-5 的 mistake_versions，不在此覆盖。

备份/回退：SQLite 单文件，升级前按 migrations/README.md 备份整库；
downgrade 只删表，不动 uploads 目录里的裁图文件。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_problem_extractions"
down_revision: str | None = "0005_photo_capture_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "problem_extractions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("photo_capture_id", sa.Integer(), nullable=False),
        sa.Column("photo_capture_item_id", sa.Integer(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("problem_text", sa.Text(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("problem_complete", sa.Boolean(), nullable=True),
        sa.Column("gate_status", sa.Text(), nullable=False),
        sa.Column("review_reasons_json", sa.Text(), nullable=False),
        sa.Column("figure_keywords_json", sa.Text(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "photo_capture_id",
            "source_kind",
            "seq",
            name="uq_problem_extractions_capture_source_seq",
        ),
        sa.ForeignKeyConstraint(
            ["photo_capture_id"],
            ["photo_captures.id"],
            name="fk_problem_extractions_capture_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["photo_capture_item_id"],
            ["photo_capture_items.id"],
            name="fk_problem_extractions_item_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_problem_extractions_capture_id",
        "problem_extractions",
        ["photo_capture_id"],
    )
    op.create_index(
        "ix_problem_extractions_item_id",
        "problem_extractions",
        ["photo_capture_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_problem_extractions_item_id", table_name="problem_extractions")
    op.drop_index("ix_problem_extractions_capture_id", table_name="problem_extractions")
    op.drop_table("problem_extractions")
