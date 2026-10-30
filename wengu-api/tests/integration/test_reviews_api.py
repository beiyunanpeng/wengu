"""P1-7a 复习排期集成测试：用户触发、事实重放、幂等、到期队列、学科闸门。

v2.5：错题经"外部转录 → 核对页确认"入本；系统内零模型调用（考核判分走 judgeAnswer），
聚焦纪律与状态机。
"""

from __future__ import annotations

import json
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
    Concept,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    ReviewSchedule,
)
from app.services.bank import find_same_type, get_bank
from app.services.review import derive_review_state, quiz_seed
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"

FORBIDDEN_KEYS = {"answer", "accept", "explanation", "verify"}


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


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "reviews.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _client(factory: async_sessionmaker) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


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


async def _seed_concept(
    factory: async_sessionmaker,
    *,
    name: str,
    category_id: str = "cnm_test_equation",
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = Concept(
            name=name,
            category_id=category_id,
            source="student",
            status="confirmed",
            merged_into_id=None,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _import_draft(
    client: AsyncClient,
    *,
    subject: str = "数学",
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str = "x=3",
    standard_answer: str = "x=2",
    suggested_topic_id: str = "cnm_test_equation",
) -> int:
    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": subject,
                    "problem_text": problem_text,
                    "student_answer": student_answer,
                    "standard_answer": standard_answer,
                    "error_cause_suggestion": "计算失误",
                    "suggested_topic_id": suggested_topic_id,
                    # 报文去重按原始内容 sha256：每题唯一 source_ref 以免复用旧批次
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
    return draft_id


async def _confirm_wrong(
    client: AsyncClient,
    *,
    subject: str = "数学",
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str = "x=3",
    answer: str = "x=2",
    primary_topic_id: str | None = None,
    concept_ids: tuple[int, ...] = (),
    error_cause: str | None = None,
    suggested_topic_id: str = "cnm_test_equation",
) -> dict:
    draft_id = await _import_draft(
        client,
        subject=subject,
        problem_text=problem_text,
        student_answer=student_answer,
        standard_answer=answer,
        suggested_topic_id=suggested_topic_id,
    )
    payload: dict = {"actor": "student"}
    if primary_topic_id is not None:
        payload["primary_topic_id"] = primary_topic_id
    if concept_ids:
        payload["concept_ids"] = list(concept_ids)
    if error_cause is not None:
        payload["error_cause"] = error_cause
    confirmed = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm", json=payload
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    body["draft_id"] = draft_id
    return body


async def _schedules(
    factory: async_sessionmaker, mistake_id: int
) -> list[ReviewSchedule]:
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ReviewSchedule)
                .where(ReviewSchedule.mistake_id == mistake_id)
                .order_by(ReviewSchedule.id)
            )
        ).all()
        return list(rows)


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _set_primary_topic(
    factory: async_sessionmaker, mistake_id: int, topic_id: str | None
) -> None:
    async with factory() as session, session.begin():
        row = await session.get(Mistake, mistake_id)
        assert row is not None
        row.primary_topic_id = topic_id


async def _due_items(client: AsyncClient, day: date) -> list[dict]:
    response = await client.get(
        "/api/reviews/due", params={"today": day.isoformat()}
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


@pytest.mark.integration
async def test_confirm_wrong_schedules_and_three_corrects_graduate(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        schedules = await _schedules(factory, mistake_id)
        assert len(schedules) == 1
        initial = schedules[0]
        assert initial.rung == 0
        assert initial.base_interval_days == 1
        assert initial.completed_at is None

        async with factory() as session:
            init_event = (
                await session.scalars(
                    select(LearningEvent).where(
                        LearningEvent.type == "review_scheduled",
                        LearningEvent.mistake_id == mistake_id,
                    )
                )
            ).one()
        payload = json.loads(init_event.payload)
        assert init_event.idempotency_key == f"review:schedule:{mistake_id}:init"
        assert payload["subject"] == "数学"
        assert payload["ladder"] == [1, 10, 30]
        assert payload["mastery"] == 0.0
        assert payload["rung"] == 0
        assert payload["times_wrong"] == 1
        assert payload["interval_days"] == 1
        assert payload["due_on"] == initial.due_date.isoformat()
        assert payload["trigger"] == "user_confirmed_wrong"
        assert "problem_text" not in payload

        before_due = await client.get(
            "/api/reviews/due",
            params={"today": (initial.due_date - timedelta(days=1)).isoformat()},
        )
        assert before_due.json()["total"] == 0

        due = await client.get(
            "/api/reviews/due", params={"today": initial.due_date.isoformat()}
        )
        assert due.status_code == 200
        assert due.json()["total"] == 1
        item = due.json()["items"][0]
        assert item["schedule_id"] == initial.id
        assert item["mistake_id"] == mistake_id
        assert item["problem_text"] == "一元一次方程：解方程 2x=4，注意移项"

        first = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": initial.id,
                "correct": True,
                "completed_on": initial.due_date.isoformat(),
            },
        )
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert first_body["graduated"] is False
        assert first_body["state"] == {
            "rung": 1,
            "times_wrong": 0,
            "trailing_correct": 1,
        }
        assert first_body["interval_days"] == 10
        assert first_body["next_schedule"]["rung"] == 1
        assert first_body["due_on"] == first_body["next_schedule"]["due_date"]

        second = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": first_body["next_schedule"]["id"],
                "correct": True,
                "completed_on": first_body["due_on"],
            },
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["state"] == {
            "rung": 2,
            "times_wrong": 0,
            "trailing_correct": 2,
        }
        assert second_body["interval_days"] == 30
        assert second_body["graduated"] is False

        third = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": second_body["next_schedule"]["id"],
                "correct": True,
                "completed_on": second_body["due_on"],
            },
        )
        assert third.status_code == 200, third.text
        third_body = third.json()
        assert third_body["graduated"] is True
        assert third_body["state"] == {
            "rung": 2,
            "times_wrong": 0,
            "trailing_correct": 3,
        }
        assert third_body["interval_days"] is None
        assert third_body["due_on"] is None
        assert third_body["next_schedule"] is None

        remaining = await client.get(
            "/api/reviews/due", params={"today": second_body["due_on"]}
        )
        assert remaining.json()["total"] == 0

    schedules = await _schedules(factory, mistake_id)
    assert len(schedules) == 3
    assert all(row.completed_at is not None for row in schedules)
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, LearningEvent) == 5  # 确认入本 + 排期 + 3 次复习

    async with factory() as session:
        state = await derive_review_state(session, mistake_id)
        attempts = (
            await session.scalars(
                select(LearningEvent).where(
                    LearningEvent.type.in_(("attempt_correct", "attempt_wrong")),
                    LearningEvent.mistake_id == mistake_id,
                )
            )
        ).all()
    assert state.rung == 2
    assert state.times_wrong == 0
    assert state.trailing_correct == 3
    # 复习完成不把作答原文写进 attempts 事件/明细（隐私最小化）
    assert all("answer" not in json.loads(event.payload) for event in attempts)


@pytest.mark.integration
async def test_wrong_resets_streak_and_halves_interval(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        initial = (await _schedules(factory, mistake_id))[0]

        first = (
            await client.post(
                f"/api/reviews/{mistake_id}/complete",
                json={
                    "schedule_id": initial.id,
                    "correct": True,
                    "completed_on": initial.due_date.isoformat(),
                },
            )
        ).json()
        schedule_id = first["next_schedule"]["id"]
        due_on = first["due_on"]

        wrong_once = (
            await client.post(
                f"/api/reviews/{mistake_id}/complete",
                json={
                    "schedule_id": schedule_id,
                    "correct": False,
                    "completed_on": due_on,
                },
            )
        ).json()
        assert wrong_once["state"] == {
            "rung": 1,
            "times_wrong": 1,
            "trailing_correct": 0,
        }
        assert wrong_once["interval_days"] == 10
        assert wrong_once["graduated"] is False

        wrong_twice = (
            await client.post(
                f"/api/reviews/{mistake_id}/complete",
                json={
                    "schedule_id": wrong_once["next_schedule"]["id"],
                    "correct": False,
                    "completed_on": wrong_once["due_on"],
                },
            )
        ).json()
        assert wrong_twice["state"] == {
            "rung": 1,
            "times_wrong": 2,
            "trailing_correct": 0,
        }
        assert wrong_twice["interval_days"] == 5  # 10 天折半

        recovered = (
            await client.post(
                f"/api/reviews/{mistake_id}/complete",
                json={
                    "schedule_id": wrong_twice["next_schedule"]["id"],
                    "correct": True,
                    "completed_on": wrong_twice["due_on"],
                },
            )
        ).json()
        assert recovered["state"] == {
            "rung": 2,
            "times_wrong": 1,
            "trailing_correct": 1,
        }
        assert recovered["graduated"] is False


@pytest.mark.integration
async def test_due_queue_filters_completed_and_future(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        first = await _confirm_wrong(client)
        second = await _confirm_wrong(client)
        first_schedule = (await _schedules(factory, first["mistake_id"]))[0]
        second_schedule = (await _schedules(factory, second["mistake_id"]))[0]
        due_day = first_schedule.due_date.isoformat()

        future = await client.get(
            "/api/reviews/due",
            params={
                "today": (
                    date.fromisoformat(due_day) - timedelta(days=1)
                ).isoformat()
            },
        )
        assert future.json()["total"] == 0

        both = await client.get("/api/reviews/due", params={"today": due_day})
        assert both.json()["total"] == 2
        assert [item["schedule_id"] for item in both.json()["items"]] == [
            first_schedule.id,
            second_schedule.id,
        ]
        # 未确认主考点 → 不出同类题，退回原题重做并标 bank_gap
        assert all(
            item["task"] == "redo" and item["bank_gap"] is True
            for item in both.json()["items"]
        )

        await client.post(
            f"/api/reviews/{first['mistake_id']}/complete",
            json={
                "schedule_id": first_schedule.id,
                "correct": True,
                "completed_on": due_day,
            },
        )
        only_second = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )
        assert only_second.json()["total"] == 1
        assert only_second.json()["items"][0]["schedule_id"] == second_schedule.id


@pytest.mark.integration
async def test_initial_and_completion_are_idempotent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        again = await client.post(
            f"/api/imports/drafts/{body['draft_id']}/confirm",
            json={"actor": "student"},
        )
        assert again.status_code == 200, again.text
        assert again.json()["already_promoted"] is True
        assert again.json()["mistake_id"] == mistake_id
        assert await _count(factory, ReviewSchedule) == 1
        async with factory() as session:
            init_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(LearningEvent)
                    .where(LearningEvent.type == "review_scheduled")
                )
            )
        assert init_count == 1

        initial = (await _schedules(factory, mistake_id))[0]
        req = {
            "schedule_id": initial.id,
            "correct": True,
            "completed_on": initial.due_date.isoformat(),
        }
        first = await client.post(
            f"/api/reviews/{mistake_id}/complete", json=req
        )
        assert first.status_code == 200, first.text
        counts = (
            await _count(factory, LearningEvent),
            await _count(factory, ReviewSchedule),
        )
        repeated = await client.post(
            f"/api/reviews/{mistake_id}/complete", json=req
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == first.json()
        assert counts == (
            await _count(factory, LearningEvent),
            await _count(factory, ReviewSchedule),
        )

        missing_schedule = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": 999,
                "correct": True,
                "completed_on": initial.due_date.isoformat(),
            },
        )
        assert missing_schedule.status_code == 404
        missing_mistake = await client.post(
            "/api/reviews/999/complete",
            json={
                "schedule_id": initial.id,
                "correct": True,
                "completed_on": initial.due_date.isoformat(),
            },
        )
        assert missing_mistake.status_code == 404


@pytest.mark.integration
async def test_stale_schedule_rung_is_rejected_without_new_events(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        initial = (await _schedules(factory, mistake_id))[0]

        async with factory() as session, session.begin():
            row = await session.get(ReviewSchedule, initial.id)
            assert row is not None
            row.rung = 1
        before = await _count(factory, LearningEvent)

        stale = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": initial.id,
                "correct": True,
                "completed_on": initial.due_date.isoformat(),
            },
        )
        assert stale.status_code == 409
        assert await _count(factory, LearningEvent) == before
        assert (await _schedules(factory, mistake_id))[0].completed_at is None


@pytest.mark.integration
async def test_mastery_is_min_of_confirmed_concepts(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    concept_a = await _seed_concept(factory, name="移项")
    concept_b = await _seed_concept(factory, name="合并同类项")

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        initial = (await _schedules(factory, mistake_id))[0]

        labeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_a, concept_b],
            },
        )
        assert labeled.status_code == 200, labeled.text
        assert [item["id"] for item in labeled.json()["labels"]["concepts"]] == [
            concept_a,
            concept_b,
        ]

        now = datetime.now(UTC)
        async with factory() as session, session.begin():
            for concept_id, kinds in (
                (concept_a, ("correct", "correct", "correct", "wrong")),
                (concept_b, ("correct", "wrong")),
            ):
                for index, kind in enumerate(kinds):
                    session.add(
                        LearningEvent(
                            type=f"attempt_{kind}",
                            actor="student",
                            mistake_id=None,
                            payload=json.dumps({"concept_id": concept_id}),
                            occurred_at=now,
                            idempotency_key=f"mastery-{concept_id}-{index}-{uuid4().hex}",
                        )
                    )

        completed = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": initial.id,
                "correct": True,
                "completed_on": initial.due_date.isoformat(),
            },
        )
        assert completed.status_code == 200, completed.text
        result = completed.json()
        assert result["mastery"] == 0.5  # min(3/4, 1/2)
        assert result["interval_days"] == 30  # ceil(10 × (1 + 0.5×4))


@pytest.mark.integration
async def test_memory_subject_uses_memory_ladder(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(
        factory,
        topic_id="cnm_test_present_simple",
        name="一般现在时",
        subject="英语",
    )

    async with _client(factory) as client:
        body = await _confirm_wrong(
            client,
            subject="英语",
            problem_text="英语：一般现在时专项练习",
            student_answer="go",
            answer="goes",
        )
        mistake_id = body["mistake_id"]
        initial = (await _schedules(factory, mistake_id))[0]
        assert initial.base_interval_days == 1

        async with factory() as session:
            payload = json.loads(
                (
                    await session.scalars(
                        select(LearningEvent).where(
                            LearningEvent.type == "review_scheduled"
                        )
                    )
                ).one().payload
            )
        assert payload["subject"] == "英语"
        assert payload["ladder"] == [1, 3, 7, 14, 30]

        first = (
            await client.post(
                f"/api/reviews/{mistake_id}/complete",
                json={
                    "schedule_id": initial.id,
                    "correct": True,
                    "completed_on": initial.due_date.isoformat(),
                },
            )
        ).json()
        assert first["interval_days"] == 3
        second = (
            await client.post(
                f"/api/reviews/{mistake_id}/complete",
                json={
                    "schedule_id": first["next_schedule"]["id"],
                    "correct": True,
                    "completed_on": first["due_on"],
                },
            )
        ).json()
        assert second["interval_days"] == 7


@pytest.mark.integration
async def test_intake_without_known_subject_keeps_mistake_without_schedule(
    tmp_path,
) -> None:
    """核对页允许定不出学科时只跳过排期，错题照常入本（§16 主考点可后补）。"""

    factory = _migrated(tmp_path)

    async with _client(factory) as client:
        body = await _confirm_wrong(
            client,
            subject="信息技术",
            problem_text="信息技术基础：二进制转换",
            student_answer="101",
            answer="100",
            suggested_topic_id="",
        )
        due = await client.get("/api/reviews/due")

    assert body["primary_topic_id"] is None
    assert body["due_on"] is None
    assert due.json()["total"] == 0
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, ReviewSchedule) == 0
    async with factory() as session:
        events = (await session.scalars(select(LearningEvent))).all()
    assert [event.type for event in events] == ["attempt_wrong"]


@pytest.mark.integration
async def test_due_queue_prefers_same_type_quiz_and_tags_system_quiz(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_001", name="有理数", subject="数学")

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        await _set_primary_topic(factory, mistake_id, "cnm_001")
        schedule = (await _schedules(factory, mistake_id))[0]

        first_items = await _due_items(client, schedule.due_date)
        assert len(first_items) == 1
        item = first_items[0]
        assert item["task"] == "quiz"
        assert item["coverage"] == "ok"
        assert item["bank_gap"] is False
        assert item["coverage_hint"] is None
        assert item["primary_topic_id"] == "cnm_001"

        quiz = item["quiz"]
        replayed = find_same_type(item["primary_topic_id"], quiz["seed"])
        assert quiz["question_id"] == replayed.question_id
        assert quiz["question_id"].startswith("cnm_001_q")
        assert quiz["topic_id"] == "cnm_001"
        assert quiz["pool_size"] == replayed.pool_size >= 4
        assert quiz["seed"] == quiz_seed(mistake_id, schedule.id)
        assert quiz["prompt"].strip()
        assert quiz["mode"] == "system"
        assert quiz["quality"] == {
            "unaudited": replayed.question.unaudited,
            "blind_verified": replayed.question.blind_verified,
            "verify_status": replayed.question.verify_status,
            "verify_reason": replayed.question.verify_reason,
        }
        assert quiz["quality"]["verify_status"] in ("verified", "unverifiable")
        _assert_no_answer_keys(quiz)

        again = (await _due_items(client, schedule.due_date))[0]["quiz"]
        assert again["question_id"] == quiz["question_id"]

        # 客户端谎报 correct 无效：服务端按 bank answer 判分
        submit = {
            "schedule_id": schedule.id,
            "question_id": quiz["question_id"],
            "answer": replayed.question.answer,
            "correct": False,
            "completed_on": schedule.due_date.isoformat(),
        }
        completed = await client.post(
            f"/api/reviews/{mistake_id}/quiz", json=submit
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()
        assert body["mode"] == "system"
        assert body["verdict"] == "correct"
        assert body["completion"]["source"] == "system_quiz"
        assert body["completion"]["correct"] is True
        assert body["question"]["question_id"] == quiz["question_id"]
        _assert_no_answer_keys(body)

        repeated = await client.post(
            f"/api/reviews/{mistake_id}/quiz", json=submit
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == body

        # 原题重做自评端点绝不接受客户端直接塞 system_quiz 结果
        rejected = await client.post(
            f"/api/reviews/{mistake_id}/complete",
            json={
                "schedule_id": schedule.id,
                "correct": True,
                "source": "system_quiz",
            },
        )
        assert rejected.status_code == 422

        records = await client.get(
            "/api/attempts", params={"source": "system_quiz"}
        )
        assert records.status_code == 200
        assert records.json()["total"] == 1
        record = records.json()["items"][0]
        assert record["source"] == "system_quiz"
        assert record["kind"] == "review"
        assert record["mistake_id"] == mistake_id
        assert record["question_id"] == quiz["question_id"]
        assert record["topic_id"] == "cnm_001"
        assert record["problem_text"] == replayed.question.prompt
        assert record["answer_text"] is None

    async with factory() as session:
        attempt = (
            await session.scalars(
                select(Attempt).where(Attempt.mistake_id == mistake_id)
            )
        ).one()
    assert attempt.source == "system_quiz"
    async with factory() as session:
        event = await session.get(LearningEvent, attempt.learning_event_id)
        assert event is not None
        payload = json.loads(event.payload)
    assert payload["source"] == "system_quiz"
    assert payload["kind"] == "review"
    assert payload["concept_ids"] == []
    assert payload["quiz_question_id"] == quiz["question_id"]
    assert payload["quiz_mode"] == "system"
    assert payload["quiz_verdict"] == "correct"


@pytest.mark.integration
async def test_due_queue_falls_back_to_redo_when_topic_has_no_questions(
    tmp_path,
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_999999", name="题库空缺", subject="数学")

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        await _set_primary_topic(factory, mistake_id, "cnm_999999")
        schedule = (await _schedules(factory, mistake_id))[0]

        item = (await _due_items(client, schedule.due_date))[0]

    assert item["task"] == "redo"
    assert item["coverage"] == "gap"
    assert item["bank_gap"] is True
    assert item["coverage_hint"] is None
    assert item["quiz"] is None
    assert item["primary_topic_id"] == "cnm_999999"


@pytest.mark.integration
async def test_due_queue_thin_coverage_still_serves_quiz(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnp_001", name="速度", subject="物理")

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        await _set_primary_topic(factory, mistake_id, "cnp_001")
        schedule = (await _schedules(factory, mistake_id))[0]

        item = (await _due_items(client, schedule.due_date))[0]

    assert item["task"] == "quiz"  # thin 不是 gap，仍正常出题
    assert item["coverage"] == "thin"
    assert item["bank_gap"] is False
    assert item["coverage_hint"] == "覆盖偏薄"
    assert item["quiz"]["question_id"].startswith("cnp_001_q")


@pytest.mark.integration
async def test_due_queue_self_eval_downgrade_for_figure_topic(tmp_path) -> None:
    """解答大题/依赖题图不参与系统判分，降级为纸上做 + 自评（student_self）。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_258", name="相似三角形", subject="数学")

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        await _set_primary_topic(factory, mistake_id, "cnm_258")
        schedule = (await _schedules(factory, mistake_id))[0]

        item = (await _due_items(client, schedule.due_date))[0]
        assert item["task"] == "self_eval"
        assert item["bank_gap"] is False
        assert item["quiz"]["mode"] == "self_eval"
        assert item["quiz"]["figure"]
        _assert_no_answer_keys(item["quiz"])

        missing_verdict = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": schedule.id,
                "question_id": item["quiz"]["question_id"],
            },
        )
        assert missing_verdict.status_code == 422

        stale = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": schedule.id,
                "question_id": "cnm_001_q1",
                "correct": True,
            },
        )
        assert stale.status_code == 409

        submitted = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": schedule.id,
                "question_id": item["quiz"]["question_id"],
                "correct": True,
                "completed_on": schedule.due_date.isoformat(),
            },
        )
        assert submitted.status_code == 200, submitted.text
        result = submitted.json()
        assert result["mode"] == "self_eval"
        assert result["verdict"] == "correct"
        assert result["completion"]["source"] == "student_self"


@pytest.mark.integration
async def test_clear_attempts_keeps_review_bound_and_rebuilds_paper_rows(
    tmp_path,
) -> None:
    """attempts 可整表清空；复习排期引用的行保留，事件仍可重建考核明细。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_001", name="有理数", subject="数学")

    async with _client(factory) as client:
        body = await _confirm_wrong(client)
        mistake_id = body["mistake_id"]
        await _set_primary_topic(factory, mistake_id, "cnm_001")
        schedule = (await _schedules(factory, mistake_id))[0]

        item = (await _due_items(client, schedule.due_date))[0]
        answer = find_same_type("cnm_001", item["quiz"]["seed"]).question.answer
        completed = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": schedule.id,
                "question_id": item["quiz"]["question_id"],
                "answer": answer,
                "completed_on": schedule.due_date.isoformat(),
            },
        )
        assert completed.status_code == 200, completed.text

        paper = (
            await client.get(
                "/api/quizzes/paper",
                params={"topic_id": "cnm_001", "count": 1, "seed": 7},
            )
        ).json()
        question = paper["items"][0]
        bank_question = get_bank().question(question["question_id"])
        assert bank_question is not None
        submit = {
            "topic_id": "cnm_001",
            "seed": 7,
            "count": 1,
            "answers": [
                {
                    "question_id": question["question_id"],
                    "answer": bank_question.answer,
                }
            ],
        }
        graded = await client.post("/api/quizzes/paper/submit", json=submit)
        assert graded.status_code == 200, graded.text
        assert graded.json()["items"][0]["status"] == "correct"

        cleared = await client.delete("/api/attempts")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"deleted": 1, "kept": 1}

        remaining = await client.get("/api/attempts")
        assert remaining.json()["total"] == 1
        assert remaining.json()["items"][0]["mistake_id"] == mistake_id

        # 事件仍是事实源：重新交同一张卷补回派生 attempts 行
        rebuilt = await client.post("/api/quizzes/paper/submit", json=submit)
        assert rebuilt.status_code == 200, rebuilt.text
        assert rebuilt.json()["items"][0]["replayed"] is True
        assert rebuilt.json()["items"][0]["attempt_id"] is not None
        assert (await client.get("/api/attempts")).json()["total"] == 2
