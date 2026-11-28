"""P6-5 家长灌库端点：前置闸门、六计数、幂等与事实源边界。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    LearningEvent,
    Mistake,
    RecitationItem,
    RecitationReview,
    ReviewSchedule,
    UserRole,
)
from app.services.session import COOKIE_NAME, issue_token
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
SEED_PATH = "/api/recitations/seed-vocab"
COUNT_FIELDS = {
    "band",
    "seen",
    "created",
    "duplicate_exact",
    "duplicate_casefold",
    "null_answer",
}

pytestmark = pytest.mark.integration


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def _write_fixture(seeds_dir: Path) -> None:
    vocab_dir = seeds_dir / "vocab"
    vocab_dir.mkdir(parents=True)
    levels = []
    details = []
    for word, stage, translation in (
        ("alpha", "primary", "阿尔法"),
        ("beta", "primary", "贝塔"),
        ("rootless", "primary", None),
        ("junior-only", "junior", "初中词"),
        ("China", "senior", "中国"),
    ):
        levels.append(
            {
                "word": word,
                "forms": [],
                "stages": [stage],
                "unaudited": True,
            }
        )
        details.append(
            {
                "word": word,
                "translation": translation,
                "exam_badges": {"tags": []},
            }
        )
    _write_json(vocab_dir / "levels.json", {"words": levels})
    _write_json(vocab_dir / "words.json", {"words": details})


@pytest.fixture
def seed_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seeds_dir = tmp_path / "seeds"
    _write_fixture(seeds_dir)
    config_path = tmp_path / "app-config.json"
    _write_json(config_path, {"seed_grade_ceiling": 6})
    monkeypatch.setenv("WENGU_SEEDS_DIR", str(seeds_dir))
    monkeypatch.setenv("WENGU_APP_CONFIG", str(config_path))
    monkeypatch.setenv("WENGU_SESSION_SECRET", "p6-5-test-secret")
    get_settings.cache_clear()
    yield seeds_dir, config_path
    get_settings.cache_clear()


def _factory(db_path: Path, revision: str | None) -> async_sessionmaker:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    if revision is not None:
        command.upgrade(config, revision)
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _migrated(tmp_path: Path, revision: str = "head") -> async_sessionmaker:
    return _factory(tmp_path / "seed-api.db", revision)


def _empty(tmp_path: Path) -> async_sessionmaker:
    return _factory(tmp_path / "empty.db", None)


@asynccontextmanager
async def _client(
    factory: async_sessionmaker,
    *,
    auth: Literal["pin", "token", "none"] = "pin",
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if auth == "pin":
            response = await client.post(
                "/api/session/pin/set", json={"pin": PIN}
            )
            assert response.status_code == 200, response.text
        elif auth == "token":
            client.cookies.set(COOKIE_NAME, issue_token())
        yield client


async def _item_rows(factory: async_sessionmaker) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.scalars(select(RecitationItem).order_by(RecitationItem.id))
        ).all()
        return [
            (
                row.id,
                row.subject,
                row.prompt,
                row.answer,
                row.unit,
                row.status,
                row.created_by,
                row.created_at,
                row.source,
            )
            for row in rows
        ]


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _assert_four_fact_tables_empty(factory: async_sessionmaker) -> None:
    assert await _count(factory, LearningEvent) == 0
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, RecitationReview) == 0
    assert await _count(factory, ReviewSchedule) == 0


async def test_parent_auth_required(seed_env, tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory, auth="none") as client:
        response = await client.post(SEED_PATH)

    assert response.status_code == 403
    assert await _count(factory, RecitationItem) == 0
    await _assert_four_fact_tables_empty(factory)


async def test_old_database_returns_db_not_migrated(seed_env, tmp_path: Path) -> None:
    factory = _migrated(tmp_path, "0025")
    roles_before = await _count(factory, UserRole)
    async with _client(factory, auth="token") as client:
        response = await client.post(SEED_PATH)

    assert response.status_code == 409, response.text
    assert set(response.json()["detail"]) == {"message", "code"}
    assert response.json()["detail"]["code"] == "db_not_migrated"
    assert await _count(factory, RecitationItem) == 0
    assert await _count(factory, UserRole) == roles_before
    await _assert_four_fact_tables_empty(factory)
    print(f"db_not_migrated(old)={response.text}")


async def test_empty_database_returns_db_not_migrated(seed_env, tmp_path: Path) -> None:
    factory = _empty(tmp_path)
    async with _client(factory, auth="token") as client:
        response = await client.post(SEED_PATH)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "db_not_migrated"
    async with factory() as session:
        table_count = int(
            await session.scalar(
                text("SELECT count(*) FROM sqlite_master WHERE type='table'")
            )
            or 0
        )
    assert table_count == 0
    print(f"db_not_migrated(empty)={response.text}")


async def test_missing_vocab_returns_vocab_not_installed(
    seed_env, tmp_path: Path
) -> None:
    seeds_dir, _ = seed_env
    (seeds_dir / "vocab" / "levels.json").unlink()
    (seeds_dir / "vocab" / "words.json").unlink()
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.post(SEED_PATH)

    assert response.status_code == 409, response.text
    assert set(response.json()["detail"]) == {"message", "code"}
    assert response.json()["detail"]["code"] == "vocab_not_installed"
    assert await _count(factory, RecitationItem) == 0
    await _assert_four_fact_tables_empty(factory)
    print(f"vocab_not_installed={response.text}")


async def test_invalid_vocab_returns_vocab_invalid(seed_env, tmp_path: Path) -> None:
    seeds_dir, _ = seed_env
    _write_json(seeds_dir / "vocab" / "words.json", [])
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.post(SEED_PATH)

    assert response.status_code == 409, response.text
    assert set(response.json()["detail"]) == {"message", "code"}
    assert response.json()["detail"]["code"] == "vocab_invalid"
    assert await _count(factory, RecitationItem) == 0
    await _assert_four_fact_tables_empty(factory)
    print(f"vocab_invalid={response.text}")


async def test_seed_success_counts_rows_and_fact_boundary(
    seed_env, tmp_path: Path
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.post(SEED_PATH)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == COUNT_FIELDS
    assert payload == {
        "band": 6,
        "seen": 3,
        "created": 3,
        "duplicate_exact": 0,
        "duplicate_casefold": 0,
        "null_answer": 1,
    }
    assert payload["created"] > 0
    rows = await _item_rows(factory)
    assert len(rows) == 3
    assert [(row[1], row[2], row[3], row[6], row[8]) for row in rows] == [
        ("英语", "alpha", "阿尔法", "seed", "seed"),
        ("英语", "beta", "贝塔", "seed", "seed"),
        ("英语", "rootless", None, "seed", "seed"),
    ]
    async with factory() as session:
        sources = list(
            (
                await session.execute(
                    select(RecitationItem.source, func.count()).group_by(
                        RecitationItem.source
                    )
                )
            ).all()
        )
    assert sources == [("seed", 3)]
    await _assert_four_fact_tables_empty(factory)


async def test_seed_is_idempotent(seed_env, tmp_path: Path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        first = await client.post(SEED_PATH)
        first_rows = await _item_rows(factory)
        second = await client.post(SEED_PATH)

    assert first.status_code == 200, first.text
    assert first.json()["created"] == 3
    assert second.status_code == 200, second.text
    assert second.json() == {
        "band": 6,
        "seen": 3,
        "created": 0,
        "duplicate_exact": 3,
        "duplicate_casefold": 0,
        "null_answer": 0,
    }
    assert await _item_rows(factory) == first_rows


async def test_band_change_is_hot_and_preserves_existing_rows(
    seed_env, tmp_path: Path
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        first = await client.post(SEED_PATH)
        assert first.status_code == 200, first.text
        assert first.json()["created"] == 3
        before = await _item_rows(factory)
        changed = await client.put(
            "/api/config", json={"seed_grade_ceiling": 9}
        )
        assert changed.status_code == 200, changed.text
        second = await client.post(SEED_PATH)

    assert second.status_code == 200, second.text
    assert second.json()["band"] == 9
    assert second.json()["seen"] == 4
    assert second.json()["created"] == 1
    after = await _item_rows(factory)
    assert after[:3] == before
    assert len(after) == 4


async def test_casefold_duplicate_preserves_manual_row(seed_env, tmp_path: Path) -> None:
    _, config_path = seed_env
    _write_json(config_path, {"seed_grade_ceiling": 16})
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        manual = await client.post(
            "/api/recitations",
            json={
                "subject": "英语",
                "prompt": "china",
                "answer": "手工释义",
            },
        )
        assert manual.status_code == 200, manual.text
        response = await client.post(SEED_PATH)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["band"] == 16
    assert payload["seen"] == 5
    assert payload["created"] == 4
    assert payload["duplicate_exact"] == 0
    assert payload["duplicate_casefold"] == 1
    rows = await _item_rows(factory)
    china_rows = [row for row in rows if row[2].casefold() == "china"]
    assert len(china_rows) == 1
    assert china_rows[0][2] == "china"
    assert china_rows[0][3] == "手工释义"
    assert china_rows[0][6] == "parent"
    assert china_rows[0][8] == "manual"
    assert len(rows) == 5
