"""P4-6 公式题判分降级集成测试：三个考核面共用同一条 fallback 纪律。

公式题答案含 LaTeX 标记 → 走受限子集 + sympy 等值判断；超出子集（如积分）
→ 系统不猜对错，降级孩子卷面自评（source=student_self），payload 打
`formula_fallback` 标签。标签只作展示/审计，不进判分结论、不改掌握度算法。

三面硬不变量：
- 手动组卷（quiz）：写 attempts/events，不新建错题；
- 同类题加练（practice）：只写 practice_records，绝不写 attempts/events；
- 到期考核（review）：fallback 未自评 → HTTP 422 reason=formula_fallback，
  补自评后落 student_self；同排期幂等回放。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
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
    PracticeRecord,
    ProblemBankItem,
    ReviewSchedule,
)
from app.services.mistakes import append_label_version
from app.services.recompute import Event as RecomputeEvent
from app.services.recompute import mastery
from app.services.review_policy import ReviewState, decide
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"
FORBIDDEN_KEYS = {"answer", "accept", "explanation", "verify"}

TOPIC = "cnm_formula"
QUESTION_ID = "cnm_formula_q1"
# 题库答案带 LaTeX 标记 → 触发公式判分；0.5 与之等值（子集内可判）。
FORMULA_ANSWER = r"\frac{1}{2}"
EQUIVALENT_ANSWER = "0.5"
# 积分超出受限子集 → UnsupportedLatex → 不可判 → 降级自评。
OUT_OF_SUBSET = r"\int x dx"
# 惰性断言用的确认细标签 id：裸确认流程 concept_ids 为空 → mastery 恒 0，
# 挂一个确认细标签让掌握度非平凡，才能证明 formula_fallback 标签真的不参与判分。
CONCEPT_ID = 9001


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
    db_path = tmp_path / "formula_fallback.db"
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
        # 手动组卷属家长区：先设 PIN 或解锁（孩子区端点不受影响）。
        status = await client.get("/api/session/status")
        if status.json()["pin_set"]:
            response = await client.post("/api/session/unlock", json={"pin": "2468"})
        else:
            response = await client.post("/api/session/pin/set", json={"pin": "2468"})
        assert response.status_code == 200, response.text
        yield client


async def _seed_formula_question(factory: async_sessionmaker) -> None:
    """一个自建考点 + 一道 active 可答公式题（numeric/无图/已核验）。"""

    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=TOPIC,
                subject="数学",
                name="公式判分考点",
                domain="数与代数",
                grade="七年级",
                semester="上册",
                chapter="公式判分考点",
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )
    # 考点先落库，再插题：problem_bank.topic_id 外键依赖已提交的 knowledge_seed 行。
    async with factory() as session, session.begin():
        session.add(
            ProblemBankItem(
                external_id=QUESTION_ID,
                subject="数学",
                problem_text="写出 1÷2 的结果（分数或小数均可）",
                answer=FORMULA_ANSWER,
                acceptable_answers_json="[]",
                unordered=False,
                verify="1/2",
                verify_vars_json="{}",
                verify_status="verified",
                source="test",
                created_at=now,
                topic_id=TOPIC,
                question_type="numeric",
                difficulty="easy",
                choices_json="[]",
                figure=None,
                hide_choice_text=False,
                percent=False,
                unaudited=True,
                blind_verified=False,
                status="active",
                updated_at=now,
            )
        )


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _only_event_payload(factory: async_sessionmaker) -> dict:
    async with factory() as session:
        events = (await session.scalars(select(LearningEvent))).all()
    assert len(events) == 1, [event.id for event in events]
    return json.loads(events[0].payload)


async def _paper(client: AsyncClient, *, seed: int = 7) -> dict:
    response = await client.get(
        "/api/quizzes/paper",
        params={"topic_id": TOPIC, "count": 1, "seed": seed},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _submit_paper(client: AsyncClient, answers: list[dict], *, seed: int = 7) -> dict:
    response = await client.post(
        "/api/quizzes/paper/submit",
        json={"topic_id": TOPIC, "seed": seed, "count": 1, "answers": answers},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
async def test_quiz_paper_formula_positive_is_system_judged(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_formula_question(factory)

    async with _client(factory) as client:
        paper = await _paper(client)
        assert len(paper["items"]) == 1
        assert paper["items"][0]["question_id"] == QUESTION_ID
        assert paper["items"][0]["mode"] == "system"
        _assert_no_answer_keys(paper)

        body = await _submit_paper(
            client, [{"question_id": QUESTION_ID, "answer": EQUIVALENT_ANSWER}]
        )
        item = body["items"][0]
        assert item["status"] == "correct"
        assert item["mode"] == "system"
        assert item["formula_fallback"] is False
        assert item["replayed"] is False
        assert item["attempt_id"] is not None
        assert body["correct"] == 1 and body["wrong"] == 0
        _assert_no_answer_keys(body)

        # 公式判对仍走 system_quiz，且 payload 不带 fallback 标签。
        assert await _count(factory, Mistake) == 0
        assert await _count(factory, Attempt) == 1
        payload = await _only_event_payload(factory)
        assert payload["source"] == "system_quiz"
        assert payload["quiz_verdict"] == "correct"
        assert "formula_fallback" not in payload

        records = await client.get("/api/attempts", params={"source": "system_quiz"})
        assert records.json()["total"] == 1

        # 同输入重放：幂等，不新增 attempt/event。
        repeated = await _submit_paper(
            client, [{"question_id": QUESTION_ID, "answer": EQUIVALENT_ANSWER}]
        )
        again = repeated["items"][0]
        assert again["replayed"] is True
        assert again["attempt_id"] == item["attempt_id"]
        assert again["formula_fallback"] is False
        assert await _count(factory, Attempt) == 1
        assert await _count(factory, LearningEvent) == 1


@pytest.mark.integration
async def test_quiz_paper_formula_fallback_downgrades_to_self_eval(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_formula_question(factory)

    async with _client(factory) as client:
        await _paper(client)

        # 超出子集且未自评 → uncertain + formula_fallback，绝不落库、绝不猜对错。
        uncertain = await _submit_paper(
            client, [{"question_id": QUESTION_ID, "answer": OUT_OF_SUBSET}]
        )
        item = uncertain["items"][0]
        assert item["status"] == "uncertain"
        assert item["formula_fallback"] is True
        assert item["attempt_id"] is None
        assert item["replayed"] is False
        assert uncertain["correct"] == 0 and uncertain["wrong"] == 0
        assert await _count(factory, Attempt) == 0
        assert await _count(factory, LearningEvent) == 0
        assert await _count(factory, Mistake) == 0

        # 补卷面自评 correct=True → 降级 student_self，payload 打标签。
        graded = await _submit_paper(
            client,
            [{"question_id": QUESTION_ID, "answer": OUT_OF_SUBSET, "correct": True}],
        )
        downgraded = graded["items"][0]
        assert downgraded["status"] == "correct"
        assert downgraded["formula_fallback"] is True
        assert downgraded["attempt_id"] is not None
        assert downgraded["replayed"] is False
        assert graded["correct"] == 1 and graded["wrong"] == 0

        assert await _count(factory, Attempt) == 1
        payload = await _only_event_payload(factory)
        assert payload["source"] == "student_self"
        assert payload["quiz_verdict"] == "correct"
        assert payload["formula_fallback"] is True

        records = await client.get("/api/attempts", params={"source": "student_self"})
        assert records.json()["total"] == 1
        assert records.json()["items"][0]["mistake_id"] is None

        # 重放：按事件记录回放，标签与 attempt 一致，不新增行。
        repeated = await _submit_paper(
            client,
            [{"question_id": QUESTION_ID, "answer": OUT_OF_SUBSET, "correct": True}],
        )
        replayed = repeated["items"][0]
        assert replayed["replayed"] is True
        assert replayed["attempt_id"] == downgraded["attempt_id"]
        assert replayed["formula_fallback"] is True
        assert await _count(factory, Attempt) == 1
        assert await _count(factory, LearningEvent) == 1


@pytest.mark.integration
async def test_practice_formula_fallback_writes_no_events(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_formula_question(factory)

    async with _client(factory) as client:
        started = await client.post(
            "/api/practice/start", json={"topic_id": TOPIC, "count": 1, "seed": 3}
        )
        assert started.status_code == 200, started.text
        assert started.json()["items"][0]["question_id"] == QUESTION_ID
        assert started.json()["items"][0]["mode"] == "system"

        # 正例：公式等值 → correct（派生表）。
        positive = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": TOPIC,
                "seed": 3,
                "count": 1,
                "items": [{"question_id": QUESTION_ID, "answer": EQUIVALENT_ANSWER}],
            },
        )
        assert positive.status_code == 200, positive.text
        assert positive.json()["items"][0]["status"] == "correct"
        assert positive.json()["items"][0]["formula_fallback"] is False

        # fallback：超出子集且未自评 → uncertain，不落行。
        fallback = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": TOPIC,
                "seed": 4,
                "count": 1,
                "items": [{"question_id": QUESTION_ID, "answer": OUT_OF_SUBSET}],
            },
        )
        assert fallback.status_code == 200, fallback.text
        uncertain = fallback.json()["items"][0]
        assert uncertain["status"] == "uncertain"
        assert uncertain["formula_fallback"] is True
        assert uncertain["practice_record_id"] is None
        assert await _count(factory, PracticeRecord) == 1  # 只有正例那行

        # 补自评 correct=False → wrong 派生行，仍带标签。
        graded = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": TOPIC,
                "seed": 4,
                "count": 1,
                "items": [
                    {"question_id": QUESTION_ID, "answer": OUT_OF_SUBSET, "correct": False}
                ],
            },
        )
        assert graded.status_code == 200, graded.text
        downgraded = graded.json()["items"][0]
        assert downgraded["status"] == "wrong"
        assert downgraded["formula_fallback"] is True
        assert downgraded["practice_record_id"] is not None

        records = await client.get(
            "/api/practice", params={"topic_id": TOPIC, "seed": 4}
        )
        assert records.json()["total"] == 1
        assert records.json()["items"][0]["is_correct"] is False

        # 重放/去重：同 (topic, seed, question) 复用既有行。
        reused = await client.post(
            "/api/practice/submit",
            json={
                "topic_id": TOPIC,
                "seed": 4,
                "count": 1,
                "items": [
                    {"question_id": QUESTION_ID, "answer": OUT_OF_SUBSET, "correct": False}
                ],
            },
        )
        assert reused.json()["items"][0]["reused"] is True
        assert reused.json()["items"][0]["status"] == "wrong"

        # 加练硬隔离：无论正例还是 fallback，都绝不写 attempts/events/错题。
        assert await _count(factory, PracticeRecord) == 2
        assert await _count(factory, Attempt) == 0
        assert await _count(factory, LearningEvent) == 0
        assert await _count(factory, Mistake) == 0


async def _import_draft(client: AsyncClient) -> int:
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
                    "suggested_topic_id": TOPIC,
                    "source_ref": f"公式测试卷 第1题 {uuid4().hex}",
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


async def _confirm_wrong(client: AsyncClient) -> int:
    draft_id = await _import_draft(client)
    confirmed = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm", json={"actor": "student"}
    )
    assert confirmed.status_code == 200, confirmed.text
    return int(confirmed.json()["mistake_id"])


async def _set_primary_topic(
    factory: async_sessionmaker, mistake_id: int, topic_id: str
) -> None:
    async with factory() as session, session.begin():
        row = await session.get(Mistake, mistake_id)
        assert row is not None
        row.primary_topic_id = topic_id


async def _set_confirmed_concept(
    factory: async_sessionmaker, mistake_id: int, concept_id: int
) -> None:
    """挂一个确认细标签，使掌握度非平凡（review._mastery_for 按确认 concept 算）。

    mistake_versions 是 append-only（DB 触发器禁 UPDATE）：必须走 append_label_version
    追加新版本，绝不直接改版本行。先落一个真实 Concept 供 resolve_concepts 校验存在性。
    """

    now = datetime.now(UTC)
    async with factory() as session, session.begin():
        if await session.get(Concept, concept_id) is None:
            session.add(
                Concept(
                    id=concept_id,
                    name="公式判分细标签",
                    category_id=TOPIC,
                    source="parent",
                    status="confirmed",
                    created_at=now,
                )
            )
            await session.flush()
        mistake = await session.get(Mistake, mistake_id)
        assert mistake is not None
        await append_label_version(
            session,
            mistake_id=mistake_id,
            base_version=mistake.current_version,
            actor="student",
            category_id=TOPIC,
            concept_ids=[concept_id],
            error_cause=None,
        )


async def _first_schedule(factory: async_sessionmaker, mistake_id: int) -> ReviewSchedule:
    async with factory() as session:
        return (
            await session.scalars(
                select(ReviewSchedule)
                .where(ReviewSchedule.mistake_id == mistake_id)
                .order_by(ReviewSchedule.id)
            )
        ).first()


async def _open_schedule(factory: async_sessionmaker, mistake_id: int) -> ReviewSchedule:
    async with factory() as session:
        return (
            await session.scalars(
                select(ReviewSchedule)
                .where(
                    ReviewSchedule.mistake_id == mistake_id,
                    ReviewSchedule.completed_at.is_(None),
                )
                .order_by(ReviewSchedule.id)
            )
        ).one()


@pytest.mark.integration
async def test_review_quiz_formula_fallback_returns_422_then_self_eval(tmp_path) -> None:
    factory = _migrated(tmp_path)
    await _seed_formula_question(factory)

    async with _client(factory) as client:
        mistake_id = await _confirm_wrong(client)
        await _set_primary_topic(factory, mistake_id, TOPIC)
        schedule = await _first_schedule(factory, mistake_id)
        assert schedule is not None
        # 确认入本本身会写事实事件；fallback 只许"不新增"，以确认后的计数为基线。
        baseline_events = await _count(factory, LearningEvent)
        baseline_attempts = await _count(factory, Attempt)

        due = await client.get(
            "/api/reviews/due", params={"today": schedule.due_date.isoformat()}
        )
        assert due.status_code == 200, due.text
        items = due.json()["items"]
        assert len(items) == 1
        assert items[0]["task"] == "quiz"
        quiz = items[0]["quiz"]
        assert quiz["question_id"] == QUESTION_ID
        assert quiz["mode"] == "system"
        _assert_no_answer_keys(quiz)

        submit = {
            "schedule_id": schedule.id,
            "question_id": QUESTION_ID,
            "answer": OUT_OF_SUBSET,
            "completed_on": schedule.due_date.isoformat(),
        }
        # 超出子集且未自评 → 422，reason=formula_fallback，绝不落库。
        rejected = await client.post(f"/api/reviews/{mistake_id}/quiz", json=submit)
        assert rejected.status_code == 422, rejected.text
        detail = rejected.json()["detail"]
        assert detail["reason"] == "formula_fallback"
        assert detail["message"]
        assert await _count(factory, Attempt) == baseline_attempts
        assert await _count(factory, LearningEvent) == baseline_events

        # 补卷面自评 correct=True → 200，降级 student_self，带标签。
        graded = await client.post(
            f"/api/reviews/{mistake_id}/quiz", json={**submit, "correct": True}
        )
        assert graded.status_code == 200, graded.text
        body = graded.json()
        assert body["verdict"] == "correct"
        assert body["mode"] == "system"
        assert body["formula_fallback"] is True
        assert body["completion"]["source"] == "student_self"
        assert body["completion"]["correct"] is True
        _assert_no_answer_keys(body)

        assert await _count(factory, Attempt) == baseline_attempts + 1
        assert await _count(factory, LearningEvent) == baseline_events + 1
        async with factory() as session:
            attempt = (
                await session.scalars(
                    select(Attempt).where(Attempt.mistake_id == mistake_id)
                )
            ).one()
            assert attempt.source == "student_self"
            event = await session.get(LearningEvent, attempt.learning_event_id)
            assert event is not None
            payload = json.loads(event.payload)
        assert payload["source"] == "student_self"
        assert payload["quiz_verdict"] == "correct"
        assert payload["formula_fallback"] is True

        # 同排期幂等回放：结果与标签一致，不新增行。
        repeated = await client.post(
            f"/api/reviews/{mistake_id}/quiz", json={**submit, "correct": True}
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == body
        assert await _count(factory, Attempt) == baseline_attempts + 1
        assert await _count(factory, LearningEvent) == baseline_events + 1


@pytest.mark.integration
async def test_review_formula_fallback_tag_is_inert_for_mastery_and_schedule(tmp_path) -> None:
    """formula_fallback 标签只作展示/审计：剥掉它，mastery、下次到期日、判分结论字段一字不变。

    对照面 =「不带 formula_fallback 标签的同类自评」：把真实事实事件逐条剥掉该标签得到孪生
    输入，其余字段一字不动。为了让 mastery 非平凡（否则"标签把 mastery 清零"的 bug 会隐形），
    先做一次系统判对的复习给 CONCEPT_ID 建立 mastery=1.0，再做公式 fallback 自评；反证
    （mastery=0 的到期日必须不同）证明 mastery 确实进了间隔公式、标签没有暗中改写它。
    """

    factory = _migrated(tmp_path)
    await _seed_formula_question(factory)

    async with _client(factory) as client:
        mistake_id = await _confirm_wrong(client)
        await _set_primary_topic(factory, mistake_id, TOPIC)
        await _set_confirmed_concept(factory, mistake_id, CONCEPT_ID)
        first = await _first_schedule(factory, mistake_id)
        assert first is not None

        # 第一次复习：系统判对（无标签），为 CONCEPT_ID 建立非平凡掌握度。
        first_graded = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": first.id,
                "question_id": QUESTION_ID,
                "answer": EQUIVALENT_ANSWER,
                "completed_on": first.due_date.isoformat(),
            },
        )
        assert first_graded.status_code == 200, first_graded.text
        assert first_graded.json()["formula_fallback"] is False
        assert first_graded.json()["completion"]["source"] == "system_quiz"

        second = await _open_schedule(factory, mistake_id)
        submit = {
            "schedule_id": second.id,
            "question_id": QUESTION_ID,
            "answer": OUT_OF_SUBSET,
            "completed_on": second.due_date.isoformat(),
        }
        # 第二次复习：公式超出子集 → 未自评 422；补自评 correct=True → fallback 带标签。
        rejected = await client.post(f"/api/reviews/{mistake_id}/quiz", json=submit)
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["reason"] == "formula_fallback"
        graded = await client.post(
            f"/api/reviews/{mistake_id}/quiz", json={**submit, "correct": True}
        )
        assert graded.status_code == 200, graded.text
        assert graded.json()["formula_fallback"] is True
        assert graded.json()["completion"]["source"] == "student_self"

        # 读全部事实事件，构造「带标签」与「剥标签」两套孪生输入（与 review._mastery_for 同构）。
        async with factory() as session:
            rows = (
                await session.scalars(select(LearningEvent).order_by(LearningEvent.id))
            ).all()
            init = (
                await session.scalars(
                    select(LearningEvent).where(
                        LearningEvent.mistake_id == mistake_id,
                        LearningEvent.type == "review_scheduled",
                    )
                )
            ).one()
            ladder = tuple(json.loads(init.payload)["ladder"])
            next_schedule = (
                await session.scalars(
                    select(ReviewSchedule).where(
                        ReviewSchedule.mistake_id == mistake_id,
                        ReviewSchedule.completed_at.is_(None),
                    )
                )
            ).one()

        # fallback 完成事件 = 最后一条 attempt_correct（第一次系统判对也在内，故取最高 id）。
        completion = next(row for row in reversed(rows) if row.type == "attempt_correct")
        completion_payload = json.loads(completion.payload)

        def _event(row: LearningEvent, *, strip_tag: bool) -> RecomputeEvent:
            payload = json.loads(row.payload)
            if strip_tag:
                payload = {
                    key: value
                    for key, value in payload.items()
                    if key != "formula_fallback"
                }
            return RecomputeEvent(
                type=row.type,
                actor=row.actor,
                mistake_id=row.mistake_id,
                payload=payload,
                occurred_at=row.occurred_at,
            )

        real_events = [_event(row, strip_tag=False) for row in rows]
        twin_events = [_event(row, strip_tag=True) for row in rows]
        # 完成前孪生事实（剥标签 + 去掉本次完成事件）= 服务端算 mastery 时的输入。
        twin_pre_events = [
            _event(row, strip_tag=True) for row in rows if row.id != completion.id
        ]

        assert completion_payload["formula_fallback"] is True
        assert completion_payload["concept_ids"] == [CONCEPT_ID]

        # ① mastery：带标签 == 剥标签 == 1.0（非平凡：两次复习都对）。
        real_mastery = mastery(real_events, CONCEPT_ID)
        twin_mastery = mastery(twin_events, CONCEPT_ID)
        assert real_mastery == twin_mastery == 1.0
        # 服务端落库的 mastery = 完成前掌握度，可由剥标签的前置事实重算复现（标签不参与）。
        twin_pre_mastery = mastery(twin_pre_events, CONCEPT_ID)
        assert completion_payload["mastery"] == twin_pre_mastery == 1.0

        # ② 下次到期日：用剥标签前置 mastery 重放 decide == 已落库下次排期 == 完成事件 due_on。
        state_before = ReviewState(
            rung=completion_payload["rung_before"],
            times_wrong=completion_payload["times_wrong_before"],
            trailing_correct=completion_payload["trailing_correct_before"],
        )
        completed_on = date.fromisoformat(completion_payload["completed_on"])
        twin_decision = decide(
            state_before,
            correct=True,
            completed_on=completed_on,
            mastery=twin_pre_mastery,
            ladder=ladder,
        )
        assert twin_decision.due_on == next_schedule.due_date
        assert twin_decision.due_on == date.fromisoformat(completion_payload["due_on"])
        # 反证：mastery 确实进间隔公式——若标签把 mastery 清零，到期日会缩短（+30 而非 +150）。
        zero_decision = decide(
            state_before,
            correct=True,
            completed_on=completed_on,
            mastery=0.0,
            ladder=ladder,
        )
        assert zero_decision.due_on != next_schedule.due_date

        # ③ 标签是纯附加元数据：真实 payload 与剥标签 payload 仅差 formula_fallback 一键，
        #    所有判分结论字段逐项相等（标签不参与任何结论）。
        twin_payload = {
            key: value
            for key, value in completion_payload.items()
            if key != "formula_fallback"
        }
        assert set(completion_payload) - set(twin_payload) == {"formula_fallback"}
        for field in (
            "quiz_verdict",
            "source",
            "correct",
            "mastery",
            "interval_days",
            "due_on",
            "rung_after",
            "times_wrong_after",
            "trailing_correct_after",
            "graduated",
        ):
            assert completion_payload[field] == twin_payload[field]
