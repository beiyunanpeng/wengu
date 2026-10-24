"""P1-1 core schema: event-sourced fact source + idempotent writes

Revision ID: 0002_p1_1_core_schema
Revises: 0001_initial_empty
Create Date: 2026-10-24

设计要点（对齐 TICKETS P1-1 / AGENTS §5）：
- learning_events 是 append-only 事实源：UNIQUE(idempotency_key) 防重复计数，
  触发器在数据库层禁止 UPDATE/DELETE。
- 掌握度 / 毕业 / 统计一律不存字段，由 services/recompute.py 从事件确定性推导。
- mistake_versions 只追加：UNIQUE(mistake_id, version)。
- import_batches.sha256 / ai_jobs.idempotency_key UNIQUE：重复导入/重试/重启不重复。
- model_runs 不落题目全文/答案/文件 URL/PII。
- 建议值与确认值成对存储（suggested_* + confirmed_*），带来源与置信度。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_p1_1_core_schema"
down_revision: str | None = "0001_initial_empty"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_GUARD = """
CREATE TRIGGER {table}_{action}_guard BEFORE {action} ON {table}
BEGIN
    SELECT RAISE(ABORT, '{table} is append-only: {action} is forbidden');
END
"""


def upgrade() -> None:
    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        # 逻辑错题 id（mistake_versions.mistake_id），不设 FK：事实源不随内容版本级联
        sa.Column("mistake_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_learning_events_idempotency_key"),
    )
    op.create_index("ix_learning_events_mistake_id", "learning_events", ["mistake_id"])
    op.create_index("ix_learning_events_type", "learning_events", ["type"])

    # 触发器在数据库层把 append-only 钉死（PG/SQLite 语法通用，SQLite 单写实例足够）
    for action in ("UPDATE", "DELETE"):
        op.execute(_APPEND_ONLY_GUARD.format(table="learning_events", action=action))

    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mistake_id", sa.Integer(), nullable=False),
        sa.Column("learning_event_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["learning_event_id"],
            ["learning_events.id"],
            name="fk_attempts_learning_event_id",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_attempts_mistake_id", "attempts", ["mistake_id"])

    op.create_table(
        "mistake_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mistake_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("problem_text", sa.Text(), nullable=True),
        sa.Column("problem_images", sa.Text(), nullable=True),
        sa.Column("standard_answer", sa.Text(), nullable=True),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),  # NULL = 待确认
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        # 知识点：AI 建议值 + 用户确认值分离（AGENTS §5）
        sa.Column("suggested_category_id", sa.Text(), nullable=True),
        sa.Column("category_confidence", sa.Float(), nullable=True),
        sa.Column("confirmed_category_id", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.Text(), nullable=True),
        # 错因：同构分离
        sa.Column("suggested_error_cause", sa.Text(), nullable=True),
        sa.Column("confirmed_error_cause", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("mistake_id", "version", name="uq_mistake_versions_mistake_version"),
    )
    op.create_index("ix_mistake_versions_mistake_id", "mistake_versions", ["mistake_id"])

    op.create_table(
        "knowledge_seed",
        sa.Column("id", sa.Text(), primary_key=True),  # 如 cnm_*（P1-1b 装载）
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("grade", sa.Text(), nullable=True),  # 高中 grade 10–16 语义为"册"
        sa.Column("semester", sa.Text(), nullable=True),
        sa.Column("chapter", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mastery_criteria", sa.Text(), nullable=True),
        sa.Column("diagnostic_question", sa.Text(), nullable=True),
        sa.Column("standards", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("unaudited", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("blind_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),  # ai | student | parent
        sa.Column("status", sa.Text(), nullable=False, server_default="suggested"),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "category_id", name="uq_concepts_name_category"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["knowledge_seed.id"], name="fk_concepts_category_id"
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"], ["concepts.id"], name="fk_concepts_merged_into_id"
        ),
    )

    op.create_table(
        "concept_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.UniqueConstraint("concept_id", "alias", name="uq_concept_aliases_concept_alias"),
        sa.ForeignKeyConstraint(
            ["concept_id"], ["concepts.id"], name="fk_concept_aliases_concept_id"
        ),
    )

    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="received"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sha256", name="uq_import_batches_sha256"),
    )

    op.create_table(
        "ingestion_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_batch_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("normalized_json", sa.Text(), nullable=False),
        sa.Column("has_placeholder", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_incomplete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "import_batch_id", "seq", name="uq_ingestion_drafts_batch_seq"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"], ["import_batches.id"], name="fk_ingestion_drafts_batch_id"
        ),
    )

    op.create_table(
        "review_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mistake_id", sa.Integer(), nullable=False),
        sa.Column("rung", sa.Integer(), nullable=False),
        sa.Column("base_interval_days", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("completed_attempt_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["learning_events.id"],
            name="fk_review_schedules_source_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["completed_attempt_id"],
            ["attempts.id"],
            name="fk_review_schedules_completed_attempt_id",
        ),
    )
    op.create_index("ix_review_schedules_mistake_id", "review_schedules", ["mistake_id"])
    op.create_index("ix_review_schedules_due_date", "review_schedules", ["due_date"])

    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("to_event_id", sa.Integer(), nullable=True),  # 水位：运行期新增留下次
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_ai_jobs_idempotency_key"),
    )

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
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["ai_job_id"], ["ai_jobs.id"], name="fk_model_runs_ai_job_id"
        ),
    )
    op.create_index("ix_model_runs_ai_job_id", "model_runs", ["ai_job_id"])

    op.create_table(
        "user_role",
        sa.Column("role", sa.Text(), primary_key=True),  # child | parent
        sa.Column("pin_hash", sa.Text(), nullable=True),  # child 默认免 PIN
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "prerequisite_edges",
        sa.Column("parent_id", sa.Text(), nullable=False),
        sa.Column("child_id", sa.Text(), nullable=False),
        sa.Column("edge_type", sa.Text(), nullable=False),  # hard | soft
        sa.Column("source", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("parent_id", "child_id", name="pk_prerequisite_edges"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["knowledge_seed.id"], name="fk_edges_parent_id"
        ),
        sa.ForeignKeyConstraint(
            ["child_id"], ["knowledge_seed.id"], name="fk_edges_child_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("prerequisite_edges")
    op.drop_table("user_role")
    op.drop_index("ix_model_runs_ai_job_id", table_name="model_runs")
    op.drop_table("model_runs")
    op.drop_table("ai_jobs")
    op.drop_index("ix_review_schedules_due_date", table_name="review_schedules")
    op.drop_index("ix_review_schedules_mistake_id", table_name="review_schedules")
    op.drop_table("review_schedules")
    op.drop_table("ingestion_drafts")
    op.drop_table("import_batches")
    op.drop_table("concept_aliases")
    op.drop_table("concepts")
    op.drop_table("knowledge_seed")
    op.drop_index("ix_mistake_versions_mistake_id", table_name="mistake_versions")
    op.drop_table("mistake_versions")
    op.drop_index("ix_attempts_mistake_id", table_name="attempts")
    op.drop_table("attempts")
    op.execute("DROP TRIGGER IF EXISTS learning_events_DELETE_guard")
    op.execute("DROP TRIGGER IF EXISTS learning_events_UPDATE_guard")
    op.drop_index("ix_learning_events_type", table_name="learning_events")
    op.drop_index("ix_learning_events_mistake_id", table_name="learning_events")
    op.drop_table("learning_events")
