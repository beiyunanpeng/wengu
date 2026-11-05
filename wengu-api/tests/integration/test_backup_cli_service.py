"""P4-1c 命令行备份：产物与家长区「备份」页同一套（list/resolve/sha256、轮转共用）。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from app.core.config import Settings
from app.services.backup import KEEP_BACKUPS, list_backups, resolve_backup
from scripts.backup_cli import main


def _make_data_dir(tmp_path: Path, *, mistakes: int = 0) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "backups").mkdir(parents=True)
    conn = sqlite3.connect(data_dir / "wengu.db")
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(
            "INSERT INTO alembic_version (version_num) VALUES ('0020_recitation')"
        )
        conn.execute("CREATE TABLE mistakes (id INTEGER PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO mistakes (id) VALUES (?)", [(index,) for index in range(mistakes)]
        )
        conn.execute("CREATE TABLE learning_events (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    return data_dir.resolve()


def _settings(data_dir: Path) -> Settings:
    return Settings(data_dir=data_dir, db_path=data_dir / "wengu.db")


def test_cli_backup_is_recognized_by_backup_service(
    tmp_path: Path, capsys
) -> None:
    data_dir = _make_data_dir(tmp_path, mistakes=3)

    assert main(["--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    settings = _settings(data_dir)

    items = list_backups(settings)
    assert len(items) == 1
    item = items[0]
    assert item.filename in out
    assert item.sha256 in out

    path = resolve_backup(settings, item.filename)
    assert path == (data_dir / "backups" / item.filename).resolve()
    assert item.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()

    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["alembic_version"] == "0020_recitation"
    assert manifest["counts"]["mistakes"] == 3


def test_cli_and_ui_share_one_rotation(tmp_path: Path) -> None:
    data_dir = _make_data_dir(tmp_path)
    settings = _settings(data_dir)

    for _ in range(KEEP_BACKUPS + 1):
        assert main(["--data-dir", str(data_dir)]) == 0

    items = list_backups(settings)
    assert len(items) == KEEP_BACKUPS, "CLI 必须与 UI 共用 KEEP_BACKUPS 轮转"
