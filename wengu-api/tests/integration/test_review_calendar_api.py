"""P2-12 复习日历只读投影集成测试（v2.7 §18 D9；非自动排课、零迁移、零模型）。

覆盖 DoD：
- 3 条不同 due_date（逾期开放 / 已完成 / 未来开放）按日归属 + 逾期标记 + 不重复计；
- 回退口径专门一条：无 completed_on 的事件按 occurred_at 日期出现（变异删回退→红）；
- 白名单钉死：CALENDAR_EVENT_TYPES == 9 个字面串（增删任一 type 即红）；
- 无 completed_on 的 5 类逐类各一条、各自按 occurred_at 归日（删白名单成员→红）；
- 今日数字与 due_queue 一致（同一把尺）+ kind 逐条相等（变异 kind 恒 redo→红）；
- 跨度 >92 天 / from>to → 422；默认窗口 today-7..today+30；恰好 92 天放行；
- 与 /api/calendar/events 硬事件、课表槽互不混入；
- 只读：各表行数不变 + 零网络 + 同输入同输出。

fixture 自包含（与 test_reviews_api / test_dashboard_api 同约定），临时库 + 独立迁移，
不碰生产 data/。completed 态用直接置 completed_at 隔离阶梯副作用，聚焦投影本身。
"""

from __future__ import annotations

import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    CalendarEvent,
    GradingVersion,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    ReviewSchedule,
    TimetableSlot,
)
from app.services.calendar import CALENDAR_EVENT_TYPES
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "calendar.db"
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
        status = await client.get("/api/session/status")
        if status.json()["pin_set"]:
            response = await client.post("/api/session/unlock", json={"pin": "2468"})
        else:
            response = await client.post("/api/session/pin/set", json={"pin": "2468"})
        assert response.status_code == 200, response.text
        yield client


async def _seed_topic(
    factory: async_sessionmaker,
    *,
    topic_id: str = "cnm_test_equation",
    name: str = "一元一次方程",
    subject: str = "数学",
) -> None:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=topic_id,
                subject=subject,
                name=name,
                domain="数与代数",
                grade="七年级",
                semester="上册",
                chapter=name,
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )


async def _confirm_wrong(
    client: AsyncClient,
    *,
    suggested_topic_id: str = "cnm_test_equation",
) -> int:
    """外部转录 → 核对页确认入本（唯一写入路径），返回 mistake_id。"""

    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": "数学",
                    "problem_text": "一元一次方程：解方程 2x=4，注意移项",
                    "student_answer": "x=3",
                    "standard_answer": "x=2",
                    "error_cause_suggestion": "计算失误",
                    "suggested_topic_id": suggested_topic_id,
                    "source_ref": f"测试卷 第3题 {uuid4().hex}",
                    "captured_at": "2026-10-28",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch_id"]
    drafts = await client.get(f"/api/imports/{batch_id}/drafts")
    assert drafts.status_code == 200, drafts.text
    (draft_id,) = (draft["id"] for draft in drafts.json()["drafts"])
    confirmed = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm", json={"actor": "student"}
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["mistake_id"]


async def _set_due(
    factory: async_sessionmaker, mistake_id: int, day: date
) -> None:
    async with factory() as session, session.begin():
        rows = (
            await session.scalars(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
            )
        ).all()
        assert rows
        for row in rows:
            row.due_date = day


async def _mark_completed(
    factory: async_sessionmaker, mistake_id: int, when: datetime
) -> None:
    """直接置 completed_at（历史完成行），隔离阶梯派生新排期的副作用。"""

    async with factory() as session, session.begin():
        rows = (
            await session.scalars(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
            )
        ).all()
        assert rows
        for row in rows:
            row.completed_at = when


async def _set_primary_topic(
    factory: async_sessionmaker, mistake_id: int, topic_id: str | None
) -> None:
    async with factory() as session, session.begin():
        row = await session.get(Mistake, mistake_id)
        assert row is not None
        row.primary_topic_id = topic_id


async def _add_learning_event(
    factory: async_sessionmaker,
    *,
    type: str,
    occurred_at: datetime,
    payload: dict | None = None,
    mistake_id: int | None = None,
) -> None:
    async with factory() as session, session.begin():
        session.add(
            LearningEvent(
                type=type,
                actor="student",
                mistake_id=mistake_id,
                payload=json.dumps(payload) if payload is not None else None,
                occurred_at=occurred_at,
                idempotency_key=f"cal-test:{uuid4().hex}",
            )
        )


async def _add_hard_event(
    factory: async_sessionmaker, day: date, *, kind: str = "exam", title: str = "月考"
) -> None:
    async with factory() as session, session.begin():
        session.add(CalendarEvent(date=day, title=title, kind=kind))


async def _add_timetable_slot(
    factory: async_sessionmaker, *, weekday: int = 1, period: int = 1
) -> None:
    async with factory() as session, session.begin():
        session.add(TimetableSlot(weekday=weekday, period=period, subject="数学"))


async def _row_counts(factory: async_sessionmaker) -> dict[str, int]:
    async with factory() as session:
        return {
            name: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for name, model in (
                ("events", LearningEvent),
                ("mistakes", Mistake),
                ("schedules", ReviewSchedule),
                ("attempts", Attempt),
                ("grading_versions", GradingVersion),
                ("timetable_slots", TimetableSlot),
                ("calendar_events", CalendarEvent),
            )
        }


def _write_app_config(tmp_path: Path, limit: int) -> Path:
    path = tmp_path / "app-config.json"
    path.write_text(json.dumps({"daily_review_limit": limit}), encoding="utf-8")
    return path


def _boom(*_args, **_kwargs):
    raise AssertionError("复习日历只读端点不得发起任何网络调用")


async def _get_calendar(
    client: AsyncClient,
    *,
    today: date,
    from_: date | None = None,
    to: date | None = None,
) -> dict:
    params: dict[str, str] = {"today": today.isoformat()}
    if from_ is not None:
        params["from"] = from_.isoformat()
    if to is not None:
        params["to"] = to.isoformat()
    response = await client.get("/api/reviews/calendar", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _get_due(client: AsyncClient, today: date) -> dict:
    response = await client.get(
        "/api/reviews/due", params={"today": today.isoformat()}
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
async def test_calendar_three_due_dates_attribution_overdue_no_dup(tmp_path) -> None:
    """3 条不同 due_date：逾期开放 / 已完成 / 未来开放，按日归属 + 标记 + 不重复计。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    today = date(2026, 11, 15)
    overdue_day = today - timedelta(days=3)
    done_day = today - timedelta(days=1)
    future_day = today + timedelta(days=5)

    async with _client(factory) as client:
        a = await _confirm_wrong(client)
        b = await _confirm_wrong(client)
        c = await _confirm_wrong(client)
        await _set_due(factory, a, overdue_day)
        await _set_due(factory, b, done_day)
        await _mark_completed(factory, b, datetime(2026, 11, 14, 10, 0, tzinfo=UTC))
        await _set_due(factory, c, future_day)
        payload = await _get_calendar(
            client, today=today, from_=today - timedelta(days=7), to=today + timedelta(days=30)
        )

    days = {d["date"]: d for d in payload["days"]}
    assert [p["mistake_id"] for p in days[overdue_day.isoformat()]["planned"]] == [a]
    assert [p["mistake_id"] for p in days[done_day.isoformat()]["planned"]] == [b]
    assert [p["mistake_id"] for p in days[future_day.isoformat()]["planned"]] == [c]

    pa = days[overdue_day.isoformat()]["planned"][0]
    assert pa["overdue"] is True and pa["completed"] is False
    pb = days[done_day.isoformat()]["planned"][0]
    assert pb["overdue"] is False and pb["completed"] is True
    pc = days[future_day.isoformat()]["planned"][0]
    assert pc["overdue"] is False and pc["completed"] is False

    # 不重复计：每条排期恰好落在自己的 due_date 一天，全窗口共 3 条
    all_planned = [p for d in payload["days"] for p in d["planned"]]
    assert sorted(p["mistake_id"] for p in all_planned) == sorted([a, b, c])
    assert len(all_planned) == 3
    for p in all_planned:
        assert p["due_date"] == next(
            d["date"] for d in payload["days"] if p in d["planned"]
        )


@pytest.mark.integration
async def test_calendar_done_fallback_to_occurred_at(tmp_path) -> None:
    """回退口径专门一条：无 completed_on 按 occurred_at 日；有 completed_on 优先。

    变异靶点①：删掉 _calendar_day 的 _fallback_day 回退（改 return None）→
    review_scheduled / mistake_labeled 两条整类消失 → 本测试红；还原 → 绿。
    """

    factory = _migrated(tmp_path)
    today = date(2026, 10, 22)
    lo, hi = date(2026, 10, 18), date(2026, 10, 28)

    async with _client(factory) as client:
        await _add_learning_event(
            factory,
            type="review_scheduled",
            occurred_at=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
            payload={"subject": "数学"},
        )
        await _add_learning_event(
            factory,
            type="mistake_labeled",
            occurred_at=datetime(2026, 10, 21, 9, 30, tzinfo=UTC),
            payload={},
        )
        # completed_on(25) 与 occurred_at(22) 不同日：必须归到 25，而非 22
        await _add_learning_event(
            factory,
            type="attempt_correct",
            occurred_at=datetime(2026, 10, 22, 23, 30, tzinfo=UTC),
            payload={"completed_on": "2026-10-25", "source": "student_self"},
        )
        # 白名单外的 type：绝不出现（证明白名单真在过滤，而非照单全收）
        await _add_learning_event(
            factory,
            type="calendar_test_excluded",
            occurred_at=datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
            payload={},
        )
        payload = await _get_calendar(client, today=today, from_=lo, to=hi)

    days = {d["date"]: d for d in payload["days"]}

    def types(day: str) -> list[str]:
        return [e["type"] for e in days[day]["done"]]

    assert "review_scheduled" in types("2026-10-20")
    assert "mistake_labeled" in types("2026-10-21")
    assert "attempt_correct" in types("2026-10-25")
    assert "attempt_correct" not in types("2026-10-22")
    all_types = [e["type"] for d in payload["days"] for e in d["done"]]
    assert "calendar_test_excluded" not in all_types
    assert set(all_types) <= CALENDAR_EVENT_TYPES


@pytest.mark.unit
def test_calendar_event_types_whitelist_pinned() -> None:
    """守卫①：白名单钉死为 9 个真实 type 的字面串集合，增删任一即红。

    用字面串而非引用 services 常量：常量被改名/增删时本条独立变红，
    不会被"引用跟着同步改"掩盖。变异靶点③：从 CALENDAR_EVENT_TYPES
    删 mistake_primary_topic_set → 本条与守卫②同时红；还原 → 绿。
    """

    assert set(CALENDAR_EVENT_TYPES) == {
        "attempt_correct",
        "attempt_wrong",
        "recitation_reviewed",
        "pomodoro_completed",
        "review_scheduled",
        "mistake_labeled",
        "mistake_voided",
        "mistake_reactivated",
        "mistake_primary_topic_set",
    }


@pytest.mark.integration
async def test_calendar_done_five_no_completed_on_types_per_type(tmp_path) -> None:
    """守卫②：无 completed_on 的 5 类逐类各造一条，各自按 occurred_at 日出现。

    这 5 类真实写入都不带 completed_on；若照抄 dashboard 不回退口径会整类消失。
    逐类钉死归日（而非只覆盖 review_scheduled），其余 4 类不再裸奔。
    变异靶点③：删白名单成员 mistake_primary_topic_set → 本条与守卫①同时红。
    """

    factory = _migrated(tmp_path)
    today = date(2026, 10, 22)
    lo, hi = date(2026, 10, 18), date(2026, 10, 28)
    per_type_day = {
        "mistake_labeled": date(2026, 10, 19),
        "mistake_voided": date(2026, 10, 20),
        "mistake_reactivated": date(2026, 10, 21),
        "review_scheduled": date(2026, 10, 22),
        "mistake_primary_topic_set": date(2026, 10, 23),
    }

    async with _client(factory) as client:
        for type_, day in per_type_day.items():
            await _add_learning_event(
                factory,
                type=type_,
                occurred_at=datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC),
                payload={},  # 无 completed_on → 必须回退 occurred_at
            )
        payload = await _get_calendar(client, today=today, from_=lo, to=hi)

    days = {d["date"]: d for d in payload["days"]}
    for type_, day in per_type_day.items():
        assert type_ in [e["type"] for e in days[day.isoformat()]["done"]], (type_, day)
    all_done = [e["type"] for d in payload["days"] for e in d["done"]]
    assert sorted(all_done) == sorted(per_type_day)  # 每类恰一条、不重不漏


@pytest.mark.integration
async def test_calendar_today_matches_due_queue_and_kind_per_item(
    tmp_path, monkeypatch
) -> None:
    """今日数字与 due_queue 同一把尺 + kind 逐条相等（quiz / redo 混合）。

    变异靶点②：把 build_calendar 的 kind 改成恒 "redo"（另算一套）→
    与 due_queue 的 kind 对齐断言红；还原 → 绿。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory)  # cnm_test_equation：无题 → redo
    await _seed_topic(factory, topic_id="cnm_001", name="有理数", subject="数学")  # 有题 → quiz
    monkeypatch.setenv("WENGU_APP_CONFIG", str(_write_app_config(tmp_path, 10)))
    today = date(2026, 11, 15)

    async with _client(factory) as client:
        m_quiz1 = await _confirm_wrong(client)
        m_redo = await _confirm_wrong(client)
        m_quiz2 = await _confirm_wrong(client)
        await _set_primary_topic(factory, m_quiz1, "cnm_001")
        await _set_primary_topic(factory, m_quiz2, "cnm_001")
        await _set_due(factory, m_quiz1, today - timedelta(days=1))
        await _set_due(factory, m_redo, today)
        await _set_due(factory, m_quiz2, today)
        due = await _get_due(client, today)
        cal = await _get_calendar(
            client, today=today, from_=today - timedelta(days=7), to=today + timedelta(days=30)
        )

    # 同一把尺：开放且 due<=today 的 planned 计数 == due_queue.due_total
    open_due = [
        p
        for d in cal["days"]
        if d["date"] <= today.isoformat()
        for p in d["planned"]
        if not p["completed"]
    ]
    assert len(open_due) == due["due_total"] == 3

    # kind 逐条相等：日历不得另建判定
    cal_kind = {p["mistake_id"]: p["kind"] for p in open_due}
    due_kind = {i["mistake_id"]: i["task"] for i in due["items"]}
    assert cal_kind == due_kind
    assert due_kind[m_quiz1] == "quiz"
    assert due_kind[m_redo] == "redo"
    assert due_kind[m_quiz2] == "quiz"


@pytest.mark.integration
async def test_calendar_range_validation_and_default_window(tmp_path) -> None:
    """from>to → 422；跨度 >92 → 422；恰好 92 放行；默认 today-7..today+30。"""

    factory = _migrated(tmp_path)
    today = date(2026, 11, 15)

    async with _client(factory) as client:
        inverted = await client.get(
            "/api/reviews/calendar",
            params={
                "today": today.isoformat(),
                "from": (today + timedelta(days=1)).isoformat(),
                "to": today.isoformat(),
            },
        )
        assert inverted.status_code == 422

        too_wide = await client.get(
            "/api/reviews/calendar",
            params={
                "today": today.isoformat(),
                "from": today.isoformat(),
                "to": (today + timedelta(days=93)).isoformat(),
            },
        )
        assert too_wide.status_code == 422

        exact = await client.get(
            "/api/reviews/calendar",
            params={
                "today": today.isoformat(),
                "from": today.isoformat(),
                "to": (today + timedelta(days=92)).isoformat(),
            },
        )
        assert exact.status_code == 200, exact.text
        assert len(exact.json()["days"]) == 93

        default = await client.get(
            "/api/reviews/calendar", params={"today": today.isoformat()}
        )
        assert default.status_code == 200, default.text
        body = default.json()
        assert body["from"] == (today - timedelta(days=7)).isoformat()
        assert body["to"] == (today + timedelta(days=30)).isoformat()
        assert body["today"] == today.isoformat()
        assert len(body["days"]) == 38


@pytest.mark.integration
async def test_calendar_does_not_mix_hard_events_or_timetable(tmp_path) -> None:
    """硬事件（考试）/ 课表槽属 /schedule，绝不混入复习日历的 planned/done。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    today = date(2026, 11, 15)

    async with _client(factory) as client:
        m = await _confirm_wrong(client)
        await _set_due(factory, m, today)
        await _add_hard_event(factory, today, kind="exam", title="月考")
        await _add_timetable_slot(factory, weekday=today.isoweekday(), period=1)
        cal = await _get_calendar(
            client, today=today, from_=today - timedelta(days=7), to=today + timedelta(days=30)
        )
        hard = await client.get(
            "/api/calendar/events",
            params={"from": today.isoformat(), "to": today.isoformat()},
        )

    assert hard.status_code == 200, hard.text
    assert len(hard.json()["items"]) == 1  # 硬事件仍在自己的端点，未被日历吞掉

    day = next(d for d in cal["days"] if d["date"] == today.isoformat())
    assert [p["mistake_id"] for p in day["planned"]] == [m]
    all_done = [e["type"] for d in cal["days"] for e in d["done"]]
    assert set(all_done) <= CALENDAR_EVENT_TYPES
    assert "exam" not in all_done


@pytest.mark.integration
async def test_calendar_is_read_only_zero_write_zero_network(
    tmp_path, monkeypatch
) -> None:
    """只读：各表行数不变 + 零网络 + 同输入同输出（确定性投影）。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_001", name="有理数", subject="数学")
    today = date(2026, 11, 15)

    async with _client(factory) as client:
        m = await _confirm_wrong(client)
        await _set_primary_topic(factory, m, "cnm_001")
        await _set_due(factory, m, today)
        before = await _row_counts(factory)
        with monkeypatch.context() as guard:
            guard.setattr(socket, "create_connection", _boom)
            guard.setattr(socket.socket, "connect", _boom)
            first = await _get_calendar(
                client, today=today, from_=today - timedelta(days=7), to=today + timedelta(days=30)
            )
            second = await _get_calendar(
                client, today=today, from_=today - timedelta(days=7), to=today + timedelta(days=30)
            )
        after = await _row_counts(factory)

    assert before == after  # 纯查询：零写入
    assert first == second  # 同输入同输出
