"""P2-2b 进行中轮次集成测试：服务端续走、完成/放弃、幂等、看板口径不变。

口径（TICKETS P2-2b）：
- start → 另一个客户端 GET active 能续走（剩余秒数由服务端时间推导）→ complete
  恰好一条 `pomodoro_completed`，payload 键与幂等键格式与 P2-2 一字不差；
- abandon 只翻状态、**不写事件**；complete 两次不产生第二条事件；
- 新端点时长严格 5–120（4/121 → 422），旧打点端点的钳制语义保持不变；
- 番茄仍不计入掌握度 / streak / 错题本 / 排期，看板只在完成后变化。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import Attempt, LearningEvent, Mistake, PomodoroSession, ReviewSchedule
from app.models.pomodoro import SESSION_ACTIVE
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
TODAY = datetime.now(UTC).date()


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "pomodoro-sessions.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(factory: async_sessionmaker) -> AsyncIterator[AsyncClient]:
    """一个独立 app + transport = 一台"新设备"，共用同一个服务端库。"""

    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _events(factory: async_sessionmaker) -> list[LearningEvent]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(LearningEvent).order_by(LearningEvent.id)
                )
            ).all()
        )


async def _sessions(factory: async_sessionmaker) -> list[PomodoroSession]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(PomodoroSession).order_by(PomodoroSession.id)
                )
            ).all()
        )


async def _count(factory: async_sessionmaker, model: object) -> int:
    async with factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(model)) or 0
        )


async def _start(
    client: AsyncClient, *, planned: int = 25, **extra: object
) -> dict:
    response = await client.post(
        "/api/pomodoros/start", json={"planned_minutes": planned, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
async def test_new_client_resumes_then_completes_exactly_one_event(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as first:
        started = await _start(first, planned=25)
        assert started["status"] == "active"
        assert started["planned_minutes"] == 25
        assert started["mistake_id"] is None
        assert started["actor"] == "student"
        assert 1495 <= started["remaining_seconds"] <= 1500
        started_at = datetime.fromisoformat(started["started_at"])
        server_now = datetime.fromisoformat(started["server_now"])
        assert started_at.tzinfo is not None
        assert abs((server_now - started_at).total_seconds()) < 5

        # 换设备：新客户端只靠 GET active 就能续走同一轮
        async with _client(factory) as second:
            active = await second.get("/api/pomodoros/active")
            assert active.status_code == 200, active.text
            resumed = active.json()["session"]
            assert resumed is not None
            assert resumed["id"] == started["id"]
            assert resumed["planned_minutes"] == 25
            assert 1490 <= resumed["remaining_seconds"] <= 1500
            assert (
                datetime.fromisoformat(resumed["started_at"]) == started_at
            )

            completed = await second.post(
                f"/api/pomodoros/{started['id']}/complete",
                json={"duration_minutes": 25, "completed_on": TODAY.isoformat()},
            )
            assert completed.status_code == 200, completed.text
            body = completed.json()
            assert body["duration_minutes"] == 25
            assert body["session_id"] == started["id"]
            assert body["status"] == "completed"

        gone = await first.get("/api/pomodoros/active")
        assert gone.json()["session"] is None

    events = await _events(factory)
    assert len(events) == 1
    event = events[0]
    assert event.type == "pomodoro_completed"
    assert event.actor == "student"
    assert event.mistake_id is None
    assert json.loads(event.payload) == {
        "mistake_id": None,
        "duration_minutes": 25,
        "completed_on": TODAY.isoformat(),
    }
    # 幂等键仍是"开始秒"，且按 UTC 计算（库里回读是 naive，不能被当本地时间）
    assert event.idempotency_key == f"pomodoro:{started_at.timestamp():.0f}"

    rows = await _sessions(factory)
    assert [(row.id, row.status) for row in rows] == [(started["id"], "completed")]


@pytest.mark.integration
async def test_complete_twice_hits_idempotency_key_and_state_guard(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        started = await _start(client, planned=25)
        first = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 25, "completed_on": TODAY.isoformat()},
        )
        assert first.status_code == 200, first.text
        again = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 40, "completed_on": TODAY.isoformat()},
        )
        assert again.status_code == 200, again.text
        assert again.json() == first.json()

        abandoned = await client.post(
            f"/api/pomodoros/{started['id']}/abandon"
        )
        assert abandoned.status_code == 409, abandoned.text

    events = await _events(factory)
    assert len(events) == 1
    assert json.loads(events[0].payload)["duration_minutes"] == 25


@pytest.mark.integration
async def test_abandon_writes_no_event_and_frees_the_slot(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        started = await _start(client, planned=45)
        abandoned = await client.post(
            f"/api/pomodoros/{started['id']}/abandon"
        )
        assert abandoned.status_code == 200, abandoned.text
        assert abandoned.json() == {
            "session_id": started["id"],
            "status": "abandoned",
        }
        assert (await client.get("/api/pomodoros/active")).json()["session"] is None

        replay = await client.post(
            f"/api/pomodoros/{started['id']}/abandon"
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == abandoned.json()

        complete = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 45},
        )
        assert complete.status_code == 409, complete.text

        # 放弃后可以重新开一轮
        restarted = await _start(client, planned=25)
        assert restarted["id"] != started["id"]

    assert await _events(factory) == []
    rows = await _sessions(factory)
    assert [row.status for row in rows] == ["abandoned", "active"]


@pytest.mark.integration
async def test_planned_and_actual_duration_out_of_range_are_422(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        for planned in (4, 121, 0, -5, 999):
            response = await client.post(
                "/api/pomodoros/start", json={"planned_minutes": planned}
            )
            assert response.status_code == 422, (planned, response.text)
        for body in (
            {},
            {"planned_minutes": True},
            {"planned_minutes": "25"},
            {"planned_minutes": 25.0},
            {"planned_minutes": 25, "actor": "teacher"},
            {"planned_minutes": 25, "mistake_id": 0},
        ):
            response = await client.post("/api/pomodoros/start", json=body)
            assert response.status_code == 422, (body, response.text)

        # 边界值可用
        assert (await _start(client, planned=5))["planned_minutes"] == 5
        await client.post(
            f"/api/pomodoros/{(await _active_id(client))}/abandon"
        )
        assert (await _start(client, planned=120))["planned_minutes"] == 120
        session_id = await _active_id(client)

        for duration in (4, 121, 0, -1):
            response = await client.post(
                f"/api/pomodoros/{session_id}/complete",
                json={"duration_minutes": duration},
            )
            assert response.status_code == 422, (duration, response.text)
        for body in ({}, {"duration_minutes": "25"}, {"duration_minutes": True}):
            response = await client.post(
                f"/api/pomodoros/{session_id}/complete", json=body
            )
            assert response.status_code == 422, (body, response.text)

        # 422 不留事实、不改状态
        assert (await client.get("/api/pomodoros/active")).json()["session"][
            "status"
        ] == "active"

    assert await _events(factory) == []


async def _active_id(client: AsyncClient) -> int:
    response = await client.get("/api/pomodoros/active")
    assert response.status_code == 200, response.text
    session = response.json()["session"]
    assert session is not None
    return int(session["id"])


@pytest.mark.integration
async def test_only_one_active_round_and_unknown_ids_are_404(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        started = await _start(client, planned=25)
        conflict = await client.post(
            "/api/pomodoros/start", json={"planned_minutes": 25}
        )
        assert conflict.status_code == 409, conflict.text

        missing_mistake = await client.post(
            "/api/pomodoros/start",
            json={"planned_minutes": 25, "mistake_id": 999},
        )
        assert missing_mistake.status_code == 404, missing_mistake.text

        for path in (
            f"/api/pomodoros/{started['id'] + 100}/complete",
            f"/api/pomodoros/{started['id'] + 100}/abandon",
        ):
            response = await client.post(
                path, json={"duration_minutes": 25}
            )
            assert response.status_code == 404, (path, response.text)

    assert len(await _sessions(factory)) == 1


@pytest.mark.integration
async def test_resume_remaining_comes_from_server_clock(tmp_path) -> None:
    """库里放一轮"10 分钟前开始"的：新客户端读到的剩余必须是 15 分钟。"""

    factory = _migrated(tmp_path)
    async with factory() as session, session.begin():
        session.add(
            PomodoroSession(
                started_at=datetime.now(UTC) - timedelta(minutes=40),
                planned_minutes=25,
                mistake_id=None,
                actor="student",
                status=SESSION_ACTIVE,
            )
        )
        session.add(
            PomodoroSession(
                started_at=datetime.now(UTC) - timedelta(minutes=10),
                planned_minutes=25,
                mistake_id=None,
                actor="student",
                status=SESSION_ACTIVE,
            )
        )

    async with _client(factory) as client:
        active = (await client.get("/api/pomodoros/active")).json()["session"]
        assert active is not None
        # 取最新一轮；已超时的那轮剩余为 0，不为负
        assert active["planned_minutes"] == 25
        assert 890 <= active["remaining_seconds"] <= 900

        completed = await client.post(
            f"/api/pomodoros/{active['id']}/complete",
            json={"duration_minutes": 25, "completed_on": TODAY.isoformat()},
        )
        assert completed.status_code == 200, completed.text

        older = (await client.get("/api/pomodoros/active")).json()["session"]
        assert older is not None
        assert older["remaining_seconds"] == 0
        abandoned = await client.post(
            f"/api/pomodoros/{older['id']}/abandon"
        )
        assert abandoned.status_code == 200, abandoned.text

    assert len(await _events(factory)) == 1


@pytest.mark.integration
async def test_early_finish_counts_actual_minutes_and_dashboard_only_moves_on_complete(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        before = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()
        assert before["pomodoros_today"] == 0

        started = await _start(client, planned=45)
        during = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()
        # 进行中不计数：看板只认完成事实
        assert during["pomodoros_today"] == 0
        assert during["focus_minutes_this_week"] == before["focus_minutes_this_week"]

        completed = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 12, "completed_on": TODAY.isoformat()},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["duration_minutes"] == 12

        after = (
            await client.get(f"/api/dashboard?today={TODAY.isoformat()}")
        ).json()

    assert after["pomodoros_today"] == 1
    assert after["focus_minutes_this_week"] == before["focus_minutes_this_week"] + 12
    for key in ("mastery", "streak", "due", "inventory", "completion", "bank_gap"):
        assert after[key] == before[key], key
    assert (
        after["event_stats"]["total_events"]
        == before["event_stats"]["total_events"] + 1
    )
    for model in (Mistake, ReviewSchedule, Attempt):
        assert await _count(factory, model) == 0


@pytest.mark.integration
async def test_completed_on_defaults_to_server_day_and_actor_is_kept(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        started = await _start(client, planned=25, actor="parent")
        completed = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 25},
        )
        assert completed.status_code == 200, completed.text

    events = await _events(factory)
    assert len(events) == 1
    assert events[0].actor == "parent"
    assert json.loads(events[0].payload)["completed_on"] == TODAY.isoformat()


@pytest.mark.integration
async def test_completed_on_honors_client_local_day(tmp_path) -> None:
    """跨时区家庭：完成日由客户端本地日给出，服务端不拿 UTC 日覆盖它。"""

    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        started = await _start(client, planned=25)
        explicit = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 25, "completed_on": "2026-11-04"},
        )
        assert explicit.status_code == 200, explicit.text

    events = await _events(factory)
    assert len(events) == 1
    assert events[0].actor == "student"
    assert json.loads(events[0].payload)["completed_on"] == "2026-11-04"


@pytest.mark.integration
async def test_legacy_record_endpoint_keeps_clamping_and_does_not_create_sessions(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        legacy = await client.post(
            "/api/pomodoros",
            json={
                "duration_minutes": 4,
                "started_at": "2026-11-04T09:00:00+08:00",
                "completed_on": "2026-11-04",
            },
        )
        assert legacy.status_code == 201, legacy.text
        assert legacy.json()["duration_minutes"] == 5
        assert (await client.get("/api/pomodoros/active")).json()["session"] is None

        started = await _start(client, planned=25)
        completed = await client.post(
            f"/api/pomodoros/{started['id']}/complete",
            json={"duration_minutes": 25, "completed_on": TODAY.isoformat()},
        )
        assert completed.status_code == 200, completed.text

    assert await _count(factory, PomodoroSession) == 1
    assert len(await _events(factory)) == 2


@pytest.mark.integration
async def test_empty_active_is_null_not_404(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.get("/api/pomodoros/active")
        assert response.status_code == 200, response.text
        assert response.json() == {"session": None}
    assert await _count(factory, PomodoroSession) == 0


@pytest.mark.integration
async def test_session_row_stores_no_derived_remaining(tmp_path) -> None:
    """剩余时间不入库：表里只有开始时刻与计划时长（AGENTS §5 不存易变字段）。"""

    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        await _start(client, planned=25)
    rows = await _sessions(factory)
    assert len(rows) == 1
    assert set(rows[0].__table__.columns.keys()) == {
        "id",
        "started_at",
        "planned_minutes",
        "mistake_id",
        "actor",
        "status",
    }
