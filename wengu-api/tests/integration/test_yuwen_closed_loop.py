"""P3-5 语文客观并入：闭环证据测试（§19-M 定案一的运行时锚定）。

- 题池全收：语文 choice 题与数学走**同一条** 转录导入 → 核对页转正 → 首排 →
  到期 → 组卷 → judgeAnswer 代码路径，零学科分支（同一夹具仅换 subject/主考点，
  行为等价）；组卷直接抽真实 seed 题池（`get_bank()` 默认装载，不改 seeds/data）。
- "不进本"闸门在转录模板 v3：作文/续写/仿写/看图写话/需整篇材料的阅读理解大题
  转录侧就不产出 → 本里就没有；运行时**没有**任何按 domain 或学科的代码闸门
  （domain=阅读理解的独立短选题照常转正、照常组卷）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
from app.seed.bank import BankQuestion
from app.services.bank import get_bank
from app.services.recompute import Event as RecomputeEvent
from app.services.recompute import mastery
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

CHANNEL = "agent_transcribe_v1"
FORBIDDEN_KEYS = {"answer", "accept", "explanation", "verify"}


def _migrated(tmp_path: Path) -> async_sessionmaker:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "yuwen_loop.db"
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
        # 组卷端点属家长区：先设 PIN（导入/核对/到期队列孩子可达，不受影响）
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
    subject: str,
    domain: str,
) -> None:
    async with factory() as session, session.begin():
        session.add(
            KnowledgeSeed(
                id=topic_id,
                subject=subject,
                name=name,
                domain=domain,
                grade="7",
                semester="上册",
                chapter=name,
                type="topic",
                unaudited=True,
                blind_verified=False,
            )
        )


async def _seed_concept(
    factory: async_sessionmaker, *, name: str, category_id: str
) -> int:
    async with factory() as session, session.begin():
        row = Concept(
            name=name,
            category_id=category_id,
            source="parent",
            status="confirmed",
            merged_into_id=None,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row.id


def _item(subject: str, topic_id: str, **overrides) -> dict:
    """同一夹具仅换 subject 与主考点 id，其余字段逐字相同（行为等价对照用）。"""

    item = {
        "subject": subject,
        "problem_text": "下列说法正确的一项是",
        "student_answer": "A",
        "standard_answer": "B",
        "error_cause_suggestion": "概念不清",
        "suggested_topic_id": topic_id,
        "source_ref": "期中卷 第3题",
        "captured_at": "2026-11-20",
    }
    item.update(overrides)
    return item


async def _import_drafts(client: AsyncClient, items: list[dict]) -> list[int]:
    response = await client.post(
        "/api/imports",
        content=json.dumps({"channel": CHANNEL, "items": items}, ensure_ascii=False),
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch_id"]
    drafts = await client.get(f"/api/imports/{batch_id}/drafts")
    return [draft["id"] for draft in drafts.json()["drafts"]]


async def _confirm(
    client: AsyncClient, draft_id: int, *, topic_id: str, concept_id: int
) -> dict:
    response = await client.post(
        f"/api/imports/drafts/{draft_id}/confirm",
        json={
            "primary_topic_id": topic_id,
            "concept_ids": [concept_id],
            "error_cause": "concept_unclear",
            "actor": "parent",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _count(factory: async_sessionmaker, model) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)))


async def _mastery(factory: async_sessionmaker, concept_id: int) -> float:
    async with factory() as session:
        rows = (await session.scalars(select(LearningEvent))).all()
    events = [
        RecomputeEvent(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    return mastery(events, concept_id)


def _wrong_answer(question: BankQuestion) -> str:
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


async def _closed_loop(
    client: AsyncClient,
    factory: async_sessionmaker,
    *,
    subject: str,
    topic_id: str,
    concept_name: str,
) -> dict:
    """入本 → 排期 → 到期 → 组卷 → judgeAnswer 全链；返回可跨学科对照的行为观测。"""

    concept_id = await _seed_concept(
        factory, name=concept_name, category_id=topic_id
    )

    # ① 入本：转录报文 → 草稿 → 核对页确认（唯一写入路径）
    draft_ids = await _import_drafts(client, [_item(subject, topic_id)])
    assert len(draft_ids) == 1
    body = await _confirm(client, draft_ids[0], topic_id=topic_id, concept_id=concept_id)
    assert body["already_promoted"] is False
    assert body["primary_topic_id"] == topic_id
    mistake_id = body["mistake_id"]
    due_on = body["due_on"]
    assert due_on

    async with factory() as session:
        mistake = await session.get(Mistake, mistake_id)
        assert mistake is not None
        assert mistake.primary_topic_id == topic_id
        assert mistake.status == "active"
        schedule = (
            await session.scalars(
                select(ReviewSchedule).where(ReviewSchedule.mistake_id == mistake_id)
            )
        ).one()
        assert schedule.rung == 0
        assert schedule.completed_at is None
        assert schedule.due_date.isoformat() == due_on
        event_types = sorted(
            (await session.scalars(select(LearningEvent.type))).all()
        )
    assert "attempt_wrong" in event_types
    assert "review_scheduled" in event_types
    assert await _count(factory, Attempt) == 0  # 入本不建 attempts

    # ② 到期：首排前一天不到期，到期日进入复习队列
    before = await client.get(
        "/api/reviews/due",
        params={"today": (date.fromisoformat(due_on) - timedelta(days=1)).isoformat()},
    )
    assert before.status_code == 200, before.text
    assert before.json()["due_total"] == 0
    due = await client.get("/api/reviews/due", params={"today": due_on})
    assert due.status_code == 200, due.text
    assert due.json()["due_total"] == 1
    assert due.json()["items"][0]["mistake_id"] == mistake_id

    # ③ 组卷：真实 seed 题池确定性抽题，可自动判分（mode=system），无答案泄漏
    paper = await client.get(
        "/api/quizzes/paper",
        params={"topic_id": topic_id, "count": 2, "seed": 7},
    )
    assert paper.status_code == 200, paper.text
    paper_body = paper.json()
    assert len(paper_body["items"]) == 2
    assert paper_body["bank_gap"] is False
    assert paper_body["shortfall"] is False
    assert all(item["mode"] == "system" for item in paper_body["items"])
    _assert_no_answer_keys(paper_body)
    bank = get_bank()
    questions = [bank.question(item["question_id"]) for item in paper_body["items"]]
    assert all(q is not None and q.subject == subject for q in questions)

    # ④ judgeAnswer 判分：服务端判（客户端谎报 correct 被忽略），事件与掌握度更新
    submitted = await client.post(
        "/api/quizzes/paper/submit",
        json={
            "topic_id": topic_id,
            "seed": 7,
            "count": 2,
            "answers": [
                {
                    "question_id": questions[0].id,
                    "answer": questions[0].answer,
                    "correct": False,
                },
                {
                    "question_id": questions[1].id,
                    "answer": _wrong_answer(questions[1]),
                    "correct": True,
                },
            ],
        },
    )
    assert submitted.status_code == 200, submitted.text
    submit_body = submitted.json()
    assert [item["status"] for item in submit_body["items"]] == ["correct", "wrong"]
    assert submit_body["correct"] == 1
    assert submit_body["wrong"] == 1
    _assert_no_answer_keys(submit_body)

    async with factory() as session:
        attempts = (await session.scalars(select(Attempt).order_by(Attempt.id))).all()
        quiz_events = (
            await session.scalars(
                select(LearningEvent).where(
                    LearningEvent.type.in_(("attempt_correct", "attempt_wrong")),
                    LearningEvent.mistake_id.is_(None),
                )
            )
        ).all()
    assert len(attempts) == 2
    assert all(a.mistake_id is None and a.kind == "quiz" for a in attempts)
    assert [a.is_correct for a in attempts] == [True, False]
    assert len(quiz_events) == 2
    for event in quiz_events:
        payload = json.loads(event.payload)
        assert payload["source"] == "system_quiz"
        assert payload["concept_ids"] == [concept_id]
        assert payload["quiz_topic_id"] == topic_id
        assert "answer" not in payload  # 作答原文不进事件（隐私最小化）
    assert await _mastery(factory, concept_id) == 0.5

    # 幂等重放：同一张卷重复交卷不重复计分
    repeated = await client.post(
        "/api/quizzes/paper/submit",
        json={
            "topic_id": topic_id,
            "seed": 7,
            "count": 2,
            "answers": [
                {"question_id": questions[0].id, "answer": questions[0].answer},
                {
                    "question_id": questions[1].id,
                    "answer": _wrong_answer(questions[1]),
                },
            ],
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert all(item["replayed"] is True for item in repeated.json()["items"])
    assert await _count(factory, Attempt) == 2
    assert await _mastery(factory, concept_id) == 0.5

    async with factory() as session:
        final_types = sorted(
            (await session.scalars(select(LearningEvent.type))).all()
        )
    return {
        "draft_count": len(draft_ids),
        "already_promoted": body["already_promoted"],
        "mistake_status": mistake.status,
        "schedule_rung": schedule.rung,
        "due_before": before.json()["due_total"],
        "due_total": due.json()["due_total"],
        "paper_count": len(paper_body["items"]),
        "paper_modes": [item["mode"] for item in paper_body["items"]],
        "coverage": paper_body["coverage"],
        "bank_gap": paper_body["bank_gap"],
        "submit_statuses": [item["status"] for item in submit_body["items"]],
        "attempt_count": len(attempts),
        "attempt_sources": [a.source for a in attempts],
        "mastery": await _mastery(factory, concept_id),
        "event_types": final_types,
        "question_types": [q.type for q in questions],
    }


@pytest.mark.integration
async def test_yuwen_and_math_share_one_closed_loop(tmp_path) -> None:
    """语文与数学走同一条代码路径：同一夹具仅换 subject/主考点，行为观测全等。

    语文考点特意选 domain=阅读理解的 cnc_j001（独立短选择题）：证明运行时
    不存在按 domain 的闭环闸门（A3′ 定案：按 domain 切会误伤 480 道独立短题）。
    """

    yuwen_factory = _migrated(tmp_path / "yuwen")
    await _seed_topic(
        yuwen_factory,
        topic_id="cnc_j001",
        name="阅读《春》",
        subject="语文",
        domain="阅读理解",
    )
    math_factory = _migrated(tmp_path / "math")
    await _seed_topic(
        math_factory,
        topic_id="cnm_001",
        name="正数与负数的概念",
        subject="数学",
        domain="数与代数",
    )

    async with (
        _client(yuwen_factory) as yuwen_client,
        _client(math_factory) as math_client,
    ):
        yuwen = await _closed_loop(
            yuwen_client,
            yuwen_factory,
            subject="语文",
            topic_id="cnc_j001",
            concept_name="课文内容理解",
        )
        math = await _closed_loop(
            math_client,
            math_factory,
            subject="数学",
            topic_id="cnm_001",
            concept_name="正负数概念辨析",
        )

    yuwen_types = yuwen.pop("question_types")
    math.pop("question_types")
    assert yuwen == math  # 零学科分支：两科行为观测逐键相等
    assert yuwen_types == ["choice", "choice"]  # 组卷真实抽到语文 choice 题


@pytest.mark.integration
async def test_transcription_gate_keeps_non_bank_items_out_of_mistakes(tmp_path) -> None:
    """"不进本"面零 mistakes 行：靠转录侧不产出，不靠代码过滤。

    卷面实况 = 2 道独立短小题错 + 作文/整篇材料阅读大题错；遵守模板 v3 的
    转录端只产出前两道（大题不进本、压根不在报文里）。全链后错题本恰好
    只有这两道短小题——服务端全收（不做任何学科/domain 过滤），闸门只在转录侧。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(
        factory,
        topic_id="cnc_j004",
        name="古代诗歌四首",
        subject="语文",
        domain="古诗文积累",
    )
    await _seed_topic(
        factory,
        topic_id="cnc_j001",
        name="阅读《春》",
        subject="语文",
        domain="阅读理解",
    )
    concept_poem = await _seed_concept(
        factory, name="古诗文意象", category_id="cnc_j004"
    )
    concept_read = await _seed_concept(
        factory, name="课文内容理解", category_id="cnc_j001"
    )
    items = [
        _item(
            "语文",
            "cnc_j004",
            problem_text="《观沧海》中“日月之行，若出其中”运用的表现手法是",
            student_answer="A",
            standard_answer="B",
        ),
        _item(
            "语文",
            "cnc_j001",
            problem_text="《春》中“小草偷偷地从土里钻出来”的“钻”字好在哪里",
            student_answer="C",
            standard_answer="A",
        ),
    ]

    async with _client(factory) as client:
        draft_ids = await _import_drafts(client, items)
        assert len(draft_ids) == 2  # 服务端全收：报文里没有的大题不会被"过滤"出来
        for draft_id, topic_id, concept_id in zip(
            draft_ids,
            ["cnc_j004", "cnc_j001"],
            [concept_poem, concept_read],
            strict=True,
        ):
            body = await _confirm(
                client, draft_id, topic_id=topic_id, concept_id=concept_id
            )
            assert body["already_promoted"] is False
            assert body["due_on"]

    async with factory() as session:
        mistakes = (await session.scalars(select(Mistake))).all()
    assert len(mistakes) == 2  # 不进本面（作文/续写/仿写/看图写话/整篇材料大题）零行
    assert {m.primary_topic_id for m in mistakes} == {"cnc_j004", "cnc_j001"}
    assert all(m.status == "active" for m in mistakes)
    assert await _count(factory, Attempt) == 0


@pytest.mark.integration
async def test_runtime_has_no_subject_or_domain_gate(tmp_path) -> None:
    """定案①②的反向锚定：运行时不设学科/domain 闸门。

    即使转录端违反模板 v3 把作文题送进来，服务端也照常收草稿、照常转正——
    "不进本"完全靠转录指令约束，核对页之后没有任何代码闸门可依赖。
    这条测试钉住"闸门位置"，防止日后有人把代码闸门加回来。
    """

    factory = _migrated(tmp_path)
    await _seed_topic(
        factory,
        topic_id="cnc_j005",
        name="写作：学会观察",
        subject="语文",
        domain="习作基础",
    )
    concept_id = await _seed_concept(
        factory, name="写作观察", category_id="cnc_j005"
    )

    async with _client(factory) as client:
        draft_ids = await _import_drafts(
            client,
            [
                _item(
                    "语文",
                    "cnc_j005",
                    problem_text="请以《窗外》为题，写一篇不少于 600 字的作文",
                    student_answer="（作文原文略）",
                    standard_answer="（评分标准略）",
                )
            ],
        )
        assert len(draft_ids) == 1
        body = await _confirm(
            client, draft_ids[0], topic_id="cnc_j005", concept_id=concept_id
        )
        assert body["primary_topic_id"] == "cnc_j005"
        assert body["due_on"]

    assert await _count(factory, Mistake) == 1
