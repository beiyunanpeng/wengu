"""P3-3a：英语背诵条目 + 记忆阶梯自评（recitation_items / recitation_reviews）

Revision ID: 0020_recitation
Revises: 0019_drop_orphan_photo_tables
Create Date: 2026-11-03

背诵条目**不是错题**：这里的两张表与 mistakes / mistake_versions / attempts
完全隔离，只写 learning_events(type='recitation_reviewed') 事实与自身的自评行，
因此不会污染掌握度、复习排期与练习记录。

- recitation_items：家长手填条目，UNIQUE(subject, prompt) 防重复；status 只有
  active/retired 两态，停用不物理删除。
- recitation_reviews：每次自评一行，UNIQUE(item_id, reviewed_on) 保证同一天只有
  一条事实；item 删除级联清自评，event 是事实源、禁止级联删除。

备份/回退：升级前先在家长区「备份」页导出（或 `POST /api/backup/export`）拿到整库
一致性快照，或按 `migrations/README.md` 把 `wengu-api/data/wengu.db` 复制到仓库外。
回退 `alembic downgrade -1` 只删本迁移新建的两张表；两表都是新增结构，不含历史回填。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_recitation"
down_revision: str | None = "0019_drop_orphan_photo_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_items() -> None:
    op.create_table(
        "recitation_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_recitation_items_status",
        ),
        sa.UniqueConstraint(
            "subject", "prompt", name="uq_recitation_items_subject_prompt"
        ),
    )


def _create_reviews() -> None:
    op.create_table(
        "recitation_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey(
                "recitation_items.id",
                ondelete="CASCADE",
                name="fk_recitation_reviews_item_id",
            ),
            nullable=False,
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("rung", sa.Integer(), nullable=False),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("scheduled_next", sa.Date(), nullable=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey(
                "learning_events.id",
                ondelete="RESTRICT",
                name="fk_recitation_reviews_event_id",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "verdict IN ('remembered', 'forgot')",
            name="ck_recitation_reviews_verdict",
        ),
        sa.UniqueConstraint(
            "item_id",
            "reviewed_on",
            name="uq_recitation_reviews_item_reviewed_on",
        ),
    )


def upgrade() -> None:
    existing = _tables()
    if "recitation_items" not in existing:
        _create_items()
    if "recitation_reviews" not in existing:
        _create_reviews()


def downgrade() -> None:
    existing = _tables()
    if "recitation_reviews" in existing:
        op.drop_table("recitation_reviews")
    if "recitation_items" in existing:
        op.drop_table("recitation_items")
