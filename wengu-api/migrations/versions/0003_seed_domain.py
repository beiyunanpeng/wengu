"""knowledge_seed 补 domain 列（P1-1b：学科内一等分组字段，看板热力图用）

Revision ID: 0003_seed_domain
Revises: 0002_p1_1_core_schema
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_seed_domain"
down_revision: str | None = "0002_p1_1_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_seed", sa.Column("domain", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge_seed") as batch_op:
        batch_op.drop_column("domain")
