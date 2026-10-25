"""P1-3b：photo_capture_items（OCR 行聚类切题产出的单题子图记录）

Revision ID: 0005_photo_capture_items
Revises: 0004_photo_captures
Create Date: 2026-10-24

设计要点（对齐 TICKETS P1-3b / AGENTS §5）：
- 一母多子：UNIQUE(photo_capture_id, seq)，重切幂等（同 seq 覆盖同一路径）。
- bbox_json 存相对母图坐标（x1,y1,x2,y2），申诉定位可回溯。
- 子图是预处理产物，不含识别结果；题目内容等 P1-4 由 VLM 精读产出。
- anchor_label 仅题号短文本（如 "12"），不回存整行 OCR 文本。

备份/回退：SQLite 单文件，升级前按 migrations/README.md 备份整库；
downgrade 只删表不动 uploads 目录里的子图文件（孤儿文件由运维清理）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_photo_capture_items"
down_revision: str | None = "0004_photo_captures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_capture_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("photo_capture_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("bbox_json", sa.Text(), nullable=False),
        sa.Column("anchor_label", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "photo_capture_id", "seq", name="uq_photo_capture_items_capture_seq"
        ),
        sa.ForeignKeyConstraint(
            ["photo_capture_id"],
            ["photo_captures.id"],
            name="fk_photo_capture_items_capture_id",
        ),
    )
    op.create_index(
        "ix_photo_capture_items_capture_id",
        "photo_capture_items",
        ["photo_capture_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_photo_capture_items_capture_id", table_name="photo_capture_items")
    op.drop_table("photo_capture_items")
