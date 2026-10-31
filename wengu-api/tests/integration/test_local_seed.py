"""P3-5 前置 / P1-1b 延伸：家长自建章级 seed（语文 cnl_ / 化学 cnc_）。

DoD（TICKETS P3-5 前置）：
1. 装载：`<data_dir>/seeds_local` 的语文点重启后仍在（source='local'、
   unaudited=1、blind_verified=0）；坏文件只告警不阻塞其余源；id 冲突拒绝。
2. CRUD：POST 生成 cnl_001 → 原子落盘 → GET 可见 → PATCH 生效；
   非 local 行 PATCH/DELETE 404；上游学科提交 422。
3. 端到端：新建语文点 → 题库录题挂点 → 错题确认 → 到期队列出 quiz（gap 关闭）。
4. DELETE 联动：mistakes.primary_topic_id / problem_bank.topic_id 置 NULL、
   错题与题目仍在、受影响计数正确；仍有 concept 引用时 409。
5. 导出脚本合并 local 行，seeds/data/topics.json 字节不变。
6. 未解锁全 403。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import Concept, KnowledgeSeed, Mistake, ProblemBankItem, ReviewSchedule
from app.seed.loader import load_seed, local_seed_files, next_local_id
from httpx import ASGITransport, AsyncClient
from scripts.export_topics_junior import DEFAULT_SRC, export
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
SEED_PATH = API_DIR.parent / "seeds" / "data" / "topics.json"
PIN = "2468"
CHANNEL = "agent_transcribe_v1"

UPSTREAM_TOPIC = {
    "id": "cnm_001",
    "subject": "数学",
    "name": "有理数",
    "domain": "数与代数",
    "grade": 7,
    "semester": "上册",
    "type": "conceptual",
    "unaudited": True,
    "blind_verified": True,
}

LOCAL_TOPICS = [
    {
        "id": f"cnl_{index:03d}",
        "subject": "语文",
        "name": name,
        "domain": "阅读",
        "grade": 7,
        "semester": "上册",
        "chapter": f"第{index}单元",
        "type": "conceptual",
        "description": f"语文知识点 {index}",
        "mastery_criteria": ["能概括段落大意"],
    }
    for index, name in enumerate(["春", "济南的冬天", "雨的四季"], start=1)
]


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", seeds_dir=tmp_path / "seeds")


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "local-seed.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@asynccontextmanager
async def _client(
    factory: async_sessionmaker, settings: Settings, *, unlock: bool = True
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if unlock:
            status = await client.get("/api/session/status")
            if status.json()["pin_set"]:
                response = await client.post(
                    "/api/session/unlock", json={"pin": PIN}
                )
            else:
                response = await client.post(
                    "/api/session/pin/set", json={"pin": PIN}
                )
            assert response.status_code == 200, response.text
        yield client


async def _create_topic(
    client: AsyncClient, *, name: str = "春", subject: str = "语文"
) -> dict:
    response = await client.post(
        "/api/local-seed/topics",
        json={
            "subject": subject,
            "name": name,
            "grade": 7,
            "semester": "上册",
            "chapter": "第一单元",
            "domain": "阅读",
            "mastery_criteria": ["能概括段落大意"],
            "type": "conceptual",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_item(
    client: AsyncClient, *, topic_id: str, prompt: str, answer: str
) -> int:
    response = await client.post(
        "/api/bank/items",
        json={
            "topic_id": topic_id,
            "type": "short",
            "difficulty": "easy",
            "prompt": prompt,
            "answer": answer,
            "choices": [],
            "verify": "",
            "source_ref": f"家长补录 {uuid4().hex}",
        },
    )
    assert response.status_code == 201, response.text
    return int(response.json()["problem_bank_id"])


async def _confirm_wrong(
    client: AsyncClient, *, subject: str, topic_id: str, problem_text: str
) -> int:
    response = await client.post(
        "/api/imports",
        json={
            "channel": CHANNEL,
            "items": [
                {
                    "subject": subject,
                    "problem_text": problem_text,
                    "student_answer": "错误作答",
                    "standard_answer": "正确作答",
                    "suggested_topic_id": topic_id,
                    "source_ref": f"测试卷 {uuid4().hex}",
                    "captured_at": "2026-10-31",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch_id"]
    drafts = await client.get(f"/api/imports/{batch_id}/drafts")
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


def _seed_digest() -> str:
    return hashlib.sha256(SEED_PATH.read_bytes()).hexdigest()


@pytest.mark.integration
async def test_loader_merges_local_sources_and_survives_restart(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _write_json(settings.seeds_dir / "data" / "topics.json", [UPSTREAM_TOPIC])
    _write_json(settings.seeds_dir / "data" / "dependencies.json", [])
    _write_json(settings.seeds_dir / "local" / "topics_化学.json", [
        {"id": "cnc_001", "subject": "化学", "name": "物质构成的奥秘", "grade": 9}
    ])
    _write_json(settings.data_dir / "seeds_local" / "topics_语文.json", LOCAL_TOPICS)
    # 坏文件：只跳过该文件
    (settings.data_dir / "seeds_local" / "broken.json").write_text(
        "{not json", encoding="utf-8"
    )
    # 重复 id：与 seeds/local 的 cnc_001 冲突，拒绝并记 error
    _write_json(settings.data_dir / "seeds_local" / "conflict.json", [
        {"id": "cnc_001", "subject": "化学", "name": "重复点"}
    ])

    factory = _migrated(tmp_path)
    async with factory() as session:
        index = await load_seed(session, settings.seeds_dir, settings.data_dir)
    async with factory() as session:
        rows = (await session.execute(select(KnowledgeSeed))).scalars().all()

    by_id = {row.id: row for row in rows}
    assert set(by_id) == {"cnm_001", "cnc_001", "cnl_001", "cnl_002", "cnl_003"}
    assert by_id["cnm_001"].source is None
    for topic_id in ("cnc_001", "cnl_001", "cnl_002", "cnl_003"):
        row = by_id[topic_id]
        assert row.source == "local"
        assert row.unaudited is True
        assert row.blind_verified is False
    assert by_id["cnl_001"].grade == "7"
    assert by_id["cnl_001"].mastery_criteria == '["能概括段落大意"]'
    assert index.topics["cnl_001"]["chapter"] == "第1单元"

    # 重启（再次装载）不重复、不丢：文件即真源
    async with factory() as session:
        await load_seed(session, settings.seeds_dir, settings.data_dir)
    async with factory() as session:
        count = len((await session.execute(select(KnowledgeSeed))).scalars().all())
    assert count == 5

    assert next_local_id("cnl_", {"cnl_001", "cnl_009", "cnx_100"}) == "cnl_010"


@pytest.mark.integration
async def test_local_topic_crud_writes_atomic_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(tmp_path)
    before = _seed_digest()

    async with _client(factory, settings) as client:
        empty = await client.get("/api/local-seed/topics")
        assert empty.status_code == 200
        assert empty.json() == {"items": [], "total": 0}

        created = await _create_topic(client)
        assert created["id"] == "cnl_001"
        assert created["unaudited"] is True
        assert created["blind_verified"] is False
        assert created["grade"] == "7"
        assert created["mistake_count"] == 0

        path = settings.data_dir / "seeds_local" / "topics_语文.json"
        assert path.exists()
        entries = json.loads(path.read_text(encoding="utf-8"))
        assert [entry["id"] for entry in entries] == ["cnl_001"]
        assert not list(path.parent.glob(".topics-*.tmp"))  # 无半写临时文件

        second = await _create_topic(client, name="济南的冬天")
        assert second["id"] == "cnl_002"

        listed = await client.get("/api/local-seed/topics", params={"subject": "语文"})
        assert listed.json()["total"] == 2
        chemistry = await client.get(
            "/api/local-seed/topics", params={"subject": "化学"}
        )
        assert chemistry.json()["total"] == 0
        rejected_subject = await client.get(
            "/api/local-seed/topics", params={"subject": "数学"}
        )
        assert rejected_subject.status_code == 422

        patched = await client.patch(
            "/api/local-seed/topics/cnl_001",
            json={"name": "春（改）", "chapter": "第二单元"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "春（改）"
        assert patched.json()["chapter"] == "第二单元"
        entries = json.loads(path.read_text(encoding="utf-8"))
        assert entries[0]["name"] == "春（改）"
        assert entries[0]["chapter"] == "第二单元"

        missing = await client.patch(
            "/api/local-seed/topics/cnl_999", json={"name": "不存在"}
        )
        assert missing.status_code == 404

        # 上游 seed 行不可改/不可删
        async with factory() as session, session.begin():
            session.add(
                KnowledgeSeed(
                    id="cnm_001", subject="数学", name="有理数", unaudited=True
                )
            )
        upstream_patch = await client.patch(
            "/api/local-seed/topics/cnm_001", json={"name": "改上游"}
        )
        upstream_delete = await client.delete("/api/local-seed/topics/cnm_001")
        assert (upstream_patch.status_code, upstream_delete.status_code) == (404, 404)

        assert (
            await client.post(
                "/api/local-seed/topics", json={"subject": "数学", "name": "有理数"}
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/local-seed/topics", json={"subject": "语文", "name": "  "}
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/local-seed/topics", json={"subject": "语文", "name": "x" * 41}
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/local-seed/topics",
                json={"subject": "语文", "name": "越界", "grade": 10},
            )
        ).status_code == 422

        removed = await client.delete("/api/local-seed/topics/cnl_002")
        assert removed.status_code == 200, removed.text
        assert removed.json()["removed"] is True
        entries = json.loads(path.read_text(encoding="utf-8"))
        assert [entry["id"] for entry in entries] == ["cnl_001"]
        assert (
            await client.delete("/api/local-seed/topics/cnl_002")
        ).status_code == 404

    assert _seed_digest() == before


@pytest.mark.integration
async def test_local_seed_id_counter_never_reuses_deleted_ids(tmp_path: Path) -> None:
    """DoD：建 001..003 → 删 003 → 再建得到 004；计数器只增不减，重启装载不受影响。"""

    settings = _settings(tmp_path)
    factory = _migrated(tmp_path)
    counter_path = settings.data_dir / "seeds_local" / "_id_counters.json"

    async with _client(factory, settings) as client:
        first = await _create_topic(client, name="春")
        second = await _create_topic(client, name="济南的冬天")
        third = await _create_topic(client, name="雨的四季")
        assert [first["id"], second["id"], third["id"]] == [
            "cnl_001",
            "cnl_002",
            "cnl_003",
        ]
        assert json.loads(counter_path.read_text(encoding="utf-8")) == {"语文": 3}

        removed = await client.delete("/api/local-seed/topics/cnl_003")
        assert removed.status_code == 200, removed.text
        # 删除不回退计数器
        assert json.loads(counter_path.read_text(encoding="utf-8")) == {"语文": 3}

        fourth = await _create_topic(client, name="古代诗歌")
        assert fourth["id"] == "cnl_004"
        assert json.loads(counter_path.read_text(encoding="utf-8")) == {"语文": 4}

        # 再删一次后仍不复用 004
        assert (
            await client.delete("/api/local-seed/topics/cnl_004")
        ).status_code == 200
        fifth = await _create_topic(client, name="现代文阅读")
        assert fifth["id"] == "cnl_005"

        topics_path = settings.data_dir / "seeds_local" / "topics_语文.json"
        entries = json.loads(topics_path.read_text(encoding="utf-8"))
        assert [entry["id"] for entry in entries] == [
            "cnl_001",
            "cnl_002",
            "cnl_005",
        ]
        assert not list(topics_path.parent.glob("._counters-*.tmp"))

    # 重启：装载器只读 topics_*.json，不把计数器当 seed
    _write_json(settings.seeds_dir / "data" / "topics.json", [UPSTREAM_TOPIC])
    _write_json(settings.seeds_dir / "data" / "dependencies.json", [])
    async with factory() as session:
        await load_seed(session, settings.seeds_dir, settings.data_dir)
    async with factory() as session:
        ids = set((await session.execute(select(KnowledgeSeed.id))).scalars())
    assert ids == {"cnm_001", "cnl_001", "cnl_002", "cnl_005"}


@pytest.mark.integration
async def test_loader_skips_underscore_files_in_both_local_sources(
    tmp_path: Path,
) -> None:
    """`_id_counters.json` 与其它下划线文件不是 topics 数组，两个本地源都必须跳过。"""

    settings = _settings(tmp_path)
    _write_json(settings.seeds_dir / "data" / "topics.json", [UPSTREAM_TOPIC])
    _write_json(settings.seeds_dir / "data" / "dependencies.json", [])
    _write_json(settings.seeds_dir / "local" / "_hidden.json", [
        {"id": "cnc_777", "subject": "化学", "name": "不应装载"}
    ])
    _write_json(settings.data_dir / "seeds_local" / "_id_counters.json", {"语文": 7})
    _write_json(settings.data_dir / "seeds_local" / "_hidden.json", [
        {"id": "cnl_777", "subject": "语文", "name": "不应装载"}
    ])
    _write_json(settings.data_dir / "seeds_local" / "topics_语文.json", LOCAL_TOPICS[:1])

    paths = local_seed_files(settings.seeds_dir, settings.data_dir)
    assert [path.name for path in paths] == ["topics_语文.json"]
    assert all(not path.name.startswith("_") for path in paths)

    factory = _migrated(tmp_path)
    async with factory() as session:
        await load_seed(session, settings.seeds_dir, settings.data_dir)
    async with factory() as session:
        ids = set((await session.execute(select(KnowledgeSeed.id))).scalars())
    assert ids == {"cnm_001", "cnl_001"}
    # 计数器文件本身未被改写
    assert json.loads(
        (settings.data_dir / "seeds_local" / "_id_counters.json").read_text(
            encoding="utf-8"
        )
    ) == {"语文": 7}


@pytest.mark.integration
async def test_local_topic_closes_bank_gap_end_to_end(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(tmp_path)
    before = _seed_digest()

    async with _client(factory, settings) as client:
        topic = await _create_topic(client, name="春")
        topic_id = topic["id"]

        # 转录模板的 suggested_topic_id / CategoryPicker 都能搜到本地点
        search = await client.get(
            "/api/seed/topics", params={"subject": "语文", "q": "春"}
        )
        assert search.status_code == 200, search.text
        assert [item["id"] for item in search.json()["items"]] == [topic_id]

        await _create_item(
            client,
            topic_id=topic_id,
            prompt="《春》中作者描写了哪些景物？",
            answer="花、草、树",
        )
        mistake_id = await _confirm_wrong(
            client,
            subject="语文",
            topic_id=topic_id,
            problem_text="语文：概括《春》的段落大意。",
        )
        await _set_due_today(factory, mistake_id)

        due = await client.get("/api/reviews/due")
        assert due.status_code == 200, due.text
        (item,) = due.json()["items"]
        assert item["mistake_id"] == mistake_id
        assert item["task"] == "quiz"  # 语文本地题池命中，gap 关闭
        quiz = item["quiz"]
        assert quiz["question_id"].startswith("manual_")
        assert quiz["pool_size"] == 1

        completed = await client.post(
            f"/api/reviews/{mistake_id}/quiz",
            json={
                "schedule_id": item["schedule_id"],
                "question_id": quiz["question_id"],
                "answer": "花、草、树",
                "completed_on": date.today().isoformat(),
            },
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["verdict"] == "correct"

        after = await client.get("/api/reviews/due")
        assert after.json()["items"] == []

    assert _seed_digest() == before


@pytest.mark.integration
async def test_delete_unbinds_mistakes_and_bank_items(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(tmp_path)
    before = _seed_digest()

    async with _client(factory, settings) as client:
        topic = await _create_topic(client, name="春")
        topic_id = topic["id"]
        problem_id = await _create_item(
            client,
            topic_id=topic_id,
            prompt="《春》的作者是谁？",
            answer="朱自清",
        )
        mistake_id = await _confirm_wrong(
            client,
            subject="语文",
            topic_id=topic_id,
            problem_text="语文：指出《春》的修辞手法。",
        )

        listed = await client.get("/api/local-seed/topics")
        usage = listed.json()["items"][0]
        assert (usage["mistake_count"], usage["problem_count"]) == (1, 1)

        removed = await client.delete(f"/api/local-seed/topics/{topic_id}")
        assert removed.status_code == 200, removed.text
        assert removed.json()["mistakes_unbound"] == 1
        assert removed.json()["problems_unbound"] == 1

        async with factory() as session:
            mistake = await session.get(Mistake, mistake_id)
            problem = await session.get(ProblemBankItem, problem_id)
            assert mistake is not None and mistake.primary_topic_id is None
            assert problem is not None and problem.topic_id is None
            assert problem.status == "active"

        assert (await client.get("/api/mistakes")).status_code == 200
        active = await client.get("/api/mistakes", params={"status": "active"})
        assert active.json()["total"] == 1
        mistake_detail = await client.get(f"/api/mistakes/{mistake_id}")
        assert mistake_detail.status_code == 200, mistake_detail.text
        # 版本快照是历史事实，不随删点改写；名称已无法解析（不显示假名称）
        assert mistake_detail.json()["labels"]["category_name"] is None
        items = await client.get("/api/bank/items", params={"status": "all"})
        assert items.json()["total"] == 1
        assert items.json()["items"][0]["topic_id"] is None

        # 仍有 concept 引用 → 409 且不删
        new_topic = await _create_topic(client, name="雨的四季")
        async with factory() as session, session.begin():
            session.add(
                Concept(
                    name="修辞",
                    category_id=new_topic["id"],
                    source="parent",
                    status="confirmed",
                    created_at=datetime.now(UTC),
                )
            )
        blocked = await client.delete(f"/api/local-seed/topics/{new_topic['id']}")
        assert blocked.status_code == 409, blocked.text
        still = await client.get(
            "/api/local-seed/topics", params={"subject": "语文"}
        )
        assert [item["id"] for item in still.json()["items"]] == [new_topic["id"]]

    assert _seed_digest() == before


@pytest.mark.integration
async def test_local_seed_requires_parent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(tmp_path)

    async with _client(factory, settings, unlock=False) as locked:
        listed = await locked.get("/api/local-seed/topics")
        created = await locked.post(
            "/api/local-seed/topics", json={"subject": "语文", "name": "春"}
        )
        patched = await locked.patch(
            "/api/local-seed/topics/cnl_001", json={"name": "春"}
        )
        deleted = await locked.delete("/api/local-seed/topics/cnl_001")
    assert [
        listed.status_code,
        created.status_code,
        patched.status_code,
        deleted.status_code,
    ] == [403, 403, 403, 403]
    assert not (settings.data_dir / "seeds_local").exists()


@pytest.mark.integration
def test_export_merges_local_rows_without_touching_upstream(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _seed_digest()
    local_dir = tmp_path / "local"
    _write_json(local_dir / "topics_语文.json", [
        {
            "id": "cnl_001",
            "subject": "语文",
            "name": "春",
            "grade": 7,
            "semester": "上册",
            "chapter": "第一单元",
        }
    ])
    _write_json(local_dir / "conflict.json", [
        {
            "id": "cnl_001",
            "subject": "语文",
            "name": "春（重复）",
            "grade": 7,
        }
    ])
    (local_dir / "broken.json").write_text("not-json", encoding="utf-8")

    out = tmp_path / "topics_junior.tsv"
    by_subject = export(DEFAULT_SRC, out, [local_dir])

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 + 664 + 1
    assert sum(by_subject.values()) == 665
    assert by_subject["语文"] == 1
    assert any(line.startswith("cnl_001\t语文\t") for line in lines)
    assert not out.read_bytes().startswith(b"\xef\xbb\xbf")
    stderr = capsys.readouterr().err
    assert "冲突" in stderr and "cnl_001" in stderr
    assert "broken.json" in stderr
    assert _seed_digest() == before
