"""P3-3b 词表批量导入集成测试：逐行报告、幂等、限额与家长门禁。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import RecitationItem
from app.services.recitation_import import (
    MAX_IMPORT_BODY_BYTES,
    MAX_IMPORT_ROWS,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"

pytestmark = pytest.mark.integration


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "recitation-import.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(
    factory: async_sessionmaker, *, unlock: bool = True
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if unlock:
            response = await client.post(
                "/api/session/pin/set", json={"pin": PIN}
            )
            assert response.status_code == 200, response.text
        yield client


async def _items(factory: async_sessionmaker) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.scalars(
                select(RecitationItem).order_by(RecitationItem.id)
            )
        ).all()
        return [
            (row.subject, row.prompt, row.answer, row.unit, row.created_by)
            for row in rows
        ]


async def test_csv_with_header_imports_every_row(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/import",
            json={
                "subject": "英语",
                "text": (
                    "prompt,answer,unit\n"
                    "abandon,放弃,Unit 1\n"
                    "ability,,Unit 1\n"
                    "absorb,吸收,\n"
                ),
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "imported": 3,
        "duplicates": [],
        "errors": [],
    }
    assert await _items(factory) == [
        ("英语", "abandon", "放弃", "Unit 1", "parent"),
        ("英语", "ability", None, "Unit 1", "parent"),
        ("英语", "absorb", "吸收", None, "parent"),
    ]


async def test_tsv_and_bom_are_accepted(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/import",
            json={
                "subject": "英语",
                "text": "\ufeffabandon\t放弃\tUnit 1\nability\t能力\n",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 2
    assert [row[1:4] for row in await _items(factory)] == [
        ("abandon", "放弃", "Unit 1"),
        ("ability", "能力", None),
    ]


async def test_mixed_batch_reports_duplicate_and_bad_rows_without_updating(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        created = await client.post(
            "/api/recitations",
            json={"subject": "英语", "prompt": "abandon"},
        )
        assert created.status_code == 200, created.text

        response = await client.post(
            "/api/recitations/import",
            json={
                "subject": "英语",
                "text": (
                    "prompt,answer\n"
                    "abandon,放弃\n"
                    ",缺少条目\n"
                    "ability,能力\n"
                    "four,columns,here,x\n"
                    "absorb,吸收\n"
                ),
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 2
    assert body["duplicates"] == [{"line": 2, "prompt": "abandon"}]
    assert body["errors"] == [
        {"line": 3, "field": "prompt", "reason": "prompt 不能为空"},
        {
            "line": 5,
            "field": "columns",
            "reason": "最多 3 列（prompt, answer, unit）",
        },
    ]
    # 重复行只报告，不覆盖家长原有条目（answer 仍为空）。
    assert await _items(factory) == [
        ("英语", "abandon", None, None, "parent"),
        ("英语", "ability", "能力", None, "parent"),
        ("英语", "absorb", "吸收", None, "parent"),
    ]


async def test_more_than_500_rows_rejects_whole_batch(tmp_path) -> None:
    factory = _migrated(tmp_path)
    text = "\n".join(f"word{i}" for i in range(MAX_IMPORT_ROWS + 1))

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/import", json={"subject": "英语", "text": text}
        )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["line"] == MAX_IMPORT_ROWS + 1
    assert str(MAX_IMPORT_ROWS) in detail["reason"]
    assert await _items(factory) == []


@pytest.mark.parametrize(
    ("line_text", "field"),
    [
        ("x" * 201, "prompt"),
        (f"abandon,{'x' * 501}", "answer"),
        (f"abandon,放弃,{'x' * 41}", "unit"),
    ],
)
async def test_overlong_field_rejects_whole_batch(
    tmp_path, line_text: str, field: str
) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/import",
            json={"subject": "英语", "text": f"ok_row\n{line_text}\n"},
        )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["line"] == 2
    assert detail["field"] == field
    assert await _items(factory) == []


async def test_oversize_body_rejected_before_parsing(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/import",
            json={"subject": "英语", "text": "x" * MAX_IMPORT_BODY_BYTES},
        )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["field"] == "text"
    assert "256KB" in detail["reason"]
    assert await _items(factory) == []


async def test_same_text_twice_is_idempotent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    text = "abandon,放弃\nability,能力\n"

    async with _client(factory) as client:
        first = await client.post(
            "/api/recitations/import", json={"subject": "英语", "text": text}
        )
        second = await client.post(
            "/api/recitations/import", json={"subject": "英语", "text": text}
        )

    assert first.status_code == 200, first.text
    assert first.json()["imported"] == 2
    assert second.status_code == 200, second.text
    assert second.json() == {
        "imported": 0,
        "duplicates": [
            {"line": 1, "prompt": "abandon"},
            {"line": 2, "prompt": "ability"},
        ],
        "errors": [],
    }
    assert len(await _items(factory)) == 2


async def test_subject_outside_memory_subjects_is_rejected(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/import",
            json={"subject": "数学", "text": "abandon,放弃\n"},
        )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["field"] == "subject"
    assert await _items(factory) == []


async def test_import_requires_parent_unlock(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory, unlock=False) as client:
        response = await client.post(
            "/api/recitations/import",
            json={"subject": "英语", "text": "abandon,放弃\n"},
        )

    assert response.status_code == 403
    assert await _items(factory) == []
