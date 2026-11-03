"""P5-6：退役视觉栈遗留的孤儿表 photo_captures / photo_capture_items

Revision ID: 0019_drop_orphan_photo_tables
Revises: 0018_practice_dedup
Create Date: 2026-11-03

v2.5 起真实题批改与提取全部移出系统，`app/` 业务代码对这两张表**零读写**
（P1-12 已删除 captures/extractions 端点与 provider 栈）。只 DROP 这两张表及其
显式索引；`problem_extractions` 按本票清单**保留**（该表同样无读写方，彻底清理另开工单），
其两个 FK 在 SQLite 里按表名解析，升级后暂时悬空、降级重建父表后自动重新有效。

备份/回退：升级前先在家长区「备份」页导出（或 `POST /api/backup/export`）拿到整库
一致性快照，或按 `migrations/README.md` 把 `wengu-api/data/wengu.db` 复制到仓库外。
降级 `alembic downgrade -1` 按 0004/0005 的原始定义重建两张空表（含 UNIQUE、FK 与索引），
**不回填历史照片/切图记录**；uploads 目录里的旧图片不动。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_drop_orphan_photo_tables"
down_revision: str | None = "0018_practice_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "photo_capture_items" in existing:
        op.drop_index(
            "ix_photo_capture_items_capture_id", table_name="photo_capture_items"
        )
        op.drop_table("photo_capture_items")
    if "photo_captures" in existing:
        op.drop_index("ix_photo_captures_status", table_name="photo_captures")
        op.drop_table("photo_captures")


def downgrade() -> None:
    existing = _tables()
    if "photo_captures" not in existing:
        op.create_table(
            "photo_captures",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sha256", sa.Text(), nullable=False),
            sa.Column("stored_path", sa.Text(), nullable=False),
            sa.Column("original_name", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False, server_default="phone"),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.UniqueConstraint("sha256", name="uq_photo_captures_sha256"),
        )
        op.create_index("ix_photo_captures_status", "photo_captures", ["status"])
    if "photo_capture_items" not in existing:
        op.create_table(
            "photo_capture_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("photo_capture_id", sa.Integer(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("stored_path", sa.Text(), nullable=False),
            sa.Column("bbox_json", sa.Text(), nullable=False),
            sa.Column("anchor_label", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="ready"),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
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
