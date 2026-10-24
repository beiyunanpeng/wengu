"""P1-1b 运行时装载器：幂等、标签、先修边全量同步、教材包校验。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine
from app.models import KnowledgeSeed, LearningEvent, PrerequisiteEdge
from app.seed.loader import SeedFormatError, load_mappings, load_seed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

TOPICS = [
    {"id": "cnm_001", "subject": "数学", "name": "有理数", "domain": "数与代数",
     "grade": 7, "unaudited": True, "blind_verified": True},
    {"id": "cne_j001", "subject": "英语", "name": "单词重音", "domain": "语音",
     "grade": 8, "unaudited": True, "blind_verified": False},
    {"id": "cnp_001", "subject": "物理", "name": "机械运动", "domain": "运动和相互作用",
     "grade": 9, "unaudited": True, "blind_verified": False},
]

EDGES = [
    {"topic_id": "cnm_001", "prerequisite_id": "cnp_001", "strength": "hard"},  # 方向反过来便于区分
    {"topic_id": "cne_j001", "prerequisite_id": "cnm_001", "strength": "soft"},
    {"topic_id": "cnm_ghost", "prerequisite_id": "cnm_001", "strength": "soft"},  # 端点缺失 → 跳过
]

GOOD_MAPPING = {
    "edition": "hujiao_math",
    "label": "沪教版数学",
    "status": "draft",
    "entries": [{"topicId": "cnm_001", "grade": 7, "term": "上", "unit": "u", "chapter": "c"}],
}


def _write_seeds(root: Path, topics=TOPICS, edges=EDGES, mapping: dict | None = GOOD_MAPPING) -> Path:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "topics.json").write_text(
        json.dumps(topics, ensure_ascii=False), encoding="utf-8"
    )
    (root / "data" / "dependencies.json").write_text(
        json.dumps(edges, ensure_ascii=False), encoding="utf-8"
    )
    if mapping is not None:
        (root / "mappings").mkdir(exist_ok=True)
        (root / "mappings" / f"{mapping['edition']}.json").write_text(
            json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
        )
    return root


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "seed.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.integration
async def test_load_seed_idempotent_and_tags(session_factory, tmp_path) -> None:
    seeds_dir = _write_seeds(tmp_path / "seeds")

    async with session_factory() as session:
        index = await load_seed(session, seeds_dir)
        await load_seed(session, seeds_dir)  # 重复装载：行数不变
        await load_seed(session, seeds_dir)

    async with session_factory() as session:
        rows = (await session.execute(select(KnowledgeSeed))).scalars().all()
        assert len(rows) == 3
        by_id = {r.id: r for r in rows}
        assert by_id["cnm_001"].blind_verified is True
        assert by_id["cne_j001"].blind_verified is False
        assert by_id["cnp_001"].blind_verified is False
        assert all(r.unaudited is True for r in rows)
        assert by_id["cnm_001"].grade == "7"  # 文本列
        assert by_id["cnm_001"].domain == "数与代数"

        edges = (await session.execute(select(PrerequisiteEdge))).scalars().all()
        assert len(edges) == 2  # 幽灵端点边被跳过
        assert {(e.parent_id, e.child_id) for e in edges} == {
            ("cnp_001", "cnm_001"),
            ("cnm_001", "cne_j001"),
        }

    # 内存索引：先修邻接表
    assert index.prerequisites_of("cnm_001") == ["cnp_001"]
    assert index.children_of("cnm_001") == ["cne_j001"]
    assert index.mappings[0]["edition"] == "hujiao_math"
    assert index.mappings[0]["status"] == "draft"


@pytest.mark.integration
async def test_edges_full_sync_and_topic_upsert(session_factory, tmp_path) -> None:
    seeds_dir = _write_seeds(tmp_path / "seeds")
    async with session_factory() as session:
        await load_seed(session, seeds_dir)

    # 改真源：更新名称、删掉一条边
    modified_topics = [{**t, "name": "有理数（改）" if t["id"] == "cnm_001" else t["name"]}
                       for t in TOPICS]
    _write_seeds(seeds_dir, topics=modified_topics, edges=EDGES[:1])

    async with session_factory() as session:
        await load_seed(session, seeds_dir)

    async with session_factory() as session:
        topics = (await session.execute(select(KnowledgeSeed))).scalars().all()
        assert len(topics) == 3  # upsert 不新增
        assert next(t for t in topics if t.id == "cnm_001").name == "有理数（改）"
        edges = (await session.execute(select(PrerequisiteEdge))).scalars().all()
        assert len(edges) == 1  # 全量同步：消失的边被删除


@pytest.mark.integration
async def test_empty_seed_start(session_factory, tmp_path) -> None:
    """化学/语文空 seed 起步：缺文件容忍，返回空索引。"""

    (tmp_path / "seeds").mkdir()
    async with session_factory() as session:
        index = await load_seed(session, tmp_path / "seeds")
    assert index.topics == {} and index.mappings == []


@pytest.mark.integration
async def test_invalid_topic_fails_fast(session_factory, tmp_path) -> None:
    seeds_dir = _write_seeds(tmp_path / "seeds", topics=[{"id": "cnm_x"}])  # 缺 subject/name
    async with session_factory() as session:
        with pytest.raises(SeedFormatError):
            await load_seed(session, seeds_dir)


@pytest.mark.integration
async def test_bad_mapping_status_fails_fast(session_factory, tmp_path) -> None:
    with pytest.raises(SeedFormatError, match="status"):
        load_mappings(_write_seeds(tmp_path / "seeds", mapping={
            **GOOD_MAPPING, "status": "bogus",
        }) / "mappings")


@pytest.mark.integration
async def test_seed_rows_survive_events_empty_check(session_factory, tmp_path) -> None:
    """装载不触碰 learning_events：seed 重跑与事实源互不干扰。"""

    seeds_dir = _write_seeds(tmp_path / "seeds")
    async with session_factory() as session:
        await load_seed(session, seeds_dir)
    async with session_factory() as session:
        count = (await session.execute(
            select(func.count()).select_from(LearningEvent)
        )).scalar_one()
        assert count == 0
