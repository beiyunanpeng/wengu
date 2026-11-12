"""P1-17：mistake_versions 订正笔记 correction_notes（v2.7 D6）

Revision ID: 0022_correction_notes
Revises: 0021_pomodoro_sessions
Create Date: 2026-11-12

订正笔记 = 卷面上孩子/家长手写的订正说明，纯展示数据：不进判分、排期、掌握度
任何链路（AGENTS §5 / 设计文档 §18 D6）。讲解移出系统 = 系统不生成讲解，
不禁存手写笔记。应用层校验 ≤500 字，库层不加 CHECK（与 standard_answer 同惯例）。

mistake_versions 被 0008 触发器钉死 append-only：本迁移用原生 ADD/DROP COLUMN，
绝不 batch 重建——batch 会连带丢掉 append-only 触发器。编辑笔记走"追加新版本行"
（复用 append_mistake_version），历史版本逐行不变。

备份/回退：升级前先在家长区「备份」页导出整库一致性快照，或按 migrations/README.md
把 wengu-api/data/wengu.db 复制到仓库外。downgrade 只删本列；历史版本行里的笔记
随之丢弃（与升级前行为一致），其余内容/标签/触发器原样保留。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_correction_notes"
down_revision: str | None = "0021_pomodoro_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("mistake_versions")
    }


def upgrade() -> None:
    if "correction_notes" not in _columns():
        op.add_column(
            "mistake_versions",
            sa.Column("correction_notes", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if "correction_notes" in _columns():
        op.drop_column("mistake_versions", "correction_notes")
