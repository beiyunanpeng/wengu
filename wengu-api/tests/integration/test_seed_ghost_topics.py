"""P5-16 补充：幽灵点语义钉死（点 upsert 不删 / 边全量重建 的有意不对称）。

场景 = 老库升级：seed JSON v1 含某点，上游 v2 把它删了，但 DB knowledge_seed 已有该行。
- 点只 upsert 不删行：幽灵行保留（保护 mistakes.primary_topic_id 等 FK 引用与历史事实），
  清理走 P1-13 归并/删除机制，装载器绝不做破坏性删除；
- 先修边全量 delete 重建：幽灵点的边随 JSON 消失（边只被本表引用，JSON 即真源）；
- 计数以 DB 为准：老库升级后可能比 JSON 多 N 个幽灵点，不断言"必须等于 JSON 条数"；
- 幽灵点无题 → 到期任务退回 redo（原题重做自评）、组卷受控 QuizTopicNotFound，不崩。

变异自证：把 _upsert_topics 改成"删除 seed 中不存在的行"→ 本文件必红（RED 输出见交付报告）。
断言右侧字面钉死（§19-L 纪律①），不从被测文件反算。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import KnowledgeSeed, Mistake, PrerequisiteEdge, ReviewSchedule
from app.seed.loader import load_seed
from app.services.bank import find_same_type, get_runtime_bank, reset_bank_cache
from app.services.quiz import QuizTopicNotFound, build_paper
from app.services.review import task_kind
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
CHANNEL = "agent_transcribe_v1"

KEEP_TOPIC = "cnm_ghost_keep"
GHOST_TOPIC = "cnm_ghost_drop"  # 真实题库无此前缀点，保证"无题"前提
TOPICS_V1 = [
    {"id": KEEP_TOPIC, "subject": "数学", "name": "保留点", "grade": 7},
    {"id": GHOST_TOPIC, "subject": "数学", "name": "上游已删的点", "grade": 7},
]
EDGES_V1 = [
    {"topic_id": GHOST_TOPIC, "prerequisite_id": KEEP_TOPIC, "strength": "soft"},
]


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "ghost.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _write_seeds(root: Path, topics: list[dict], edges: list[dict]) -> Path:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "topics.json").write_text(
        json.dumps(topics, ensure_ascii=False), encoding="utf-8"
    )
    (root / "data" / "dependencies.json").write_text(
        json.dumps(edges, ensure_ascii=False), encoding="utf-8"
    )
    return root


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
            response = await client.post("/api/session/unlock", json={"pin": PIN})
        else:
            response = await client.post("/api/session/pin/set", json={"pin": PIN})
        assert response.status_code == 200, response.text
        yield client


async def _confirm_wrong(client: AsyncClient, topic_id: str) -> int:
    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": "数学",
                    "problem_text": "幽灵点挂题",
                    "student_answer": "错误作答",
                    "standard_answer": "正确作答",
                    "suggested_topic_id": topic_id,
                    "source_ref": f"测试卷 {uuid4().hex}",
                    "captured_at": "2026-11-19",
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
        f"/api/imports/drafts/{draft_id}/confirm",
        json={"actor": "student", "primary_topic_id": topic_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    return int(confirmed.json()["mistake_id"])


async def _set_due_today(factory: async_sessionmaker, mistake_id: int) -> None:
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
            row.due_date = date.today()


@pytest.mark.integration
async def test_ghost_row_survives_reload_and_edges_rebuild(tmp_path: Path) -> None:
    """①不报错不删行 ③边随全量重建消失 ④计数以 DB 为准（可多 N 个幽灵点）。"""

    factory = _migrated(tmp_path)
    seeds = _write_seeds(tmp_path / "seeds", TOPICS_V1, EDGES_V1)
    async with factory() as session:
        await load_seed(session, seeds, data_dir=tmp_path / "runtime")

    # 上游 v2：删掉幽灵点与它的边
    _write_seeds(seeds, TOPICS_V1[:1], [])
    async with factory() as session:
        index = await load_seed(session, seeds, data_dir=tmp_path / "runtime")  # ① 不报错

    async with factory() as session:
        rows = (await session.execute(select(KnowledgeSeed))).scalars().all()
        by_id = {row.id: row for row in rows}
        # ④ DB 为准：JSON 只剩 1 点，DB 仍 2 行——多出的 1 个是幽灵点，不断言相等
        assert len(rows) == 2
        assert GHOST_TOPIC in by_id  # ① 不自动删除（保护错题引用与历史事实）
        assert by_id[GHOST_TOPIC].name == "上游已删的点"
        edges = (await session.execute(select(PrerequisiteEdge))).scalars().all()
        assert edges == []  # ③ 边全量重建：幽灵点的边已消失

    # 内存索引以 JSON 为真源：幽灵点不在索引里，但 DB 行仍在——不对称是有意的
    assert set(index.topics) == {KEEP_TOPIC}


@pytest.mark.integration
async def test_ghost_topic_due_falls_back_to_redo(tmp_path: Path) -> None:
    """②幽灵点无题：到期退回 redo（原题重做自评）、组卷受控拦截，不崩。"""

    factory = _migrated(tmp_path)
    seeds = _write_seeds(tmp_path / "seeds", TOPICS_V1, EDGES_V1)
    async with factory() as session:
        await load_seed(session, seeds, data_dir=tmp_path / "runtime")
    reset_bank_cache()

    async with _client(factory) as client:
        mistake_id = await _confirm_wrong(client, GHOST_TOPIC)
        await _set_due_today(factory, mistake_id)

        # 老库升级：v2 删点后再装载
        _write_seeds(seeds, TOPICS_V1[:1], [])
        async with factory() as session:
            await load_seed(session, seeds, data_dir=tmp_path / "runtime")
        reset_bank_cache()

        response = await client.get(
            "/api/reviews/due", params={"today": date.today().isoformat()}
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["task"] == "redo"  # 无题 → 原题重做（自评），不是崩溃
        assert item["bank_gap"] is True
        assert item["quiz"] is None

    async with factory() as session:
        mistake = await session.get(Mistake, mistake_id)
        assert mistake is not None
        assert mistake.primary_topic_id == GHOST_TOPIC  # 错题引用未被破坏
        bank = await get_runtime_bank(session)
        pick = find_same_type(GHOST_TOPIC, 7, bank=bank)
        assert pick.question is None
        assert pick.coverage == "gap"
        assert task_kind(pick) == "redo"
        # 组卷对未知/无题点是受控领域错误（API 404），不是未处理异常
        with pytest.raises(QuizTopicNotFound):
            await build_paper(session, GHOST_TOPIC, 7, 1)
