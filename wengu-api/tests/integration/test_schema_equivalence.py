"""P5-19：dictation_sheets 迁移建库 vs ORM 建库的结构等价守卫（docs/STATUS.md §7 第 19 条）。

0025 用 ALTER TABLE ADD COLUMN 后 sqlite_master 文本两侧必然不同，逐字对照已合理移除；
本测试补回结构化对照：列名+类型+可空性+默认值 / 主键 / CHECK 名 / 外键 / 唯一约束 / 索引。
只比 dictation_sheets 一张表——全仓 23 表约 30 处历史性 server_default 差异未立项，不扩面。
SQLite 的 get_check_constraints 返回 sql_text 为空串，故 CHECK 只比名字。
任一侧没建出目标表必须失败并指明是哪一侧，禁止 skip 语义（防"两边都空所以相等"）。
"""

from __future__ import annotations

from pathlib import Path

import app.models  # noqa: F401  注册全部表（__init__ 只显式导出部分模型，DictationSheet 靠模块导入注册）
import pytest
from alembic import command
from alembic.config import Config
from app.core.database import Base
from sqlalchemy import create_engine, inspect

API_DIR = Path(__file__).resolve().parents[2]
TABLE = "dictation_sheets"

pytestmark = pytest.mark.integration


def describe_table(inspection, name: str) -> dict:
    """六项结构化指纹；不比 sqlite_master 文本（ALTER 之后必然不同）。"""

    return {
        "columns": {
            column["name"]: {
                "type": str(column["type"]),
                "nullable": column["nullable"],
                "default": column["default"],
            }
            for column in inspection.get_columns(name)
        },
        "primary_key": inspection.get_pk_constraint(name)["constrained_columns"],
        "check_names": sorted(
            constraint["name"] for constraint in inspection.get_check_constraints(name)
        ),
        "foreign_keys": sorted(
            (
                fk["name"],
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
            )
            for fk in inspection.get_foreign_keys(name)
        ),
        "unique_constraints": sorted(
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspection.get_unique_constraints(name)
        ),
        "indexes": sorted(
            (index["name"], tuple(index["column_names"]), index["unique"])
            for index in inspection.get_indexes(name)
        ),
    }


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _fingerprint(db_path: Path, side: str) -> dict:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspection = inspect(connection)
            tables = set(inspection.get_table_names())
            assert TABLE in tables, (
                f"{side}未建出 {TABLE}（实际建出：{sorted(tables)}）"
            )
            return describe_table(inspection, TABLE)
    finally:
        engine.dispose()


def test_dictation_sheets_migration_orm_equivalence(tmp_path) -> None:
    migrated_db = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(migrated_db), "head")
    migrated = _fingerprint(migrated_db, "alembic 迁移侧")

    modeled_db = tmp_path / "modeled.db"
    engine = create_engine(f"sqlite:///{modeled_db.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    modeled = _fingerprint(modeled_db, "ORM create_all 侧")

    if migrated != modeled:
        migrated_cols = set(migrated["columns"])
        modeled_cols = set(modeled["columns"])
        lines = [
            f"{TABLE} 迁移建库与 ORM 建库结构不一致：",
            f"  仅迁移侧有的列：{sorted(migrated_cols - modeled_cols)}",
            f"  仅 ORM 侧有的列：{sorted(modeled_cols - migrated_cols)}",
        ]
        for key in migrated:
            if migrated[key] != modeled[key]:
                lines.append(
                    f"  指纹项 {key} 不同：\n"
                    f"    迁移侧 = {migrated[key]}\n"
                    f"    ORM 侧 = {modeled[key]}"
                )
        pytest.fail("\n".join(lines))
