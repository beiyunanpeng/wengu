"""P3-3a 英语背诵集成测试：家长维护、孩子自评、阶梯与事实边界。

钉死的口径：
- 条目只写 `recitation_items` / `recitation_reviews` / `learning_events`，
  `mistakes` / `mistake_versions` / `attempts` / `review_schedules` 全表内容不变；
- 同日重复自评幂等：不产生第二条自评或事件，返回既有结果；
- 阶梯 `(1,3,7,14,30)`：remembered 进一档、forgot 保档，下次到期从
  `reviewed_on` 起算；最高档 remembered 毕业（`scheduled_next=NULL`）；
- 看板 `今日背诵` 与打卡同时可见，`recitation_reviewed` 只打标签、不进掌握度；
- `daily_recitation_limit` 热加载，超 20 收口。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    LearningEvent,
    Mistake,
    MistakeVersion,
    RecitationItem,
    RecitationReview,
    ReviewSchedule,
)
from app.services.recompute import RECITATION_REVIEWED
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
BASE = date(2026, 11, 1)

pytestmark = pytest.mark.integration


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "recitation.db"
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


async def _create(
    client: AsyncClient,
    *,
    subject: str = "英语",
    prompt: str,
    answer: str | None = None,
    unit: str | None = None,
) -> dict:
    response = await client.post(
        "/api/recitations",
        json={
            "subject": subject,
            "prompt": prompt,
            "answer": answer,
            "unit": unit,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _review(
    client: AsyncClient,
    item_id: int,
    verdict: str,
    reviewed_on: date,
) -> dict:
    response = await client.post(
        f"/api/recitations/{item_id}/review",
        json={"verdict": verdict, "reviewed_on": reviewed_on.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _snapshot(factory: async_sessionmaker) -> dict[str, list[tuple]]:
    """四张错题链路表的全量内容快照（行数与每列内容）。"""

    async with factory() as session:
        return {
            "mistakes": [
                tuple(row)
                for row in await session.execute(
                    select(*Mistake.__table__.columns).order_by(Mistake.id)
                )
            ],
            "mistake_versions": [
                tuple(row)
                for row in await session.execute(
                    select(*MistakeVersion.__table__.columns).order_by(
                        MistakeVersion.id
                    )
                )
            ],
            "attempts": [
                tuple(row)
                for row in await session.execute(
                    select(*Attempt.__table__.columns).order_by(Attempt.id)
                )
            ],
            "review_schedules": [
                tuple(row)
                for row in await session.execute(
                    select(*ReviewSchedule.__table__.columns).order_by(
                        ReviewSchedule.id
                    )
                )
            ],
        }


async def test_writes_require_parent_but_reads_are_child_area(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory, unlock=False) as client:
        denied = await client.post(
            "/api/recitations",
            json={"subject": "英语", "prompt": "abandon"},
        )
        assert denied.status_code == 403
        assert (await client.get("/api/recitations")).status_code == 200
        assert (await client.get("/api/recitations/due")).status_code == 200

        response = await client.post("/api/session/pin/set", json={"pin": PIN})
        assert response.status_code == 200
        item = await _create(client, prompt="abandon")
        patch = await client.patch(
            f"/api/recitations/{item['id']}",
            json={"status": "retired"},
        )
        assert patch.status_code == 200
        assert patch.json()["status"] == "retired"


async def test_create_list_duplicate_and_validation(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        first = await _create(
            client, prompt="abandon", answer="放弃", unit="Unit 1"
        )
        assert first["status"] == "active"
        assert first["created_by"] == "parent"
        await _create(client, prompt="ability")
        await _create(client, subject="语文", prompt="默写《静夜思》")

        listing = (await client.get("/api/recitations")).json()
        assert listing["total"] == 3
        assert [item["id"] for item in listing["items"]] == [3, 2, 1]

        english = (await client.get("/api/recitations?subject=英语")).json()
        assert english["total"] == 2

        duplicate = await client.post(
            "/api/recitations",
            json={"subject": "英语", "prompt": "  abandon  "},
        )
        assert duplicate.status_code == 409

        blank = await client.post(
            "/api/recitations",
            json={"subject": "英语", "prompt": "   "},
        )
        assert blank.status_code == 422

        missing = await client.patch(
            "/api/recitations/999", json={"prompt": "x"}
        )
        assert missing.status_code == 404


async def test_ladder_walks_every_step_and_graduates(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        item = await _create(client, prompt="abandon")
        item_id = item["id"]

        steps = [
            (BASE, 1, 3),
            (BASE + timedelta(days=3), 2, 7),
            (BASE + timedelta(days=10), 3, 14),
            (BASE + timedelta(days=24), 4, 30),
        ]
        for reviewed_on, rung, wait in steps:
            result = await _review(
                client, item_id, "remembered", reviewed_on
            )
            assert result["rung"] == rung
            assert result["scheduled_next"] == (
                reviewed_on + timedelta(days=wait)
            ).isoformat()
            assert result["graduated"] is False

        graduated = await _review(
            client, item_id, "remembered", BASE + timedelta(days=54)
        )
        assert graduated["rung"] == 4
        assert graduated["scheduled_next"] is None
        assert graduated["graduated"] is True

        due = (
            await client.get(
                f"/api/recitations/due?today={BASE + timedelta(days=365)}"
            )
        ).json()
        assert due["due_total"] == 0
        assert due["items"] == []


async def test_forgot_keeps_rung_and_starts_from_review_date(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        item = await _create(client, prompt="abandon")
        item_id = item["id"]

        first = await _review(client, item_id, "remembered", BASE)
        assert first["rung"] == 1
        assert first["scheduled_next"] == (
            BASE + timedelta(days=3)
        ).isoformat()

        late = BASE + timedelta(days=10)
        forgot = await _review(client, item_id, "forgot", late)
        assert forgot["rung"] == 1
        assert forgot["scheduled_next"] == (
            late + timedelta(days=3)
        ).isoformat()


async def test_same_day_review_is_idempotent(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        item = await _create(client, prompt="abandon")
        item_id = item["id"]

        first = await _review(client, item_id, "remembered", BASE)
        second = await _review(client, item_id, "forgot", BASE)

        assert first["created"] is True
        assert second["created"] is False
        assert second["review_id"] == first["review_id"]
        assert second["event_id"] == first["event_id"]
        assert second["rung"] == 1
        assert second["scheduled_next"] == (
            BASE + timedelta(days=3)
        ).isoformat()

    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(RecitationReview)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(LearningEvent)
                .where(LearningEvent.type == RECITATION_REVIEWED)
            )
            == 1
        )


async def test_recitation_never_touches_mistake_chain(tmp_path) -> None:
    factory = _migrated(tmp_path)

    before = await _snapshot(factory)
    async with _client(factory) as client:
        item = await _create(client, prompt="abandon")
        await _review(client, item["id"], "remembered", BASE)
    after = await _snapshot(factory)

    assert after == before
    assert all(rows == [] for rows in after.values())

    async with factory() as session:
        events = (
            (
                await session.execute(
                    select(LearningEvent).where(
                        LearningEvent.type == RECITATION_REVIEWED
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].mistake_id is None
        payload = json.loads(events[0].payload)
        assert payload == {
            "item_id": item["id"],
            "verdict": "remembered",
            "rung": 1,
            "scheduled_next": (BASE + timedelta(days=3)).isoformat(),
            "completed_on": BASE.isoformat(),
        }
        assert await session.get(RecitationItem, item["id"]) is not None
        assert (
            await session.scalar(select(func.count()).select_from(Attempt))
            == 0
        )


async def test_dashboard_and_streak_include_recitation(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        item = await _create(client, prompt="abandon")
        await _review(client, item["id"], "remembered", BASE)

        board = (
            await client.get(f"/api/dashboard?today={BASE.isoformat()}")
        ).json()

    assert board["recitations_today"] == 1
    assert board["recitation_limit"] == 5
    assert board["streak"]["today_done"] is True
    assert board["streak"]["current_streak"] == 1
    assert board["event_stats"]["by_type"][RECITATION_REVIEWED] == 1
    assert board["event_stats"]["attempts_correct"] == 0
    assert board["event_stats"]["attempts_wrong"] == 0
    assert board["mastery"]["overall"] == 0.0


async def test_daily_limit_hot_reloads_and_clamps_at_20(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(config_path))
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        for index in range(7):
            await _create(client, prompt=f"word-{index}")

        default_due = (
            await client.get(
                f"/api/recitations/due?today={BASE.isoformat()}"
            )
        ).json()
        assert default_due["due_total"] == 7
        assert default_due["limit"] == 5
        assert default_due["returned"] == 5

        config_path.write_text(
            json.dumps({"daily_recitation_limit": 2}), encoding="utf-8"
        )
        narrowed = (
            await client.get(
                f"/api/recitations/due?today={BASE.isoformat()}"
            )
        ).json()
        assert narrowed["limit"] == 2
        assert narrowed["returned"] == 2
        assert narrowed["due_total"] == 7

        config_path.write_text(
            json.dumps({"daily_recitation_limit": 25}), encoding="utf-8"
        )
        widened = (
            await client.get(
                f"/api/recitations/due?today={BASE.isoformat()}"
            )
        ).json()
        assert widened["limit"] == 20
        assert widened["returned"] == 7


async def test_retired_item_leaves_queue_and_rejects_review(tmp_path) -> None:
    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        item = await _create(client, prompt="abandon")
        retired = await client.patch(
            f"/api/recitations/{item['id']}",
            json={"status": "retired"},
        )
        assert retired.status_code == 200

        due = (
            await client.get(
                f"/api/recitations/due?today={BASE.isoformat()}"
            )
        ).json()
        assert due["due_total"] == 0

        blocked = await client.post(
            f"/api/recitations/{item['id']}/review",
            json={"verdict": "remembered", "reviewed_on": BASE.isoformat()},
        )
        assert blocked.status_code == 409
