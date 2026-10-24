from __future__ import annotations

import pytest
from app.core.database import create_sqlite_engine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
async def test_sqlite_pragmas_and_crud(tmp_path) -> None:
    engine = create_sqlite_engine(tmp_path / "test.db")
    try:
        async with engine.begin() as conn:
            journal_mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar()
            foreign_keys = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar()
            busy_timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar()

            assert journal_mode == "wal"
            assert foreign_keys == 1
            assert busy_timeout == 5000

            await conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
            await conn.execute(
                text(
                    "CREATE TABLE child ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_id INTEGER NOT NULL REFERENCES parent(id)"
                    ")"
                )
            )
            await conn.execute(text("INSERT INTO parent (id) VALUES (1)"))
            await conn.execute(text("INSERT INTO child (id, parent_id) VALUES (10, 1)"))

        async with engine.connect() as conn:
            value = (
                await conn.execute(text("SELECT parent_id FROM child WHERE id = 10"))
            ).scalar_one()
            assert value == 1

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO child (id, parent_id) VALUES (11, 999)"))
    finally:
        await engine.dispose()
