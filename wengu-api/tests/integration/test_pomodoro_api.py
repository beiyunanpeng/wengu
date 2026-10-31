"""P2-2 番茄钟集成测试：打点事实、幂等、钳制、不影响既有信号、看板聚合。

口径（TICKETS P2-2）：
- 完成打点 = 一条 `pomodoro_completed` 事件（幂等键 `pomodoro:{started_at秒}`）；
- duration 由服务端钳制 5–120；参数非法 422；不存在的 mistake_id → 404；
- 番茄不计入掌握度 / streak / 打卡，不写错题/排期/attempts；
- 看板 `pomodoros_today / focus_minutes_this_week` 从事件现算，空库全零。
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
from app.models import Attempt, LearningEvent, Mistake, ReviewSchedule
from app.services.events import record_event
from app.services.pomodoro import summarize_pomodoros
from app.services.recompute import ATTEMPT_CORRECT, Event
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 4)
WEEK_START = TODAY - timedelta(days=TODAY.weekday())


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "pomodoro.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(factory: async_sessionmaker) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _payload(
    *,
    duration: int = 25,
    started_at: str = "2026-11-04T09:00:00+08:00",
    completed_on: str = "2026-11-04",
    mistake_id: int | None = None,
    actor: str = "student",
) -> dict[str, object]:
    body: dict[str, object] = {
        "duration_minutes": duration,
        "started_at": started_at,
        "completed_on": completed_on,
        "actor": actor,
    }
    if mistake_id is not None:
        body["mistake_id"] = mistake_id
    return body


async def _events(factory: async_sessionmaker) -> list[Event]:
    async with factory() as session:
        rows = (
            await session.scalars(
                select(LearningEvent).order_by(LearningEvent.id)
            )
        ).all()
    return [
        Event(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]


async def _count(factory: async_sessionmaker, model: object) -> int:
    async with factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(model)) or 0
        )


@pytest.mark.integration
async def test_pomodoro_is_recorded_as_idempotent_fact(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        first = await client.post(
            "/api/pomodoros", json=_payload(duration=25)
        )
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["duration_minutes"] == 25
        assert isinstance(body["id"], int)

        # 同一 started_at 秒重放：返回同一事件，duration 以已存事实为准
        replay = await client.post(
            "/api/pomodoros",
            json=_payload(
                duration=99,
                started_at="2026-11-04T01:00:00Z",
            ),
        )
        assert replay.status_code == 201, replay.text
        assert replay.json() == body

        events = await _events(factory)
        assert len(events) == 1
        event = events[0]
        assert event.type == "pomodoro_completed"
        assert event.actor == "student"
        assert event.mistake_id is None
        assert json.loads(event.payload) == {
            "mistake_id": None,
            "duration_minutes": 25,
            "completed_on": "2026-11-04",
        }


@pytest.mark.integration
async def test_duration_is_clamped_and_invalid_payloads_are_422(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        for index, (raw, expected) in enumerate(
            (
                (1, 5),
                (4, 5),
                (5, 5),
                (120, 120),
                (121, 120),
                (999, 120),
            )
        ):
            response = await client.post(
                "/api/pomodoros",
                json=_payload(
                    duration=raw,
                    started_at=f"2026-11-04T09:{index:02d}:00+08:00",
                ),
            )
            assert response.status_code == 201, (raw, response.text)
            assert response.json()["duration_minutes"] == expected

        invalid = [
            _payload(duration=0),
            _payload(duration=-3),
            {"duration_minutes": True, "started_at": "2026-11-04T10:00:00+08:00", "completed_on": "2026-11-04"},
            {"duration_minutes": "25", "started_at": "2026-11-04T10:00:00+08:00", "completed_on": "2026-11-04"},
            {"duration_minutes": 25, "completed_on": "2026-11-04"},
            {"duration_minutes": 25, "started_at": "not-a-date", "completed_on": "2026-11-04"},
            {"duration_minutes": 25, "started_at": "2026-11-04T10:00:00+08:00", "completed_on": "2026-13-01"},
            _payload(actor="teacher"),
            _payload(mistake_id=0),
        ]
        for body in invalid:
            response = await client.post("/api/pomodoros", json=body)
            assert response.status_code == 422, (body, response.text)

        missing_mistake = await client.post(
            "/api/pomodoros", json=_payload(mistake_id=999)
        )
        assert missing_mistake.status_code == 404, missing_mistake.text


@pytest.mark.integration
async def test_pomodoro_does_not_touch_mastery_streak_or_writes(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with factory() as session, session.begin():
        await record_event(
            session,
            ATTEMPT_CORRECT,
            "student",
            idempotency_key="test:attempt:1",
            payload={
                "source": "student_self",
                "completed_on": TODAY.isoformat(),
            },
        )
    counts_before = {
        model.__name__: await _count(factory, model)
        for model in (Mistake, ReviewSchedule, Attempt)
    }

    async with _client(factory) as client:
        before = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()
        assert before["streak"]["today_done"] is True
        assert before["streak"]["current_streak"] == 1
        assert before["pomodoros_today"] == 0
        assert before["focus_minutes_this_week"] == 0

        recorded = await client.post(
            "/api/pomodoros", json=_payload(duration=25)
        )
        assert recorded.status_code == 201, recorded.text

        after = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()

    # 番茄不改掌握度 / streak / 打卡 / 到期 / 存量 / 毕业
    assert after["mastery"] == before["mastery"]
    assert after["streak"] == before["streak"]
    assert after["due"] == before["due"]
    assert after["inventory"] == before["inventory"]
    assert after["completion"] == before["completion"]
    assert after["bank_gap"] == before["bank_gap"]

    # 只有番茄展示字段与原始事件计数变化
    assert after["pomodoros_today"] == 1
    assert after["focus_minutes_this_week"] == 25
    assert (
        after["event_stats"]["total_events"]
        == before["event_stats"]["total_events"] + 1
    )
    assert after["event_stats"]["attempts_correct"] == 1

    counts_after = {
        model.__name__: await _count(factory, model)
        for model in (Mistake, ReviewSchedule, Attempt)
    }
    assert counts_after == counts_before
    events = await _events(factory)
    assert [event.type for event in events] == [
        ATTEMPT_CORRECT,
        "pomodoro_completed",
    ]


@pytest.mark.integration
async def test_dashboard_pomodoro_fields_match_event_recompute(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        empty = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()
        assert empty["pomodoros_today"] == 0
        assert empty["focus_minutes_this_week"] == 0

        for duration, started_at, completed_on in (
            (25, "2026-11-04T09:00:00+08:00", "2026-11-04"),
            (40, "2026-11-02T09:00:00+08:00", "2026-11-02"),
            (30, "2026-10-20T09:00:00+08:00", "2026-10-20"),
        ):
            response = await client.post(
                "/api/pomodoros",
                json=_payload(
                    duration=duration,
                    started_at=started_at,
                    completed_on=completed_on,
                ),
            )
            assert response.status_code == 201, response.text

        dashboard = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()
        assert dashboard["pomodoros_today"] == 1
        assert dashboard["focus_minutes_this_week"] == 65

        recomputed = summarize_pomodoros(
            await _events(factory), TODAY, WEEK_START
        )
        assert recomputed.pomodoros_today == dashboard["pomodoros_today"]
        assert (
            recomputed.focus_minutes_this_week
            == dashboard["focus_minutes_this_week"]
        )

        await client.post(
            "/api/pomodoros",
            json=_payload(
                duration=25, started_at="2026-11-04T15:00:00+08:00"
            ),
        )
        refreshed = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()
        assert refreshed["pomodoros_today"] == 2
        assert refreshed["focus_minutes_this_week"] == 90
