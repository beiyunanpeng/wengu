"""P1-3 主通道：photo_captures（手机拍照 HTTP 秒传落本地存储的事实表）

Revision ID: 0004_photo_captures
Revises: 0003_seed_domain
Create Date: 2026-10-24

设计要点（对齐 TICKETS P1-3 / AGENTS §5）：
- sha256 UNIQUE：同一照片重传/重试/重启返回已有行，幂等不重复落库。
- stored_path 存 uploads_dir 相对路径（哈希改名），文件本体不进库、不进日志。
- status='pending' 表示已落库待 P1-3b/4 消费；本表不含识别结果，
  Phase 0 闸门内不做自动入库/自动排复习。
- P1-3b 将加 photo_capture_item（一母多子的切题子图），本表为其母表。

备份/回退：SQLite 单文件，升级前按 migrations/README.md 备份整库；
downgrade 只删表不动 uploads 目录里的文件（孤儿文件由运维清理）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_photo_captures"
down_revision: str | None = "0003_seed_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="phone"),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sha256", name="uq_photo_captures_sha256"),
    )
    op.create_index("ix_photo_captures_status", "photo_captures", ["status"])


def downgrade() -> None:
    op.drop_index("ix_photo_captures_status", table_name="photo_captures")
    op.drop_table("photo_captures")
