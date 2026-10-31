"""P5-2 家长一键备份：一致性快照 + zip 打包 + 轮转保留。

纪律（AGENTS §7 一键备份 / §9 数据与隐私）：
- 快照只用 SQLite `VACUUM INTO`（原生一致性快照，等价于拷 wal 已提交内容），
  不直接拷贝 `wengu.db-wal/-shm`；全程只读业务库，不写任何表。
- 临时快照与半成品 zip 放 `<data_dir>/backups_tmp/`，结束后清理。
- 成品落 `<data_dir>/backups/wengu-backup-<UTC 时间戳>.zip`，只保留最近 10 份。
- 日志只记文件名 / 大小 / sha256 / 计数，不记题目内容与 PII。
- 恢复不在线热替换 SQLite：走 `scripts/restore.ps1` + `docs/deploy/backup-restore.md`。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings

BACKUP_PREFIX = "wengu-backup-"
BACKUP_SUFFIX = ".zip"
KEEP_BACKUPS = 10
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
DB_NAME = "wengu.db"

BACKUP_NAME_RE = re.compile(r"^wengu-backup-\d{8}T\d{12}Z\.zip$")
CHUNK_SIZE = 1024 * 1024

# 只统计、不读取内容；表名来自本仓模型，不接受外部输入。
COUNT_TABLES = (
    "knowledge_seed",
    "mistakes",
    "learning_events",
    "review_schedules",
    "attempts",
    "practice_records",
    "problem_bank",
    "ingestion_drafts",
    "bank_drafts",
    "photo_captures",
    "photo_capture_items",
    "timetable_slots",
    "calendar_events",
)

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """备份失败（API 映射 500，细节只进日志）。"""


class BackupNameError(BackupError):
    """备份文件名非法（API 映射 400）。"""


class BackupNotFound(BackupError):
    """备份文件不存在（API 映射 404）。"""


@dataclass(frozen=True)
class BackupInfo:
    filename: str
    created_at: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class BackupResult:
    path: Path
    sha256: str
    size_bytes: int
    manifest: dict[str, Any]


def backups_dir(settings: Settings) -> Path:
    return Path(settings.data_dir) / "backups"


def backup_tmp_dir(settings: Settings) -> Path:
    return Path(settings.data_dir) / "backups_tmp"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backup_files(settings: Settings) -> list[Path]:
    root = backups_dir(settings)
    if not root.is_dir():
        return []
    return [
        path
        for path in root.iterdir()
        if path.is_file() and BACKUP_NAME_RE.fullmatch(path.name)
    ]


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    existing = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in COUNT_TABLES
        if table in existing
    }


def _snapshot_meta(path: Path) -> tuple[str | None, dict[str, int]]:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return (str(row[0]) if row else None), _table_counts(conn)
    finally:
        conn.close()


def _vacuum_into(db_path: Path, target: Path) -> None:
    """生成一致性快照。

    `mode=ro` / `PRAGMA query_only` 会让 VACUUM INTO 报只读错误，因此使用普通
    连接，但只执行 VACUUM INTO（写目标文件），不触碰业务表。
    """

    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("VACUUM INTO ?", (str(target),))
    except sqlite3.Error as exc:
        raise BackupError(f"生成一致性快照失败：{exc}") from exc
    finally:
        conn.close()


def _add_file(
    zf: zipfile.ZipFile, path: Path, arcname: str, files: list[dict[str, Any]]
) -> None:
    digest = _sha256_file(path)
    zf.write(path, arcname)
    files.append(
        {"path": arcname, "sha256": digest, "size_bytes": path.stat().st_size}
    )


def _add_tree(
    zf: zipfile.ZipFile,
    root: Path,
    arc_root: str,
    files: list[dict[str, Any]],
) -> None:
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        arcname = f"{arc_root}/{path.relative_to(root).as_posix()}"
        _add_file(zf, path, arcname, files)


def _add_inbox(
    zf: zipfile.ZipFile,
    inbox: Path,
    files: list[dict[str, Any]],
) -> None:
    """只打包未处理文件（根目录条目）；`.processed/` 是已处理归档，不进备份。"""

    if not inbox.is_dir():
        return
    for path in sorted(inbox.iterdir()):
        if path.is_symlink() or not path.is_file() or path.name.startswith("."):
            continue
        _add_file(zf, path, f"inbox/{path.name}", files)


def create_backup(settings: Settings) -> BackupResult:
    db_path = Path(settings.db_path) if settings.db_path else None
    if db_path is None or not db_path.is_file():
        raise BackupError("业务库不存在，无法备份")

    out_dir = backups_dir(settings)
    tmp_root = backup_tmp_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_root.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="snapshot-", dir=tmp_root))
    try:
        snapshot = work / DB_NAME
        _vacuum_into(db_path, snapshot)
        alembic_version, counts = _snapshot_meta(snapshot)

        now = datetime.now(UTC)
        created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        filename = f"{BACKUP_PREFIX}{now.strftime('%Y%m%dT%H%M%S%fZ')}{BACKUP_SUFFIX}"
        tmp_zip = work / filename

        files: list[dict[str, Any]] = []
        data_dir = Path(settings.data_dir)
        with zipfile.ZipFile(
            tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as zf:
            _add_file(zf, snapshot, DB_NAME, files)
            _add_tree(zf, data_dir / "uploads", "uploads", files)
            _add_tree(zf, data_dir / "seeds_local", "seeds_local", files)
            _add_inbox(zf, Path(settings.inbox_path), files)
            manifest: dict[str, Any] = {
                "version": MANIFEST_VERSION,
                "created_at": created_at,
                "alembic_version": alembic_version,
                "counts": counts,
                "files": files,
            }
            zf.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )

        target = out_dir / filename
        os.replace(tmp_zip, target)
        size_bytes = target.stat().st_size
        digest = _sha256_file(target)
        logger.info(
            "备份完成：%s（%d 字节，sha256=%s，错题=%d，事件=%d）",
            target.name,
            size_bytes,
            digest,
            counts.get("mistakes", 0),
            counts.get("learning_events", 0),
        )
        rotate_backups(settings)
        return BackupResult(
            path=target,
            sha256=digest,
            size_bytes=size_bytes,
            manifest=manifest,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def rotate_backups(settings: Settings, keep: int = KEEP_BACKUPS) -> list[str]:
    """只保留最近 `keep` 份；只删 backups/ 下匹配命名的 zip，日志只记文件名。"""

    items = sorted(
        _backup_files(settings),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    removed: list[str] = []
    for path in items[keep:]:
        try:
            path.unlink()
        except OSError:
            logger.warning("备份轮转：删除失败 %s", path.name)
            continue
        removed.append(path.name)
        logger.info("备份轮转：删除旧备份 %s（保留最近 %d 份）", path.name, keep)
    return removed


def list_backups(settings: Settings) -> list[BackupInfo]:
    items = sorted(
        _backup_files(settings),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    return [
        BackupInfo(
            filename=path.name,
            created_at=_iso(path.stat().st_mtime),
            size_bytes=path.stat().st_size,
            sha256=_sha256_file(path),
        )
        for path in items
    ]


def resolve_backup(settings: Settings, name: str) -> Path:
    """解析下载目标：只允许 backups/ 下的规范文件名，任何路径成分一律拒绝。"""

    if not name or len(name) > 128:
        raise BackupNameError("备份文件名非法")
    if any(ch in name for ch in ("/", "\\", ":", "\x00")) or ".." in name:
        raise BackupNameError("备份文件名非法")
    if Path(name).name != name or not BACKUP_NAME_RE.fullmatch(name):
        raise BackupNameError("备份文件名非法")

    root = backups_dir(settings)
    path = root / name
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BackupNotFound("备份文件不存在") from exc
    if resolved.parent != root.resolve() or not resolved.is_file():
        raise BackupNotFound("备份文件不存在")
    return resolved
