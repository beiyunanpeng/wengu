"""GET /api/seed/summary 只读验证接口（unaudited/blind_verified 透传路径）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.seed.loader import load_seed
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


async def _load(tmp_path) -> tuple[Path, Path]:
    """tmp db（迁移到 head）+ tmp seeds 目录（3 知识点 / 2 边 / 1 教材包）。"""

    seeds_dir = tmp_path / "seeds"
    (seeds_dir / "data").mkdir(parents=True)
    (seeds_dir / "data" / "topics.json").write_text(
        json.dumps(
            [
                {"id": "cnm_001", "subject": "数学", "name": "有理数", "unaudited": True,
                 "blind_verified": True},
                {"id": "cnm_002", "subject": "数学", "name": "整式", "unaudited": True,
                 "blind_verified": True},
                {"id": "cne_j001", "subject": "英语", "name": "单词重音", "unaudited": True,
                 "blind_verified": False},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (seeds_dir / "data" / "dependencies.json").write_text(
        json.dumps(
            [{"topic_id": "cne_j001", "prerequisite_id": "cnm_001", "strength": "hard"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (seeds_dir / "mappings").mkdir()
    (seeds_dir / "mappings" / "hujiao_math.json").write_text(
        json.dumps({"edition": "hujiao_math", "label": "沪教版数学", "status": "draft",
                    "entries": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    db_path = tmp_path / "api.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")

    engine = create_sqlite_engine(db_path)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await load_seed(session, seeds_dir)
    await engine.dispose()
    return db_path, seeds_dir


@pytest.mark.integration
async def test_seed_summary_reflects_loaded_flags(tmp_path, monkeypatch) -> None:
    db_path, seeds_dir = await _load(tmp_path)
    engine = create_sqlite_engine(db_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def override_session():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(
        "app.api.seed.get_settings", lambda: SimpleNamespace(seeds_dir=seeds_dir)
    )
    application.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/seed/summary")
    finally:
        await engine.dispose()
        application.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["topics_total"] == 3
    assert body["edges_total"] == 1
    # 同科 >1 行：能抓住 Boolean sum 被结果处理器吞成 True/False 的回归
    assert body["subjects"]["数学"] == {"topics": 2, "unaudited": 2, "blind_verified": 2}
    assert body["subjects"]["英语"] == {"topics": 1, "unaudited": 1, "blind_verified": 0}
    assert body["mappings"] == [
        {"edition": "hujiao_math", "label": "沪教版数学", "status": "draft", "entry_count": 0}
    ]


@pytest.mark.integration
async def test_seed_summary_empty_seed(tmp_path, monkeypatch) -> None:
    """空 seed 起步：全零，不报错。"""

    seeds_dir = tmp_path / "empty-seeds"
    (seeds_dir / "data").mkdir(parents=True)
    (seeds_dir / "data" / "topics.json").write_text("[]", encoding="utf-8")
    (seeds_dir / "data" / "dependencies.json").write_text("[]", encoding="utf-8")

    db_path = tmp_path / "empty.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")

    engine = create_sqlite_engine(db_path)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def override_session():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(
        "app.api.seed.get_settings", lambda: SimpleNamespace(seeds_dir=seeds_dir)
    )
    application.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/seed/summary")
    finally:
        await engine.dispose()
        application.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "topics_total": 0,
        "edges_total": 0,
        "subjects": {},
        "mappings": [],
    }
