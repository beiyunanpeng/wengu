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
