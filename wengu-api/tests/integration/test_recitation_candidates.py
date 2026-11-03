"""P3-3c 从错题抽词集成测试：取数边界、已有条目排除、批量入库与错题链路零变化。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    GradingResult,
    KnowledgeSeed,
    Mistake,
    MistakeVersion,
    RecitationItem,
    ReviewSchedule,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
TOPIC_EN = "eng_seed_001"
TOPIC_MATH = "cnm_001"

pytestmark = pytest.mark.integration


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "recitation-candidates.db"
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


async def _seed_topics(factory: async_sessionmaker) -> None:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=TOPIC_EN,
                subject="英语",
                name="英语词汇",
                type="topic",
                unaudited=True,
                blind_verified=True,
            )
        )
        session.add(
            KnowledgeSeed(
                id=TOPIC_MATH,
                subject="数学",
                name="有理数",
                type="topic",
                unaudited=True,
                blind_verified=True,
            )
        )
        await session.flush()


async def _seed_mistake(
    factory: async_sessionmaker,
    *,
    source_id: int,
    versions: list[str],
    topic_id: str = TOPIC_EN,
    status: str = "active",
) -> int:
    """直接造 facts：grading_results → mistakes → mistake_versions（末版为当前版）。"""

    async with factory() as session, session.begin():
        now = datetime.now(UTC)
        grading = GradingResult(
            source_kind="ingestion_draft",
            source_id=source_id,
            question_type="objective",
            problem_text=versions[-1],
            status="confirmed",
            current_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(grading)
        await session.flush()
        mistake = Mistake(
            source_grading_id=grading.id,
            status=status,
            current_version=len(versions),
            primary_topic_id=topic_id,
            created_at=now,
            updated_at=now,
        )
        session.add(mistake)
        await session.flush()
        for version, problem_text in enumerate(versions, start=1):
            session.add(
                MistakeVersion(
                    mistake_id=mistake.id,
                    version=version,
                    problem_text=problem_text,
                    status="confirmed",
                    suggested_concept_ids_json="[]",
                    confirmed_concept_ids_json="[]",
                    created_at=now,
                )
            )
        await session.flush()
        return mistake.id


async def _snapshot(factory: async_sessionmaker) -> tuple:
    """四表快照：抽词/入库绝不允许改动错题链路。"""

    async with factory() as session:
        mistakes = (
            await session.execute(select(Mistake).order_by(Mistake.id))
        ).scalars().all()
        versions = (
            await session.execute(
                select(MistakeVersion).order_by(MistakeVersion.id)
            )
        ).scalars().all()
        attempts = int(
            await session.scalar(select(func.count()).select_from(Attempt)) or 0
        )
        schedules = int(
            await session.scalar(
                select(func.count()).select_from(ReviewSchedule)
            )
            or 0
        )
        return (
            [
                (
                    row.id,
                    row.status,
                    row.current_version,
                    row.primary_topic_id,
                    row.source_grading_id,
                )
                for row in mistakes
            ],
            [
                (
                    row.id,
                    row.mistake_id,
                    row.version,
                    row.problem_text,
                    row.status,
                    row.confirmed_category_id,
                )
                for row in versions
            ],
            attempts,
            schedules,
        )


async def _items(factory: async_sessionmaker) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.scalars(
                select(RecitationItem).order_by(RecitationItem.id)
            )
        ).all()
        return [
            (row.subject, row.prompt, row.answer, row.unit, row.status)
            for row in rows
        ]


async def test_candidates_only_cover_active_english_current_versions(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    await _seed_mistake(
        factory,
        source_id=1,
        versions=["obsoleteword student", "currentword student"],
    )
    await _seed_mistake(
        factory,
        source_id=2,
        versions=["mathword"],
        topic_id=TOPIC_MATH,
    )
    await _seed_mistake(
        factory, source_id=3, versions=["voidedword"], status="voided"
    )
    await _seed_mistake(
        factory,
        source_id=4,
        versions=["mathwords"],
        topic_id=TOPIC_MATH,
    )

    async with _client(factory) as client:
        response = await client.get("/api/recitations/candidates")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {"word": "currentword", "mistake_count": 1},
        {"word": "student", "mistake_count": 1},
    ]


async def test_candidates_exclude_active_and_retired_items(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    await _seed_mistake(
        factory, source_id=1, versions=["apple banana cherry date"]
    )

    async with _client(factory) as client:
        active = await client.post(
            "/api/recitations",
            json={"subject": "英语", "prompt": "APPLE"},
        )
        assert active.status_code == 200, active.text
        retired = await client.post(
            "/api/recitations",
            json={"subject": "英语", "prompt": "banana"},
        )
        assert retired.status_code == 200, retired.text
        patched = await client.patch(
            f"/api/recitations/{retired.json()['id']}",
            json={"status": "retired"},
        )
        assert patched.status_code == 200, patched.text

        response = await client.get("/api/recitations/candidates")

    assert response.status_code == 200, response.text
    assert [entry["word"] for entry in response.json()] == ["cherry", "date"]


async def test_candidates_and_batch_require_parent_unlock(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    await _seed_mistake(factory, source_id=1, versions=["apple"])

    async with _client(factory, unlock=False) as client:
        listing = await client.get("/api/recitations/candidates")
        batch = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["apple"]},
        )

    assert listing.status_code == 403, listing.text
    assert batch.status_code == 403, batch.text
    assert await _items(factory) == []


async def test_batch_reports_duplicate_and_invalid_without_auto_answer(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/candidates/batch",
            json={
                "words": ["apple", "banana", "apple", "中文", "x"],
                "unit": " Unit 3 ",
            },
        )
        listing = await client.get("/api/recitations", params={"limit": 10})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 2
    assert body["created"] == [
        {"id": 1, "prompt": "apple"},
        {"id": 2, "prompt": "banana"},
    ]
    assert body["duplicates"] == [{"line": 3, "prompt": "apple"}]
    assert [error["line"] for error in body["errors"]] == [4, 5]
    assert all(error["field"] == "words" for error in body["errors"])
    # 只入库词条本身：不自动配释义，卡面只显示 prompt。
    assert await _items(factory) == [
        ("英语", "apple", None, "Unit 3", "active"),
        ("英语", "banana", None, "Unit 3", "active"),
    ]
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 2


async def test_repeat_batch_is_idempotent_and_batch_rejects_over_limit(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        first = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["apple", "banana"]},
        )
        second = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["apple", "banana"]},
        )
        too_many = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": [f"word{i}" for i in range(51)]},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["imported"] == 0
    assert second.json()["duplicates"] == [
        {"line": 1, "prompt": "apple"},
        {"line": 2, "prompt": "banana"},
    ]
    assert too_many.status_code == 422, too_many.text
    assert too_many.json()["detail"][0]["loc"][-1] == "words"
    assert len(await _items(factory)) == 2


async def test_extraction_and_batch_leave_mistake_chain_untouched(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    await _seed_mistake(
        factory, source_id=1, versions=["diligent student"]
    )
    before = await _snapshot(factory)

    async with _client(factory) as client:
        listed = await client.get("/api/recitations/candidates")
        assert listed.status_code == 200, listed.text
        assert [entry["word"] for entry in listed.json()] == [
            "diligent",
            "student",
        ]
        created = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["diligent"]},
        )
        assert created.status_code == 200, created.text

    assert await _snapshot(factory) == before


async def test_retired_batch_item_leaves_due_and_is_not_rediscovered(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    await _seed_mistake(factory, source_id=1, versions=["diligent"])
    await _seed_mistake(factory, source_id=2, versions=["diligent plan"])
    day = "2026-11-03"

    async with _client(factory) as client:
        before = await client.get("/api/recitations/candidates")
        assert before.json() == [
            {"word": "diligent", "mistake_count": 2},
            {"word": "plan", "mistake_count": 1},
        ]

        created = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["diligent"]},
        )
        assert created.status_code == 200, created.text
        item_id = created.json()["created"][0]["id"]

        due = await client.get(
            "/api/recitations/due", params={"today": day}
        )
        assert [entry["item"]["prompt"] for entry in due.json()["items"]] == [
            "diligent"
        ]

        retired = await client.patch(
            f"/api/recitations/{item_id}", json={"status": "retired"}
        )
        assert retired.status_code == 200, retired.text

        after_due = await client.get(
            "/api/recitations/due", params={"today": day}
        )
        after_candidates = await client.get("/api/recitations/candidates")
        reimport = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["diligent"]},
        )

    assert after_due.json()["items"] == []
    # 已停用条目仍算"已有"，所以再抽词不会再出现——要背它需家长手动启用。
    assert after_candidates.json() == [
        {"word": "plan", "mistake_count": 1}
    ]
    assert reimport.status_code == 200, reimport.text
    assert reimport.json()["imported"] == 0
    assert reimport.json()["duplicates"] == [{"line": 1, "prompt": "diligent"}]
