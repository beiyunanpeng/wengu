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
    "bank_drafts",
    "photo_captures",
    "photo_capture_items",
    "problem_extractions",
    "problem_bank",
    "grading_results",
    "grading_versions",
    "mistakes",
    "practice_records",
    "review_schedules",
    "user_role",
    "prerequisite_edges",
    "timetable_slots",
    "calendar_events",
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
def test_p2_3_timetable_and_calendar_up_down_up(tmp_path) -> None:
    """0015：课表/日历两表可逆；一条一科、kind 枚举、日期索引由库层兜底。"""

    db_path = tmp_path / "schedule.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "0014_parent_pin")
    assert {"timetable_slots", "calendar_events"}.isdisjoint(_tables(db_path))

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            slot_columns = {
                column["name"] for column in inspector.get_columns("timetable_slots")
            }
            event_columns = {
                column["name"] for column in inspector.get_columns("calendar_events")
            }
            slot_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("timetable_slots")
            }
            event_indexes = {
                index["name"] for index in inspector.get_indexes("calendar_events")
            }
        assert slot_columns == {"id", "weekday", "period", "subject", "note"}
        assert event_columns == {
            "id",
            "date",
            "title",
            "kind",
            "subject",
            "note",
        }
        assert "uq_timetable_slots_weekday_period" in slot_uniques
        assert "ix_calendar_events_date" in event_indexes

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO timetable_slots (weekday, period, subject)"
                    " VALUES (1, 1, '数学')"
                )
            )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError, match="timetable_slots.weekday"
            ):
                connection.execute(
                    text(
                        "INSERT INTO timetable_slots (weekday, period, subject)"
                        " VALUES (1, 1, '语文')"
                    )
                )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text(
                        "INSERT INTO timetable_slots (weekday, period, subject)"
                        " VALUES (9, 1, '语文')"
                    )
                )
            connection.execute(
                text(
                    "INSERT INTO calendar_events (date, title, kind)"
                    " VALUES ('2026-11-10', '月考', 'exam')"
                )
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text(
                        "INSERT INTO calendar_events (date, title, kind)"
                        " VALUES ('2026-11-11', '旅游', 'holiday')"
                    )
                )
            assert (
                connection.scalar(text("SELECT COUNT(*) FROM calendar_events"))
                == 1
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0014_parent_pin")
    assert {"timetable_slots", "calendar_events"}.isdisjoint(_tables(db_path))

    command.upgrade(config, "head")
    assert {"timetable_slots", "calendar_events"} <= _tables(db_path)


@pytest.mark.integration
def test_p3_1_bank_drafts_and_problem_bank_columns(tmp_path) -> None:
    """0016：bank_drafts 新表 + problem_bank 录题列；既有行保持原值、新列为 NULL。"""

    db_path = tmp_path / "bank-drafts.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "0015_timetable_calendar")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO problem_bank (external_id, subject, problem_text,"
                    " answer, verify, created_at)"
                    " VALUES ('old-1', '数学', '1+1=?', '2', '1+1', CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    added_columns = {
        "topic_id": True,
        "question_type": True,
        "difficulty": True,
        "choices_json": True,
        "figure": True,
        "hide_choice_text": True,
        "percent": True,
        "unaudited": True,
        "blind_verified": True,
    }

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert "bank_drafts" in inspector.get_table_names()
            draft_columns = {
                column["name"] for column in inspector.get_columns("bank_drafts")
            }
            draft_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("bank_drafts")
            }
            draft_indexes = {
                index["name"] for index in inspector.get_indexes("bank_drafts")
            }
            bank_columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns("problem_bank")
            }
            bank_fks = inspector.get_foreign_keys("problem_bank")
            old_row = connection.execute(
                text(
                    "SELECT subject, problem_text, answer, verify, topic_id,"
                    " question_type, unaudited FROM problem_bank"
                    " WHERE external_id = 'old-1'"
                )
            ).one()
        assert draft_columns == {
            "id",
            "import_batch_id",
            "seq",
            "normalized_json",
            "has_placeholder",
            "status",
            "created_at",
        }
        assert "uq_bank_drafts_batch_seq" in draft_uniques
        assert "ix_bank_drafts_status" in draft_indexes
        for name, nullable in added_columns.items():
            assert bank_columns[name] is nullable
        topic_fk = next(
            fk for fk in bank_fks if fk["constrained_columns"] == ["topic_id"]
        )
        assert topic_fk["referred_table"] == "knowledge_seed"
        assert topic_fk["options"].get("ondelete") == "SET NULL"
        assert old_row == ("数学", "1+1=?", "2", "1+1", None, None, None)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO import_batches"
                    " (id, channel, sha256, status, created_at)"
                    " VALUES (1, 'agent_bank_transcribe_v1', 'sha-1',"
                    " 'imported', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO bank_drafts"
                    " (import_batch_id, seq, normalized_json, created_at)"
                    " VALUES (1, 1, '{}', CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError, match="bank_drafts.import_batch_id"
            ):
                connection.execute(
                    text(
                        "INSERT INTO bank_drafts"
                        " (import_batch_id, seq, normalized_json, created_at)"
                        " VALUES (1, 1, '{}', CURRENT_TIMESTAMP)"
                    )
                )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text(
                        "INSERT INTO bank_drafts"
                        " (import_batch_id, seq, normalized_json, status, created_at)"
                        " VALUES (1, 2, '{}', 'unknown', CURRENT_TIMESTAMP)"
                    )
                )
    finally:
        engine.dispose()

    command.downgrade(config, "0015_timetable_calendar")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert "bank_drafts" not in inspector.get_table_names()
            bank_columns = {
                column["name"] for column in inspector.get_columns("problem_bank")
            }
            remaining = connection.execute(
                text(
                    "SELECT subject, problem_text, answer, verify"
                    " FROM problem_bank WHERE external_id = 'old-1'"
                )
            ).one()
        assert added_columns.keys().isdisjoint(bank_columns)
        assert remaining == ("数学", "1+1=?", "2", "1+1")
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert "bank_drafts" in _tables(db_path)


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
def test_p1_12_drops_model_tables_reversibly(tmp_path) -> None:
    """0013：DROP model_runs / ai_jobs；down 重建空表（含尝试链列与索引）。"""

    db_path = tmp_path / "drop-model-tables.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "0012_attempts_mistake_nullable")
    assert {"model_runs", "ai_jobs"} <= _tables(db_path)

    command.upgrade(config, "head")
    tables = _tables(db_path)
    assert {"model_runs", "ai_jobs"}.isdisjoint(tables)
    assert {"learning_events", "attempts", "grading_results"} <= tables

    command.downgrade(config, "0012_attempts_mistake_nullable")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            assert {"model_runs", "ai_jobs"} <= set(
                inspect(connection).get_table_names()
            )
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("model_runs")
            }
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes("model_runs")
            }
            job_uniques = {
                constraint["name"]
                for constraint in inspect(connection).get_unique_constraints("ai_jobs")
            }
        assert {"attempt_group", "attempt_index", "error_kind"} <= columns
        assert {
            "ix_model_runs_ai_job_id",
            "ix_model_runs_attempt_group",
        } <= indexes
        assert "uq_ai_jobs_idempotency_key" in job_uniques
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert {"model_runs", "ai_jobs"}.isdisjoint(_tables(db_path))


@pytest.mark.integration
def test_v25_quiz_attempts_allow_null_mistake(tmp_path) -> None:
    """0012：手动组卷 attempts 不挂错题；回退先清 NULL 行再恢复 NOT NULL。"""

    db_path = tmp_path / "quiz-attempts.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]: column["nullable"]
                for column in inspect(connection).get_columns("attempts")
            }
        assert columns["mistake_id"] is True

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO learning_events (type, actor, idempotency_key)"
                    " VALUES ('attempt_correct', 'student', 'quiz-null-1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO attempts (learning_event_id, kind, source,"
                    " is_correct, created_at)"
                    " VALUES (1, 'quiz', 'system_quiz', 1, CURRENT_TIMESTAMP)"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT mistake_id FROM attempts WHERE id = 1")
                )
                is None
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0011_v25_intake_and_quiz")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]: column["nullable"]
                for column in inspect(connection).get_columns("attempts")
            }
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes("attempts")
            }
            remaining = connection.scalar(text("SELECT COUNT(*) FROM attempts"))
        assert columns["mistake_id"] is False
        assert {"ix_attempts_mistake_id", "ix_attempts_problem_bank_id"} <= indexes
        assert remaining == 0
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]: column["nullable"]
                for column in inspect(connection).get_columns("attempts")
            }
        assert columns["mistake_id"] is True
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


@pytest.mark.integration
def test_v25_intake_and_quiz_columns(tmp_path) -> None:
    """0011：attempts.source/problem_bank_id + mistakes.primary_topic_id；旧行回填 manual。"""

    db_path = tmp_path / "v25-intake.db"
    config = _alembic_config(db_path)

    # 先在 0010 停住，造一条旧 attempts 行，验证升级后回填 manual
    command.upgrade(config, "0010_model_run_attempts")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO learning_events (type, actor, idempotency_key)"
                    " VALUES ('attempt_wrong', 'student', 'v25-e1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO attempts (mistake_id, learning_event_id, kind,"
                    " is_correct, created_at)"
                    " VALUES (1, 1, 'redo', 0, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            attempt_cols = {
                column["name"] for column in inspect(connection).get_columns("attempts")
            }
            attempt_idx = {
                index["name"] for index in inspect(connection).get_indexes("attempts")
            }
            mistake_cols = {
                column["name"] for column in inspect(connection).get_columns("mistakes")
            }
            mistake_idx = {
                index["name"] for index in inspect(connection).get_indexes("mistakes")
            }
        assert {"source", "problem_bank_id"} <= attempt_cols
        assert "ix_attempts_problem_bank_id" in attempt_idx
        assert "primary_topic_id" in mistake_cols
        assert "ix_mistakes_primary_topic_id" in mistake_idx

        with engine.begin() as connection:
            # 旧行回填 manual
            assert (
                connection.scalar(text("SELECT source FROM attempts WHERE id = 1"))
                == "manual"
            )
            # 考核溯源：seed / 题库 / 批改单 / 错题 / 作答 全链路插入读回
            connection.execute(
                text(
                    "INSERT INTO knowledge_seed (id, subject, name, unaudited,"
                    " blind_verified)"
                    " VALUES ('cnm_042', '数学', '一元二次方程', 1, 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO problem_bank (external_id, subject, problem_text,"
                    " answer, verify, created_at)"
                    " VALUES ('pb-1', '数学', '1+1=?', '2', '1+1 == 2',"
                    " CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO grading_results (source_kind, source_id,"
                    " question_type, problem_text, created_at, updated_at)"
                    " VALUES ('problem_extraction', 1, 'objective', '1+1=?',"
                    " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO mistakes (source_grading_id, primary_topic_id)"
                    " VALUES (1, 'cnm_042')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO attempts (mistake_id, learning_event_id,"
                    " problem_bank_id, kind, source, is_correct, created_at)"
                    " VALUES (1, 1, 1, 'quiz', 'system_quiz', 1, CURRENT_TIMESTAMP)"
                )
            )
            row = connection.execute(
                text("SELECT source, problem_bank_id FROM attempts WHERE id = 2")
            ).one()
            assert row == ("system_quiz", 1)
            assert (
                connection.scalar(
                    text("SELECT primary_topic_id FROM mistakes WHERE id = 1")
                )
                == "cnm_042"
            )
    finally:
        engine.dispose()

    # 回退干净、再升级可重复
    command.downgrade(config, "0010_model_run_attempts")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            attempt_cols = {
                column["name"] for column in inspect(connection).get_columns("attempts")
            }
            mistake_cols = {
                column["name"] for column in inspect(connection).get_columns("mistakes")
            }
        assert "source" not in attempt_cols
        assert "problem_bank_id" not in attempt_cols
        assert "primary_topic_id" not in mistake_cols
    finally:
        engine.dispose()

    command.upgrade(config, "head")
