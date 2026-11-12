from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from app.models import PomodoroSession, RecitationItem, RecitationReview
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import CreateIndex, CreateTable

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
    "recitation_items",
    "recitation_reviews",
    "pomodoro_sessions",
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


def _master_ddl(db_path: Path, involved: set[str]) -> dict[str, str]:
    """`sqlite_master.sql` 原文快照：涉及表本身 + 挂在它们上面的索引。"""

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
            " WHERE sql IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return {
        f"{kind}:{name}": sql
        for kind, name, table, sql in rows
        if table in involved
    }


def _split_ddl_items(body: str) -> list[str]:
    """按括号深度 0 的逗号切列/约束，忽略单双引号里的逗号。"""

    items: list[str] = []
    buffer: list[str] = []
    depth = 0
    quote: str | None = None
    for char in body:
        if quote is not None:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
        elif char == "(":
            depth += 1
            buffer.append(char)
        elif char == ")":
            depth -= 1
            buffer.append(char)
        elif char == "," and depth == 0:
            items.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    if "".join(buffer).strip():
        items.append("".join(buffer))
    return items


def _canonical_table_ddl(sql: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """SQLite batch 重建只改呈现方式时，仍保留全部语义 token 的规范化。

    仅抹平三处 SQLite 自身产生的无意义差异：表名加不加双引号、
    `DEFAULT CURRENT_TIMESTAMP` 是否带括号、约束子句顺序。列顺序保持原位，
    列类型 / NOT NULL / DEFAULT / CHECK / 约束名 / REFERENCES / ON DELETE
    全部逐字比较。
    """

    match = re.match(
        r'CREATE TABLE\s+(?:"([^"]+)"|([A-Za-z0-9_]+))\s*\((.*)\)\s*$',
        sql,
        re.S,
    )
    assert match is not None, sql
    name = match.group(1) or match.group(2)
    columns: list[str] = []
    constraints: list[str] = []
    for item in _split_ddl_items(match.group(3)):
        text = " ".join(item.split()).strip()
        text = re.sub(r"DEFAULT\s*\(\s*([^()]+?)\s*\)", r"DEFAULT \1", text)
        if text.upper().startswith(
            ("CONSTRAINT ", "PRIMARY KEY", "UNIQUE", "FOREIGN KEY", "CHECK")
        ):
            constraints.append(text)
        else:
            columns.append(text)
    return name, tuple(columns), tuple(sorted(constraints))


def _ddl_mismatches(
    before: dict[str, str], after: dict[str, str]
) -> list[str]:
    lines: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            lines.append(f"{key}\n  before: {before.get(key)!r}\n  after:  {after.get(key)!r}")
    return lines


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
def test_p3_1c_bank_item_lifecycle_up_down_up(tmp_path) -> None:
    """0017：problem_bank 加 status/updated_at；旧行回填 active，软作废枚举可逆。"""

    db_path = tmp_path / "bank-lifecycle.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "0016_bank_drafts")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO problem_bank (external_id, subject, problem_text,"
                    " answer, verify, created_at)"
                    " VALUES ('legacy-1', '数学', '1+1=?', '2', '1+1',"
                    " CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns("problem_bank")
            }
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("problem_bank")
            }
            legacy = connection.execute(
                text(
                    "SELECT status, updated_at FROM problem_bank"
                    " WHERE external_id = 'legacy-1'"
                )
            ).one()
        assert columns["status"] is False
        assert columns["updated_at"] is True
        assert "ck_problem_bank_status" in checks
        assert tuple(legacy) == ("active", None)

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE problem_bank SET status = 'voided' WHERE external_id = 'legacy-1'")
            )
            assert (
                connection.scalar(
                    text(
                        "SELECT status FROM problem_bank WHERE external_id = 'legacy-1'"
                    )
                )
                == "voided"
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text("UPDATE problem_bank SET status = 'deleted' WHERE external_id = 'legacy-1'")
                )
    finally:
        engine.dispose()

    command.downgrade(config, "0016_bank_drafts")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"] for column in inspector.get_columns("problem_bank")
            }
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("problem_bank")
            }
            remaining = connection.execute(
                text(
                    "SELECT subject, problem_text, answer FROM problem_bank"
                    " WHERE external_id = 'legacy-1'"
                )
            ).one()
        assert {"status", "updated_at"}.isdisjoint(columns)
        assert "ck_problem_bank_status" not in checks
        assert tuple(remaining) == ("数学", "1+1=?", "2")
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"] for column in inspect(connection).get_columns("problem_bank")
            }
            status = connection.scalar(
                text(
                    "SELECT status FROM problem_bank WHERE external_id = 'legacy-1'"
                )
            )
        assert {"status", "updated_at"} <= columns
        assert status == "active"
    finally:
        engine.dispose()


@pytest.mark.integration
def test_p3_2d_practice_dedup_up_down_up(tmp_path) -> None:
    """0018：practice_records 加 topic_id/seed/dedup_key + 部分唯一索引；旧行 NULL 可读。"""

    db_path = tmp_path / "practice-dedup.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "0017_bank_item_lifecycle")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO practice_records (kind, problem_text, created_at)"
                    " VALUES ('variant', '旧加练题', CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns("practice_records")
            }
            indexes = {
                index["name"]: index
                for index in inspector.get_indexes("practice_records")
            }
            legacy = connection.execute(
                text(
                    "SELECT topic_id, seed, dedup_key FROM practice_records"
                    " WHERE problem_text = '旧加练题'"
                )
            ).one()
        assert columns["topic_id"] is True
        assert columns["seed"] is True
        assert columns["dedup_key"] is True
        assert bool(indexes["uq_practice_records_dedup_key"]["unique"])
        assert tuple(legacy) == (None, None, None)

        with engine.begin() as connection:
            # 多 NULL 不冲突（历史行/通用记录）
            connection.execute(
                text(
                    "INSERT INTO practice_records (kind, problem_text, created_at)"
                    " VALUES ('extra', '无分组记录', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO practice_records"
                    " (kind, problem_text, topic_id, seed, dedup_key, created_at)"
                    " VALUES ('variant', '题A', 'cnm_001', 7,"
                    " 'variant:cnm_001:7:q1', CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError,
                match="practice_records.dedup_key",
            ):
                connection.execute(
                    text(
                        "INSERT INTO practice_records"
                        " (kind, problem_text, topic_id, seed, dedup_key, created_at)"
                        " VALUES ('variant', '题A重复', 'cnm_001', 7,"
                        " 'variant:cnm_001:7:q1', CURRENT_TIMESTAMP)"
                    )
                )
            # 不同 seed 同题 → 不同 dedup_key，各自一行
            connection.execute(
                text(
                    "INSERT INTO practice_records"
                    " (kind, problem_text, topic_id, seed, dedup_key, created_at)"
                    " VALUES ('variant', '题A', 'cnm_001', 8,"
                    " 'variant:cnm_001:8:q1', CURRENT_TIMESTAMP)"
                )
            )
            assert (
                connection.scalar(text("SELECT COUNT(*) FROM practice_records")) == 4
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0017_bank_item_lifecycle")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"] for column in inspector.get_columns("practice_records")
            }
            indexes = {
                index["name"] for index in inspector.get_indexes("practice_records")
            }
            remaining = connection.scalar(
                text("SELECT COUNT(*) FROM practice_records")
            )
        assert {"topic_id", "seed", "dedup_key"}.isdisjoint(columns)
        assert "uq_practice_records_dedup_key" not in indexes
        assert remaining == 4
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("practice_records")
            }
            dedup_values = set(
                connection.execute(
                    text("SELECT dedup_key FROM practice_records")
                ).scalars()
            )
        assert {"topic_id", "seed", "dedup_key"} <= columns
        assert dedup_values == {None}
    finally:
        engine.dispose()


@pytest.mark.integration
def test_p5_6_drops_orphan_photo_tables_up_down_up(tmp_path) -> None:
    """0019：三张视觉栈孤儿表一并 DROP；down 重建结构（数据不回填），up/down/up 可重入。"""

    db_path = tmp_path / "drop-photo-tables.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "0018_practice_dedup")
    assert {
        "photo_captures",
        "photo_capture_items",
        "problem_extractions",
    } <= _tables(db_path)

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO photo_captures (sha256, stored_path, created_at)"
                    " VALUES ('sha-1', 'uploads/a.jpg', CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO photo_capture_items"
                    " (photo_capture_id, seq, stored_path, bbox_json, created_at)"
                    " VALUES (1, 1, 'uploads/a-1.jpg', '[0,0,1,1]',"
                    " CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO problem_extractions"
                    " (photo_capture_id, photo_capture_item_id, seq, source_kind,"
                    " image_path, problem_text, gate_status, review_reasons_json,"
                    " figure_keywords_json, prompt_id, prompt_version, provider,"
                    " model, created_at)"
                    " VALUES (1, 1, 1, 'slice', 'uploads/a-1.jpg', '旧提取题',"
                    " 'ready_for_grading', '[]', '[]', 'p1', 1, 'mock', 'm1',"
                    " CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    tables = _tables(db_path)
    assert {
        "photo_captures",
        "photo_capture_items",
        "problem_extractions",
    }.isdisjoint(tables)
    assert len(tables - {"alembic_version"}) == 22

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            violations = connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert violations == []
    finally:
        engine.dispose()

    command.downgrade(config, "0018_practice_dedup")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            assert {
                "photo_captures",
                "photo_capture_items",
                "problem_extractions",
            } <= set(inspector.get_table_names())
            capture_columns = {
                column["name"] for column in inspector.get_columns("photo_captures")
            }
            item_columns = {
                column["name"]
                for column in inspector.get_columns("photo_capture_items")
            }
            extraction_columns = {
                column["name"]
                for column in inspector.get_columns("problem_extractions")
            }
            capture_indexes = {
                index["name"] for index in inspector.get_indexes("photo_captures")
            }
            item_indexes = {
                index["name"]
                for index in inspector.get_indexes("photo_capture_items")
            }
            extraction_indexes = {
                index["name"]
                for index in inspector.get_indexes("problem_extractions")
            }
            capture_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("photo_captures")
            }
            item_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "photo_capture_items"
                )
            }
            extraction_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "problem_extractions"
                )
            }
            item_fks = inspector.get_foreign_keys("photo_capture_items")
            extraction_fks = {
                fk["name"]: fk
                for fk in inspector.get_foreign_keys("problem_extractions")
            }
            capture_count = connection.scalar(
                text("SELECT COUNT(*) FROM photo_captures")
            )
            item_count = connection.scalar(
                text("SELECT COUNT(*) FROM photo_capture_items")
            )
            extraction_count = connection.scalar(
                text("SELECT COUNT(*) FROM problem_extractions")
            )
        assert capture_columns == {
            "id",
            "sha256",
            "stored_path",
            "original_name",
            "source",
            "status",
            "created_at",
        }
        assert item_columns == {
            "id",
            "photo_capture_id",
            "seq",
            "stored_path",
            "bbox_json",
            "anchor_label",
            "status",
            "created_at",
        }
        assert extraction_columns == {
            "id",
            "photo_capture_id",
            "photo_capture_item_id",
            "seq",
            "source_kind",
            "image_path",
            "problem_text",
            "student_answer",
            "confidence",
            "problem_complete",
            "gate_status",
            "review_reasons_json",
            "figure_keywords_json",
            "prompt_id",
            "prompt_version",
            "provider",
            "model",
            "created_at",
        }
        assert "ix_photo_captures_status" in capture_indexes
        assert "ix_photo_capture_items_capture_id" in item_indexes
        assert {
            "ix_problem_extractions_capture_id",
            "ix_problem_extractions_item_id",
        } <= extraction_indexes
        assert "uq_photo_captures_sha256" in capture_uniques
        assert "uq_photo_capture_items_capture_seq" in item_uniques
        assert "uq_problem_extractions_capture_source_seq" in extraction_uniques
        assert item_fks[0]["referred_table"] == "photo_captures"
        assert item_fks[0]["name"] == "fk_photo_capture_items_capture_id"
        assert set(extraction_fks) == {
            "fk_problem_extractions_capture_id",
            "fk_problem_extractions_item_id",
        }
        assert (
            extraction_fks["fk_problem_extractions_capture_id"]["referred_table"]
            == "photo_captures"
        )
        assert (
            extraction_fks["fk_problem_extractions_item_id"]["referred_table"]
            == "photo_capture_items"
        )
        for fk in extraction_fks.values():
            assert fk["options"].get("ondelete") == "CASCADE"
        # 只重建结构，不承诺找回历史数据
        assert (capture_count, item_count, extraction_count) == (0, 0, 0)
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert {
        "photo_captures",
        "photo_capture_items",
        "problem_extractions",
    }.isdisjoint(_tables(db_path))


@pytest.mark.integration
def test_p3_2d_reversible_ddl_matches_pre_migration(tmp_path) -> None:
    """0018 down 必须把 practice_records 恢复到 0017 的完整 DDL。

    SQLite `batch_alter_table(recreate="always")` 会重写表名引号、DEFAULT 括号
    和约束子句顺序；这三处是呈现差异，先规范化再逐字比对其余全部 token。
    索引定义不做任何规范化，直接原文比较。
    """

    db_path = tmp_path / "practice-dedup-ddl.db"
    config = _alembic_config(db_path)
    involved = {"practice_records"}

    command.upgrade(config, "0017_bank_item_lifecycle")
    before = _master_ddl(db_path, involved)
    assert before, "0017 应存在 practice_records 及其索引"

    command.upgrade(config, "head")
    command.downgrade(config, "0017_bank_item_lifecycle")
    after = _master_ddl(db_path, involved)

    assert before.keys() == after.keys()
    for key in before:
        if key.startswith("table:"):
            assert _canonical_table_ddl(before[key]) == _canonical_table_ddl(
                after[key]
            ), key
        else:
            assert before[key] == after[key], key


@pytest.mark.integration
def test_p5_6_reversible_ddl_is_byte_identical(tmp_path) -> None:
    """0019 down 重建的三张表与 7 个 DDL 对象必须与 0018 原文逐字一致。

    0019 用 `op.create_table` 显式重建，不经过 batch 反射，因此这里不放过
    任何格式化差异：列类型、NOT NULL、server_default、UNIQUE/FK 约束名、
    ON DELETE 与索引定义都要求两侧 `sqlite_master.sql` 完全相同。
    """

    db_path = tmp_path / "drop-photo-ddl.db"
    config = _alembic_config(db_path)
    involved = {
        "photo_captures",
        "photo_capture_items",
        "problem_extractions",
    }

    command.upgrade(config, "0018_practice_dedup")
    before = _master_ddl(db_path, involved)
    assert set(before) == {
        "table:photo_captures",
        "index:ix_photo_captures_status",
        "table:photo_capture_items",
        "index:ix_photo_capture_items_capture_id",
        "table:problem_extractions",
        "index:ix_problem_extractions_capture_id",
        "index:ix_problem_extractions_item_id",
    }, "0019 前置应看到三张表与四个索引共 7 个 DDL 对象"

    command.upgrade(config, "head")
    command.downgrade(config, "0018_practice_dedup")
    after = _master_ddl(db_path, involved)

    mismatches = _ddl_mismatches(before, after)
    assert not mismatches, "0019 降级后的 DDL 与升级前不一致：\n" + "\n".join(
        mismatches
    )


@pytest.mark.integration
def test_p3_3a_recitation_tables_up_down_up(tmp_path) -> None:
    """0020：两张背诵表可逆；CHECK/UNIQUE/FK 由库层兜底，删条目级联清自评。"""

    db_path = tmp_path / "recitation.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "0019_drop_orphan_photo_tables")
    assert {"recitation_items", "recitation_reviews"}.isdisjoint(_tables(db_path))

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            item_columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns("recitation_items")
            }
            review_columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns("recitation_reviews")
            }
            item_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("recitation_items")
            }
            review_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(
                    "recitation_reviews"
                )
            }
            item_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("recitation_items")
            }
            review_uniques = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    "recitation_reviews"
                )
            }
            review_fks = {
                fk["name"]: fk
                for fk in inspector.get_foreign_keys("recitation_reviews")
            }
        assert item_columns == {
            "id": False,
            "subject": False,
            "prompt": False,
            "answer": True,
            "unit": True,
            "status": False,
            "created_by": False,
            "created_at": False,
        }
        assert review_columns == {
            "id": False,
            "item_id": False,
            "verdict": False,
            "rung": False,
            "reviewed_on": False,
            "scheduled_next": True,
            "event_id": False,
            "created_at": False,
        }
        assert "ck_recitation_items_status" in item_checks
        assert "ck_recitation_reviews_verdict" in review_checks
        assert "uq_recitation_items_subject_prompt" in item_uniques
        assert "uq_recitation_reviews_item_reviewed_on" in review_uniques
        assert set(review_fks) == {
            "fk_recitation_reviews_item_id",
            "fk_recitation_reviews_event_id",
        }
        assert (
            review_fks["fk_recitation_reviews_item_id"]["referred_table"]
            == "recitation_items"
        )
        assert (
            review_fks["fk_recitation_reviews_item_id"]["options"].get("ondelete")
            == "CASCADE"
        )
        assert (
            review_fks["fk_recitation_reviews_event_id"]["referred_table"]
            == "learning_events"
        )
        assert (
            review_fks["fk_recitation_reviews_event_id"]["options"].get("ondelete")
            == "RESTRICT"
        )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO learning_events (id, type, actor, idempotency_key)"
                    " VALUES (1, 'recitation_reviewed', 'student',"
                    " 'recitation:1:2026-11-03')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO recitation_items"
                    " (subject, prompt, answer, unit, created_by, created_at)"
                    " VALUES ('英语', 'abandon', '放弃', 'Unit 1', 'parent',"
                    " CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO recitation_reviews"
                    " (item_id, verdict, rung, reviewed_on, scheduled_next,"
                    " event_id, created_at)"
                    " VALUES (1, 'remembered', 0, '2026-11-03', '2026-11-04', 1,"
                    " CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError, match="recitation_items.subject"
            ):
                connection.execute(
                    text(
                        "INSERT INTO recitation_items"
                        " (subject, prompt, created_by, created_at)"
                        " VALUES ('英语', 'abandon', 'parent', CURRENT_TIMESTAMP)"
                    )
                )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text(
                        "INSERT INTO recitation_items"
                        " (subject, prompt, status, created_by, created_at)"
                        " VALUES ('英语', 'retire-me', 'deleted', 'parent',"
                        " CURRENT_TIMESTAMP)"
                    )
                )
            with pytest.raises(
                sqlalchemy.exc.IntegrityError, match="recitation_reviews.item_id"
            ):
                connection.execute(
                    text(
                        "INSERT INTO recitation_reviews"
                        " (item_id, verdict, rung, reviewed_on, event_id, created_at)"
                        " VALUES (1, 'forgot', 0, '2026-11-03', 1,"
                        " CURRENT_TIMESTAMP)"
                    )
                )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text(
                        "INSERT INTO recitation_reviews"
                        " (item_id, verdict, rung, reviewed_on, event_id, created_at)"
                        " VALUES (1, 'maybe', 0, '2026-11-04', 1,"
                        " CURRENT_TIMESTAMP)"
                    )
                )
            assert (
                connection.scalar(text("SELECT COUNT(*) FROM recitation_reviews"))
                == 1
            )
    finally:
        engine.dispose()

    # 默认连接不开 foreign_keys，单独开 PRAGMA 验证 ON DELETE CASCADE
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM recitation_items WHERE id = 1")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM recitation_reviews").fetchone() == (
            0,
        )
    finally:
        conn.close()

    command.downgrade(config, "0019_drop_orphan_photo_tables")
    assert {"recitation_items", "recitation_reviews"}.isdisjoint(_tables(db_path))

    command.upgrade(config, "head")
    assert {"recitation_items", "recitation_reviews"} <= _tables(db_path)


@pytest.mark.integration
def test_p3_3a_recitation_reversible_ddl_is_byte_identical(tmp_path) -> None:
    """0020 用 op.create_table 显式建表：回退再升级的 DDL 与首次升级、ORM 模型逐字一致。"""

    db_path = tmp_path / "recitation-ddl.db"
    config = _alembic_config(db_path)
    involved = {"recitation_items", "recitation_reviews"}

    command.upgrade(config, "0019_drop_orphan_photo_tables")
    assert _master_ddl(db_path, involved) == {}

    command.upgrade(config, "head")
    before = _master_ddl(db_path, involved)
    assert set(before) == {
        "table:recitation_items",
        "table:recitation_reviews",
    }

    model_engine = create_engine("sqlite://")
    try:
        for model in (RecitationItem, RecitationReview):
            compiled = str(CreateTable(model.__table__).compile(model_engine)).strip()
            assert before[f"table:{model.__tablename__}"] == compiled
    finally:
        model_engine.dispose()

    command.downgrade(config, "0019_drop_orphan_photo_tables")
    assert _master_ddl(db_path, involved) == {}

    command.upgrade(config, "head")
    after = _master_ddl(db_path, involved)

    mismatches = _ddl_mismatches(before, after)
    assert not mismatches, "0020 回退再升级后的 DDL 与首次升级不一致：\n" + "\n".join(
        mismatches
    )


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


@pytest.mark.integration
def test_p2_2b_pomodoro_sessions_reversible_ddl_is_byte_identical(tmp_path) -> None:
    """0021 用 op.create_table 显式建表：回退再升级的 DDL 与首次升级、ORM 逐字一致。"""

    db_path = tmp_path / "pomodoro-sessions-ddl.db"
    config = _alembic_config(db_path)
    involved = {"pomodoro_sessions"}

    command.upgrade(config, "0020_recitation")
    assert _master_ddl(db_path, involved) == {}

    command.upgrade(config, "head")
    before = _master_ddl(db_path, involved)
    assert set(before) == {
        "table:pomodoro_sessions",
        "index:ix_pomodoro_sessions_status",
    }

    model_engine = create_engine("sqlite://")
    try:
        table = PomodoroSession.__table__
        compiled = str(CreateTable(table).compile(model_engine)).strip()
        assert before["table:pomodoro_sessions"] == compiled
        index = next(iter(table.indexes))
        assert before[f"index:{index.name}"] == str(
            CreateIndex(index).compile(model_engine)
        ).strip()
    finally:
        model_engine.dispose()

    command.downgrade(config, "0020_recitation")
    assert _master_ddl(db_path, involved) == {}

    command.upgrade(config, "head")
    after = _master_ddl(db_path, involved)

    mismatches = _ddl_mismatches(before, after)
    assert not mismatches, "0021 回退再升级后的 DDL 与首次升级不一致：\n" + "\n".join(
        mismatches
    )


@pytest.mark.integration
def test_p2_2b_pomodoro_sessions_status_and_duration_guards(tmp_path) -> None:
    """三态 CHECK + 计划时长 5–120 CHECK + status 默认 active；回退只删本表。"""

    db_path = tmp_path / "pomodoro-sessions-guard.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO pomodoro_sessions"
                    " (started_at, planned_minutes, actor)"
                    " VALUES (CURRENT_TIMESTAMP, 25, 'student')"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT status FROM pomodoro_sessions WHERE id = 1")
                )
                == "active"
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                connection.execute(
                    text(
                        "INSERT INTO pomodoro_sessions"
                        " (started_at, planned_minutes, actor, status)"
                        " VALUES (CURRENT_TIMESTAMP, 25, 'student', 'paused')"
                    )
                )
            for minutes in (4, 121):
                with pytest.raises(sqlalchemy.exc.IntegrityError, match="CHECK"):
                    connection.execute(
                        text(
                            "INSERT INTO pomodoro_sessions"
                            " (started_at, planned_minutes, actor)"
                            f" VALUES (CURRENT_TIMESTAMP, {minutes}, 'student')"
                        )
                    )
            assert (
                connection.scalar(text("SELECT COUNT(*) FROM pomodoro_sessions"))
                == 1
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0020_recitation")
    assert "pomodoro_sessions" not in _tables(db_path)
    assert _master_ddl(db_path, {"pomodoro_sessions"}) == {}

    command.upgrade(config, "head")
    assert "pomodoro_sessions" in _tables(db_path)


@pytest.mark.integration
def test_p1_17_correction_notes_reversible_ddl_is_byte_identical(tmp_path) -> None:
    """0022 原生 ADD/DROP COLUMN：up/down/up 后 mistake_versions 的 DDL（含 append-only
    触发器）与首次升级逐字一致。不与 ORM 比列序——DB 列序 = 0002 建表 + 0008/0022 末尾追加。"""

    db_path = tmp_path / "correction-notes-ddl.db"
    config = _alembic_config(db_path)
    involved = {"mistake_versions"}

    command.upgrade(config, "0021_pomodoro_sessions")
    pre = _master_ddl(db_path, involved)
    assert "correction_notes" not in pre["table:mistake_versions"]

    command.upgrade(config, "head")
    before = _master_ddl(db_path, involved)
    assert "correction_notes" in before["table:mistake_versions"]
    # append-only 触发器随原生 ADD COLUMN 原样保留（batch 重建会连带丢掉，这里钉死）
    assert "trigger:mistake_versions_UPDATE_guard" in before
    assert "trigger:mistake_versions_DELETE_guard" in before

    command.downgrade(config, "0021_pomodoro_sessions")
    downgraded = _master_ddl(db_path, involved)
    assert "correction_notes" not in downgraded["table:mistake_versions"]
    assert "trigger:mistake_versions_UPDATE_guard" in downgraded
    assert "trigger:mistake_versions_DELETE_guard" in downgraded

    command.upgrade(config, "head")
    after = _master_ddl(db_path, involved)

    mismatches = _ddl_mismatches(before, after)
    assert not mismatches, "0022 回退再升级后的 DDL 与首次升级不一致：\n" + "\n".join(
        mismatches
    )


@pytest.mark.integration
def test_p1_17_correction_notes_nullable_and_append_only_guard(tmp_path) -> None:
    """correction_notes 可空、库层无 CHECK；UPDATE 该列仍被 append-only 触发器拒绝。"""

    db_path = tmp_path / "correction-notes-guard.db"
    config = _alembic_config(db_path)
    command.upgrade(config, "head")

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
            assert (
                connection.scalar(
                    text("SELECT correction_notes FROM mistake_versions WHERE id = 1")
                )
                is None
            )
            connection.execute(
                text(
                    "INSERT INTO mistake_versions"
                    " (mistake_id, version, status, created_at, correction_notes)"
                    " VALUES (1, 2, 'active', CURRENT_TIMESTAMP, '移项要变号')"
                )
            )
            assert (
                connection.scalar(
                    text("SELECT correction_notes FROM mistake_versions WHERE id = 2")
                )
                == "移项要变号"
            )
            with pytest.raises(sqlalchemy.exc.IntegrityError, match="append-only"):
                connection.execute(
                    text(
                        "UPDATE mistake_versions SET correction_notes = 'x' WHERE id = 2"
                    )
                )
    finally:
        engine.dispose()

    command.downgrade(config, "0021_pomodoro_sessions")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                c["name"] for c in inspect(connection).get_columns("mistake_versions")
            }
        assert "correction_notes" not in columns
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            columns = {
                c["name"] for c in inspect(connection).get_columns("mistake_versions")
            }
        assert "correction_notes" in columns
    finally:
        engine.dispose()
