"""P1-6 错题本集成测试：唯一写入（核对页确认）、两级标签、派生练习表、seed/concept 查询。

v2.5：真实题在系统外批改，错题只经"外部转录 → 核对页确认"入本，系统内零模型调用；
这里只验证纪律与数据隔离。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
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
from app.services import recompute, streak
from app.services.backup import create_backup
from app.services.concepts import concept_family_ids, resolve_concepts
from app.services.mistake_images import MAX_IMAGE_BYTES
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
    factory: async_sessionmaker,
    *,
    unlock: bool = True,
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


@pytest.mark.integration
async def test_list_subject_filter_shares_dashboard_mapping(tmp_path) -> None:
    """P2-13 DoD：subject 经 `primary_topic_id`→seed 归并（**不是** category_id）。

    夹具刻意让 m4 不挂主考点（primary_topic_id=NULL → 学科落"未挂考点"），
    而其版本有效知识点仍回退到建议值 cnm_test_equation——以此钉死"学科"和
    "知识点"是两根独立的轴，`subject` 绝不能拿 `category_id` 冒充。
    并断言列表 total 与看板学科卡 total 逐科相等（卡片 N 道 → 点进去 N 道）。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_test_english", name="词汇", subject="英语")

    async with _client(factory) as client:
        m1 = await _create_mistake(
            client, problem_text="解方程 2x=4", answer="x=2", error_cause="calculation"
        )
        m2 = await _create_mistake(
            client, problem_text="解方程 5x=10", answer="x=2", error_cause="careless"
        )
        m3 = await _create_mistake(
            client,
            problem_text="翻译 apple",
            answer="苹果",
            primary_topic_id="cnm_test_english",
        )
        m4 = await _create_mistake(
            client, problem_text="无主考点题", answer="略", primary_topic_id=None
        )
        m5 = await _create_mistake(
            client, problem_text="解方程 3x=9", answer="x=3", error_cause="calculation"
        )
        for _ in range(3):
            await _complete_correct(client, factory, m5["mistake_id"])

        math_resp = await client.get("/api/mistakes", params={"subject": "数学"})
        english_resp = await client.get("/api/mistakes", params={"subject": "英语"})
        unassigned_resp = await client.get("/api/mistakes", params={"subject": "未挂考点"})
        unknown_resp = await client.get("/api/mistakes", params={"subject": "不存在的学科"})
        q_math = await client.get("/api/mistakes", params={"subject": "数学", "q": "解方程"})
        cause_math = await client.get(
            "/api/mistakes", params={"subject": "数学", "error_cause": "calculation"}
        )
        graduated_math = await client.get(
            "/api/mistakes", params={"subject": "数学", "mastery_state": "graduated"}
        )
        unassigned_equation = await client.get(
            "/api/mistakes", params={"subject": "未挂考点", "category_id": "cnm_test_equation"}
        )
        math_equation = await client.get(
            "/api/mistakes", params={"subject": "数学", "category_id": "cnm_test_equation"}
        )
        paged = await client.get(
            "/api/mistakes", params={"subject": "数学", "limit": 1, "offset": 1}
        )
        dashboard = await client.get("/api/dashboard")

    math_ids = {m1["mistake_id"], m2["mistake_id"], m5["mistake_id"]}
    assert _ids(math_resp) == math_ids
    assert math_resp.json()["total"] == 3
    assert _ids(english_resp) == {m3["mistake_id"]}
    assert _ids(unassigned_resp) == {m4["mistake_id"]}
    assert unknown_resp.status_code == 200, unknown_resp.text
    assert unknown_resp.json()["items"] == []
    assert unknown_resp.json()["total"] == 0

    # 与既有四个筛选可组合
    assert _ids(q_math) == math_ids
    assert _ids(cause_math) == {m1["mistake_id"], m5["mistake_id"]}
    assert _ids(graduated_math) == {m5["mistake_id"]}
    # 学科走 primary_topic_id、知识点走版本有效标签：m4 未挂主考点（学科=未挂考点），
    # 但确认前有效知识点回退到建议值 cnm_test_equation —— 两轴独立，不可互相冒充
    assert _ids(unassigned_equation) == {m4["mistake_id"]}
    assert _ids(math_equation) == math_ids

    assert paged.status_code == 200, paged.text
    page = paged.json()
    assert page["total"] == 3  # 过滤后总数，不是全库总数
    assert [item["id"] for item in page["items"]] == [m2["mistake_id"]]

    assert dashboard.status_code == 200, dashboard.text
    cards = {item["subject"]: item for item in dashboard.json()["subjects"]}
    assert cards["数学"] == {"subject": "数学", "active": 2, "graduated": 1, "total": 3}
    assert cards["数学"]["total"] == math_resp.json()["total"]
    assert cards["英语"]["total"] == english_resp.json()["total"] == 1
    assert cards["未挂考点"]["total"] == unassigned_resp.json()["total"] == 1


@pytest.mark.integration
async def test_voided_trash_list_and_restore_roundtrip(tmp_path) -> None:
    """P2-10 DoD：回收站走 status=voided 列表；void 退出 due、unvoid 回到 due；
    未解锁 unvoid/void 403（恢复入口家长专属）。复用 e2e ② 路径，零新端点。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        body = await _create_mistake(client)
        mistake_id = body["mistake_id"]

        async with factory() as session:
            schedule = (
                await session.execute(
                    select(ReviewSchedule).where(
                        ReviewSchedule.mistake_id == mistake_id
                    )
                )
            ).scalar_one()
        due_day = schedule.due_date.isoformat()

        active_before = await client.get(
            "/api/mistakes", params={"status": "active"}
        )
        voided_before = await client.get(
            "/api/mistakes", params={"status": "voided"}
        )
        due_before = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )

        voided = await client.post(
            f"/api/mistakes/{mistake_id}/void",
            json={"actor": "parent", "reason": "已当面讲通，暂不复习"},
        )
        active_after = await client.get(
            "/api/mistakes", params={"status": "active"}
        )
        voided_after = await client.get(
            "/api/mistakes", params={"status": "voided"}
        )
        due_after = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )

        unvoided = await client.post(
            f"/api/mistakes/{mistake_id}/unvoid", json={"actor": "parent"}
        )
        active_restored = await client.get(
            "/api/mistakes", params={"status": "active"}
        )
        voided_restored = await client.get(
            "/api/mistakes", params={"status": "voided"}
        )
        due_restored = await client.get(
            "/api/reviews/due", params={"today": due_day}
        )

    # 初始：在本 1 / 回收站 0 / 到期 1
    assert active_before.json()["total"] == 1
    assert voided_before.json()["total"] == 0
    assert due_before.json()["due_total"] == 1

    # 作废后：退出在本与到期队列，进入回收站（status=voided 列表契约）
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "voided"
    assert active_after.json()["total"] == 0
    assert voided_after.json()["total"] == 1
    assert _ids(voided_after) == {mistake_id}
    assert voided_after.json()["items"][0]["status"] == "voided"
    assert due_after.json()["due_total"] == 0

    # 恢复后：回到在本与到期队列，回收站清空
    assert unvoided.status_code == 200, unvoided.text
    assert unvoided.json()["status"] == "active"
    assert active_restored.json()["total"] == 1
    assert _ids(active_restored) == {mistake_id}
    assert voided_restored.json()["total"] == 0
    assert due_restored.json()["due_total"] == 1
    assert mistake_id in {
        item["mistake_id"] for item in due_restored.json()["items"]
    }

    # 家长专属：未解锁（无会话 cookie）时恢复/作废端点 403，孩子区拿不到操作权。
    async with _client(factory, unlock=False) as locked:
        locked_unvoid = await locked.post(
            f"/api/mistakes/{mistake_id}/unvoid", json={"actor": "parent"}
        )
        locked_void = await locked.post(
            f"/api/mistakes/{mistake_id}/void", json={"actor": "parent"}
        )
    assert locked_unvoid.status_code == 403
    assert locked_void.status_code == 403


# ---- P1-16 原题图附件（孩子区，零模型，唯一目录 uploads/）----

_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)


def _image_settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", db_path=tmp_path / "mistakes.db")


async def _upload_image(
    client: AsyncClient,
    mistake_id: int,
    *,
    data: bytes = _PNG_1PX,
    mime: str = "image/png",
    filename: str = "page.png",
):
    return await client.post(
        f"/api/mistakes/{mistake_id}/images",
        files={"file": (filename, data, mime)},
    )


@pytest.mark.integration
async def test_problem_image_upload_read_backup_and_delete(tmp_path) -> None:
    """上传→详情可见→读取字节一致→备份 zip 含该文件→改标签不丢图→删除只删本文件。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    settings = _image_settings(tmp_path)

    async with _client(factory, settings=settings) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]

        uploaded = await _upload_image(client, mistake_id)
        assert uploaded.status_code == 200, uploaded.text
        images = uploaded.json()["problem_images"]
        assert len(images) == 1
        rel = images[0]
        assert re.fullmatch(rf"uploads/{mistake_id}/[0-9a-f-]{{36}}\.png", rel)
        # mistake_versions 是 append-only：上传追加 v2 并 bump current_version。
        assert uploaded.json()["current_version"] == 2

        detail = await client.get(f"/api/mistakes/{mistake_id}")
        assert detail.json()["problem_images"] == [rel]

        got = await client.get(f"/api/mistakes/{mistake_id}/images/0")
        assert got.status_code == 200, got.text
        assert got.content == _PNG_1PX
        assert got.headers["content-type"] == "image/png"
        assert got.headers["cache-control"] == "no-store"

        stored = settings.data_dir / rel
        assert stored.is_file()
        assert stored.read_bytes() == _PNG_1PX
        assert stored.resolve().is_relative_to(settings.uploads_dir.resolve())

        # 改标签透传 problem_images：唯一写入路径，不丢图、不新建第二条路径。
        # 上传已把 current_version 推到 2，乐观锁 base_version 随之取 2。
        labeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={"base_version": 2, "error_cause": "careless"},
        )
        assert labeled.status_code == 200, labeled.text
        assert labeled.json()["problem_images"] == [rel]

        result = create_backup(settings)
        with zipfile.ZipFile(result.path) as zf:
            assert rel in zf.namelist()
            assert zf.read(rel) == _PNG_1PX
            manifest = json.loads(zf.read("manifest.json"))
            entry = next(f for f in manifest["files"] if f["path"] == rel)
            assert entry["sha256"] == hashlib.sha256(_PNG_1PX).hexdigest()
            assert entry["size_bytes"] == len(_PNG_1PX)

        deleted = await client.delete(f"/api/mistakes/{mistake_id}/images/0")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["problem_images"] == []
        assert not stored.exists()


@pytest.mark.integration
async def test_problem_image_validation_returns_stable_422_codes(tmp_path) -> None:
    """非白名单 MIME / 魔数不符 / >5MB / 第 4 张 → 422 稳定码，且校验失败不落盘。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    settings = _image_settings(tmp_path)

    async with _client(factory, settings=settings) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]

        svg = await _upload_image(
            client,
            mistake_id,
            data=b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            mime="image/svg+xml",
            filename="x.svg",
        )
        assert svg.status_code == 422, svg.text
        assert svg.json()["detail"]["code"] == "image_mime_not_allowed"

        mismatch = await _upload_image(
            client,
            mistake_id,
            data=b"\xff\xd8\xff\xe0" + b"\x00" * 64,
            mime="image/png",
        )
        assert mismatch.status_code == 422, mismatch.text
        assert mismatch.json()["detail"]["code"] == "image_magic_mismatch"

        big = _PNG_1PX + b"\x00" * (MAX_IMAGE_BYTES + 1 - len(_PNG_1PX))
        too_large = await _upload_image(client, mistake_id, data=big)
        assert too_large.status_code == 422, too_large.text
        assert too_large.json()["detail"]["code"] == "image_too_large"

        for _ in range(3):
            ok = await _upload_image(client, mistake_id)
            assert ok.status_code == 200, ok.text
        fourth = await _upload_image(client, mistake_id)
        assert fourth.status_code == 422, fourth.text
        assert fourth.json()["detail"]["code"] == "image_limit_reached"

        # 四次失败都没落盘：该题目录下恰好 3 个文件，详情也只有 3 张。
        assert len(list((settings.uploads_dir / str(mistake_id)).iterdir())) == 3
        detail = await client.get(f"/api/mistakes/{mistake_id}")
        assert len(detail.json()["problem_images"]) == 3


@pytest.mark.integration
async def test_problem_image_filename_injection_stays_uuid(tmp_path) -> None:
    """原始文件名（../）绝不进路径：存储名是 uuid4 形态，限定在 uploads/<id>/。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    settings = _image_settings(tmp_path)

    async with _client(factory, settings=settings) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]
        resp = await _upload_image(
            client, mistake_id, filename="../../../etc/passwd.png"
        )
        assert resp.status_code == 200, resp.text
        rel = resp.json()["problem_images"][0]
        stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        assert _UUID_RE.fullmatch(stem), rel
        assert rel.startswith(f"uploads/{mistake_id}/")
        assert ".." not in rel and "passwd" not in rel
        assert len(list((settings.uploads_dir / str(mistake_id)).iterdir())) == 1
        assert not (tmp_path / "etc").exists()


@pytest.mark.integration
async def test_problem_image_endpoints_are_child_area_no_pin(tmp_path) -> None:
    """孩子区免 PIN：未解锁会话也能上传/读取/删除（与 /labels 同级）。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    settings = _image_settings(tmp_path)

    async with _client(factory, settings=settings) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]

    async with _client(factory, unlock=False, settings=settings) as locked:
        up = await _upload_image(locked, mistake_id)
        assert up.status_code == 200, up.text
        got = await locked.get(f"/api/mistakes/{mistake_id}/images/0")
        assert got.status_code == 200, got.text
        rm = await locked.delete(f"/api/mistakes/{mistake_id}/images/0")
        assert rm.status_code == 200, rm.text
        assert rm.json()["problem_images"] == []


@pytest.mark.integration
async def test_problem_image_missing_mistake_or_index_404(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    settings = _image_settings(tmp_path)

    async with _client(factory, settings=settings) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]
        await _upload_image(client, mistake_id)

        bad_index = await client.get(f"/api/mistakes/{mistake_id}/images/5")
        assert bad_index.status_code == 404
        bad_delete = await client.delete(f"/api/mistakes/{mistake_id}/images/5")
        assert bad_delete.status_code == 404
        missing_get = await client.get("/api/mistakes/9999/images/0")
        assert missing_get.status_code == 404
        missing_upload = await _upload_image(client, 9999)
        assert missing_upload.status_code == 404


@pytest.mark.integration
async def test_notes_edit_appends_version_and_keeps_history(tmp_path) -> None:
    """P1-17：编辑订正笔记只追加版本行；历史版本逐行不变（全表快照）；不记事件、不动排期。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]
        created = await client.get(f"/api/mistakes/{mistake_id}")
        assert created.json()["correction_notes"] is None  # 不带笔记入本 = NULL

        versions_before = await _mistake_version_snapshot(factory)
        events_before = await _count(factory, LearningEvent)
        schedules_before = await _count(factory, ReviewSchedule)

        edited = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={
                "base_version": 1,
                "correction_notes": "移项要变号，下次先写这一步",
            },
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["current_version"] == 2
        assert body["correction_notes"] == "移项要变号，下次先写这一步"

        detail = await client.get(f"/api/mistakes/{mistake_id}")
        assert detail.json()["correction_notes"] == "移项要变号，下次先写这一步"

    assert await _count(factory, MistakeVersion) == 2
    versions_after = await _mistake_version_snapshot(factory)
    # 历史 v1 行逐行不变（快照含 correction_notes 在内的全部列）
    assert versions_after[0] == versions_before[0]
    v2 = versions_after[1]
    assert v2["version"] == 2
    assert v2["correction_notes"] == "移项要变号，下次先写这一步"
    # 其余内容全量透传，只改笔记
    assert v2["problem_text"] == versions_before[0]["problem_text"]
    assert v2["standard_answer"] == versions_before[0]["standard_answer"]
    assert v2["student_answer"] == versions_before[0]["student_answer"]
    # 笔记纯展示：不记学习事件、不动排期/掌握度
    assert await _count(factory, LearningEvent) == events_before
    assert await _count(factory, ReviewSchedule) == schedules_before


@pytest.mark.integration
async def test_notes_carry_forward_across_labels_images_and_notes(tmp_path) -> None:
    """P1-17：笔记/标签/原题图互相透传，任一路编辑都不丢其他字段；历史逐行不变。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    concept_id = await _seed_concept(
        factory, name="移项", category_id="cnm_test_equation"
    )
    settings = _image_settings(tmp_path)

    async with _client(factory, settings=settings) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]

        # v2：写笔记
        notes = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "移项要变号"},
        )
        assert notes.status_code == 200, notes.text
        snap_after_notes = await _mistake_version_snapshot(factory)

        # v3：改标签 → 笔记保留
        labeled = await client.post(
            f"/api/mistakes/{mistake_id}/labels",
            json={
                "base_version": 2,
                "category_id": "cnm_test_equation",
                "concept_ids": [concept_id],
                "error_cause": "calculation",
            },
        )
        assert labeled.status_code == 200, labeled.text
        assert labeled.json()["correction_notes"] == "移项要变号"
        snap_after_labels = await _mistake_version_snapshot(factory)
        assert snap_after_labels[:2] == snap_after_notes

        # v4：上传原题图 → 笔记 + 标签保留
        uploaded = await _upload_image(client, mistake_id)
        assert uploaded.status_code == 200, uploaded.text
        rel = uploaded.json()["problem_images"][0]
        assert uploaded.json()["correction_notes"] == "移项要变号"
        assert uploaded.json()["labels"]["error_cause"] == "calculation"
        snap_after_image = await _mistake_version_snapshot(factory)
        assert snap_after_image[:3] == snap_after_labels

        # v5：再改笔记 → 标签 + 原题图保留
        notes2 = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 4, "correction_notes": "订正：先移项再合并"},
        )
        assert notes2.status_code == 200, notes2.text
        body = notes2.json()
        assert body["current_version"] == 5
        assert body["correction_notes"] == "订正：先移项再合并"
        assert body["problem_images"] == [rel]
        assert body["labels"]["error_cause"] == "calculation"
        assert [c["id"] for c in body["labels"]["concepts"]] == [concept_id]

    assert await _count(factory, MistakeVersion) == 5
    final = await _mistake_version_snapshot(factory)
    assert final[:4] == snap_after_image  # 前 4 行逐行不变


@pytest.mark.integration
async def test_notes_edit_child_area_no_pin(tmp_path) -> None:
    """P1-17：孩子区免 PIN——未解锁会话也能编辑/读取订正笔记（与 /labels、/images 同级）。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]

    async with _client(factory, unlock=False) as locked:
        edited = await locked.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "孩子自己补的笔记"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["correction_notes"] == "孩子自己补的笔记"
        detail = await locked.get(f"/api/mistakes/{mistake_id}")
        assert detail.json()["correction_notes"] == "孩子自己补的笔记"


@pytest.mark.integration
async def test_notes_edit_optimistic_lock_state_and_missing(tmp_path) -> None:
    """P1-17：base_version 乐观锁 409；已作废 409；不存在 404；冲突都不追加版本。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]
        first = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "第一版笔记"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["current_version"] == 2

        stale = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "过期提交"},
        )
        assert stale.status_code == 409, stale.text
        assert await _count(factory, MistakeVersion) == 2  # 冲突不追加

        voided = await client.post(
            f"/api/mistakes/{mistake_id}/void",
            json={"actor": "parent", "reason": "测试作废"},
        )
        assert voided.status_code == 200, voided.text
        state_conflict = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 2, "correction_notes": "作废后改笔记"},
        )
        assert state_conflict.status_code == 409, state_conflict.text

        missing = await client.post(
            "/api/mistakes/9999/notes",
            json={"base_version": 1, "correction_notes": "无此题"},
        )
        assert missing.status_code == 404, missing.text

    assert await _count(factory, MistakeVersion) == 2


@pytest.mark.integration
async def test_notes_edit_overlong_empty_and_bad_actor(tmp_path) -> None:
    """P1-17：>500 → 422 不写盘；空白/None → NULL；非法 actor → 422。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]

        overlong = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "x" * 501},
        )
        assert overlong.status_code == 422, overlong.text
        assert await _count(factory, MistakeVersion) == 1  # 超长不写盘

        bad_actor = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "x", "actor": "teacher"},
        )
        assert bad_actor.status_code == 422, bad_actor.text

        # 空白 strip 后 = 不存（NULL）
        blank = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={"base_version": 1, "correction_notes": "   "},
        )
        assert blank.status_code == 200, blank.text
        assert blank.json()["correction_notes"] is None
        assert blank.json()["current_version"] == 2

        # 显式 null 同样落 NULL；家长 actor 也允许
        explicit_null = await client.post(
            f"/api/mistakes/{mistake_id}/notes",
            json={
                "base_version": 2,
                "correction_notes": None,
                "actor": "parent",
            },
        )
        assert explicit_null.status_code == 200, explicit_null.text
        assert explicit_null.json()["correction_notes"] is None

    async with factory() as session:
        rows = (
            await session.scalars(
                select(MistakeVersion).order_by(MistakeVersion.version)
            )
        ).all()
    assert [r.correction_notes for r in rows] == [None, None, None]


# ---- P1-18 主考点可设定与更正（根表 + 审计事件，零迁移） ----


async def _event_rows(factory: async_sessionmaker) -> list[LearningEvent]:
    async with factory() as session:
        return list(
            (
                await session.scalars(
                    select(LearningEvent).order_by(LearningEvent.id)
                )
            ).all()
        )


def _recompute_events(rows: list[LearningEvent]) -> list[recompute.Event]:
    return [
        recompute.Event(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]


async def _mastery_snapshot(
    factory: async_sessionmaker, concept_ids: list[int]
) -> dict[int, float]:
    events = _recompute_events(await _event_rows(factory))
    return {cid: recompute.mastery(events, cid) for cid in concept_ids}


async def _schedule_snapshot(
    factory: async_sessionmaker, mistake_id: int
) -> list[tuple]:
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ReviewSchedule)
                .where(ReviewSchedule.mistake_id == mistake_id)
                .order_by(ReviewSchedule.id)
            )
        ).all()
    return [
        (row.id, row.due_date, row.completed_at, row.rung) for row in rows
    ]


async def _seed_attempts(
    factory: async_sessionmaker, concept_id: int, kinds: tuple[str, ...]
) -> None:
    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        for index, kind in enumerate(kinds):
            session.add(
                LearningEvent(
                    type=f"attempt_{kind}",
                    actor="student",
                    mistake_id=None,
                    payload=json.dumps(
                        {"concept_id": concept_id, "source": "student_self"}
                    ),
                    occurred_at=now,
                    idempotency_key=f"p118-mastery-{concept_id}-{index}-{uuid4().hex}",
                )
            )


@pytest.mark.integration
async def test_primary_topic_set_writes_root_and_audit_event_only(tmp_path) -> None:
    """P1-18 核心：写根表 + 恰 1 条审计事件；不 bump 版本、不追加版本行、历史零改动。

    同值幂等 no-op（0 新增、updated_at 不变）；null 落 NULL；学科经唯一口径投影。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory, topic_id="cnm_test_english", name="词汇", subject="英语"
    )

    async with _client(factory) as client:
        body = await _create_mistake(client, primary_topic_id=None)
        mistake_id = body["mistake_id"]
        assert body["primary_topic_id"] is None

        detail = (await client.get(f"/api/mistakes/{mistake_id}")).json()
        assert detail["primary_topic_id"] is None
        assert detail["primary_topic_subject"] == "未挂考点"
        before_updated = detail["updated_at"]
        before_versions = await _count(factory, MistakeVersion)
        before_events = await _event_rows(factory)

        # null → 数学：恰新增 1 条事件，根表列 + updated_at 变，版本不动
        set_math = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={
                "base_version": 1,
                "primary_topic_id": "cnm_test_equation",
                "actor": "student",
            },
        )
        assert set_math.status_code == 200, set_math.text
        math_body = set_math.json()
        assert math_body["primary_topic_id"] == "cnm_test_equation"
        assert math_body["primary_topic_subject"] == "数学"
        assert math_body["current_version"] == 1
        assert math_body["updated_at"] != before_updated

        after_math = await _event_rows(factory)
        before_ids = {event.id for event in before_events}
        new_events = [e for e in after_math if e.id not in before_ids]
        assert len(new_events) == 1
        event = new_events[0]
        assert event.type == "mistake_primary_topic_set"
        assert event.mistake_id == mistake_id
        assert event.idempotency_key == (
            f"mistake:{mistake_id}:primary-topic:1:cnm_test_equation"
        )
        assert json.loads(event.payload) == {
            "from_topic_id": None,
            "to_topic_id": "cnm_test_equation",
            "actor": "student",
            "base_version": 1,
        }
        # 历史事件零改动（逐条比对 type/payload/occurred_at/key）
        assert await _count(factory, MistakeVersion) == before_versions
        after_by_id = {e.id: e for e in after_math}
        for old in before_events:
            now = after_by_id[old.id]
            assert (
                now.type,
                now.payload,
                now.occurred_at,
                now.idempotency_key,
            ) == (old.type, old.payload, old.occurred_at, old.idempotency_key)

        # 同值重复：幂等 no-op，0 新增、updated_at 不变
        repeat = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_test_equation"},
        )
        assert repeat.status_code == 200, repeat.text
        assert repeat.json()["updated_at"] == math_body["updated_at"]
        assert len(await _event_rows(factory)) == len(after_math)

        # 数学 → 英语：同 base_version 再恰新增 1 条（键含 to_topic_id 不撞）
        set_eng = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={
                "base_version": 1,
                "primary_topic_id": "cnm_test_english",
                "actor": "parent",
            },
        )
        assert set_eng.status_code == 200, set_eng.text
        assert set_eng.json()["primary_topic_subject"] == "英语"
        after_eng = await _event_rows(factory)
        assert len(after_eng) == len(after_math) + 1
        assert after_eng[-1].idempotency_key == (
            f"mistake:{mistake_id}:primary-topic:1:cnm_test_english"
        )
        assert json.loads(after_eng[-1].payload)["from_topic_id"] == (
            "cnm_test_equation"
        )

        # 英语 → null：清除落 NULL，学科回"未挂考点"
        clear = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": None},
        )
        assert clear.status_code == 200, clear.text
        assert clear.json()["primary_topic_id"] is None
        assert clear.json()["primary_topic_subject"] == "未挂考点"
        after_clear = await _event_rows(factory)
        assert len(after_clear) == len(after_eng) + 1
        assert after_clear[-1].idempotency_key == (
            f"mistake:{mistake_id}:primary-topic:1:null"
        )
        assert json.loads(after_clear[-1].payload)["to_topic_id"] is None

    # 版本表行数与 current_version 全程不变（专门断言）
    assert await _count(factory, MistakeVersion) == before_versions == 1
    async with factory() as session:
        root = await session.get(Mistake, mistake_id)
        assert root.current_version == 1
        assert root.primary_topic_id is None


@pytest.mark.integration
async def test_primary_topic_idempotency_key_includes_to_topic(tmp_path) -> None:
    """P1-18 可证伪锚点：同 base_version 两次不同目标 → 恰 2 条事件。

    幂等键含 to_topic_id 时两键不撞、各记 1 条；若把 to_topic_id 从键里拿掉，
    第二次会被 UNIQUE 去重 → 只剩 1 条，本断言变红（还原后复绿）。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(
        factory, topic_id="cnm_test_english", name="词汇", subject="英语"
    )

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client, primary_topic_id=None))[
            "mistake_id"
        ]
        baseline = len(await _event_rows(factory))

        first = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_test_equation"},
        )
        assert first.status_code == 200, first.text
        assert len(await _event_rows(factory)) == baseline + 1

        second = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_test_english"},
        )
        assert second.status_code == 200, second.text
        # 改一次恰新增 1 条：两次不同目标共 2 条（去掉 to_topic_id 会塌成 1 条）
        assert len(await _event_rows(factory)) == baseline + 2

    async with factory() as session:
        keys = (
            await session.scalars(
                select(LearningEvent.idempotency_key).where(
                    LearningEvent.type == "mistake_primary_topic_set"
                )
            )
        ).all()
    assert set(keys) == {
        f"mistake:{mistake_id}:primary-topic:1:cnm_test_equation",
        f"mistake:{mistake_id}:primary-topic:1:cnm_test_english",
    }


@pytest.mark.integration
async def test_primary_topic_optimistic_lock_state_unknown_and_missing(
    tmp_path,
) -> None:
    """P1-18：base_version≠current → 409；voided → 409；未知 seed → 422；不存在 → 404。

    冲突/非法一律不写事件、不追加版本行；非法 actor → 422。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client))["mistake_id"]
        baseline = len(await _event_rows(factory))

        stale = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 99, "primary_topic_id": "cnm_test_equation"},
        )
        assert stale.status_code == 409, stale.text

        unknown = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_missing"},
        )
        assert unknown.status_code == 422, unknown.text

        bad_actor = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={
                "base_version": 1,
                "primary_topic_id": "cnm_test_equation",
                "actor": "teacher",
            },
        )
        assert bad_actor.status_code == 422, bad_actor.text

        missing = await client.post(
            "/api/mistakes/9999/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_test_equation"},
        )
        assert missing.status_code == 404, missing.text

        # 冲突/非法都不写盘
        assert len(await _event_rows(factory)) == baseline
        assert await _count(factory, MistakeVersion) == 1

        voided = await client.post(
            f"/api/mistakes/{mistake_id}/void",
            json={"actor": "parent", "reason": "测试作废"},
        )
        assert voided.status_code == 200, voided.text
        state_conflict = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_test_equation"},
        )
        assert state_conflict.status_code == 409, state_conflict.text

    assert await _count(factory, MistakeVersion) == 1


@pytest.mark.integration
async def test_primary_topic_child_area_no_pin(tmp_path) -> None:
    """P1-18：孩子区免 PIN——未解锁会话也能设定/读取主考点（与 /labels、/notes 同级）。"""

    factory = _migrated(tmp_path)
    await _seed_topic(factory)

    async with _client(factory) as client:
        mistake_id = (await _create_mistake(client, primary_topic_id=None))[
            "mistake_id"
        ]

    async with _client(factory, unlock=False) as locked:
        edited = await locked.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_test_equation"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["primary_topic_id"] == "cnm_test_equation"
        detail = await locked.get(f"/api/mistakes/{mistake_id}")
        assert detail.json()["primary_topic_subject"] == "数学"


@pytest.mark.integration
async def test_primary_topic_keeps_mastery_schedule_streak_and_moves_due_kind(
    tmp_path,
) -> None:
    """P1-18 DoD：mastery/排期/streak 不受影响；due kind 由 redo→quiz（有题），

    无题则 bank_gap=true 不抛错；学科卡归位、inventory.unassigned_active 减 1。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(factory)
    await _seed_topic(factory, topic_id="cnm_001", name="有理数", subject="数学")
    await _seed_topic(
        factory, topic_id="cnm_999999", name="题库空缺", subject="数学"
    )
    concept_id = await _seed_concept(
        factory, name="正负数", category_id="cnm_001"
    )
    await _seed_attempts(factory, concept_id, ("correct", "wrong"))

    # 新事件类型绝不进 streak（让主考点不参与 streak）
    assert "mistake_primary_topic_set" not in streak.LEARNING_EVENT_TYPES

    async with _client(factory) as client:
        mistake_id = (
            await _create_mistake(
                client, primary_topic_id="cnm_001", concept_ids=(concept_id,)
            )
        )["mistake_id"]
        # 核对页要求选细标签前先有主考点，故先入本再经端点清除 → 未挂考点作"改前"基线
        cleared = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": None},
        )
        assert cleared.status_code == 200, cleared.text
        schedule = await _open_schedule(factory, mistake_id)
        due_day = schedule.due_date.isoformat()

        before_item = next(
            item
            for item in (
                await client.get(
                    "/api/reviews/due", params={"today": due_day}
                )
            ).json()["items"]
            if item["mistake_id"] == mistake_id
        )
        assert before_item["task"] == "redo"
        assert before_item["bank_gap"] is True

        before_dash = (await client.get("/api/dashboard")).json()
        before_mastery = await _mastery_snapshot(factory, [concept_id])
        before_schedules = await _schedule_snapshot(factory, mistake_id)
        assert before_mastery[concept_id] == 0.5
        assert before_dash["inventory"]["unassigned_active"] == 1

        # 设定主考点 → cnm_001（seed 题库有题）：due kind 变 quiz
        set_topic = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_001"},
        )
        assert set_topic.status_code == 200, set_topic.text

        after_item = next(
            item
            for item in (
                await client.get(
                    "/api/reviews/due", params={"today": due_day}
                )
            ).json()["items"]
            if item["mistake_id"] == mistake_id
        )
        assert after_item["task"] == "quiz"
        assert after_item["bank_gap"] is False
        assert after_item["primary_topic_id"] == "cnm_001"
        assert after_item["quiz"] is not None

        # mastery 全等、排期行数与 due_date 不变
        assert await _mastery_snapshot(factory, [concept_id]) == before_mastery
        assert await _schedule_snapshot(factory, mistake_id) == before_schedules

        # 学科卡归位 + unassigned_active 减 1
        after_dash = (await client.get("/api/dashboard")).json()
        before_cards = {c["subject"]: c for c in before_dash["subjects"]}
        after_cards = {c["subject"]: c for c in after_dash["subjects"]}
        assert before_cards["未挂考点"]["active"] == 1
        assert after_cards.get("未挂考点", {}).get("active", 0) == 0
        assert after_cards["数学"]["active"] == (
            before_cards.get("数学", {}).get("active", 0) + 1
        )
        assert after_dash["inventory"]["unassigned_active"] == 0

        # 改挂无题知识点：bank_gap=true 不抛错（退回 redo）
        gap_topic = await client.post(
            f"/api/mistakes/{mistake_id}/primary-topic",
            json={"base_version": 1, "primary_topic_id": "cnm_999999"},
        )
        assert gap_topic.status_code == 200, gap_topic.text
        gap_item = next(
            item
            for item in (
                await client.get(
                    "/api/reviews/due", params={"today": due_day}
                )
            ).json()["items"]
            if item["mistake_id"] == mistake_id
        )
        assert gap_item["task"] == "redo"
        assert gap_item["bank_gap"] is True
        assert gap_item["quiz"] is None
