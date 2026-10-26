"""P1-7a：review_schedules 幂等唯一索引

Revision ID: 0009_review_schedules
Revises: 0008_mistakes_practice
Create Date: 2026-10-26

0002 已创建 review_schedules（列/索引与 models/review.py 一致），本迁移不重复建表，
只补两条数据库级幂等防线：
- source_event_id UNIQUE：一个事实事件最多生成一条排期；
- mistake_id 部分 UNIQUE（completed_at IS NULL）：同一错题同时最多一条未完成排期。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1；只删本迁移新增索引，
不删表、不清排期数据。升级/回退都先 inspect 索引，可重复执行。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_review_schedules"
down_revision: str | None = "0008_mistakes_practice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_INDEX = "uq_review_schedules_source_event_id"
_OPEN_INDEX = "uq_review_schedules_open_mistake"


def _index_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes("review_schedules")}


def upgrade() -> None:
    names = _index_names()
    if _SOURCE_INDEX not in names:
        op.create_index(
            _SOURCE_INDEX,
            "review_schedules",
            ["source_event_id"],
            unique=True,
        )
    if _OPEN_INDEX not in names:
        op.create_index(
            _OPEN_INDEX,
            "review_schedules",
            ["mistake_id"],
            unique=True,
            sqlite_where=sa.text("completed_at IS NULL"),
        )


def downgrade() -> None:
    names = _index_names()
    if _OPEN_INDEX in names:
        op.drop_index(_OPEN_INDEX, table_name="review_schedules")
    if _SOURCE_INDEX in names:
        op.drop_index(_SOURCE_INDEX, table_name="review_schedules")
