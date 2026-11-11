"""P1-6 错题本集成测试：唯一写入（核对页确认）、两级标签、派生练习表、seed/concept 查询。

v2.5：真实题在系统外批改，错题只经"外部转录 → 核对页确认"入本，系统内零模型调用；
这里只验证纪律与数据隔离。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Concept,
    ConceptAlias,
    GradingVersion,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    PracticeRecord,
    ProblemBankItem,
    ReviewSchedule,
)
from app.services.concepts import concept_family_ids, resolve_concepts
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "mistakes.db"
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
        # 作废/撤销/归并属家长区：默认先设 PIN 或解锁（孩子区端点不受影响）
        if unlock:
            status = await client.get("/api/session/status")
            if status.json()["pin_set"]:
                response = await client.post(
                    "/api/session/unlock", json={"pin": "2468"}
                )
            else:
                response = await client.post(
                    "/api/session/pin/set", json={"pin": "2468"}
                )
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
                chapter="一元一次方程",
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )


async def _seed_concept(
    factory: async_sessionmaker,
    *,
    name: str,
    category_id: str,
    aliases: tuple[str, ...] = (),
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
        for alias in aliases:
            session.add(ConceptAlias(concept_id=row.id, alias=alias))
        await session.flush()
        return row.id


async def _seed_bank(
    factory: async_sessionmaker,
    *,
    problem_text: str = "求 1/2",
    answer: str = "1/2",
) -> int:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        row = ProblemBankItem(
            external_id=uuid4().hex,
            subject="数学",
            problem_text=problem_text,
            answer=answer,
            acceptable_answers_json="[]",
            unordered=False,
            verify=answer,
            verify_vars_json="{}",
            verify_status="verified",
            source="test",
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _import_draft(
    client: AsyncClient,
    *,
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str = "x=3",
    standard_answer: str = "x=2",
    subject: str = "数学",
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
                    # 报文去重按 sha256：每题唯一 source_ref，避免测试间复用旧批次
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


async def _create_mistake(
    client: AsyncClient,
    *,
    problem_text: str = "一元一次方程：解方程 2x=4，注意移项",
    student_answer: str = "x=3",
    answer: str = "x=2",
    primary_topic_id: str | None = "cnm_test_equation",
    error_cause: str | None = None,
    concept_ids: tuple[int, ...] = (),
) -> dict:
    draft_id = await _import_draft(
        client,
        problem_text=problem_text,
        student_answer=student_answer,
        standard_answer=answer,
    )
    payload: dict = {"actor": "student"}
    if primary_topic_id is not None:
        payload["primary_topic_id"] = primary_topic_id
    if error_cause is not None:
        payload["error_cause"] = error_cause
    if concept_ids:
        payload["concept_ids"] = list(concept_ids)
    confirmed = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm", json=payload
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    body["draft_id"] = draft_id
    return body


@pytest.mark.integration
async def test_intake_confirmation_creates_mistake_once(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )

    async with _client(factory) as client:
        body = await _create_mistake(
            client, error_cause="calculation", concept_ids=(concept_id,)
        )
        mistake_id = body["mistake_id"]
        count_after_create = await _count(factory, Mistake)
        versions_after_create = await _count(factory, MistakeVersion)

        listed = await client.get("/api/mistakes")
        detail = await client.get(f"/api/mistakes/{mistake_id}")

        again = await client.post(
            f"/api/imports/drafts/{body['draft_id']}/confirm",
            json={"actor": "student"},
        )

    assert body["already_promoted"] is False
    assert count_after_create == 1
    assert versions_after_create == 1
    assert await _count(factory, ReviewSchedule) == 1

    assert listed.status_code == 200
    listing = listed.json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["id"] == mistake_id
    assert item["problem_text"] == "一元一次方程：解方程 2x=4，注意移项"
    assert item["is_correct"] is False
    labels = item["labels"]
    assert labels["confirmed"] is True
    assert labels["confirmed_by"] == "student"
    assert labels["category_id"] == "cnm_test_equation"
    assert labels["category_name"] == "一元一次方程"
    assert [c["id"] for c in labels["concepts"]] == [concept_id]
    assert labels["error_cause"] == "calculation"
    assert item["suggestion"]["category_id"] == "cnm_test_equation"

    assert detail.status_code == 200
    assert detail.json() == item

    assert again.status_code == 200, again.text
    assert again.json()["already_promoted"] is True
    assert again.json()["mistake_id"] == mistake_id
    assert await _count(factory, Mistake) == 1
    assert await _count(factory, MistakeVersion) == 1  # 重复确认不追加内容版本
    assert await _count(factory, ReviewSchedule) == 1  # 重复确认不重复排期

    async with factory() as session:
        events = (await session.scalars(select(LearningEvent).order_by(LearningEvent.id))).all()
    assert [event.type for event in events] == ["review_scheduled", "attempt_wrong"]
    assert [event.mistake_id for event in events] == [mistake_id, mistake_id]


@pytest.mark.integration
async def test_void_and_unvoid_mistake_lifecycle(tmp_path) -> None:
    """作废/撤销只翻 status + 追加事件：退出活跃列表与到期队列，历史全部留痕。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        body = await _create_mistake(client)
        mistake_id = body["mistake_id"]
        versions_before = await _count(factory, MistakeVersion)

        async with factory() as session:
            schedule = (
                await session.execute(
                    select(ReviewSchedule).where(
                        ReviewSchedule.mistake_id == mistake_id
                    )
                )
            ).scalar_one()
        due_day = schedule.due_date.isoformat()

        due_before = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )
        assert due_before.json()["due_total"] == 1

        voided = await client.post(
            f"/api/mistakes/{mistake_id}/void",
            json={"actor": "parent", "reason": "已当面讲通，暂不复习"},
        )
        again = await client.post(
            f"/api/mistakes/{mistake_id}/void", json={"actor": "student"}
        )
        active_list = await client.get("/api/mistakes?status=active")
        all_list = await client.get("/api/mistakes?status=all")
        due_after = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )
        detail = await client.get(f"/api/mistakes/{mistake_id}")
        labels = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 1, "error_cause": "careless"},
        )
        missing = await client.post(
            "/api/mistakes/9999/void", json={"actor": "student"}
        )
        bad_actor = await client.post(
            f"/api/mistakes/{mistake_id}/void", json={"actor": "teacher"}
        )

        unvoided = await client.post(
            f"/api/mistakes/{mistake_id}/unvoid", json={"actor": "student"}
        )
        again_unvoid = await client.post(
            f"/api/mistakes/{mistake_id}/unvoid", json={"actor": "student"}
        )
        due_restored = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )
        bad_actor_unvoid = await client.post(
            f"/api/mistakes/{mistake_id}/unvoid", json={"actor": "teacher"}
        )
        final_list = await client.get("/api/mistakes")

    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"
    assert voided.json()["labels"]["category_id"] == "cnm_test_equation"
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "voided"
    assert active_list.json()["total"] == 0
    assert all_list.json()["total"] == 1
    assert all_list.json()["items"][0]["status"] == "voided"
    assert due_after.json()["due_total"] == 0
    assert detail.status_code == 200
    assert detail.json()["status"] == "voided"
    assert detail.json()["current_version"] == 1
    assert detail.json()["problem_text"] == "一元一次方程：解方程 2x=4，注意移项"
    assert labels.status_code == 409  # 已作废错题沿用"不能改标签"护栏
    assert missing.status_code == 404
    assert bad_actor.status_code == 409

    assert unvoided.status_code == 200, unvoided.text
    assert unvoided.json()["status"] == "active"
    assert again_unvoid.status_code == 200, again_unvoid.text
    assert again_unvoid.json()["status"] == "active"
    assert bad_actor_unvoid.status_code == 409
    assert due_restored.json()["due_total"] == 1
    assert due_restored.json()["items"][0]["mistake_id"] == mistake_id
    assert final_list.json()["total"] == 1

    assert await _count(factory, MistakeVersion) == versions_before
    async with factory() as session:
        events = (
            await session.scalars(
                select(LearningEvent).order_by(LearningEvent.id)
            )
        ).all()
    assert [event.type for event in events] == [
        "review_scheduled",
        "attempt_wrong",
        "mistake_voided",
        "mistake_reactivated",
    ]
    void_event = events[2]
    assert void_event.idempotency_key == f"mistake:{mistake_id}:void"
    assert void_event.actor == "parent"
    payload = json.loads(void_event.payload)
    assert payload["actor"] == "parent"
    assert payload["reason"] == "已当面讲通，暂不复习"
    assert payload["mistake_id"] == mistake_id
    assert events[3].idempotency_key == f"mistake:{mistake_id}:reactivate"
    assert events[3].actor == "student"


@pytest.mark.integration
async def test_label_confirmation_optimistic_lock_and_filters(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory,
        topic_id="cne_test_reading",
        name="阅读理解",
        subject="英语",
    )
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )
    other_concept_id = await _seed_concept(
        factory, name="略读", category_id="cne_test_reading"
    )

    async with _client(factory) as client:
        body = await _create_mistake(client)
        mistake_id = body["mistake_id"]

        labeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
                "error_cause": "calculation",
                "actor": "student",
            },
        )
        stale = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 1, "category_id": "cnm_test_equation"},
        )
        bad_cause = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "error_cause": "made_up"},
        )
        bad_category = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "category_id": "cnm_missing"},
        )
        wrong_category = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 2,
                "category_id": "cnm_test_equation",
                "concept_ids": [other_concept_id],
            },
        )
        by_category = await client.get(
            "/api/mistakes?category_id=cnm_test_equation"
        )
        by_concept = await client.get(f"/api/mistakes?concept_id={concept_id}")
        by_cause = await client.get("/api/mistakes?error_cause=calculation")
        miss = await client.get("/api/mistakes?error_cause=careless")

    assert labeled.status_code == 200, labeled.text
    labeled_body = labeled.json()
    assert labeled_body["current_version"] == 2
    assert labeled_body["labels"]["confirmed"] is True
    assert labeled_body["labels"]["confirmed_by"] == "student"
    assert labeled_body["labels"]["category_id"] == "cnm_test_equation"
    assert labeled_body["labels"]["error_cause"] == "calculation"
    assert labeled_body["labels"]["error_cause_label"] == "计算失误"
    assert [c["id"] for c in labeled_body["labels"]["concepts"]] == [concept_id]

    assert stale.status_code == 409
    assert bad_cause.status_code == 422
    assert bad_category.status_code == 422
    assert wrong_category.status_code == 422
    assert by_category.json()["total"] == 1
    assert by_concept.json()["total"] == 1
    assert by_cause.json()["total"] == 1
    assert miss.json()["total"] == 0
    assert await _count(factory, MistakeVersion) == 2

    async with factory() as session:
        events = (await session.scalars(select(LearningEvent))).all()
    labeled_events = [event for event in events if event.type == "mistake_labeled"]
    assert len(labeled_events) == 1
    assert labeled_events[0].idempotency_key == f"mistake:{mistake_id}:v2"
    assert labeled_events[0].mistake_id == mistake_id


@pytest.mark.integration
async def test_partial_label_update_preserves_other_confirmed_values(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )

    async with _client(factory) as client:
        body = await _create_mistake(client)
        mistake_id = body["mistake_id"]
        await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
                "error_cause": "calculation",
            },
        )
        partial = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "error_cause": "careless"},
        )
        cleared = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 3, "concept_ids": []},
        )

    assert partial.status_code == 200, partial.text
    labels = partial.json()["labels"]
    assert labels["category_id"] == "cnm_test_equation"
    assert [c["id"] for c in labels["concepts"]] == [concept_id]
    assert labels["error_cause"] == "careless"

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["labels"]["category_id"] == "cnm_test_equation"
    assert cleared.json()["labels"]["concepts"] == []
    assert cleared.json()["labels"]["error_cause"] == "careless"
    assert await _count(factory, MistakeVersion) == 4


@pytest.mark.integration
async def test_concept_create_reuse_merge_and_historical_label_resolution(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        first = await client.post(
            "/api/concepts",
            json={
                "name": "移项",
                "category_id": "cnm_test_equation",
                "aliases": ["移项法则"],
            },
        )
        reused = await client.post(
            "/api/concepts",
            json={"name": "移项法则", "category_id": "cnm_test_equation"},
        )
        target = await client.post(
            "/api/concepts",
            json={"name": "等式性质", "category_id": "cnm_test_equation"},
        )
        concept_id = first.json()["id"]
        target_id = target.json()["id"]

        body = await _create_mistake(client)
        mistake_id = body["mistake_id"]
        await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 1,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
            },
        )
        merged = await client.post(
            "/api/concepts/merge",
            json={"source_id": concept_id, "target_id": target_id},
        )
        detail = await client.get(f"/api/mistakes/{mistake_id}")
        concepts = await client.get("/api/concepts?category_id=cnm_test_equation")
        q = await client.get("/api/concepts?q=法则")

    assert first.status_code == 200, first.text
    assert first.json()["reused"] is False
    assert first.json()["aliases"] == ["移项法则"]
    assert reused.status_code == 200
    assert reused.json()["id"] == concept_id
    assert reused.json()["reused"] is True

    assert merged.status_code == 200, merged.text
    assert merged.json()["source"]["merged_into_id"] == target_id
    assert merged.json()["target"]["id"] == target_id
    assert merged.json()["aliases_moved"] >= 1

    assert detail.status_code == 200
    resolved = detail.json()["labels"]["concepts"]
    assert len(resolved) == 1
    assert resolved[0]["id"] == target_id
    assert resolved[0]["name"] == "等式性质"

    ids = {item["id"] for item in concepts.json()["items"]}
    assert concept_id not in ids
    assert target_id in ids
    assert [item["id"] for item in q.json()["items"]] == [target_id]


@pytest.mark.integration
async def test_practice_records_are_isolated_and_clearable(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    bank_id = await _seed_bank(factory)

    async with _client(factory) as client:
        body = await _create_mistake(client)
        mistake_id = body["mistake_id"]
        before = (
            await _count(factory, MistakeVersion),
            await _count(factory, LearningEvent),
            await _count(factory, GradingVersion),
        )

        variant = await client.post(
            "/api/practice-records",
            json={
                "kind": "variant",
                "source_mistake_id": mistake_id,
                "problem_bank_id": bank_id,
                "student_answer": "1/2",
                "is_correct": True,
            },
        )
        extra = await client.post(
            "/api/practice-records",
            json={
                "kind": "extra",
                "problem_text": "自选加练：3x=6",
                "student_answer": "x=2",
            },
        )
        listed = await client.get(
            f"/api/practice-records?source_mistake_id={mistake_id}"
        )
        all_rows = await client.get("/api/practice-records")
        cleared = await client.delete("/api/practice-records")
        empty = await client.get("/api/practice-records")
        detail = await client.get(f"/api/mistakes/{mistake_id}")

        missing_mistake = await client.post(
            "/api/practice-records",
            json={"kind": "extra", "source_mistake_id": 999, "problem_text": "x"},
        )
        missing_text = await client.post(
            "/api/practice-records", json={"kind": "extra"}
        )

    assert variant.status_code == 200, variant.text
    assert variant.json()["problem_text"] == "求 1/2"
    assert variant.json()["problem_bank_id"] == bank_id
    assert extra.status_code == 200
    assert extra.json()["problem_text"] == "自选加练：3x=6"

    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == variant.json()["id"]
    assert all_rows.json()["total"] == 2
    assert cleared.json()["deleted"] == 2
    assert empty.json()["total"] == 0
    assert detail.status_code == 200
    assert detail.json()["id"] == mistake_id

    after = (
        await _count(factory, MistakeVersion),
        await _count(factory, LearningEvent),
        await _count(factory, GradingVersion),
    )
    assert before == after  # 派生表不写事件、不动错题版本/批改版本

    assert missing_mistake.status_code == 404
    assert missing_text.status_code == 422
    assert await _count(factory, PracticeRecord) == 0


@pytest.mark.integration
async def test_seed_topics_query_and_mistake_options(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory,
        topic_id="cne_test_word",
        name="词汇",
        subject="英语",
    )

    async with _client(factory) as client:
        all_topics = await client.get("/api/seed/topics")
        math_topics = await client.get("/api/seed/topics?subject=数学")
        search = await client.get("/api/seed/topics?q=方程")
        paged = await client.get("/api/seed/topics?limit=1&offset=1")
        options = await client.get("/api/mistakes/options")

    assert all_topics.status_code == 200, all_topics.text
    assert all_topics.json()["total"] == 2
    assert math_topics.json()["total"] == 1
    assert math_topics.json()["items"][0]["id"] == "cnm_test_equation"
    assert [item["id"] for item in search.json()["items"]] == ["cnm_test_equation"]
    assert paged.json()["total"] == 2
    assert len(paged.json()["items"]) == 1

    causes = {item["id"]: item["label"] for item in options.json()["error_causes"]}
    assert causes["prerequisite_gap"] == "前置知识缺失"
    assert causes["calculation"] == "计算失误"
    assert "other" in causes


async def _mistake_version_snapshot(factory: async_sessionmaker) -> list[dict]:
    async with factory() as session:
        rows = (
            await session.scalars(select(MistakeVersion).order_by(MistakeVersion.id))
        ).all()
    return [
        {
            column.name: getattr(row, column.name)
            for column in MistakeVersion.__table__.columns
        }
        for row in rows
    ]


@pytest.mark.integration
async def test_merge_preview_and_merge_keep_history_and_resolve_family(tmp_path) -> None:
    """P1-13：预览实扫 active 错题；归并只改 merged_into_id/别名，历史版本逐行不变。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    source_id = await _seed_concept(
        factory,
        name="移项",
        category_id="cnm_test_equation",
        aliases=("移项法则",),
    )
    target_id = await _seed_concept(
        factory, name="等式性质", category_id="cnm_test_equation"
    )

    async with _client(factory) as client:
        first = await _create_mistake(
            client, problem_text="题一：解方程 2x=4", concept_ids=(source_id,)
        )
        await _create_mistake(
            client, problem_text="题二：解方程 3x=9", concept_ids=(source_id,)
        )
        voided = await _create_mistake(
            client, problem_text="题三：解方程 4x=8", concept_ids=(source_id,)
        )
        voided_response = await client.post(
            f"/api/mistakes/{voided['mistake_id']}/void",
            json={"actor": "parent", "reason": "测试作废"},
        )
        assert voided_response.status_code == 200, voided_response.text

        versions_before = await _mistake_version_snapshot(factory)

        preview = await client.get(
            "/api/concepts/merge-preview",
            params={"source_id": source_id, "target_id": target_id},
        )
        merged = await client.post(
            "/api/concepts/merge",
            json={"source_id": source_id, "target_id": target_id, "actor": "parent"},
        )
        listed = await client.get("/api/concepts?category_id=cnm_test_equation")
        detail = await client.get(f"/api/mistakes/{first['mistake_id']}")

    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["source"]["id"] == source_id
    assert preview_body["target"]["id"] == target_id
    assert preview_body["source_aliases"] == ["移项法则"]
    assert preview_body["projected_aliases_moved"] == 2  # 源名称 + 源别名
    assert preview_body["affected_mistakes"] == 2  # 2 道 active，voided 不计
    assert preview_body["same_category"] is True

    assert merged.status_code == 200, merged.text
    merged_body = merged.json()
    assert merged_body["source"]["merged_into_id"] == target_id
    assert merged_body["aliases_moved"] == 2  # 源名称 + 源别名
    # 确认框显示的数字必须与归并响应一致（不把源名称漏报）
    assert preview_body["projected_aliases_moved"] == merged_body["aliases_moved"]
    assert "移项" in merged_body["target"]["aliases"]
    assert "移项法则" in merged_body["target"]["aliases"]

    assert await _mistake_version_snapshot(factory) == versions_before

    listed_ids = {item["id"] for item in listed.json()["items"]}
    assert source_id not in listed_ids
    assert target_id in listed_ids
    assert [c["id"] for c in detail.json()["labels"]["concepts"]] == [target_id]

    async with factory() as session:
        resolved = await resolve_concepts(session, [source_id])
        family = await concept_family_ids(session, target_id)
        source_row = await session.get(Concept, source_id)
    assert [concept.id for concept in resolved] == [target_id]
    assert source_id in family
    assert source_row is not None
    assert source_row.merged_into_id == target_id


@pytest.mark.integration
async def test_merge_requires_parent_but_child_concept_area_stays_open(tmp_path) -> None:
    """P1-13：仅归并端点挂 PIN；未解锁时列表与建点/复用仍可用。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    source_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )
    target_id = await _seed_concept(
        factory, name="等式性质", category_id="cnm_test_equation"
    )

    async with _client(factory, unlock=False) as client:
        created = await client.post(
            "/api/concepts",
            json={"name": "孩子新建点", "category_id": "cnm_test_equation"},
        )
        listed = await client.get("/api/concepts?category_id=cnm_test_equation")
        preview = await client.get(
            "/api/concepts/merge-preview",
            params={"source_id": source_id, "target_id": target_id},
        )
        merged = await client.post(
            "/api/concepts/merge",
            json={"source_id": source_id, "target_id": target_id, "actor": "parent"},
        )

    assert listed.status_code == 200, listed.text
    assert created.status_code == 200, created.text
    assert created.json()["reused"] is False
    assert "孩子新建点" in {item["name"] for item in listed.json()["items"]}

    assert preview.status_code == 403
    assert merged.status_code == 403

    async with factory() as session:
        source_row = await session.get(Concept, source_id)
    assert source_row is not None
    assert source_row.merged_into_id is None


@pytest.mark.integration
async def test_merge_error_branches_return_stable_codes(tmp_path) -> None:
    """P1-13：自归并/跨 category/第三方别名/已归并 → 409；不存在 → 404。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory, topic_id="cnm_test_geometry", name="几何", subject="数学"
    )
    equation_source = await _seed_concept(
        factory, name="方程源", category_id="cnm_test_equation"
    )
    equation_target = await _seed_concept(
        factory, name="方程目标", category_id="cnm_test_equation"
    )
    geometry_concept = await _seed_concept(
        factory, name="几何点", category_id="cnm_test_geometry"
    )
    alias_source = await _seed_concept(
        factory,
        name="别名源",
        category_id="cnm_test_equation",
        aliases=("冲突别名",),
    )
    await _seed_concept(factory, name="冲突别名", category_id="cnm_test_equation")
    already_merged_source = await _seed_concept(
        factory, name="已归并源", category_id="cnm_test_equation"
    )
    middle = await _seed_concept(factory, name="中间点", category_id="cnm_test_equation")
    final = await _seed_concept(factory, name="最终点", category_id="cnm_test_equation")

    async with _client(factory) as client:
        self_merge = await client.post(
            "/api/concepts/merge",
            json={
                "source_id": equation_source,
                "target_id": equation_source,
                "actor": "parent",
            },
        )
        cross_preview = await client.get(
            "/api/concepts/merge-preview",
            params={"source_id": equation_source, "target_id": geometry_concept},
        )
        cross_merge = await client.post(
            "/api/concepts/merge",
            json={
                "source_id": equation_source,
                "target_id": geometry_concept,
                "actor": "parent",
            },
        )
        alias_conflict = await client.post(
            "/api/concepts/merge",
            json={
                "source_id": alias_source,
                "target_id": equation_target,
                "actor": "parent",
            },
        )
        first_merge = await client.post(
            "/api/concepts/merge",
            json={
                "source_id": already_merged_source,
                "target_id": middle,
                "actor": "parent",
            },
        )
        again_source = await client.post(
            "/api/concepts/merge",
            json={
                "source_id": already_merged_source,
                "target_id": middle,
                "actor": "parent",
            },
        )
        merge_middle = await client.post(
            "/api/concepts/merge",
            json={"source_id": middle, "target_id": final, "actor": "parent"},
        )
        to_merged_target = await client.post(
            "/api/concepts/merge",
            json={
                "source_id": equation_target,
                "target_id": middle,
                "actor": "parent",
            },
        )
        missing_preview = await client.get(
            "/api/concepts/merge-preview",
            params={"source_id": 999999, "target_id": equation_target},
        )
        missing_merge = await client.post(
            "/api/concepts/merge",
            json={"source_id": 999999, "target_id": equation_target, "actor": "parent"},
        )

    assert self_merge.status_code == 409, self_merge.text
    assert cross_preview.status_code == 200, cross_preview.text
    assert cross_preview.json()["same_category"] is False
    assert cross_merge.status_code == 409, cross_merge.text
    assert alias_conflict.status_code == 409, alias_conflict.text
    assert "请先归并那个概念" in alias_conflict.json()["detail"]
    assert first_merge.status_code == 200, first_merge.text
    assert again_source.status_code == 409, again_source.text
    assert merge_middle.status_code == 200, merge_middle.text
    assert to_merged_target.status_code == 409, to_merged_target.text
    assert missing_preview.status_code == 404, missing_preview.text
    assert missing_merge.status_code == 404, missing_merge.text


async def _open_schedule(
    factory: async_sessionmaker, mistake_id: int
) -> ReviewSchedule:
    async with factory() as session:
        return (
            await session.execute(
                select(ReviewSchedule)
                .where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
                .order_by(ReviewSchedule.id)
                .limit(1)
            )
        ).scalar_one()


async def _complete_correct(
    client: AsyncClient, factory: async_sessionmaker, mistake_id: int
) -> dict:
    schedule = await _open_schedule(factory, mistake_id)
    response = await client.post(
        f"/api/reviews/{mistake_id}/complete",
        json={
            "schedule_id": schedule.id,
            "correct": True,
            "completed_on": schedule.due_date.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ids(response) -> set[int]:
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["items"]}


@pytest.mark.integration
async def test_list_q_searches_current_text_and_answer_case_insensitive(
    tmp_path,
) -> None:
    """P2-9 DoD：q 命中题干/答案、大小写不敏感、空 q 不过滤、通配符转义（%/_/\\）、
    不搜历史版本、超长 422。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        m1 = await _create_mistake(
            client, problem_text="解方程 2x=4", answer="x=2"
        )
        m2 = await _create_mistake(
            client, problem_text="Triangle ABC 的面积", answer="12"
        )
        m3 = await _create_mistake(
            client, problem_text="应用题：路程问题", answer="ABC"
        )
        # % 鉴别对：仅差一个通配位，未转义时 q="5%off" 会把 5Xoff 也命中
        m4 = await _create_mistake(client, problem_text="5%off", answer="0.5")
        m5 = await _create_mistake(client, problem_text="5Xoff", answer="0.5")
        # 反斜杠鉴别：题干含真反斜杠 a\b
        m6 = await _create_mistake(client, problem_text="a\\b", answer="1")
        all_ids = {
            m1["mistake_id"],
            m2["mistake_id"],
            m3["mistake_id"],
            m4["mistake_id"],
            m5["mistake_id"],
            m6["mistake_id"],
        }

        # 历史版本设防：直插一条 version 比当前小的历史行（确认入本后当前 version=1，
        # 故历史行 version=0），唯一关键词只存在于历史版本，当前版本不含它。
        async with factory() as session, session.begin():
            session.add(
                MistakeVersion(
                    mistake_id=m1["mistake_id"],
                    version=0,
                    problem_text="旧题干关键词ZZZ",
                    standard_answer="旧答案",
                    created_at=datetime.now(UTC),
                )
            )

        stem_hit = await client.get("/api/mistakes", params={"q": "方程"})
        answer_hit = await client.get("/api/mistakes", params={"q": "X=2"})
        case_insensitive = await client.get("/api/mistakes", params={"q": "abc"})
        empty_q = await client.get("/api/mistakes", params={"q": ""})
        no_q = await client.get("/api/mistakes")
        percent_literal = await client.get("/api/mistakes", params={"q": "5%off"})
        percent_other = await client.get("/api/mistakes", params={"q": "5Xoff"})
        underscore_literal = await client.get(
            "/api/mistakes", params={"q": "a_c"}
        )
        backslash_literal = await client.get(
            "/api/mistakes", params={"q": "a\\b"}
        )
        backslash_stripped = await client.get("/api/mistakes", params={"q": "ab"})
        history_only = await client.get(
            "/api/mistakes", params={"q": "旧题干关键词ZZZ"}
        )
        current_after_history = await client.get(
            "/api/mistakes", params={"q": "解方程"}
        )
        no_match = await client.get("/api/mistakes", params={"q": "不存在的词"})
        too_long = await client.get("/api/mistakes", params={"q": "x" * 101})
        max_length = await client.get("/api/mistakes", params={"q": "x" * 100})

    assert _ids(stem_hit) == {m1["mistake_id"]}
    assert _ids(answer_hit) == {m1["mistake_id"]}
    # abc 同时命中 m2 题干（大写 ABC）与 m3 答案：大小写不敏感 + 答案可搜
    assert _ids(case_insensitive) == {m2["mistake_id"], m3["mistake_id"]}
    assert _ids(empty_q) == all_ids
    assert _ids(no_q) == all_ids
    # % 转义：q="5%off" 只命中字面 5%off；未转义时 % 当通配会连 5Xoff 一起命中
    assert _ids(percent_literal) == {m4["mistake_id"]}
    assert _ids(percent_other) == {m5["mistake_id"]}
    assert _ids(underscore_literal) == set()
    # 反斜杠转义：q="a\b" 命中 a\b；q="ab" 不命中它（未转义 \ 时 ESCAPE 行为会分叉）
    assert _ids(backslash_literal) == {m6["mistake_id"]}
    assert m6["mistake_id"] not in _ids(backslash_stripped)
    # 历史版本设防：唯一关键词只在 version=0 历史行 → 空集；当前版本仍可正常搜到
    assert _ids(history_only) == set()
    assert m1["mistake_id"] in _ids(current_after_history)
    assert no_match.status_code == 200
    assert no_match.json()["total"] == 0
    assert too_long.status_code == 422, too_long.text
    assert max_length.status_code == 200, max_length.text


@pytest.mark.integration
async def test_list_mastery_state_derived_from_review_replay(tmp_path) -> None:
    """P2-9 DoD：pending=rung0、consolidating=rung≥1 未毕业、graduated=错数归零+尾部连对≥3。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        pending = await _create_mistake(client)
        consolidating = await _create_mistake(client)
        graduated = await _create_mistake(client)
        pending_id = pending["mistake_id"]
        consolidating_id = consolidating["mistake_id"]
        graduated_id = graduated["mistake_id"]

        first = await _complete_correct(client, factory, consolidating_id)
        assert first["state"]["rung"] == 1
        assert first["graduated"] is False

        for expected_rung in (1, 2, 2):
            body = await _complete_correct(client, factory, graduated_id)
            assert body["state"]["rung"] == expected_rung
        assert body["graduated"] is True
        assert body["state"]["times_wrong"] == 0
        assert body["state"]["trailing_correct"] == 3

        pending_resp = await client.get(
            "/api/mistakes", params={"mastery_state": "pending"}
        )
        consolidating_resp = await client.get(
            "/api/mistakes", params={"mastery_state": "consolidating"}
        )
        graduated_resp = await client.get(
            "/api/mistakes", params={"mastery_state": "graduated"}
        )
        default_resp = await client.get("/api/mistakes")
        invalid = await client.get(
            "/api/mistakes", params={"mastery_state": "mastered"}
        )

    assert _ids(pending_resp) == {pending_id}
    assert _ids(consolidating_resp) == {consolidating_id}
    assert _ids(graduated_resp) == {graduated_id}
    assert _ids(default_resp) == {pending_id, consolidating_id, graduated_id}
    assert invalid.status_code == 422, invalid.text


@pytest.mark.integration
async def test_list_filters_combine_and_keep_pagination_contract(tmp_path) -> None:
    """P2-9 DoD：q 与 category/error_cause/mastery_state 组合；total/分页契约不变。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory, topic_id="cnm_test_geometry", name="几何", subject="数学"
    )

    async with _client(factory) as client:
        m1 = await _create_mistake(
            client,
            problem_text="解方程 2x=4",
            answer="x=2",
            error_cause="calculation",
        )
        m2 = await _create_mistake(
            client,
            problem_text="解方程 5x=10",
            answer="x=2",
            error_cause="careless",
        )
        m3 = await _create_mistake(
            client,
            problem_text="三角形面积",
            answer="12",
            primary_topic_id="cnm_test_geometry",
            error_cause="calculation",
        )
        m4 = await _create_mistake(
            client,
            problem_text="解方程 3x=9",
            answer="x=3",
            error_cause="calculation",
        )
        await _complete_correct(client, factory, m2["mistake_id"])
        for _ in range(3):
            await _complete_correct(client, factory, m4["mistake_id"])

        q_only = await client.get("/api/mistakes", params={"q": "解方程"})
        q_category = await client.get(
            "/api/mistakes",
            params={"q": "解方程", "category_id": "cnm_test_equation"},
        )
        q_category_cause = await client.get(
            "/api/mistakes",
            params={
                "q": "解方程",
                "category_id": "cnm_test_equation",
                "error_cause": "calculation",
            },
        )
        q_cause_pending = await client.get(
            "/api/mistakes",
            params={
                "q": "解方程",
                "error_cause": "calculation",
                "mastery_state": "pending",
            },
        )
        answer_wrong_category = await client.get(
            "/api/mistakes",
            params={"q": "x=2", "category_id": "cnm_test_geometry"},
        )
        paged = await client.get(
            "/api/mistakes", params={"q": "解方程", "limit": 1, "offset": 1}
        )

    equation_ids = {m1["mistake_id"], m2["mistake_id"], m4["mistake_id"]}
    assert _ids(q_only) == equation_ids
    assert _ids(q_category) == equation_ids
    assert _ids(q_category_cause) == {m1["mistake_id"], m4["mistake_id"]}
    assert _ids(q_cause_pending) == {m1["mistake_id"]}
    assert _ids(answer_wrong_category) == set()
    assert m3["mistake_id"] not in _ids(q_only)

    assert paged.status_code == 200, paged.text
    page = paged.json()
    assert page["total"] == 3
    # id 倒序：m4, m2, m1 → offset=1 取 m2
    assert [item["id"] for item in page["items"]] == [m2["mistake_id"]]
