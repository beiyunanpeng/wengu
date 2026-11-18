"""P5-15 本地命名空间解耦守卫（DoD ①②③，设计文档 §19-G-3 定案一）。

① 核心可证伪夹具：上游语文点 cnc_j001（source 非 local、grade=10）必须在
   ceiling=9 下被过滤、且不进转录目录；本地 loc_ 点（grade NULL）两侧恒保留。
   变异：把 _in_junior_catalog 判据改回"按前缀" → 本守卫必须红。
② 回流守卫：本地前缀常量不得取任何 ^cn[a-z]_ 形态；学科白名单键钉死语文/化学。
③ legacy 拒绝：cnl_/cnc_ 本地文件 → 装载报错 + seed_loaded=false + 改名指引，
   不得静默装载；改名后重启恢复 loaded=true。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import app.main as main_module
import app.seed.loader as loader_module
import pytest
from alembic import command
from alembic.config import Config
from app.core import runtime_config
from app.core.config import Settings, get_settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import KnowledgeSeed
from app.seed.loader import LegacyLocalIdError, load_seed
from httpx import ASGITransport, AsyncClient
from scripts import export_topics_junior as export_script
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

UPSTREAM_CHINESE = {
    "id": "cnc_j001",
    "subject": "语文",
    "name": "上游语文点（高中册）",
    "grade": 10,
}
UPSTREAM_JUNIOR = {"id": "cnm_j001", "subject": "数学", "name": "初中数学点", "grade": 9}
LOCAL_CHINESE = {"id": "loc_001", "subject": "语文", "name": "家长自建章级点"}


def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "wengu.db",
        seeds_dir=tmp_path / "seeds",
    )


def _migrated(settings: Settings) -> async_sessionmaker:
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", f"sqlite:///{Path(settings.db_path).as_posix()}"
    )
    command.upgrade(config, "head")
    engine = create_sqlite_engine(Path(settings.db_path))
    return async_sessionmaker(engine, expire_on_commit=False)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _seed_fixture(settings: Settings, local_entries: list[dict]) -> Path:
    data_dir = Path(settings.seeds_dir) / "data"
    _write_json(data_dir / "topics.json", [UPSTREAM_CHINESE, UPSTREAM_JUNIOR])
    _write_json(data_dir / "dependencies.json", [])
    _write_json(
        Path(settings.data_dir) / "seeds_local" / "topics_语文.json", local_entries
    )
    return data_dir / "topics.json"


@asynccontextmanager
async def _lifespan_client(
    factory: async_sessionmaker, settings: Settings, monkeypatch
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(loader_module, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_config, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_config, "PROJECT_ROOT", Path(settings.data_dir).parent / "repo"
    )
    monkeypatch.delenv("WENGU_APP_CONFIG", raising=False)

    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.mark.unit
def test_local_prefix_never_in_upstream_family() -> None:
    """DoD ②：loc_ 永不落在上游 cn?_ 家族；白名单键不变；两侧常量同一把尺。"""

    for module in (loader_module, export_script):
        assert module.LOCAL_PREFIX == "loc_"
        assert re.match(r"^cn[a-z]_", module.LOCAL_PREFIX) is None
        assert tuple(module.LOCAL_SUBJECTS) == ("语文", "化学")
        assert module.LEGACY_LOCAL_PREFIXES == ("cnl_", "cnc_")
        assert not hasattr(module, "LOCAL_SUBJECT_PREFIXES")
    assert export_script.LOCAL_PREFIX == loader_module.LOCAL_PREFIX
    assert export_script.LOCAL_SUBJECTS == loader_module.LOCAL_SUBJECTS


@pytest.mark.integration
async def test_upstream_chinese_filtered_by_grade_not_prefix(
    tmp_path: Path, monkeypatch
) -> None:
    """DoD ①：cnc_j001（grade=10、source 非 local）ceiling=9 被过滤且不进转录目录；
    本地 loc_001（grade NULL）与初中上游点两侧恒保留。判据按 source，不按前缀。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    src = _seed_fixture(settings, [LOCAL_CHINESE])
    config_path = Path(settings.data_dir) / "app-config.json"
    config_path.write_text(json.dumps({"seed_grade_ceiling": 9}), encoding="utf-8")

    async with _lifespan_client(factory, settings, monkeypatch) as client:
        summary = (await client.get("/api/seed/summary")).json()
        assert summary["topics_total"] == 2
        topics = (await client.get("/api/seed/topics", params={"limit": 200})).json()
        assert {t["id"] for t in topics["items"]} == {"cnm_j001", "loc_001"}

    out = tmp_path / "topics_junior.tsv"
    export_script.export(src, out, [Path(settings.data_dir) / "seeds_local"])
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "cnc_j001" not in "\n".join(lines)
    assert any(line.startswith("loc_001\t语文\t") for line in lines)
    assert any(line.startswith("cnm_j001\t数学\t") for line in lines)


@pytest.mark.integration
@pytest.mark.parametrize("legacy_id", ["cnl_001", "cnc_001"])
async def test_legacy_local_file_rejected_and_degrades(
    tmp_path: Path, monkeypatch, legacy_id: str
) -> None:
    """DoD ③：legacy 本地文件 → 装载报错 + seed_loaded=false + 改名指引；
    绝不静默装载（库里零行）；改名 loc_001 后重启恢复。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _seed_fixture(settings, [{"id": legacy_id, "subject": "语文", "name": "旧本地点"}])

    async with factory() as session:
        with pytest.raises(LegacyLocalIdError) as excinfo:
            await load_seed(session, settings.seeds_dir, settings.data_dir)
    message = str(excinfo.value)
    assert "loc_" in message
    assert f"请将 {legacy_id} 改为 loc_001" in message

    async with factory() as session:
        rows = (await session.execute(select(KnowledgeSeed))).scalars().all()
    assert rows == []  # 失败发生在事务之前：上游点也不静默入库

    async with _lifespan_client(factory, settings, monkeypatch) as client:
        status = await client.get("/api/setup/status")
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["seed_loaded"] is False
        assert body["seed_error"] == "format"
        assert legacy_id not in status.text
        health = await client.get("/health")
        assert health.status_code == 200, health.text

    _write_json(
        Path(settings.data_dir) / "seeds_local" / "topics_语文.json", [LOCAL_CHINESE]
    )
    async with _lifespan_client(factory, settings, monkeypatch) as client:
        status = await client.get("/api/setup/status")
        assert status.json()["seed_loaded"] is True
        assert status.json()["seed_error"] is None
        topics = (await client.get("/api/seed/topics", params={"limit": 200})).json()
        assert "loc_001" in {t["id"] for t in topics["items"]}


@pytest.mark.unit
def test_export_rejects_legacy_with_rename_guidance(tmp_path: Path) -> None:
    """导出脚本侧同口径：legacy 条目拒绝 + 告警含改名指引，不静默进目录。"""

    local_dir = tmp_path / "local"
    _write_json(
        local_dir / "topics_语文.json",
        [{"id": "cnl_001", "subject": "语文", "name": "旧本地点"}],
    )
    topics, warnings = export_script.load_local_topics([local_dir], set())
    assert topics == []
    assert any("请将 cnl_001 改为 loc_001" in warning for warning in warnings)
