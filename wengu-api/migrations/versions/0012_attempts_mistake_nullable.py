"""P1-11：attempts.mistake_id 可空（家长手动组卷的考核不挂错题）

Revision ID: 0012_attempts_mistake_nullable
Revises: 0011_v25_intake_and_quiz
Create Date: 2026-10-29

唯一写入路径不变：错题只由"核对页确认"产生。家长手动组卷挂在知识点上、没有
对应错题，因此该列在 v2.5 考核闭环里置为可空；复习闭环的 attempts 仍写 mistake_id。
掌握度仍以 learning_events 为唯一事实源，不新建表。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1。SQLite 改可空需重建表；
回退时先删掉 mistake_id IS NULL 的派生作答明细（手动组卷考核结果，可按来源重做），
再恢复 NOT NULL。learning_events 事实保持 append-only，不被回退删除。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_attempts_mistake_nullable"
down_revision: str | None = "0011_v25_intake_and_quiz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column(table: str, name: str) -> dict[str, object] | None:
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns(table):
        if column["name"] == name:
            return column
    return None


def upgrade() -> None:
    column = _column("attempts", "mistake_id")
    if column is None:
        raise RuntimeError("attempts.mistake_id 不存在，无法升级")
    if column["nullable"]:
        return
    with op.batch_alter_table("attempts") as batch:
        batch.alter_column("mistake_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    column = _column("attempts", "mistake_id")
    if column is not None and not column["nullable"]:
        return
    # 手动组卷的作答明细是派生数据（可按来源重做）；回退到 NOT NULL 前先清掉。
    op.execute(sa.text("DELETE FROM attempts WHERE mistake_id IS NULL"))
    with op.batch_alter_table("attempts") as batch:
        batch.alter_column("mistake_id", existing_type=sa.Integer(), nullable=False)
