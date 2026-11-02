"""P5-2 家长一键备份：一致性快照、内容完整、只读、安全、轮转。

DoD：
1. 快照可被 sqlite3 打开、`PRAGMA integrity_check` = ok，含导出前已提交数据；
   并发写入期间导出仍保持一致性。
2. zip 含 wengu.db + manifest.json（sha256 与实物一致）+ uploads / seeds_local /
   inbox 未处理文件；`.processed/` 不进包。
3. 未解锁 export/list/download 全 403；download 拒绝 `../` 与绝对路径。
4. 导出前后业务库各表行数与内容零变化；轮转只删 backups/ 下超期 zip。

恢复演练（DoD 5）由 `scripts/restore.ps1` + `docs/deploy/backup-restore.md` 承担，
脚本只在停机后整库替换，不提供在线热恢复。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import KnowledgeSeed, LearningEvent, PracticeRecord
from app.services.backup import (
    KEEP_BACKUPS,
    BackupNameError,
    BackupNotFound,
    create_backup,
    list_backups,
    resolve_backup,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "wengu.db",
        seeds_dir=tmp_path / "seeds",
    )


def _migrated(data_dir: Path) -> async_sessionmaker:
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "wengu.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(factory: async_sessionmaker, events: int = 2) -> None:
    now = datetime(2026, 10, 31, 12, 0, 0)
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id="cnm_001",
                subject="数学",
                name="有理数",
                domain="数与代数",
                grade="七年级",
                semester="上册",
                chapter="有理数",
                type="topic",
                unaudited=True,
                blind_verified=True,
            )
        )
        for index in range(events):
            session.add(
                LearningEvent(
                    type="confirm",
                    actor="parent",
                    mistake_id=None,
                    payload='{"seed": true}',
                    occurred_at=now,
                    idempotency_key=f"seed-event-{index}",
                )
            )
        session.add(
            PracticeRecord(
                kind="extra",
                problem_text="1+1=?",
                student_answer="2",
                is_correct=True,
                created_at=now,
            )
        )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _seed_and_dispose(data_dir: Path, events: int = 2) -> None:
    factory = _migrated(data_dir)
    engine = factory.kw["bind"]
    try:
        await _seed(factory, events)
    finally:
        await engine.dispose()


def _prepare(tmp_path: Path, events: int = 2) -> Settings:
    settings = _settings(tmp_path)
    asyncio.run(_seed_and_dispose(settings.data_dir, events))
    return settings


def _table_snapshot(db_path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in tables
        }
    finally:
        conn.close()


def _scalar(db_path: Path, sql: str) -> object:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


async def _unlock(client: AsyncClient) -> None:
    status = await client.get("/api/session/status")
    if status.json()["pin_set"]:
        response = await client.post("/api/session/unlock", json={"pin": PIN})
    else:
        response = await client.post("/api/session/pin/set", json={"pin": PIN})
    assert response.status_code == 200, response.text


@asynccontextmanager
async def _client(
    factory: async_sessionmaker, settings: Settings, *, unlock: bool = True
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if unlock:
            await _unlock(client)
        yield client


def _extract_snapshot(archive: Path, target: Path) -> Path:
    with zipfile.ZipFile(archive) as zf:
        target.write_bytes(zf.read("wengu.db"))
    return target


def test_create_backup_is_read_only_and_complete(tmp_path: Path) -> None:
    settings = _prepare(tmp_path)
    data_dir = Path(settings.data_dir)
    _write(data_dir / "uploads" / "page1.png", "fake-image-bytes")
    _write(data_dir / "uploads" / "nested" / "page2.png", "more-bytes")
    _write(data_dir / "seeds_local" / "topics_语文.json", "[]")
    _write(data_dir / "seeds_local" / "_id_counters.json", '{"语文": 3}')
    _write(data_dir / "inbox" / "pending.json", '{"items": []}')
    _write(data_dir / "inbox" / ".processed" / "old.json", "{}")

    before = _table_snapshot(settings.db_path)
    result = create_backup(settings)
    after = _table_snapshot(settings.db_path)

    assert before == after, "导出不得修改业务库任何表"
    assert result.path.parent == data_dir / "backups"
    assert result.path.name.startswith("wengu-backup-")
    assert result.size_bytes == result.path.stat().st_size
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert not any((data_dir / "backups_tmp").iterdir()), "临时目录应清理"

    with zipfile.ZipFile(result.path) as zf:
        names = set(zf.namelist())
        assert "wengu.db" in names
        assert "manifest.json" in names
        assert "uploads/page1.png" in names
        assert "uploads/nested/page2.png" in names
        assert "seeds_local/topics_语文.json" in names
        assert "seeds_local/_id_counters.json" in names
        assert "inbox/pending.json" in names
        assert "inbox/.processed/old.json" not in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["version"] == 1
        assert manifest["alembic_version"]
        assert manifest["counts"]["learning_events"] == 2
        assert manifest["counts"]["knowledge_seed"] == 1
        assert manifest["counts"]["practice_records"] == 1
        for item in manifest["files"]:
            payload = zf.read(item["path"])
            assert len(payload) == item["size_bytes"]
            assert hashlib.sha256(payload).hexdigest() == item["sha256"]

    snapshot = _extract_snapshot(result.path, tmp_path / "snapshot.db")
    conn = sqlite3.connect(str(snapshot))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM learning_events WHERE idempotency_key LIKE 'seed-event-%'"
            ).fetchone()[0]
            == 2
        )
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == (
            manifest["alembic_version"]
        )
    finally:
        conn.close()


def test_snapshot_stays_consistent_under_concurrent_writes(tmp_path: Path) -> None:
    settings = _prepare(tmp_path, events=1)

    stop = threading.Event()
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            conn = sqlite3.connect(str(settings.db_path), timeout=30)
            try:
                index = 0
                while not stop.is_set():
                    conn.execute(
                        "INSERT INTO learning_events "
                        "(type, actor, mistake_id, payload, occurred_at, idempotency_key) "
                        "VALUES ('confirm', 'parent', NULL, '{}', ?, ?)",
                        (
                            "2026-10-31 12:00:00.000000",
                            f"concurrent-{index}",
                        ),
                    )
                    conn.commit()
                    index += 1
                    time.sleep(0.01)
            finally:
                conn.close()
        except BaseException as exc:  # pragma: no cover - 失败时直接在断言里暴露
            errors.append(exc)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        result = create_backup(settings)
    finally:
        stop.set()
        thread.join(timeout=10)

    assert errors == []
    snapshot = _extract_snapshot(result.path, tmp_path / "concurrent.db")
    conn = sqlite3.connect(str(snapshot))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        keys = {
            row[0]
            for row in conn.execute("SELECT idempotency_key FROM learning_events")
        }
        assert "seed-event-0" in keys, "导出前已提交的数据必须在快照里"
        assert result.manifest["counts"]["learning_events"] == len(keys)
    finally:
        conn.close()


def test_rotation_keeps_ten_newest_and_only_backup_zips(tmp_path: Path) -> None:
    settings = _prepare(tmp_path)
    backups = Path(settings.data_dir) / "backups"
    backups.mkdir(parents=True, exist_ok=True)

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    dummy: list[Path] = []
    for index in range(KEEP_BACKUPS + 2):
        stamp = base + timedelta(seconds=index)
        name = f"wengu-backup-{stamp.strftime('%Y%m%dT%H%M%S%fZ')}.zip"
        path = backups / name
        path.write_bytes(b"dummy")
        os.utime(path, (stamp.timestamp(), stamp.timestamp()))
        dummy.append(path)
    keep_me = backups / "notes.txt"
    keep_me.write_text("not a backup", encoding="utf-8")

    result = create_backup(settings)

    remaining = sorted(path.name for path in backups.iterdir())
    valid = [name for name in remaining if name.startswith("wengu-backup-")]
    assert len(valid) == KEEP_BACKUPS
    assert result.path.name in valid
    assert keep_me.exists()
    assert "wengu-backup-20260101T120000000000Z.zip" not in remaining
    assert "wengu-backup-20260101T120001000000Z.zip" not in remaining
    assert "wengu-backup-20260101T120002000000Z.zip" not in remaining


def test_list_and_resolve_reject_path_components(tmp_path: Path) -> None:
    settings = _prepare(tmp_path)
    result = create_backup(settings)

    items = list_backups(settings)
    assert [item.filename for item in items] == [result.path.name]
    assert items[0].sha256 == result.sha256
    assert resolve_backup(settings, result.path.name) == result.path.resolve()

    for name in (
        "../wengu.db",
        "..\\wengu.db",
        "C:\\Windows\\win.ini",
        "/etc/passwd",
        "wengu-backup-evil.zip",
        "",
    ):
        with pytest.raises(BackupNameError):
            resolve_backup(settings, name)

    with pytest.raises(BackupNotFound):
        resolve_backup(settings, "wengu-backup-20260101T120000000000Z.zip")


@pytest.mark.asyncio
async def test_backup_routes_require_parent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings.data_dir)
    await _seed(factory, events=1)
    result = create_backup(settings)

    async with _client(factory, settings, unlock=False) as client:
        assert (await client.post("/api/backup/export")).status_code == 403
        assert (await client.get("/api/backup/list")).status_code == 403
        assert (
            await client.get(f"/api/backup/download/{result.path.name}")
        ).status_code == 403


@pytest.mark.asyncio
async def test_export_list_download_and_traversal_defense(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings.data_dir)
    await _seed(factory, events=2)
    _write(Path(settings.data_dir) / "uploads" / "page1.png", "fake-image")

    async with _client(factory, settings) as client:
        before = _table_snapshot(settings.db_path)
        exported = await client.post("/api/backup/export")
        assert exported.status_code == 200, exported.text
        body = exported.json()
        assert body["filename"].startswith("wengu-backup-")
        assert body["sha256"]
        assert body["size_bytes"] > 0
        assert body["manifest"]["counts"]["learning_events"] == 2
        assert body["manifest"]["file_count"] >= 2

        listing = await client.get("/api/backup/list")
        assert listing.status_code == 200
        payload = listing.json()
        assert payload["keep"] == KEEP_BACKUPS
        assert payload["items"][0]["filename"] == body["filename"]
        assert payload["items"][0]["sha256"] == body["sha256"]

        download = await client.get(f"/api/backup/download/{body['filename']}")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        assert hashlib.sha256(download.content).hexdigest() == body["sha256"]

        for bad in (
            "../wengu.db",
            "..%5Cwengu.db",
            "C:%5CWindows%5Cwin.ini",
            "wengu-backup-evil.zip",
        ):
            response = await client.get(f"/api/backup/download/{bad}")
            assert response.status_code in (400, 404), (bad, response.status_code)

        missing = await client.get(
            "/api/backup/download/wengu-backup-20260101T120000000000Z.zip"
        )
        assert missing.status_code == 404

    after = _table_snapshot(settings.db_path)
    assert before == after, "导入/导出接口不得改动业务库"
    assert _scalar(settings.db_path, "SELECT COUNT(*) FROM learning_events") == 2
