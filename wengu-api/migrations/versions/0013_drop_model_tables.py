"""P1-12：删除 model_runs / ai_jobs（wengu 转零模型）

Revision ID: 0013_drop_model_tables
Revises: 0012_attempts_mistake_nullable
Create Date: 2026-10-30

v2.5 起 wengu 不再调用任何云端模型，`ai_jobs`/`model_runs` 两张表已无读写方
（gateway/成本护栏/model_audit 已随 P1-12 删除）。只 DROP 这两张表；
`learning_events`/`attempts` 等事实与派生表不动。

备份/回退：升级前把 wengu-api/data/wengu.db 复制到仓库外（migrations/README.md）。
回退：cd wengu-api && venv/Scripts/alembic downgrade -1。down 按 0002+0010 的原始
定义重建空表（含 UNIQUE、FK 与索引），不回填历史模型审计数据。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_drop_model_tables"
down_revision: str | None = "0012_attempts_mistake_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "model_runs" in existing:
        op.drop_index("ix_model_runs_ai_job_id", table_name="model_runs")
        op.drop_table("model_runs")
    if "ai_jobs" in existing:
        op.drop_table("ai_jobs")


def downgrade() -> None:
    existing = _tables()
    if "ai_jobs" not in existing:
        op.create_table(
            "ai_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_type", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("idempotency_key", sa.Text(), nullable=False),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("to_event_id", sa.Integer(), nullable=True),
            sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("idempotency_key", name="uq_ai_jobs_idempotency_key"),
        )
    if "model_runs" not in existing:
        op.create_table(
            "model_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ai_job_id", sa.Integer(), nullable=True),
            sa.Column("task_type", sa.Text(), nullable=False),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("prompt_id", sa.Text(), nullable=False),
            sa.Column("prompt_version", sa.Text(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("usage_json", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("attempt_group", sa.Text(), nullable=True),
            sa.Column("attempt_index", sa.Integer(), nullable=True),
            sa.Column("error_kind", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.ForeignKeyConstraint(
                ["ai_job_id"], ["ai_jobs.id"], name="fk_model_runs_ai_job_id"
            ),
        )
        op.create_index("ix_model_runs_ai_job_id", "model_runs", ["ai_job_id"])
        op.create_index("ix_model_runs_attempt_group", "model_runs", ["attempt_group"])
