"""P2-4：确保 user_role 存在家长行（PIN 首次进家长区时再设置）

Revision ID: 0014_parent_pin
Revises: 0013_drop_model_tables
Create Date: 2026-10-30

两角色 = 孩子默认视图 + 家长本地 PIN，不做登录/账号/多租户。
本票只保证 `user_role` 里有 `(role='parent', pin_hash=NULL)` 一行；PIN 由
`POST /api/session/pin/set` 首次设置时写入 scrypt 哈希（见 services/session.py）。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1。down 只删除本迁移补建且
**仍未设置 PIN** 的 parent 行；已设置 PIN 的行保留，避免误删家长凭据。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_parent_pin"
down_revision: str | None = "0013_drop_model_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _parent_count() -> int:
    bind = op.get_bind()
    return int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM user_role WHERE role = 'parent'")
        ).scalar_one()
    )


def upgrade() -> None:
    if _parent_count() == 0:
        op.get_bind().execute(
            sa.text(
                "INSERT INTO user_role (role, pin_hash, created_at) "
                "VALUES ('parent', NULL, CURRENT_TIMESTAMP)"
            )
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM user_role WHERE role = 'parent' AND pin_hash IS NULL"
        )
    )
