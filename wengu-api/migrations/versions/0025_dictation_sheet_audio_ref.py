"""P3-4b：dictation_sheets 加 audio_ref（卷级挂接听写音频，可空 TEXT 存文件名）

Revision ID: 0025_dictation_sheet_audio_ref
Revises: 0024_dictation_sheets
Create Date: 2026-11-21

一卷一音频：audio_ref 只存 <data_dir>/audio/ 内的纯文件名，默写卷留空（NULL）；
不提供改挂、不做多音频、不逐词对时间戳，也不预留任何其他列。音频本体是第三方
课程文件，绝不进 git、绝不进备份包（设计文档 §19-G-3 定案二同一条理由），
因此本列只是文件名引用，不存路径、不存内容。

dictation_sheets 无 append-only 触发器，但沿用 0022 的原生 ADD/DROP COLUMN
惯例（不 batch 重建），既有行 audio_ref 自动为 NULL，历史卷面内容零变化。

备份/回退：升级前先在家长区「备份」页导出整库一致性快照，或按 migrations/README.md
把 wengu-api/data/wengu.db 复制到仓库外。downgrade 只删本列；挂接关系随之丢弃
（音频文件本身在 data/audio/ 不受影响），其余列与 CHECK 原样保留。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_dictation_sheet_audio_ref"
down_revision: str | None = "0024_dictation_sheets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("dictation_sheets")
    }


def upgrade() -> None:
    if "audio_ref" not in _columns():
        op.add_column(
            "dictation_sheets",
            sa.Column("audio_ref", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if "audio_ref" in _columns():
        op.drop_column("dictation_sheets", "audio_ref")
