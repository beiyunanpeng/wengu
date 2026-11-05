"""P4-1c 命令行备份入口（服务未起也能导出）。

只调用 `app.services.backup.create_backup`：产物与家长区「备份」页完全同一套——
同落 `<data_dir>/backups/wengu-backup-<UTC时间戳>.zip`，共用 `KEEP_BACKUPS=10` 轮转。

无 PIN / 无鉴权：能执行本命令 = 能导出全部错题、订正答案与上传原图。
失败只给退出码与一行原因（及服务日志），不推送通知。

用法：
    cd wengu-api && venv\\Scripts\\python -m scripts.backup_cli
    cd wengu-api && venv\\Scripts\\python -m scripts.backup_cli --data-dir ..\\data   # Docker 形态
    ... --dry-run    # 只打印将备份哪份库、产物落哪、现有备份与版本，不写文件
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.backup import (
    BACKUP_NAME_RE,
    COUNT_TABLES,
    BackupError,
    backups_dir,
    create_backup,
)


def _settings(data_dir: Path | None) -> Settings:
    if data_dir is None:
        return get_settings()
    resolved = data_dir.resolve()
    return Settings(data_dir=resolved, db_path=resolved / "wengu.db")


def _existing_backups(settings: Settings) -> list[Path]:
    root = backups_dir(settings)
    if not root.is_dir():
        return []
    return sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and BACKUP_NAME_RE.fullmatch(path.name)
        ),
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def _read_meta(db_path: Path) -> tuple[str | None, dict[str, int]]:
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        version_row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        existing = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in COUNT_TABLES
            if table in existing
        }
        return (str(version_row[0]) if version_row else None), counts
    finally:
        conn.close()


def _print_target(settings: Settings, db_path: Path) -> None:
    print(f"数据目录：{settings.data_dir}")
    print(f"将备份：{db_path}")
    print(f"产物目录：{backups_dir(settings)}")


def _print_meta(alembic_version: str | None, counts: dict[str, int]) -> None:
    print(f"alembic：{alembic_version or '未知'}")
    print(
        "计数："
        f"mistakes={counts.get('mistakes', 0)}，"
        f"learning_events={counts.get('learning_events', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "命令行备份（无需 PIN：能执行本命令 = 能导出全部错题、答案与上传原图）。"
            "产物与家长区「备份」页同一实现与轮转。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m scripts.backup_cli\n"
            "  python -m scripts.backup_cli --data-dir ..\\data   # Docker 形态的 <仓库>/data\n"
            "  python -m scripts.backup_cli --data-dir ..\\data --dry-run\n"
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="数据目录（默认用当前配置指向的那份；Docker 形态请指 <仓库>/data）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将备份的库 / 产物目录 / 现有备份与版本，不写任何文件",
    )
    args = parser.parse_args(argv)

    settings = _settings(args.data_dir)
    db_path = Path(settings.db_path) if settings.db_path else None
    if db_path is None or not db_path.is_file():
        _print_target(settings, db_path or Path("<未配置>"))
        print("备份失败：业务库不存在，无法备份", file=sys.stderr)
        return 1

    _print_target(settings, db_path)
    try:
        alembic_version, counts = _read_meta(db_path)
        if args.dry_run:
            backups = _existing_backups(settings)
            oldest = backups[0].name if backups else "无"
            print(f"现有备份：{len(backups)} 份（最旧：{oldest}）")
            _print_meta(alembic_version, counts)
            print("（dry-run：未写任何文件）")
            return 0

        result = create_backup(settings)
    except BackupError as exc:
        print(f"备份失败：{exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"备份失败：读取业务库失败：{exc}", file=sys.stderr)
        return 1

    print(f"备份完成：{result.path.name}")
    print(f"size_bytes：{result.size_bytes}")
    print(f"sha256：{result.sha256}")
    manifest = result.manifest
    _print_meta(
        manifest.get("alembic_version"), manifest.get("counts") or {}
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
