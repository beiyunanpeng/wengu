"""P2-3 课表/日历集成测试：孩子只读同见、家长写、校验 422、窗口查询。

口径（TICKETS P2-3）：
- 课表/日历是约束层，不生成任务；写操作只挂 require_parent，孩子区读不受影响；
- weekday 1–7、period 1–12、kind 枚举、日期合法 → 422；一节一科 → 409；
- 事件按日期升序，缺省未来 30 天（含今天）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "schedule.db"
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


async def _unlock(client: AsyncClient) -> None:
    status = await client.get("/api/session/status")
    if status.json()["pin_set"]:
        response = await client.post("/api/session/unlock", json={"pin": PIN})
    else:
        response = await client.post("/api/session/pin/set", json={"pin": PIN})
    assert response.status_code == 200, response.text


@pytest.mark.integration
async def test_child_reads_are_open_and_writes_need_parent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        for path in ("/api/timetable", "/api/calendar/events"):
            response = await client.get(path)
            assert response.status_code == 200, (path, response.text)
            assert response.json() == {"items": []}

        locked = [
            await client.post(
                "/api/timetable/slots",
                json={"weekday": 1, "period": 1, "subject": "数学"},
            ),
            await client.delete("/api/timetable/slots/1"),
            await client.post(
                "/api/calendar/events",
                json={"date": "2026-11-10", "title": "月考", "kind": "exam"},
            ),
            await client.delete("/api/calendar/events/1"),
        ]
        assert [response.status_code for response in locked] == [403] * 4

        await _unlock(client)
        created = await client.post(
            "/api/timetable/slots",
            json={"weekday": 1, "period": 1, "subject": "数学"},
        )
        assert created.status_code == 201, created.text
        # 孩子区读仍不需要 PIN，且能看到家长刚录入的课表
        assert (await client.get("/api/timetable")).json()["items"][0][
            "subject"
        ] == "数学"


@pytest.mark.integration
async def test_timetable_slot_crud_validation_and_ordering(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        await _unlock(client)

        invalid_payloads = [
            {"weekday": 0, "period": 1, "subject": "数学"},
            {"weekday": 8, "period": 1, "subject": "数学"},
            {"weekday": 1, "period": 0, "subject": "数学"},
            {"weekday": 1, "period": 13, "subject": "数学"},
            {"weekday": 1, "period": 1, "subject": ""},
            {"weekday": 1, "period": 1, "subject": "   "},
            {"weekday": 1, "period": 1, "subject": "数学" * 30},
        ]
        for payload in invalid_payloads:
            response = await client.post("/api/timetable/slots", json=payload)
            assert response.status_code == 422, (payload, response.text)

        created = []
        for weekday, period, subject, note in (
            (3, 2, "英语", None),
            (1, 2, "数学", "讲评"),
            (1, 1, "语文", None),
        ):
            response = await client.post(
                "/api/timetable/slots",
                json={
                    "weekday": weekday,
                    "period": period,
                    "subject": subject,
                    "note": note,
                },
            )
            assert response.status_code == 201, response.text
            created.append(response.json())

        listing = (await client.get("/api/timetable")).json()["items"]
        assert [(row["weekday"], row["period"]) for row in listing] == [
            (1, 1),
            (1, 2),
            (3, 2),
        ]
        assert listing[1]["note"] == "讲评"
        assert listing[0]["note"] is None

        duplicate = await client.post(
            "/api/timetable/slots",
            json={"weekday": 1, "period": 1, "subject": "物理"},
        )
        assert duplicate.status_code == 409, duplicate.text

        deleted = await client.delete(f"/api/timetable/slots/{created[0]['id']}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": created[0]["id"]}
        remaining = (await client.get("/api/timetable")).json()["items"]
        assert (1, 2, "数学") in [
            (row["weekday"], row["period"], row["subject"])
            for row in remaining
        ]
        assert created[0]["id"] not in [row["id"] for row in remaining]

        missing = await client.delete(f"/api/timetable/slots/{created[0]['id']}")
        assert missing.status_code == 404


@pytest.mark.integration
async def test_calendar_event_crud_window_and_ordering(tmp_path) -> None:
    factory = _migrated(tmp_path)
    today = date.today()
    async with _client(factory) as client:
        await _unlock(client)

        invalid_payloads = [
            {"date": "2026-11-10", "title": "月考", "kind": "holiday"},
            {"date": "2026-02-30", "title": "月考", "kind": "exam"},
            {"date": "2026-11-10", "title": "   ", "kind": "exam"},
            {"date": "2026-11-10", "title": "月考", "kind": "exam", "subject": " "},
        ]
        for payload in invalid_payloads:
            response = await client.post("/api/calendar/events", json=payload)
            assert response.status_code == 422, (payload, response.text)

        entries = [
            (today + timedelta(days=10), "月考", "exam", "数学"),
            (today + timedelta(days=3), "数学竞赛", "competition", None),
            (today + timedelta(days=40), "期末", "exam", None),
            (today - timedelta(days=2), "请假", "leave", None),
        ]
        created: list[dict] = []
        for day, title, kind, subject in entries:
            response = await client.post(
                "/api/calendar/events",
                json={
                    "date": day.isoformat(),
                    "title": title,
                    "kind": kind,
                    "subject": subject,
                },
            )
            assert response.status_code == 201, response.text
            created.append(response.json())

        window = await client.get(
            "/api/calendar/events",
            params={
                "from": today.isoformat(),
                "to": (today + timedelta(days=30)).isoformat(),
            },
        )
        assert window.status_code == 200, window.text
        items = window.json()["items"]
        assert [item["date"] for item in items] == [
            (today + timedelta(days=3)).isoformat(),
            (today + timedelta(days=10)).isoformat(),
        ]
        assert [item["kind"] for item in items] == ["competition", "exam"]
        assert items[1]["subject"] == "数学"

        # 缺省窗口 = 今天起未来 30 天，与显式传参一致
        default_window = (await client.get("/api/calendar/events")).json()
        assert default_window == window.json()

        past = await client.get(
            "/api/calendar/events",
            params={
                "from": (today - timedelta(days=5)).isoformat(),
                "to": today.isoformat(),
            },
        )
        assert [item["kind"] for item in past.json()["items"]] == ["leave"]

        reversed_window = await client.get(
            "/api/calendar/events",
            params={
                "from": today.isoformat(),
                "to": (today - timedelta(days=1)).isoformat(),
            },
        )
        assert reversed_window.status_code == 422

        removed = await client.delete(
            f"/api/calendar/events/{created[0]['id']}"
        )
        assert removed.status_code == 200
        assert removed.json() == {"deleted": created[0]["id"]}
        after = (await client.get("/api/calendar/events")).json()["items"]
        assert created[0]["id"] not in [item["id"] for item in after]

        missing = await client.delete(f"/api/calendar/events/{created[0]['id']}")
        assert missing.status_code == 404
