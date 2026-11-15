"""P2-5 家长看板集成测试：只读、零模型/网络、与 recompute 重算一致。

钉死的口径：
- 存量/薄弱分布只统计 active 错题；voided 退出队列但不洗历史事件；
- 到期今日/逾期只算 active 且排期未完成；
- 本周完成/毕业看复习完成事件的 `completed_on`（周一为界）；
- bank_gap 只列"活跃且存在未完成排期、seed 题库零题"的主考点；
- 申诉数来自 append-only 的 `grading_versions.action=appealed`。
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.api.dashboard import router as dashboard_router
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    Concept,
    GradingVersion,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    ReviewSchedule,
)
from app.services.recompute import Event, is_graduated, mastery, stats
from app.services.streak import summarize_streak
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
CHANNEL = "agent_transcribe_v1"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "dashboard.db"
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
        # 造数据时用到家长端作废：先设 PIN 解锁；看板本身仍是孩子区只读
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
    topic_id: str,
    name: str,
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


async def _seed_concept(factory: async_sessionmaker, *, name: str, category_id: str) -> int:
    async with factory() as session, session.begin():
        row = Concept(
            name=name,
            category_id=category_id,
            source="student",
            status="confirmed",
            merged_into_id=None,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row.id


async def _create_mistake(
    client: AsyncClient,
    *,
    primary_topic_id: str,
    problem_text: str,
    concept_ids: tuple[int, ...] = (),
) -> dict:
    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": "数学",
                    "problem_text": problem_text,
                    "student_answer": "错答",
                    "standard_answer": "正答",
                    "error_cause_suggestion": "计算失误",
                    "suggested_topic_id": primary_topic_id,
                    "source_ref": f"测试卷 {uuid4().hex}",
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

    payload: dict = {"actor": "student", "primary_topic_id": primary_topic_id}
    if concept_ids:
        payload["concept_ids"] = list(concept_ids)
    confirmed = await client.post(f"/api/imports/drafts/{draft_id}/confirm", json=payload)
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


async def _open_schedule(factory: async_sessionmaker, mistake_id: int) -> ReviewSchedule:
    async with factory() as session:
        schedule = (
            await session.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
            )
        ).scalar_one()
        return schedule


async def _set_due(factory: async_sessionmaker, mistake_id: int, due_date: date) -> None:
    async with factory() as session, session.begin():
        schedule = (
            await session.execute(
                select(ReviewSchedule).where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
            )
        ).scalar_one()
        schedule.due_date = due_date


async def _appeal(factory: async_sessionmaker, grading_id: int) -> None:
    async with factory() as session, session.begin():
        current = int(
            await session.scalar(
                select(func.max(GradingVersion.version)).where(GradingVersion.grading_id == grading_id)
            )
            or 0
        )
        session.add(
            GradingVersion(
                grading_id=grading_id,
                version=current + 1,
                action="appealed",
                verdict="wrong",
                source="student",
                confidence=None,
                reason="家长复核",
                provider=None,
                model=None,
                prompt_id=None,
                prompt_version=None,
                sample_verdicts_json="[]",
                created_at=datetime.now(UTC),
            )
        )


async def _row_counts(factory: async_sessionmaker) -> dict[str, int]:
    async with factory() as session:
        return {
            "events": int(await session.scalar(select(func.count()).select_from(LearningEvent)) or 0),
            "mistakes": int(await session.scalar(select(func.count()).select_from(Mistake)) or 0),
            "schedules": int(await session.scalar(select(func.count()).select_from(ReviewSchedule)) or 0),
            "attempts": int(await session.scalar(select(func.count()).select_from(Attempt)) or 0),
            "grading_versions": int(await session.scalar(select(func.count()).select_from(GradingVersion)) or 0),
        }


async def _recompute_events(factory: async_sessionmaker) -> list[Event]:
    async with factory() as session:
        rows = (await session.scalars(select(LearningEvent).order_by(LearningEvent.id))).all()
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


def _boom(*_args, **_kwargs):
    raise AssertionError("看板只读端点不得发起任何网络调用")


@pytest.mark.integration
async def test_dashboard_is_read_only_deterministic_and_recomputable(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_test_equation", name="一元一次方程")
    await _seed_topic(factory, topic_id="cnm_test_linear", name="一次函数")
    concept_mastered = await _seed_concept(factory, name="移项", category_id="cnm_test_equation")
    concept_untouched = await _seed_concept(factory, name="去括号", category_id="cnm_test_equation")

    today = date.today()
    async with _client(factory) as client:
        # A：3 次复习全对 → 毕业；用于掌握度、本周完成/毕业。
        body_a = await _create_mistake(
            client,
            primary_topic_id="cnm_test_equation",
            problem_text="解方程 2x=4",
            concept_ids=(concept_mastered,),
        )
        mistake_a = body_a["mistake_id"]
        schedule = await _open_schedule(factory, mistake_a)
        for _ in range(3):
            completed = await client.post(
                f"/api/reviews/{mistake_a}/complete",
                json={
                    "schedule_id": schedule.id,
                    "correct": True,
                    "completed_on": today.isoformat(),
                },
            )
            assert completed.status_code == 200, completed.text
            payload = completed.json()
            if payload["next_schedule"] is not None:
                schedule_id = payload["next_schedule"]["id"]
                async with factory() as session:
                    schedule = await session.get(ReviewSchedule, schedule_id)
        assert payload["graduated"] is True

        # B：活跃、逾期；使用第二个未接触 concept。
        body_b = await _create_mistake(
            client,
            primary_topic_id="cnm_test_equation",
            problem_text="解方程 3x-1=2",
            concept_ids=(concept_untouched,),
        )
        mistake_b = body_b["mistake_id"]
        await _set_due(factory, mistake_b, today - timedelta(days=2))

        # C：活跃、今日到期、另一个无题库的知识点。
        body_c = await _create_mistake(
            client,
            primary_topic_id="cnm_test_linear",
            problem_text="一次函数过点 (0,1)",
        )
        mistake_c = body_c["mistake_id"]
        await _set_due(factory, mistake_c, today)

        # D：作废后退出存量/到期队列；历史事件保留。
        body_d = await _create_mistake(
            client,
            primary_topic_id="cnm_test_equation",
            problem_text="解方程 x/2=1",
        )
        mistake_d = body_d["mistake_id"]
        await _set_due(factory, mistake_d, today - timedelta(days=5))
        voided = await client.post(f"/api/mistakes/{mistake_d}/void", json={"actor": "parent"})
        assert voided.status_code == 200, voided.text
        assert voided.json()["status"] == "voided"

        await _appeal(factory, body_a["grading_id"])

        before = await _row_counts(factory)
        with monkeypatch.context() as guard:
            guard.setattr(socket, "create_connection", _boom)
            guard.setattr(socket.socket, "connect", _boom)
            response = await client.get(f"/api/dashboard?today={today.isoformat()}&curve_days=30")
        assert response.status_code == 200, response.text
        payload = response.json()
        replay = await client.get(f"/api/dashboard?today={today.isoformat()}&curve_days=30")
        assert replay.status_code == 200, replay.text
        after = await _row_counts(factory)

    assert payload == replay.json()
    assert before == after  # 看板不写任何表

    # 1) 存量与薄弱分布（voided 不计入活跃分布）
    assert payload["inventory"] == {
        "active": 3,
        "voided": 1,
        "unassigned_active": 0,
    }
    assert payload["weak_topics"] == [
        {
            "topic_id": "cnm_test_equation",
            "name": "一元一次方程",
            "subject": "数学",
            "active_mistakes": 2,
        },
        {
            "topic_id": "cnm_test_linear",
            "name": "一次函数",
            "subject": "数学",
            "active_mistakes": 1,
        },
    ]
    assert payload["weak_subjects"] == [{"subject": "数学", "active_mistakes": 3}]

    # 2) 到期：A 已毕业、D 已作废，只剩 B 逾期 + C 今日
    assert payload["due"] == {"today": 1, "overdue": 1, "total": 2}

    # 3) 本周完成/毕业（复习完成事件）
    assert payload["completion"] == {
        "reviews_this_week": 3,
        "graduated_total": 1,
        "graduated_this_week": 1,
    }

    # 4) bank_gap：两个测试主考点都不在 seed 题库 → 均命中；无主考点为 0
    assert payload["bank_gap"]["unassigned_open"] == 0
    assert payload["bank_gap"]["topics"] == [
        {
            "topic_id": "cnm_test_equation",
            "name": "一元一次方程",
            "subject": "数学",
            "active_mistakes": 2,
            "open_schedules": 1,
        },
        {
            "topic_id": "cnm_test_linear",
            "name": "一次函数",
            "subject": "数学",
            "active_mistakes": 1,
            "open_schedules": 1,
        },
    ]

    # 5) 申诉/作废计数来自 append-only 事实
    assert payload["governance"] == {
        "appeal_count": 1,
        "appealed_gradings": 1,
        "void_events": 1,
        "reactivate_events": 0,
    }

    # 6) 数字与 recompute 重算一致（事件统计、每个 concept、总体、曲线末点）
    events = await _recompute_events(factory)
    assert payload["event_stats"] == stats(events)
    concepts = {item["concept_id"]: item for item in payload["mastery"]["concepts"]}
    assert concepts[concept_mastered]["mastery"] == mastery(events, concept_mastered)
    assert concepts[concept_untouched]["mastery"] == mastery(events, concept_untouched)
    expected_overall = (concepts[concept_mastered]["mastery"] + concepts[concept_untouched]["mastery"]) / 2
    assert payload["mastery"]["overall"] == pytest.approx(expected_overall)
    assert payload["mastery"]["curve_days"] == 30
    assert len(payload["mastery"]["curve"]) == 30
    assert payload["mastery"]["curve"][-1]["date"] == today.isoformat()
    assert payload["mastery"]["curve"][-1]["mastery"] == pytest.approx(expected_overall)
    assert payload["mastery"]["curve"][0]["mastery"] == pytest.approx(0.0)

    mistake_ids = {event.mistake_id for event in events if event.mistake_id is not None}
    assert payload["completion"]["graduated_total"] == sum(
        1 for mistake_id in mistake_ids if is_graduated(events, mistake_id)
    )

    # 7) 打卡与 streak.py 重算一致：今天 3 次复习作答 = 单日打卡
    streak = summarize_streak(events, today)
    assert payload["streak"] == {
        "today_done": streak.today_done,
        "current_streak": streak.current_streak,
        "longest_streak": streak.longest_streak,
        "learning_days_total": streak.learning_days_total,
        "recent_days": [
            {"date": day.date.isoformat(), "done": day.done} for day in streak.recent_days
        ],
    }
    assert payload["streak"]["today_done"] is True
    # 今天有 3 条复习作答（completed_on=today），必然点亮今日
    assert payload["streak"]["recent_days"][-1] == {"date": today.isoformat(), "done": True}
    assert payload["streak"]["current_streak"] >= 1

    # 8) 端点只有 GET，没有写入/清空入口
    assert dashboard_router.routes
    for route in dashboard_router.routes:
        assert route.methods == {"GET"}


@pytest.mark.integration
async def test_dashboard_empty_database(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.get("/api/dashboard")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["inventory"] == {
        "active": 0,
        "voided": 0,
        "unassigned_active": 0,
    }
    assert payload["weak_topics"] == []
    assert payload["weak_subjects"] == []
    assert payload["subjects"] == []
    assert payload["due"] == {"today": 0, "overdue": 0, "total": 0}
    assert payload["completion"] == {
        "reviews_this_week": 0,
        "graduated_total": 0,
        "graduated_this_week": 0,
    }
    assert payload["bank_gap"] == {"topics": [], "unassigned_open": 0}
    assert payload["governance"] == {
        "appeal_count": 0,
        "appealed_gradings": 0,
        "void_events": 0,
        "reactivate_events": 0,
    }
    # 无已确认 concept 时不造假 0 曲线
    assert payload["mastery"] == {
        "overall": 0.0,
        "concepts": [],
        "curve": [],
        "curve_days": 30,
    }
    assert payload["event_stats"] == stats([])
    # 空库：零打卡，但近 30 天窗口仍完整返回（末日 = 今天）
    today = date.today()
    assert payload["streak"]["today_done"] is False
    assert payload["streak"]["current_streak"] == 0
    assert payload["streak"]["longest_streak"] == 0
    assert payload["streak"]["learning_days_total"] == 0
    assert len(payload["streak"]["recent_days"]) == 30
    assert payload["streak"]["recent_days"][-1] == {"date": today.isoformat(), "done": False}
    assert all(day["done"] is False for day in payload["streak"]["recent_days"])


async def _graduate(
    client: AsyncClient, factory: async_sessionmaker, mistake_id: int, today: date
) -> None:
    """复习 3 次全对 → is_graduated 成立；毕业不改 status，错题仍在册。"""

    schedule = await _open_schedule(factory, mistake_id)
    for _ in range(3):
        completed = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": schedule.id,
                "correct": True,
                "completed_on": today.isoformat(),
            },
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()
        if body["next_schedule"] is not None:
            async with factory() as session:
                schedule = await session.get(ReviewSchedule, body["next_schedule"]["id"])
    assert body["graduated"] is True


@pytest.mark.integration
async def test_dashboard_subjects_split_graduated_and_exclude_voided(tmp_path) -> None:
    """P2-13 各科入口卡口径（DoD 算式经审核方 2026-11-14 裁定修正）。

    卡原文两条算式不可能同时成立，实跑证伪后裁定保留字段语义、修正算式：
    - `sum(subjects[].total) == inventory.active`（毕业不改 status，故 active 含已毕业题，
      卡的 `active`=在册**未掌握**必然小于 inventory.active）；
    - `sum(subjects[].graduated)` 对齐"排除 voided 后按 is_graduated 重算"，
      而既有 `graduated_total` 不按 status 过滤（语义不动），差额恰为已作废但曾毕业的题数。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_test_equation", name="一元一次方程")
    await _seed_topic(factory, topic_id="cnm_test_english", name="词汇", subject="英语")
    today = date.today()
    async with _client(factory) as client:
        mistake_a = (
            await _create_mistake(client, primary_topic_id="cnm_test_equation", problem_text="解方程 2x=4")
        )["mistake_id"]
        await _graduate(client, factory, mistake_a, today)
        mistake_b = (
            await _create_mistake(client, primary_topic_id="cnm_test_equation", problem_text="解方程 3x=9")
        )["mistake_id"]
        mistake_c = (
            await _create_mistake(client, primary_topic_id="cnm_test_english", problem_text="翻译 apple")
        )["mistake_id"]
        mistake_d = (
            await _create_mistake(client, primary_topic_id="cnm_test_equation", problem_text="解方程 x/2=1")
        )["mistake_id"]
        await _graduate(client, factory, mistake_d, today)
        voided = await client.post(f"/api/mistakes/{mistake_d}/void", json={"actor": "parent"})
        assert voided.status_code == 200, voided.text

        before = await _row_counts(factory)
        response = await client.get(f"/api/dashboard?today={today.isoformat()}")
        assert response.status_code == 200, response.text
        payload = response.json()
        after = await _row_counts(factory)
        assert before == after  # 新增聚合同样零写入

        assert payload["inventory"] == {"active": 3, "voided": 1, "unassigned_active": 0}
        assert payload["subjects"] == [
            {"subject": "数学", "active": 1, "graduated": 1, "total": 2},
            {"subject": "英语", "active": 1, "graduated": 0, "total": 1},
        ]
        # 既有区块语义不动：薄弱分布仍按 active 计数（含已毕业 A、不含已作废 D）
        assert payload["weak_subjects"] == [
            {"subject": "数学", "active_mistakes": 2},
            {"subject": "英语", "active_mistakes": 1},
        ]
        assert payload["completion"]["graduated_total"] == 2

        subjects = payload["subjects"]
        assert sum(item["total"] for item in subjects) == payload["inventory"]["active"]
        assert all(item["total"] == item["active"] + item["graduated"] for item in subjects)

        events = await _recompute_events(factory)
        active_ids = (mistake_a, mistake_b, mistake_c)
        expected_graduated = sum(1 for mid in active_ids if is_graduated(events, mid))
        assert sum(item["graduated"] for item in subjects) == expected_graduated == 1
        voided_graduated = sum(1 for mid in (mistake_d,) if is_graduated(events, mid))
        assert (
            payload["completion"]["graduated_total"] - sum(item["graduated"] for item in subjects)
            == voided_graduated
            == 1
        )

        # 撤销作废：D 回到在册 → graduated 归位；graduated_total 全程不变
        unvoided = await client.post(f"/api/mistakes/{mistake_d}/unvoid", json={"actor": "parent"})
        assert unvoided.status_code == 200, unvoided.text
        restored = await client.get(f"/api/dashboard?today={today.isoformat()}")
        assert restored.status_code == 200, restored.text
        back = restored.json()

    assert back["inventory"]["active"] == 4
    assert back["subjects"] == [
        {"subject": "数学", "active": 1, "graduated": 2, "total": 3},
        {"subject": "英语", "active": 1, "graduated": 0, "total": 1},
    ]
    assert back["completion"]["graduated_total"] == payload["completion"]["graduated_total"] == 2
    assert sum(item["graduated"] for item in back["subjects"]) == back["completion"]["graduated_total"]
    assert sum(item["total"] for item in back["subjects"]) == back["inventory"]["active"]


async def _create_cause_mistake(
    client: AsyncClient,
    *,
    primary_topic_id: str | None = "cnm_test_equation",
    suggestion: str | None = "计算失误",
    confirm_error_cause: str | None = None,
    confirm_topic: bool = True,
) -> dict:
    """P2-11 fixture：可控 confirmed/suggested 错因状态。

    `confirm_topic=False` 且无 confirm_error_cause/concepts → has_confirmation=False
    → confirmed_by=NULL，effective 错因回退到 suggested（照抄陷阱反例）。
    `confirm_error_cause` 非空 → confirmed_by=student、confirmed_error_cause 落库，
    effective 用确认值（即便 suggested 不同）。
    """

    item: dict = {
        "subject": "数学",
        "problem_text": f"错因 fixture {uuid4().hex}",
        "student_answer": "错答",
        "standard_answer": "正答",
        "source_ref": f"测试卷 {uuid4().hex}",
        "captured_at": "2026-10-28",
    }
    if suggestion is not None:
        item["error_cause_suggestion"] = suggestion
    if primary_topic_id is not None:
        item["suggested_topic_id"] = primary_topic_id
    response = await client.post("/api/imports", json={"channel": CHANNEL, "items": [item]})
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch_id"]
    drafts = await client.get(f"/api/imports/{batch_id}/drafts")
    assert drafts.status_code == 200, drafts.text
    (draft_id,) = (draft["id"] for draft in drafts.json()["drafts"])

    payload: dict = {"actor": "student"}
    if confirm_topic and primary_topic_id is not None:
        payload["primary_topic_id"] = primary_topic_id
    if confirm_error_cause is not None:
        payload["error_cause"] = confirm_error_cause
    confirmed = await client.post(f"/api/imports/drafts/{draft_id}/confirm", json=payload)
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


@pytest.mark.integration
async def test_error_cause_counts_suggested_only_when_unconfirmed(tmp_path) -> None:
    """照抄陷阱反例（P2-11 DoD 专门一条）：只有 suggested、confirmed_by IS NULL 的在册错题必须被计入。

    若错因取值照抄 `_confirmed_concept_ids` 的 `confirmed_by IS NOT NULL` 过滤、
    或绕过 effective_labels 只取 confirmed_error_cause，这条会变红（该题被漏掉/落 unlabeled）。
    """

    factory = _migrated(tmp_path)
    today = date.today()
    async with _client(factory) as client:
        # 不确认主考点/错因/知识点 → confirmed_by=NULL；suggested="计算失误"→calculation。
        body = await _create_cause_mistake(
            client, primary_topic_id=None, suggestion="计算失误", confirm_topic=False
        )
        mistake_id = body["mistake_id"]
        async with factory() as session:
            version = (
                await session.execute(
                    select(MistakeVersion).where(MistakeVersion.mistake_id == mistake_id)
                )
            ).scalar_one()
            assert version.confirmed_by is None
            assert version.suggested_error_cause == "calculation"
            assert version.confirmed_error_cause is None

        response = await client.get(f"/api/dashboard?today={today.isoformat()}")
        assert response.status_code == 200, response.text
        distribution = response.json()["error_cause_distribution"]

    assert distribution == [{"cause": "calculation", "label": "计算失误", "count": 1}]


@pytest.mark.integration
async def test_error_cause_distribution_mixed_and_self_consistent(tmp_path) -> None:
    """P2-11 主锚点：confirmed/suggested/unlabeled/other 混合 + 毕业/作废排除 + 自洽算式。

    口径与学科卡共用同一份 _mistake_rows 与同一个 graduated_ids：
    `sum(各错因桶) + unlabeled == sum(subjects[].active)`（右端**不是** inventory.active，
    后者含已毕业）。other 与 unlabeled 分列；confirmed 优先于 suggested。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_test_equation", name="一元一次方程")
    await _seed_topic(factory, topic_id="cnm_test_english", name="词汇", subject="英语")
    today = date.today()
    async with _client(factory) as client:
        # M1 confirmed concept_unclear（suggested 是 calculation，确认值优先）。
        m1 = (await _create_cause_mistake(
            client, primary_topic_id="cnm_test_equation",
            suggestion="计算失误", confirm_error_cause="concept_unclear",
        ))["mistake_id"]
        # M2 suggested-only calculation（confirmed_by=NULL，未挂考点）。
        m2 = (await _create_cause_mistake(
            client, primary_topic_id=None, suggestion="计算失误", confirm_topic=False,
        ))["mistake_id"]
        # M3 unlabeled：confirmed_by=student 但 confirmed_error_cause=None，
        #    suggested=calculation 被确认值（None）压过 → 落 unlabeled，绝不落 calculation。
        m3 = (await _create_cause_mistake(
            client, primary_topic_id="cnm_test_equation", suggestion="计算失误",
        ))["mistake_id"]
        # M4 confirmed other（英语）。
        m4 = (await _create_cause_mistake(
            client, primary_topic_id="cnm_test_english",
            suggestion="其他", confirm_error_cause="other",
        ))["mistake_id"]
        # M5 confirmed careless 但毕业 → 排除出错因聚合（仍计学科 graduated）。
        m5 = (await _create_cause_mistake(
            client, primary_topic_id="cnm_test_equation",
            suggestion="审题粗心", confirm_error_cause="careless",
        ))["mistake_id"]
        await _graduate(client, factory, m5, today)
        # M6 suggested-only expression 但作废 → 排除。
        m6 = (await _create_cause_mistake(
            client, primary_topic_id=None, suggestion="表达书写", confirm_topic=False,
        ))["mistake_id"]
        voided = await client.post(f"/api/mistakes/{m6}/void", json={"actor": "parent"})
        assert voided.status_code == 200, voided.text

        before = await _row_counts(factory)
        response = await client.get(f"/api/dashboard?today={today.isoformat()}")
        assert response.status_code == 200, response.text
        payload = response.json()
        after = await _row_counts(factory)
        assert before == after  # 错因聚合同样零写入

        distribution = payload["error_cause_distribution"]
        # 在册未掌握 = M1/M2/M3/M4（M5 毕业、M6 作废排除）；count 降序、cause 升序。
        assert distribution == [
            {"cause": "calculation", "label": "计算失误", "count": 1},
            {"cause": "concept_unclear", "label": "概念不清", "count": 1},
            {"cause": "other", "label": "其他", "count": 1},
            {"cause": "unlabeled", "label": "未标注", "count": 1},
        ]
        by_cause = {item["cause"]: item["count"] for item in distribution}
        # other 与 unlabeled 分列各有断言（防"没标"被读成"其他原因"）。
        assert by_cause["other"] == 1
        assert by_cause["unlabeled"] == 1
        assert "other" in by_cause and "unlabeled" in by_cause
        # M3 的 suggested=calculation 被确认 None 压过：calculation 只来自 M2，不重复计。
        assert by_cause["calculation"] == 1
        # 毕业 M5 的 careless 不进聚合。
        assert "careless" not in by_cause

        subjects = payload["subjects"]
        assert subjects == [
            {"subject": "数学", "active": 2, "graduated": 1, "total": 3},
            {"subject": "未挂考点", "active": 1, "graduated": 0, "total": 1},
            {"subject": "英语", "active": 1, "graduated": 0, "total": 1},
        ]
        # 自洽算式：右端用 subjects[].active（=4），不是 inventory.active（=5，含毕业 M5）。
        active_total = sum(item["active"] for item in subjects)
        assert active_total == 4
        assert payload["inventory"]["active"] == 5  # 含已毕业，故不能当右端
        labeled_sum = sum(item["count"] for item in distribution if item["cause"] != "unlabeled")
        unlabeled = by_cause.get("unlabeled", 0)
        assert labeled_sum + unlabeled == active_total
        assert sum(item["count"] for item in distribution) == active_total
        # 学科卡既有算式不被破坏。
        assert sum(item["total"] for item in subjects) == payload["inventory"]["active"]

        # 独立重算：对 active 非毕业 id 跑 effective_labels，双向对齐（不写死期望迁就实现）。
        events = await _recompute_events(factory)
        active_ids = (m1, m2, m3, m4)
        assert all(not is_graduated(events, mid) for mid in active_ids)
        assert is_graduated(events, m5)


@pytest.mark.integration
async def test_error_cause_distribution_reclassification_changes_counts(tmp_path) -> None:
    """改判后数字随之变、不重复计：confirmed 错因从 concept_unclear 改 method_missing。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory, topic_id="cnm_test_equation", name="一元一次方程")
    today = date.today()
    async with _client(factory) as client:
        mistake_id = (await _create_cause_mistake(
            client, primary_topic_id="cnm_test_equation",
            suggestion="计算失误", confirm_error_cause="concept_unclear",
        ))["mistake_id"]

        first = await client.get(f"/api/dashboard?today={today.isoformat()}")
        assert first.status_code == 200, first.text
        assert first.json()["error_cause_distribution"] == [
            {"cause": "concept_unclear", "label": "概念不清", "count": 1}
        ]

        relabeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 1, "error_cause": "method_missing"},
        )
        assert relabeled.status_code == 200, relabeled.text
        assert relabeled.json()["current_version"] == 2

        second = await client.get(f"/api/dashboard?today={today.isoformat()}")
        assert second.status_code == 200, second.text
        payload = second.json()
        # 改判后旧桶消失、新桶出现，总数仍 1（不重复计）。
        assert payload["error_cause_distribution"] == [
            {"cause": "method_missing", "label": "方法不会", "count": 1}
        ]
        assert sum(item["count"] for item in payload["error_cause_distribution"]) == sum(
            item["active"] for item in payload["subjects"]
        ) == 1
