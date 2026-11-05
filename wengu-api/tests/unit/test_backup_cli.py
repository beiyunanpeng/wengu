"""P4-1c 命令行备份：--dry-run 输出与失败退出码（临时 data_dir，不碰真实库）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.backup_cli import main


def _make_data_dir(
    tmp_path: Path, *, version: str = "0020_recitation", mistakes: int = 0
) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "backups").mkdir(parents=True)
    conn = sqlite3.connect(data_dir / "wengu.db")
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)", (version,)
        )
        conn.execute("CREATE TABLE mistakes (id INTEGER PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO mistakes (id) VALUES (?)", [(index,) for index in range(mistakes)]
        )
        conn.execute("CREATE TABLE learning_events (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    return data_dir


def test_dry_run_prints_target_meta_and_writes_nothing(
    tmp_path: Path, capsys
) -> None:
    data_dir = _make_data_dir(tmp_path, mistakes=3).resolve()
    oldest = "wengu-backup-20260101T120000000000Z.zip"
    (data_dir / "backups" / oldest).write_bytes(b"placeholder")
    before = sorted(path.name for path in (data_dir / "backups").iterdir())

    code = main(["--data-dir", str(data_dir), "--dry-run"])
    out = capsys.readouterr().out

    assert code == 0
    assert f"数据目录：{data_dir}" in out
    assert f"将备份：{data_dir / 'wengu.db'}" in out
    assert f"产物目录：{data_dir / 'backups'}" in out
    assert f"现有备份：1 份（最旧：{oldest}）" in out
    assert "alembic：0020_recitation" in out
    assert "mistakes=3" in out
    assert sorted(path.name for path in (data_dir / "backups").iterdir()) == before
    assert not (data_dir / "backups_tmp").exists(), "dry-run 不得创建临时目录"


def test_missing_database_exits_nonzero(tmp_path: Path, capsys) -> None:
    data_dir = tmp_path / "empty"

    assert main(["--data-dir", str(data_dir)]) != 0
    assert "业务库不存在" in capsys.readouterr().err

    assert main(["--data-dir", str(data_dir), "--dry-run"]) != 0
    assert "业务库不存在" in capsys.readouterr().err
    assert not (data_dir / "backups").exists()
