"""P0-3 端到端回归：真实 ASGI + 临时 SQLite + Alembic 迁到 head。

三条链路必须跨引擎咬合，不接受"接口 200"式断言：

① 投递外部转录 JSON → 落草稿 → 核对页确认入本 → 到期队列出同类题考核 →
   服务端 judgeAnswer 判分写 attempts(system_quiz) → 看板/streak 与事件事实
   手工推导的数字逐项相等。
② 错题作废退出活跃列表与到期队列 → 撤销回到期队列；作废前的历史事件与
   mistake_versions 一行不改，只追加 void / reactivate 两条审计事件。
③ 家长解锁 → 导出备份 → 快照 PRAGMA integrity_check=ok → manifest 计数与
   快照库、业务库的实际计数逐项相等。

不 mock 服务层、不调模型、不引入浏览器栈；页面/模板不在本用例范围。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    Concept,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    ReviewSchedule,
)
from app.services.backup import BACKUP_NAME_RE, DB_NAME, MANIFEST_NAME
from app.services.bank import get_bank
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
CHANNEL = "agent_transcribe_v1"
TOPIC_ID = "cnm_001"
SUBJECT = "数学"
ENGLISH_TOPIC_ID = "eng_e2e_001"
ENGLISH_SUBJECT = "英语"
FORBIDDEN_KEYS = {"answer", "accept", "explanation", "verify"}


def _migrated(db_path: Path) -> async_sessionmaker:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(
    factory: async_sessionmaker,
    *,
    settings: Settings | None = None,
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _set_pin(client: AsyncClient) -> None:
    status = await client.get("/api/session/status")
    assert status.status_code == 200, status.text
    if not status.json()["pin_set"]:
        response = await client.post("/api/session/pin/set", json={"pin": PIN})
        assert response.status_code == 200, response.text


async def _unlock(client: AsyncClient) -> None:
    await _set_pin(client)
    response = await client.post("/api/session/unlock", json={"pin": PIN})
    assert response.status_code == 200, response.text


async def _seed_topic_and_concept(
    factory: async_sessionmaker,
) -> tuple[str, int]:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=TOPIC_ID,
                subject=SUBJECT,
                name="有理数",
                domain="数与代数",
                grade="七年级",
                semester="上册",
                chapter="有理数",
                type="topic",
                unaudited=True,
                blind_verified=True,
            )
        )
        await session.flush()
        concept = Concept(
            name="异号相加",
            category_id=TOPIC_ID,
            source="parent",
            status="confirmed",
            created_at=datetime.now(UTC),
        )
        session.add(concept)
        await session.flush()
        return TOPIC_ID, concept.id


async def _seed_english_topic_and_concept(
    factory: async_sessionmaker,
) -> tuple[str, int]:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=ENGLISH_TOPIC_ID,
                subject=ENGLISH_SUBJECT,
                name="英语词汇",
                grade="七年级",
                type="topic",
                unaudited=True,
                blind_verified=True,
            )
        )
        await session.flush()
        concept = Concept(
            name="词汇拼写",
            category_id=ENGLISH_TOPIC_ID,
            source="parent",
            status="confirmed",
            created_at=datetime.now(UTC),
        )
        session.add(concept)
        await session.flush()
        return ENGLISH_TOPIC_ID, concept.id


def _items() -> list[dict]:
    return [
        {
            "subject": SUBJECT,
            "problem_text": "计算 -3 + 5",
            "student_answer": "-8",
            "standard_answer": "2",
            "error_cause_suggestion": "计算失误",
            "suggested_topic_id": TOPIC_ID,
            "source_ref": "e2e 第1题",
            "captured_at": "2026-11-01",
        },
        {
            "subject": SUBJECT,
            "problem_text": "计算 7 - 12",
            "student_answer": "5",
            "standard_answer": "-5",
            "error_cause_suggestion": "计算失误",
            "suggested_topic_id": TOPIC_ID,
            "source_ref": "e2e 第2题",
            "captured_at": "2026-11-01",
        },
    ]


def _english_items() -> list[dict]:
    return [
        {
            "subject": ENGLISH_SUBJECT,
            "problem_text": (
                "The diligent student is diligent in the library."
            ),
            "student_answer": (
                "The diligent student is diligent in library."
            ),
            "standard_answer": (
                "The diligent student is diligent in the library."
            ),
            "error_cause_suggestion": "拼写与介词",
            "suggested_topic_id": ENGLISH_TOPIC_ID,
            "source_ref": "e2e 英语第1题",
            "captured_at": "2026-11-01",
        },
        {
            "subject": ENGLISH_SUBJECT,
            "problem_text": (
                "A diligent plan and patient practice bring patient progress."
            ),
            "student_answer": (
                "A diligent plan and patient practice bring patient progres."
            ),
            "standard_answer": (
                "A diligent plan and patient practice bring patient progress."
            ),
            "error_cause_suggestion": "拼写错误",
            "suggested_topic_id": ENGLISH_TOPIC_ID,
            "source_ref": "e2e 英语第2题",
            "captured_at": "2026-11-01",
        },
    ]


async def _import_and_confirm(
    client: AsyncClient,
    factory: async_sessionmaker,
    *,
    concept_id: int,
    actor: str = "parent",
    items: list[dict] | None = None,
    topic_id: str = TOPIC_ID,
) -> list[dict]:
    payload_items = _items() if items is None else items
    response = await client.post(
        "/api/imports",
        content=json.dumps(
            {"channel": CHANNEL, "items": payload_items}, ensure_ascii=False
        ),
    )
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["accepted_count"] == len(payload_items)
    assert imported["draft_count"] == len(payload_items)
    assert imported["duplicate"] is False

    drafts = await client.get(f"/api/imports/{imported['batch_id']}/drafts")
    assert drafts.status_code == 200, drafts.text
    ordered = sorted(drafts.json()["drafts"], key=lambda row: row["seq"])
    assert [row["normalized"]["problem_text"] for row in ordered] == [
        row["problem_text"] for row in payload_items
    ]
    assert all(row["status"] == "draft" for row in ordered)
    assert all(row["normalized"]["standard_answer"] for row in ordered)

    confirmations = []
    for draft in ordered:
        confirmed = await client.post(
            f"/api/imports/drafts/{draft['id']}/confirm",
            json={
                "primary_topic_id": topic_id,
                "concept_ids": [concept_id],
                "error_cause": "calculation",
                "actor": actor,
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        body = confirmed.json()
        assert body["already_promoted"] is False
        assert body["primary_topic_id"] == topic_id
        confirmations.append(body)

    pending = await client.get("/api/imports/drafts")
    promoted = await client.get("/api/imports/drafts?status=promoted")
    assert pending.json()["total"] == 0
    assert promoted.json()["total"] == len(payload_items)
    return confirmations


def _wrong_answer(question) -> str:
    if question.type == "choice":
        for choice in question.choices:
            if choice.key != question.answer and choice.key not in question.accept:
                return choice.key
        return "Z"
    if question.type == "numeric":
        return "999999"
    return "这是一段不会与标准答案等价的作答"


def _assert_no_answer_keys(payload: object) -> None:
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in FORBIDDEN_KEYS, (key, node)
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)


async def _event_rows(factory: async_sessionmaker) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(LearningEvent).order_by(LearningEvent.id)
            )
        ).scalars().all()
        return [
            (
                row.id,
                row.type,
                row.actor,
                row.mistake_id,
                row.payload,
                row.occurred_at,
                row.idempotency_key,
            )
            for row in rows
        ]


async def _version_rows(factory: async_sessionmaker) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(MistakeVersion).order_by(MistakeVersion.id)
            )
        ).scalars().all()
        return [
            (
                row.id,
                row.mistake_id,
                row.version,
                row.problem_text,
                row.standard_answer,
                row.student_answer,
                row.is_correct,
                row.status,
                row.confirmed_category_id,
                row.confirmed_concept_ids_json,
                row.confirmed_error_cause,
                row.confirmed_by,
                row.correction_notes,
            )
            for row in rows
        ]


async def _mistake_chain_snapshot(factory: async_sessionmaker) -> tuple:
    """四表快照：抽词/入库前后必须逐行相等。"""

    async with factory() as session:
        mistakes = (
            await session.execute(select(Mistake).order_by(Mistake.id))
        ).scalars().all()
        versions = (
            await session.execute(
                select(MistakeVersion).order_by(MistakeVersion.id)
            )
        ).scalars().all()
        attempts = len((await session.execute(select(Attempt))).all())
        schedules = len(
            (await session.execute(select(ReviewSchedule))).all()
        )
        return (
            [
                (
                    row.id,
                    row.status,
                    row.current_version,
                    row.primary_topic_id,
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


def _learning_days(events: list[tuple]) -> set[date]:
    """按 AGENTS/streak 文档：优先 payload.completed_on，缺失回退 occurred_at。

    P3-3a 起 `recitation_reviewed` 也计入学习日（只背诵不做题同样算打卡）。
    """

    days: set[date] = set()
    for _id, event_type, _actor, _mistake, payload, occurred_at, _key in events:
        if event_type not in (
            "attempt_correct",
            "attempt_wrong",
            "recitation_reviewed",
        ):
            continue
        data = json.loads(payload) if payload else {}
        raw = data.get("completed_on")
        if isinstance(raw, str):
            try:
                days.add(date.fromisoformat(raw))
                continue
            except ValueError:
                pass
        days.add(occurred_at.date())
    return days


def _expected_streak(events: list[tuple], today: date) -> dict:
    days = _learning_days(events)
    anchor = (
        today
        if today in days
        else (today - timedelta(days=1) if today - timedelta(days=1) in days else None)
    )
    current = 0
    cursor = anchor
    while cursor is not None and cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day

    return {
        "today_done": today in days,
        "current_streak": current,
        "longest_streak": longest,
        "learning_days_total": len(days),
    }


@pytest.mark.e2e
async def test_transcribe_confirm_quiz_dashboard_consistency(tmp_path) -> None:
    """① 导入→确认→排期→考核→判分→看板：五处数字必须互相咬合。"""

    factory = _migrated(tmp_path / "closed-loop.db")
    _, concept_id = await _seed_topic_and_concept(factory)

    async with _client(factory) as client:
        confirmations = await _import_and_confirm(
            client, factory, concept_id=concept_id
        )
        due_day = date.fromisoformat(confirmations[0]["due_on"])
        assert due_day == date.fromisoformat(confirmations[1]["due_on"])

        before_due = await client.get(
            "/api/reviews/due",
            params={"today": (due_day - timedelta(days=1)).isoformat()},
        )
        assert before_due.status_code == 200, before_due.text
        assert before_due.json()["due_total"] == 0

        due = await client.get(
            "/api/reviews/due", params={"today": due_day.isoformat()}
        )
        assert due.status_code == 200, due.text
        due_body = due.json()
        assert due_body["due_total"] == 2
        assert due_body["returned"] == 2
        assert due_body["today_completed"] == 0
        assert len(due_body["items"]) == 2
        _assert_no_answer_keys(due_body)

        by_mistake = {
            item["mistake_id"]: item for item in due_body["items"]
        }
        assert set(by_mistake) == {
            confirm["mistake_id"] for confirm in confirmations
        }
        assert all(item["task"] == "quiz" for item in due_body["items"])
        assert all(item["bank_gap"] is False for item in due_body["items"])
        assert all(item["quiz"]["topic_id"] == TOPIC_ID for item in due_body["items"])

        bank = get_bank()
        verdicts = []
        for index, confirm in enumerate(
            sorted(confirmations, key=lambda row: row["mistake_id"])
        ):
            item = by_mistake[confirm["mistake_id"]]
            question = bank.question(item["quiz"]["question_id"])
            assert question is not None
            answer = question.answer if index == 0 else _wrong_answer(question)
            submitted = await client.post(
                f"/api/reviews/{confirm['mistake_id']}/quiz",
                json={
                    "schedule_id": item["schedule_id"],
                    "question_id": question.id,
                    "answer": answer,
                    # 客户端谎报必须被服务端忽略：第二题实际答错却传 correct=True
                    "correct": index == 0,
                    "completed_on": due_day.isoformat(),
                    "actor": "student",
                },
            )
            assert submitted.status_code == 200, submitted.text
            body = submitted.json()
            assert body["mode"] == "system"
            assert body["completion"]["source"] == "system_quiz"
            assert body["completion"]["schedule_id"] == item["schedule_id"]
            assert body["completion"]["correct"] is (index == 0)
            assert body["verdict"] == ("correct" if index == 0 else "wrong")
            verdicts.append(body["verdict"])
        assert verdicts == ["correct", "wrong"]

        after_due = await client.get(
            "/api/reviews/due", params={"today": due_day.isoformat()}
        )
        assert after_due.status_code == 200, after_due.text
        assert after_due.json()["due_total"] == 0
        assert after_due.json()["returned"] == 0
        assert after_due.json()["today_completed"] == 2

        attempts = await client.get(
            "/api/attempts", params={"source": "system_quiz"}
        )
        assert attempts.status_code == 200, attempts.text
        attempt_body = attempts.json()
        assert attempt_body["total"] == 2
        assert all(row["kind"] == "review" for row in attempt_body["items"])
        assert all(row["source"] == "system_quiz" for row in attempt_body["items"])
        assert all(row["topic_id"] == TOPIC_ID for row in attempt_body["items"])
        assert {row["is_correct"] for row in attempt_body["items"]} == {True, False}

        active = await client.get("/api/mistakes", params={"status": "active"})
        all_mistakes = await client.get("/api/mistakes", params={"status": "all"})
        assert active.json()["total"] == 2
        assert all_mistakes.json()["total"] == 2
        assert all(
            row["status"] == "active" for row in active.json()["items"]
        )

        dashboard = await client.get(
            "/api/dashboard", params={"today": due_day.isoformat()}
        )
        assert dashboard.status_code == 200, dashboard.text
        snapshot = dashboard.json()

    assert snapshot["inventory"] == {
        "active": 2,
        "voided": 0,
        "unassigned_active": 0,
    }
    assert snapshot["weak_topics"] == [
        {
            "topic_id": TOPIC_ID,
            "name": "有理数",
            "subject": SUBJECT,
            "active_mistakes": 2,
        }
    ]
    assert snapshot["weak_subjects"] == [
        {"subject": SUBJECT, "active_mistakes": 2}
    ]
    assert snapshot["mastery"]["overall"] == 0.5
    assert snapshot["mastery"]["concepts"] == [
        {
            "concept_id": concept_id,
            "name": "异号相加",
            "category_id": TOPIC_ID,
            "category_name": "有理数",
            "mastery": 0.5,
        }
    ]
    assert snapshot["due"] == {"today": 0, "overdue": 0, "total": 0}
    assert snapshot["completion"]["reviews_this_week"] == 2
    assert snapshot["completion"]["graduated_total"] == 0
    assert snapshot["completion"]["graduated_this_week"] == 0
    assert snapshot["bank_gap"] == {"topics": [], "unassigned_open": 0}
    assert snapshot["governance"] == {
        "appeal_count": 0,
        "appealed_gradings": 0,
        "void_events": 0,
        "reactivate_events": 0,
    }

    # 事件事实：2 次确认各写 attempt_wrong + review_scheduled，2 次考核各写 1 条。
    # attempts 派生表只有 2 条考核；看板 event_stats 统计的是 4 条作答事件（确认含 2 条）。
    assert snapshot["event_stats"] == {
        "total_events": 6,
        "by_type": {
            "attempt_wrong": 3,
            "review_scheduled": 2,
            "attempt_correct": 1,
        },
        "attempts_correct": 1,
        "attempts_wrong": 3,
        "attempt_accuracy": 0.25,
    }

    events = await _event_rows(factory)
    expected_streak = _expected_streak(events, due_day)
    assert {
        key: snapshot["streak"][key] for key in expected_streak
    } == expected_streak
    assert len(snapshot["streak"]["recent_days"]) == 30
    assert snapshot["streak"]["recent_days"][-1] == {
        "date": due_day.isoformat(),
        "done": True,
    }


@pytest.mark.e2e
async def test_void_unvoid_does_not_rewrite_history(tmp_path) -> None:
    """② 作废/撤销只追加审计事件：原历史与 versions 零改动，队列状态可逆。"""

    factory = _migrated(tmp_path / "void-lifecycle.db")
    _, concept_id = await _seed_topic_and_concept(factory)

    async with _client(factory) as client:
        await _unlock(client)
        confirmations = await _import_and_confirm(
            client, factory, concept_id=concept_id
        )
        keep = confirmations[0]["mistake_id"]
        due_day = date.fromisoformat(confirmations[0]["due_on"])
        before_events = await _event_rows(factory)
        before_versions = await _version_rows(factory)

        active_before = await client.get(
            "/api/mistakes", params={"status": "active"}
        )
        due_before = await client.get(
            "/api/reviews/due", params={"today": due_day.isoformat()}
        )
        assert active_before.json()["total"] == 2
        assert due_before.json()["due_total"] == 2

        voided = await client.post(
            f"/api/mistakes/{keep}/void",
            json={"actor": "parent", "reason": "已当面讲通，暂不复习"},
        )
        again = await client.post(
            f"/api/mistakes/{keep}/void", json={"actor": "student"}
        )
        active_after = await client.get(
            "/api/mistakes", params={"status": "active"}
        )
        all_after = await client.get("/api/mistakes", params={"status": "all"})
        due_after = await client.get(
            "/api/reviews/due", params={"today": due_day.isoformat()}
        )
        detail_voided = await client.get(f"/api/mistakes/{keep}")

        unvoided = await client.post(
            f"/api/mistakes/{keep}/unvoid", json={"actor": "student"}
        )
        again_unvoid = await client.post(
            f"/api/mistakes/{keep}/unvoid", json={"actor": "student"}
        )
        active_restored = await client.get(
            "/api/mistakes", params={"status": "active"}
        )
        due_restored = await client.get(
            "/api/reviews/due", params={"today": due_day.isoformat()}
        )
        detail_active = await client.get(f"/api/mistakes/{keep}")

    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "voided"

    assert active_after.json()["total"] == 1
    assert all_after.json()["total"] == 2
    assert due_after.json()["due_total"] == 1
    assert detail_voided.json()["status"] == "voided"

    assert unvoided.status_code == 200, unvoided.text
    assert unvoided.json()["status"] == "active"
    assert again_unvoid.status_code == 200, again_unvoid.text
    assert again_unvoid.json()["status"] == "active"
    assert active_restored.json()["total"] == 2
    assert due_restored.json()["due_total"] == 2
    assert keep in {
        item["mistake_id"] for item in due_restored.json()["items"]
    }
    assert detail_active.json()["status"] == "active"

    after_events = await _event_rows(factory)
    after_versions = await _version_rows(factory)

    # 作废前的历史必须逐行原样保留；versions 全程不因状态切换增删改。
    assert after_events[: len(before_events)] == before_events
    assert after_versions == before_versions

    appended = after_events[len(before_events) :]
    assert [row[1] for row in appended] == [
        "mistake_voided",
        "mistake_reactivated",
    ]
    assert [row[6] for row in appended] == [
        f"mistake:{keep}:void",
        f"mistake:{keep}:reactivate",
    ]
    assert [row[2] for row in appended] == ["parent", "student"]
    # 幂等重复请求不重复写审计事件：只追加这一对。
    assert len(after_events) == len(before_events) + 2


@pytest.mark.e2e
async def test_recitation_manual_entry_ladder_dashboard_streak(tmp_path) -> None:
    """④ 家长手填 3 条 → 到期 3 条 → 混合自评 → 阶梯/看板/打卡互相咬合。"""

    factory = _migrated(tmp_path / "recitation-loop.db")
    day = date(2026, 11, 2)

    async with _client(factory) as client:
        await _unlock(client)
        items = []
        for prompt, answer, unit in [
            ("abandon", "放弃", "Unit 1"),
            ("ability", "能力", "Unit 1"),
            ("absorb", "吸收", "Unit 2"),
        ]:
            created = await client.post(
                "/api/recitations",
                json={
                    "subject": "英语",
                    "prompt": prompt,
                    "answer": answer,
                    "unit": unit,
                },
            )
            assert created.status_code == 200, created.text
            items.append(created.json())
        assert [item["id"] for item in items] == [1, 2, 3]

        due = await client.get(
            "/api/recitations/due", params={"today": day.isoformat()}
        )
        assert due.status_code == 200, due.text
        due_body = due.json()
        assert due_body["due_total"] == 3
        assert due_body["returned"] == 3
        assert due_body["limit"] == 5
        assert [entry["item"]["prompt"] for entry in due_body["items"]] == [
            "abandon",
            "ability",
            "absorb",
        ]
        assert all(entry["rung"] == 0 for entry in due_body["items"])
        assert all(entry["reviewed_on"] is None for entry in due_body["items"])

        # 混合自评：第 1、3 条记得（新条目进一档 +3 天）；
        # 第 2 条没记住（新条目保持 rung 0，下次从当天 +1 天起算）。
        first_round = [
            ("remembered", 1, 3),
            ("forgot", 0, 1),
            ("remembered", 1, 3),
        ]
        for item, (verdict, expected_rung, wait) in zip(
            items, first_round, strict=True
        ):
            reviewed = await client.post(
                f"/api/recitations/{item['id']}/review",
                json={
                    "verdict": verdict,
                    "reviewed_on": day.isoformat(),
                    "actor": "student",
                },
            )
            assert reviewed.status_code == 200, reviewed.text
            body = reviewed.json()
            assert body["created"] is True
            assert body["rung"] == expected_rung
            assert body["scheduled_next"] == (
                day + timedelta(days=wait)
            ).isoformat()
            assert body["graduated"] is False

        # 同日重复提交幂等：不新增自评/事件，也不改写阶梯。
        repeated = await client.post(
            "/api/recitations/1/review",
            json={"verdict": "forgot", "reviewed_on": day.isoformat()},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["created"] is False
        assert repeated.json()["rung"] == 1

        due_after = await client.get(
            "/api/recitations/due", params={"today": day.isoformat()}
        )
        assert due_after.json()["due_total"] == 0

        # 第二轮（第 1 条再次记得）：rung 1 → 2，下次 +7 天；第 2 条仍是 rung 0。
        ladder_day = day + timedelta(days=3)
        second = await client.post(
            "/api/recitations/1/review",
            json={"verdict": "remembered", "reviewed_on": ladder_day.isoformat()},
        )
        assert second.status_code == 200, second.text
        assert second.json()["rung"] == 2
        assert second.json()["scheduled_next"] == (
            ladder_day + timedelta(days=7)
        ).isoformat()

        dashboard = await client.get(
            "/api/dashboard", params={"today": day.isoformat()}
        )
        assert dashboard.status_code == 200, dashboard.text
        board = dashboard.json()

    assert board["recitations_today"] == 3
    assert board["recitation_limit"] == 5
    assert board["streak"]["today_done"] is True
    assert board["streak"]["learning_days_total"] == 2
    assert board["event_stats"]["by_type"]["recitation_reviewed"] == 4
    assert board["event_stats"]["attempts_correct"] == 0
    assert board["event_stats"]["attempts_wrong"] == 0
    assert board["mastery"]["overall"] == 0.0
    assert board["inventory"]["active"] == 0

    events = await _event_rows(factory)
    recitations = [row for row in events if row[1] == "recitation_reviewed"]
    assert len(recitations) == 4
    assert all(row[3] is None for row in recitations)
    assert [row[6] for row in recitations] == [
        f"recitation:1:{day.isoformat()}",
        f"recitation:2:{day.isoformat()}",
        f"recitation:3:{day.isoformat()}",
        f"recitation:1:{ladder_day.isoformat()}",
    ]

    expected_streak = _expected_streak(events, day)
    assert {
        key: board["streak"][key] for key in expected_streak
    } == expected_streak

    async with factory() as session:
        for model in (Mistake, MistakeVersion, Attempt, ReviewSchedule):
            assert (await session.execute(select(model))).all() == []
        assert (
            await session.execute(
                select(LearningEvent).where(
                    LearningEvent.type.in_(
                        ("attempt_correct", "attempt_wrong")
                    )
                )
            )
        ).all() == []


@pytest.mark.e2e
async def test_recitation_import_report_then_due_and_ladder(tmp_path) -> None:
    """⑤ 家长导入 3 行（1 重复、1 坏）→ 报告正确、好行入库 → 孩子自评走阶梯。"""

    factory = _migrated(tmp_path / "recitation-import-loop.db")
    day = date(2026, 11, 2)

    async with _client(factory) as client:
        await _unlock(client)
        created = await client.post(
            "/api/recitations",
            json={
                "subject": "英语",
                "prompt": "abandon",
                "answer": "放弃",
                "unit": "Unit 1",
            },
        )
        assert created.status_code == 200, created.text

        imported = await client.post(
            "/api/recitations/import",
            json={
                "subject": "英语",
                "text": (
                    "prompt,answer,unit\n"
                    "abandon,放弃,Unit 1\n"
                    "ability,能力,Unit 1\n"
                    ",缺少条目,Unit 2\n"
                ),
            },
        )
        assert imported.status_code == 200, imported.text
        report = imported.json()
        assert report["imported"] == 1
        assert report["duplicates"] == [{"line": 2, "prompt": "abandon"}]
        assert report["errors"] == [
            {"line": 4, "field": "prompt", "reason": "prompt 不能为空"}
        ]

        due = await client.get(
            "/api/recitations/due", params={"today": day.isoformat()}
        )
        assert due.status_code == 200, due.text
        due_body = due.json()
        assert due_body["due_total"] == 2
        assert [entry["item"]["prompt"] for entry in due_body["items"]] == [
            "abandon",
            "ability",
        ]

        # 导入行拿到 id=2；remembered → rung 1，下次从实际完成日 +3 天。
        reviewed = await client.post(
            "/api/recitations/2/review",
            json={"verdict": "remembered", "reviewed_on": day.isoformat()},
        )
        assert reviewed.status_code == 200, reviewed.text
        body = reviewed.json()
        assert body["item"]["prompt"] == "ability"
        assert body["created"] is True
        assert body["rung"] == 1
        assert body["scheduled_next"] == (
            day + timedelta(days=3)
        ).isoformat()

        repeated = await client.post(
            "/api/recitations/2/review",
            json={"verdict": "remembered", "reviewed_on": day.isoformat()},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["created"] is False
        assert repeated.json()["rung"] == 1

        dashboard = await client.get(
            "/api/dashboard", params={"today": day.isoformat()}
        )
        assert dashboard.status_code == 200, dashboard.text
        board = dashboard.json()

    assert board["recitations_today"] == 1
    assert board["recitation_limit"] == 5
    assert board["streak"]["today_done"] is True
    assert board["event_stats"]["by_type"]["recitation_reviewed"] == 1
    assert board["mastery"]["overall"] == 0.0

    async with factory() as session:
        for model in (Mistake, MistakeVersion, Attempt, ReviewSchedule):
            assert (await session.execute(select(model))).all() == []


@pytest.mark.e2e
async def test_backup_export_snapshot_and_manifest_agree(tmp_path) -> None:
    """③ 家长导出 → 快照可打开且 integrity_check=ok → manifest 计数逐项相等。"""

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "wengu.db",
        seeds_dir=tmp_path / "seeds",
    )
    factory = _migrated(settings.db_path)
    _, concept_id = await _seed_topic_and_concept(factory)

    async with _client(factory, settings=settings) as client:
        await _set_pin(client)
        locked_lock = await client.post("/api/session/lock")
        assert locked_lock.status_code == 200, locked_lock.text
        locked = await client.post("/api/backup/export")
        assert locked.status_code == 403, locked.text

        await _unlock(client)
        await _import_and_confirm(client, factory, concept_id=concept_id)
        exported = await client.post("/api/backup/export")
        assert exported.status_code == 200, exported.text
        body = exported.json()
        assert BACKUP_NAME_RE.fullmatch(body["filename"])
        assert body["manifest"]["version"] == 1
        assert body["manifest"]["file_count"] == 1  # 数据目录没有 uploads/seeds_local/inbox

        downloaded = await client.get(
            f"/api/backup/download/{body['filename']}"
        )
        assert downloaded.status_code == 200, downloaded.text

    archive_bytes = downloaded.content
    assert len(archive_bytes) == body["size_bytes"]
    assert hashlib.sha256(archive_bytes).hexdigest() == body["sha256"]

    archive_path = tmp_path / body["filename"]
    archive_path.write_bytes(archive_bytes)
    with zipfile.ZipFile(archive_path) as zf:
        names = set(zf.namelist())
        assert {DB_NAME, MANIFEST_NAME} <= names
        manifest = json.loads(zf.read(MANIFEST_NAME))
        snapshot_path = tmp_path / "snapshot.db"
        snapshot_path.write_bytes(zf.read(DB_NAME))

    snapshot = sqlite3.connect(str(snapshot_path))
    try:
        assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        snapshot_counts = {
            table: int(
                snapshot.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in manifest["counts"]
        }
        snapshot_revision = snapshot.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    finally:
        snapshot.close()

    live = sqlite3.connect(str(settings.db_path))
    try:
        live_counts = {
            table: int(
                live.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in manifest["counts"]
        }
        live_revision = live.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    finally:
        live.close()

    assert manifest["counts"] == snapshot_counts
    assert manifest["counts"] == live_counts
    assert manifest["alembic_version"] == snapshot_revision == live_revision
    assert manifest["counts"]["mistakes"] == 2
    assert manifest["counts"]["learning_events"] == 4
    assert manifest["counts"]["review_schedules"] == 2
    assert manifest["counts"]["ingestion_drafts"] == 2
    assert manifest["counts"]["attempts"] == 0
    assert manifest["counts"]["knowledge_seed"] == 1


@pytest.mark.e2e
async def test_english_candidates_batch_import_then_due_and_ladder(tmp_path) -> None:
    """⑥ 2 条已确认英语错题 → 抽词排序/去重/停用词 → 勾选入库 → /due → 自评走阶梯。"""

    factory = _migrated(tmp_path / "recitation-candidates-loop.db")
    _, concept_id = await _seed_english_topic_and_concept(factory)
    day = date(2026, 11, 3)

    async with _client(factory) as client:
        await _unlock(client)
        confirmations = await _import_and_confirm(
            client,
            factory,
            concept_id=concept_id,
            items=_english_items(),
            topic_id=ENGLISH_TOPIC_ID,
        )
        assert len(confirmations) == 2
        before = await _mistake_chain_snapshot(factory)

        candidates = await client.get("/api/recitations/candidates")
        assert candidates.status_code == 200, candidates.text
        rows = candidates.json()
        # 跨两题出现两次的 diligent 排第一；同题内重复只算一次。
        assert rows[0] == {"word": "diligent", "mistake_count": 2}
        assert {"word": "patient", "mistake_count": 1} in rows
        assert [row["word"] for row in rows] == [
            "diligent",
            "bring",
            "library",
            "patient",
            "plan",
            "practice",
            "progress",
            "student",
        ]
        assert not {"the", "a", "and", "is", "in"} & {
            row["word"] for row in rows
        }

        batch = await client.post(
            "/api/recitations/candidates/batch",
            json={"words": ["diligent", "patient"], "unit": "错题抽词"},
        )
        assert batch.status_code == 200, batch.text
        report = batch.json()
        assert report["imported"] == 2
        assert report["duplicates"] == []
        created = report["created"]
        assert [row["prompt"] for row in created] == ["diligent", "patient"]

        due = await client.get(
            "/api/recitations/due", params={"today": day.isoformat()}
        )
        assert due.status_code == 200, due.text
        assert due.json()["due_total"] == 2
        assert [
            entry["item"]["prompt"] for entry in due.json()["items"]
        ] == ["diligent", "patient"]
        assert all(
            entry["item"]["answer"] is None for entry in due.json()["items"]
        )

        remaining = await client.get("/api/recitations/candidates")
        remaining_words = [row["word"] for row in remaining.json()]
        assert "diligent" not in remaining_words
        assert "patient" not in remaining_words

        remembered = await client.post(
            f"/api/recitations/{created[0]['id']}/review",
            json={"verdict": "remembered", "reviewed_on": day.isoformat()},
        )
        assert remembered.status_code == 200, remembered.text
        assert remembered.json()["rung"] == 1
        assert remembered.json()["scheduled_next"] == (
            day + timedelta(days=3)
        ).isoformat()

        forgot = await client.post(
            f"/api/recitations/{created[1]['id']}/review",
            json={"verdict": "forgot", "reviewed_on": day.isoformat()},
        )
        assert forgot.status_code == 200, forgot.text
        assert forgot.json()["rung"] == 0
        assert forgot.json()["scheduled_next"] == (
            day + timedelta(days=1)
        ).isoformat()

    after = await _mistake_chain_snapshot(factory)
    assert after == before
    assert before[0] and before[1]


@pytest.mark.e2e
async def test_setup_wizard_completes_and_limit_takes_effect(
    tmp_path, monkeypatch
) -> None:
    """⑦ 全新库 → 未完成 → 向导设上限并标记完成 → 状态翻转 → due 立即生效。"""

    config_path = tmp_path / "app-config.json"
    monkeypatch.setenv("WENGU_APP_CONFIG", str(config_path))
    assert not config_path.exists()
    factory = _migrated(tmp_path / "setup.db")

    async with _client(factory) as client:
        status = await client.get("/api/setup/status")
        assert status.status_code == 200, status.text
        # _client 不跑 lifespan，seed 未装载 → 默认 False
        assert status.json() == {
            "setup_completed": False,
            "seed_loaded": False,
            "seed_error": None,
        }

        # 未完成也不劫持路由：复习队列照常可读，上限仍是默认值。
        due = await client.get("/api/reviews/due")
        assert due.status_code == 200, due.text
        assert due.json()["daily_limit"] == 10

        locked = await client.put("/api/config", json={"setup_completed": True})
        assert locked.status_code == 403

        await _unlock(client)

        for invalid in ("yes", 1, None):
            response = await client.put(
                "/api/config", json={"setup_completed": invalid}
            )
            assert response.status_code == 422, (invalid, response.text)
        assert not config_path.exists(), "非法值不得写盘"

        put = await client.put(
            "/api/config",
            json={"daily_review_limit": 3, "setup_completed": True},
        )
        assert put.status_code == 200, put.text
        assert put.json()["values"]["setup_completed"] is True

        after = await client.get("/api/setup/status")
        assert after.json() == {
            "setup_completed": True,
            "seed_loaded": False,
            "seed_error": None,
        }
        due_after = await client.get("/api/reviews/due")
        assert due_after.status_code == 200, due_after.text
        assert due_after.json()["daily_limit"] == 3

    written = json.loads(config_path.read_text(encoding="utf-8"))
    assert written["daily_review_limit"] == 3
    assert written["setup_completed"] is True


@pytest.mark.e2e
async def test_paste_raw_json_partial_duplicate_and_confirm(tmp_path) -> None:
    """⑧ 原文路径投递：部分坏项逐条报告 → 重投去重 → 核对页确认一条入本。"""

    factory = _migrated(tmp_path / "paste-import-loop.db")
    topic_id, concept_id = await _seed_topic_and_concept(factory)

    items = [
        *_items(),
        {
            "subject": SUBJECT,
            "problem_text": "",
            "student_answer": "1",
            "standard_answer": "2",
            "source_ref": "e2e 坏项",
            "captured_at": "2026-11-01",
        },
    ]
    raw = json.dumps(
        {"channel": CHANNEL, "items": items}, ensure_ascii=False
    ).encode("utf-8")

    async with _client(factory) as client:
        before = await _mistake_chain_snapshot(factory)

        # 与前端 importRawText 同一条路径：body 就是原文，不先构建对象再序列化。
        response = await client.post(
            "/api/imports",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["duplicate"] is False
        assert body["status"] == "partial"
        assert body["accepted_count"] == 2
        assert body["draft_count"] == 2
        assert body["dropped_unknown_fields"] == 0
        assert body["errors"] == [
            {
                "index": 2,
                "field": "problem_text",
                "reason": "题目为空（必填）",
            }
        ]

        assert await _mistake_chain_snapshot(factory) == before, "导入不建错题"

        drafts = await client.get(f"/api/imports/{body['batch_id']}/drafts")
        assert drafts.status_code == 200, drafts.text
        draft_rows = drafts.json()["drafts"]
        assert [row["normalized"]["problem_text"] for row in draft_rows] == [
            "计算 -3 + 5",
            "计算 7 - 12",
        ]

        # 同一段原文再投一次：sha256 命中，返回旧批次，不重复建批。
        duplicate = await client.post(
            "/api/imports",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert duplicate.status_code == 201, duplicate.text
        duplicate_body = duplicate.json()
        assert duplicate_body["duplicate"] is True
        assert duplicate_body["batch_id"] == body["batch_id"]
        assert duplicate_body["draft_count"] == 2
        again = await client.get(f"/api/imports/{body['batch_id']}/drafts")
        assert again.json()["total"] == 2

        # 非 JSON：400 + 可读消息，不吐内部堆栈。
        invalid = await client.post(
            "/api/imports",
            content="这不是 JSON".encode(),
            headers={"Content-Type": "application/json"},
        )
        assert invalid.status_code == 400, invalid.text
        assert "JSON 解析失败" in invalid.json()["detail"]
        assert "Traceback" not in invalid.text

        # 核对页确认一条 → 唯一写入路径建错题 + 首次排期。
        confirmed = await client.post(
            f"/api/imports/drafts/{draft_rows[0]['id']}/confirm",
            json={
                "primary_topic_id": topic_id,
                "concept_ids": [concept_id],
                "error_cause": "calculation",
                "actor": "parent",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        confirm_body = confirmed.json()
        assert confirm_body["already_promoted"] is False
        assert confirm_body["primary_topic_id"] == topic_id

        after = await _mistake_chain_snapshot(factory)
        assert len(after[0]) == 1
        assert after[0][0][1] == "active"
        assert len(after[1]) == 1
        assert after[2] == before[2], "确认入本不写 attempts"
        assert after[3] == before[3] + 1, "确认入本只排首次复习"


@pytest.mark.e2e
async def test_bom_prefixed_payload_dedupes_with_plain(tmp_path) -> None:
    """⑨ 投递侧显式剥离 BOM：带/不带 BOM 的同内容报文命中同一 sha256。"""

    factory = _migrated(tmp_path / "bom-import.db")
    plain = json.dumps({"channel": CHANNEL, "items": _items()}, ensure_ascii=False)

    def frontend_body(text: str) -> bytes:
        # 与 ImportPage.submitRaw 一致：先显式剥离 U+FEFF，再 trim。
        return re.sub(r"^\ufeff+", "", text).strip().encode()

    async with _client(factory) as client:
        first = await client.post(
            "/api/imports",
            content=frontend_body("\ufeff\ufeff" + plain),
            headers={"Content-Type": "application/json"},
        )
        assert first.status_code == 201, first.text
        first_body = first.json()
        assert first_body["duplicate"] is False
        assert first_body["draft_count"] == 2
        assert first_body["accepted_count"] == 2
        assert first_body["errors"] == []

        second = await client.post(
            "/api/imports",
            content=frontend_body(plain),
            headers={"Content-Type": "application/json"},
        )
        assert second.status_code == 201, second.text
        second_body = second.json()
        assert second_body["duplicate"] is True
        assert second_body["batch_id"] == first_body["batch_id"]
        assert second_body["draft_count"] == 2


@pytest.mark.e2e
async def test_problem_image_upload_reveal_then_backup_contains(tmp_path) -> None:
    """⑩ 原题图上传 → 读取端点揭示同字节 → 导出备份 zip 含该附件（P1-16 / v2.7 D5）。"""

    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "wengu.db",
        seeds_dir=tmp_path / "seeds",
    )
    factory = _migrated(settings.db_path)
    _, concept_id = await _seed_topic_and_concept(factory)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    async with _client(factory, settings=settings) as client:
        await _unlock(client)
        confirmations = await _import_and_confirm(
            client, factory, concept_id=concept_id
        )
        mistake_id = confirmations[0]["mistake_id"]

        uploaded = await client.post(
            f"/api/mistakes/{mistake_id}/images",
            files={"file": ("page.png", png, "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        detail = uploaded.json()
        assert len(detail["problem_images"]) == 1
        rel_path = detail["problem_images"][0]
        # 落盘路径 = uploads/<id>/<uuid4>.png，原始文件名 page.png 绝不进路径。
        assert rel_path.startswith(f"uploads/{mistake_id}/")
        assert rel_path.endswith(".png")
        stem = rel_path.rsplit("/", 1)[-1][:-4]
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            stem,
        )

        # 揭示：读取端点返回同字节 + 正确 Content-Type，不缓存。
        revealed = await client.get(f"/api/mistakes/{mistake_id}/images/0")
        assert revealed.status_code == 200, revealed.text
        assert revealed.content == png
        assert revealed.headers["content-type"] == "image/png"
        assert revealed.headers["cache-control"] == "no-store"

        # 家长导出备份 → zip 含该附件且字节一致（与 rel_path 同形 arcname）。
        exported = await client.post("/api/backup/export")
        assert exported.status_code == 200, exported.text
        body = exported.json()
        assert body["manifest"]["file_count"] == 2  # 快照库 + uploads/ 下一张
        downloaded = await client.get(
            f"/api/backup/download/{body['filename']}"
        )
        assert downloaded.status_code == 200, downloaded.text

    archive_path = tmp_path / body["filename"]
    archive_path.write_bytes(downloaded.content)
    with zipfile.ZipFile(archive_path) as zf:
        names = set(zf.namelist())
        assert rel_path in names
        assert zf.read(rel_path) == png
        manifest = json.loads(zf.read(MANIFEST_NAME))
        entry = next(f for f in manifest["files"] if f["path"] == rel_path)
        assert entry["size_bytes"] == len(png)
        assert entry["sha256"] == hashlib.sha256(png).hexdigest()


@pytest.mark.e2e
async def test_correction_notes_transcribe_confirm_display_edit_appends(
    tmp_path,
) -> None:
    """⑪ 转录带订正笔记 → 确认入本 → 详情显示 → 孩子编辑追加版本，历史逐行不变（P1-17 / v2.7 D6）。"""

    factory = _migrated(tmp_path / "correction-notes.db")
    _, concept_id = await _seed_topic_and_concept(factory)

    items = _items()
    items[0]["correction_notes"] = "异号相加取绝对值大的符号，再相减"
    # 第二题不带笔记：入本后 correction_notes 必须是 NULL（空 = 不存）。

    async with _client(factory) as client:
        await _unlock(client)
        confirmations = await _import_and_confirm(
            client, factory, concept_id=concept_id, items=items
        )
        with_notes = confirmations[0]["mistake_id"]
        without_notes = confirmations[1]["mistake_id"]

        detail_with = await client.get(f"/api/mistakes/{with_notes}")
        detail_without = await client.get(f"/api/mistakes/{without_notes}")
        assert (
            detail_with.json()["correction_notes"]
            == items[0]["correction_notes"]
        )
        assert detail_without.json()["correction_notes"] is None

        versions_before = await _version_rows(factory)
        events_before = await _event_rows(factory)

        edited = await client.post(
            f"/api/mistakes/{with_notes}/notes",
            json={
                "base_version": 1,
                "correction_notes": "订正：先定符号再算绝对值",
                "actor": "student",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["current_version"] == 2
        assert edited.json()["correction_notes"] == "订正：先定符号再算绝对值"

        detail_after = await client.get(f"/api/mistakes/{with_notes}")
        assert (
            detail_after.json()["correction_notes"] == "订正：先定符号再算绝对值"
        )

    versions_after = await _version_rows(factory)
    # 历史版本行逐行不变（快照含 correction_notes 列）；只追加一行 v2。
    assert versions_after[: len(versions_before)] == versions_before
    assert len(versions_after) == len(versions_before) + 1
    appended = versions_after[-1]
    assert appended[1] == with_notes  # mistake_id
    assert appended[2] == 2  # version
    assert appended[-1] == "订正：先定符号再算绝对值"  # correction_notes
    # 笔记纯展示：编辑不追加任何学习事件，不进判分/排期/掌握度链路。
    assert await _event_rows(factory) == events_before
