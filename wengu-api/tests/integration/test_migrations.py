from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

API_DIR = Path(__file__).resolve().parents[2]


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
    assert _tables(db_path) - {"alembic_version"} == set()

    command.downgrade(config, "base")
    assert _tables(db_path) - {"alembic_version"} == set()

    command.upgrade(config, "head")
    assert _tables(db_path) - {"alembic_version"} == set()
