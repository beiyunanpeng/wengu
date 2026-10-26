"""P1-7a 复习排期集成测试：用户触发、事实重放、幂等、到期队列、学科闸门。

模型调用为零（客观题判分走 judgeAnswer）；聚焦纪律与状态机，不验证真实 VLM。
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
    Concept,
    GradingResult,
    GradingVersion,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    PhotoCapture,
    ProblemExtraction,
    ReviewSchedule,
)
from app.providers.base import CallMeta, GradeResult
from app.services.ai_gateway import get_ai_gateway
from app.services.review import derive_review_state
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "reviews.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


class FakeGradeGateway:
    async def grade(
        self,
        problem_text: str,
        student_answer: str,
        *,
        prompt: str = "",
        standard_answer: str = "",
        sample_index: int = 0,
    ) -> tuple[GradeResult, CallMeta]:
        return (
            GradeResult(
                verdict="correct", confidence=0.9, source="ai", rationale="ok"
            ),
            CallMeta(
                provider="fake",
                model="fake-v1",
                latency_ms=1,
                prompt_id="grade",
                prompt_version=1,
            ),
        )


def _client(factory: async_sessionmaker, gateway) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
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


async def _seed_extraction(
    factory: async_sessionmaker,
    *,
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str | None = "x=3",
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        capture = PhotoCapture(
            sha256=uuid4().hex,
            stored_path="pages/x.png",
            original_name="x.png",
            source="phone",
            status="sliced",
            created_at=now,
        )
        session.add(capture)
        await session.flush()
        row = ProblemExtraction(
            photo_capture_id=capture.id,
            seq=1,
            source_kind="slice",
            image_path="slices/x-01.png",
            problem_text=problem_text,
            student_answer=student_answer,
            confidence=0.9,
            problem_complete=True,
            gate_status="ready_for_grading",
            review_reasons_json="[]",
            figure_keywords_json="[]",
            prompt_id="extract_problem",
            prompt_version=1,
            provider="fake",
            model="fake-v1",
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _confirm_wrong(
    client: AsyncClient,
    factory: async_sessionmaker,
    *,
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str = "x=3",
    answer: str = "x=2",
) -> dict:
    extraction_id = await _seed_extraction(
        factory, problem_text=problem_text, student_answer=student_answer
    )
    created = await client.post(
        "/api/gradings",
        json={
            "source_kind": "problem_extraction",
            "source_id": extraction_id,
            "question_type": "objective",
            "answer": answer,
        },
    )
    assert created.status_code == 200, created.text
    grading = created.json()["grading"]
    confirmed = await client.post(
        f"/api/gradings/{grading['id']}/confirm",
        json={"base_version": 1, "verdict": "wrong"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


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


@pytest.mark.integration
async def test_confirm_wrong_schedules_and_three_corrects_graduate(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)

    async with _client(factory, gateway) as client:
        body = await _confirm_wrong(client, factory)
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
    gateway = FakeGradeGateway()
    await _seed_topic(factory)

    async with _client(factory, gateway) as client:
        body = await _confirm_wrong(client, factory)
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
async def test_due_queue_filters_completed_future_and_voided(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)

    async with _client(factory, gateway) as client:
        first = await _confirm_wrong(client, factory)
        second = await _confirm_wrong(client, factory)
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

        await client.post(
            f"/api/gradings/{second['id']}/appeal",
            json={"base_version": 2, "verdict": "correct"},
        )
        voided = await client.get("/api/reviews/due", params={"today": due_day})
        assert voided.json()["total"] == 0

        blocked = await client.post(
            f"/api/reviews/{second['mistake_id']}/complete",
            json={
                "schedule_id": second_schedule.id,
                "correct": True,
                "completed_on": due_day,
            },
        )
        assert blocked.status_code == 409


@pytest.mark.integration
async def test_initial_and_completion_are_idempotent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(factory)

    async with _client(factory, gateway) as client:
        body = await _confirm_wrong(client, factory)
        mistake_id = body["mistake_id"]
        again = await client.post(
            f"/api/gradings/{body['id']}/confirm",
            json={"base_version": 2},
        )
        assert again.status_code == 200, again.text
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
    gateway = FakeGradeGateway()
    await _seed_topic(factory)

    async with _client(factory, gateway) as client:
        body = await _confirm_wrong(client, factory)
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
    gateway = FakeGradeGateway()
    await _seed_topic(factory)
    concept_a = await _seed_concept(factory, name="移项")
    concept_b = await _seed_concept(factory, name="合并同类项")

    async with _client(factory, gateway) as client:
        body = await _confirm_wrong(client, factory)
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
    gateway = FakeGradeGateway()
    await _seed_topic(
        factory,
        topic_id="cnm_test_present_simple",
        name="一般现在时",
        subject="英语",
    )

    async with _client(factory, gateway) as client:
        body = await _confirm_wrong(
            client,
            factory,
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
async def test_unknown_subject_rolls_back_confirmation(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()

    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(
            factory, problem_text="1+1=?", student_answer="3"
        )
        created = await client.post(
            "/api/gradings",
            json={
                "source_kind": "problem_extraction",
                "source_id": extraction_id,
                "question_type": "objective",
                "answer": "2",
            },
        )
        grading = created.json()["grading"]
        confirmed = await client.post(
            f"/api/gradings/{grading['id']}/confirm",
            json={"base_version": 1, "verdict": "wrong"},
        )

    assert confirmed.status_code == 422
    assert "无法确定学科" in confirmed.json()["detail"]
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, ReviewSchedule) == 0
    assert await _count(factory, LearningEvent) == 0
    assert await _count(factory, GradingVersion) == 1
    async with factory() as session:
        row = await session.get(GradingResult, grading["id"])
        assert row is not None
        assert row.current_version == 1
        assert row.status == "pending"


@pytest.mark.integration
async def test_unsupported_subject_rolls_back_confirmation(tmp_path) -> None:
    factory = _migrated(tmp_path)
    gateway = FakeGradeGateway()
    await _seed_topic(
        factory,
        topic_id="cnm_test_it",
        name="信息技术基础",
        subject="信息技术",
    )

    async with _client(factory, gateway) as client:
        extraction_id = await _seed_extraction(
            factory, problem_text="信息技术基础：二进制转换", student_answer="101"
        )
        created = await client.post(
            "/api/gradings",
            json={
                "source_kind": "problem_extraction",
                "source_id": extraction_id,
                "question_type": "objective",
                "answer": "100",
            },
        )
        grading = created.json()["grading"]
        confirmed = await client.post(
            f"/api/gradings/{grading['id']}/confirm",
            json={"base_version": 1, "verdict": "wrong"},
        )

    assert confirmed.status_code == 422
    assert "未配置复习阶梯" in confirmed.json()["detail"]
    assert await _count(factory, Mistake) == 0
    assert await _count(factory, ReviewSchedule) == 0
    assert await _count(factory, LearningEvent) == 0
