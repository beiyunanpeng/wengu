from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

API_DIR = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "learning_events",
    "attempts",
    "mistake_versions",
    "knowledge_seed",
    "concepts",
    "concept_aliases",
    "import_batches",
    "ingestion_drafts",
    "photo_captures",
    "photo_capture_items",
    "problem_extractions",
    "problem_bank",
    "grading_results",
    "grading_versions",
    "mistakes",
    "practice_records",
    "review_schedules",
    "ai_jobs",
    "model_runs",
    "user_role",
    "prerequisite_edges",
}

# 易变状态一律不存字段（AGENTS §5：掌握度/毕业/统计由事实推导）
FORBIDDEN_COLUMNS = {
    "review_schedules": {"mastery", "graduated", "mastered"},
    "learning_events": set(),
    "mistake_versions": {"mastery"},
}


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _tables(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            return set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.integration
def test_migrations_upgrade_and_downgrade(tmp_path) -> None:
    db_path = tmp_path / "migrations.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "head")
    assert _tables(db_path) - {"alembic_version"} == EXPECTED_TABLES

    command.downgrade(config, "base")
    assert _tables(db_path) - {"alembic_version"} == set()

    command.upgrade(config, "head")
    assert _tables(db_path) - {"alembic_version"} == EXPECTED_TABLES


@pytest.mark.integration
def test_no_mutable_state_columns(tmp_path) -> None:
    db_path = tmp_path / "columns.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            for table, forbidden in FORBIDDEN_COLUMNS.items():
                columns = {c["name"] for c in inspect(connection).get_columns(table)}
                assert columns.isdisjoint(forbidden), f"{table} 存了易变字段: {columns & forbidden}"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_learning_events_append_only_guard(tmp_path) -> None:
    """数据库触发器把 append-only 钉死：UPDATE/DELETE 直接报错（RAISE(ABORT) → IntegrityError）。"""

    db_path = tmp_path / "guard.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO learning_events (type, actor, idempotency_key)"
                    " VALUES ('attempt_correct', 'student', 'guard-key-1')"
                )
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(
                    text("UPDATE learning_events SET type = 'x' WHERE idempotency_key = 'guard-key-1'")
                )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(text("DELETE FROM learning_events WHERE id = 1"))
            # INSERT 不受限
            connection.execute(
                text(
                    "INSERT INTO learning_events (type, actor, idempotency_key)"
                    " VALUES ('attempt_wrong', 'student', 'guard-key-2')"
                )
            )
    finally:
        engine.dispose()


@pytest.mark.integration
def test_grading_versions_append_only_guard(tmp_path) -> None:
    db_path = tmp_path / "grading-guard.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO grading_results"
                    " (source_kind, source_id, question_type, problem_text, created_at, updated_at)"
                    " VALUES ('problem_extraction', 1, 'objective', '1+1=?',"
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO grading_versions"
                    " (grading_id, version, action, verdict, source, created_at)"
                    " VALUES (1, 1, 'suggested', 'correct', 'code', CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(text("UPDATE grading_versions SET verdict = 'wrong' WHERE id = 1"))
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(text("DELETE FROM grading_versions WHERE id = 1"))
    finally:
        engine.dispose()


@pytest.mark.integration
def test_mistake_versions_append_only_guard(tmp_path) -> None:
    db_path = tmp_path / "mistake-guard.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO mistake_versions"
                    " (mistake_id, version, status, created_at)"
                    " VALUES (1, 1, 'active', CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(
                    text("UPDATE mistake_versions SET status = 'voided' WHERE id = 1")
                )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(text("DELETE FROM mistake_versions WHERE id = 1"))
    finally:
        engine.dispose()


@pytest.mark.integration
def test_model_runs_attempt_chain_columns(tmp_path) -> None:
    """0010：尝试链三列 + 索引，可重复上下迁移。"""

    db_path = tmp_path / "attempts.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("model_runs")
            }
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes("model_runs")
            }
        assert {"attempt_group", "attempt_index", "error_kind"} <= columns
        assert "ix_model_runs_attempt_group" in indexes
    finally:
        engine.dispose()

    command.downgrade(config, "0009_review_schedules")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("model_runs")
            }
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes("model_runs")
            }
        assert {"attempt_group", "attempt_index", "error_kind"}.isdisjoint(columns)
        assert "ix_model_runs_attempt_group" not in indexes
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("model_runs")
            }
        assert {"attempt_group", "attempt_index", "error_kind"} <= columns
    finally:
        engine.dispose()


@pytest.mark.integration
def test_review_schedules_idempotency_indexes(tmp_path) -> None:
    """0009：同一事实事件最多一条排期；同一错题最多一条未完成排期。"""

    db_path = tmp_path / "review-index.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            indexes = {
                index["name"]: index
                for index in inspect(connection).get_indexes("review_schedules")
            }
        assert indexes["uq_review_schedules_source_event_id"]["unique"]
        assert indexes["uq_review_schedules_open_mistake"]["unique"]

        with engine.begin() as connection:
            for event_id in (1, 2):
                connection.execute(
                    text(
                        "INSERT INTO learning_events"
                        " (id, type, actor, idempotency_key)"
                        f" VALUES ({event_id}, 'review_scheduled', 'student',"
                        f" 'review-index-{event_id}')"
                    )
                )
            connection.execute(
                text(
                    "INSERT INTO review_schedules"
                    " (mistake_id, rung, base_interval_days, due_date, source_event_id)"
                    " VALUES (1, 0, 1, '2026-10-27', 1)"
                )
            )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError, match="review_schedules.source_event_id"
            ):
                connection.execute(
                    text(
                        "INSERT INTO review_schedules"
                        " (mistake_id, rung, base_interval_days, due_date, source_event_id)"
                        " VALUES (2, 0, 1, '2026-10-27', 1)"
                    )
                )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError, match="review_schedules.mistake_id"
            ):
                connection.execute(
                    text(
                        "INSERT INTO review_schedules"
                        " (mistake_id, rung, base_interval_days, due_date, source_event_id)"
                        " VALUES (1, 0, 1, '2026-10-27', 2)"
                    )
                )
            # 已完成排期不占"未完成"唯一位：同错题可继续拥有下一条 open 排期
            connection.execute(
                text(
                    "UPDATE review_schedules SET completed_at = CURRENT_TIMESTAMP"
                    " WHERE source_event_id = 1"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO review_schedules"
                    " (mistake_id, rung, base_interval_days, due_date, source_event_id)"
                    " VALUES (1, 1, 10, '2026-11-06', 2)"
                )
            )
            count = connection.scalar(text("SELECT COUNT(*) FROM review_schedules"))
        assert count == 2
    finally:
        engine.dispose()

    command.downgrade(config, "0008_mistakes_practice")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            names = {
                index["name"]
                for index in inspect(connection).get_indexes("review_schedules")
            }
        assert "uq_review_schedules_source_event_id" not in names
        assert "uq_review_schedules_open_mistake" not in names
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            names = {
                index["name"]
                for index in inspect(connection).get_indexes("review_schedules")
            }
        assert {"uq_review_schedules_source_event_id", "uq_review_schedules_open_mistake"} <= names
    finally:
        engine.dispose()
