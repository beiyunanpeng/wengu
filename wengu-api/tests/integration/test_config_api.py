"""P5-1a 家长运行时配置端点：路径解析、热加载、校验、权限、并发与备份。

钉死的口径：
- `WENGU_APP_CONFIG` → `<data_dir>/app-config.json` → 仓库根 `config/`（只读）；
- PUT 白名单 + 区间校验，非法 422 且不写文件；
- 未解锁 GET/PUT 全 403；
- PUT 后不重启，`/api/reviews/due` 的 `daily_limit` 立即变化；
- 备份包含 `<data>/app-config.json` 时恢复值不丢（旧包无该文件时不报错）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core import runtime_config
from app.core.config import Settings, get_settings
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.services.backup import create_backup
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"

pytestmark = pytest.mark.integration


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
            response = await client.post("/api/session/pin/set", json={"pin": PIN})
            assert response.status_code == 200, response.text
        yield client


def _use(tmp_path: Path, monkeypatch, settings: Settings) -> None:
    """让运行时读取（review/recitation）与端点看到同一份配置。"""

    monkeypatch.delenv("WENGU_APP_CONFIG", raising=False)
    monkeypatch.setattr(runtime_config, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_config, "PROJECT_ROOT", tmp_path / "repo")


async def test_put_hot_reloads_due_limit_without_restart(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use(tmp_path, monkeypatch, settings)

    async with _client(factory, settings) as client:
        initial = await client.get("/api/config")
        assert initial.status_code == 200, initial.text
        body = initial.json()
        assert body["file_source"] == "default"
        assert body["legacy"] is False
        assert body["values"] == {
            "daily_review_limit": 10,
            "daily_recitation_limit": 5,
            "exam_day_limit_factor": 1.5,
            "setup_completed": False,
        }
        assert body["sources"] == {
            "daily_review_limit": "default",
            "daily_recitation_limit": "default",
            "exam_day_limit_factor": "default",
            "setup_completed": "default",
        }
        assert Path(body["write_path"]) == Path(settings.data_dir) / "app-config.json"

        due_before = await client.get("/api/reviews/due")
        assert due_before.json()["daily_limit"] == 10

        put = await client.put(
            "/api/config",
            json={"daily_review_limit": 3, "exam_day_limit_factor": 2},
        )
        assert put.status_code == 200, put.text
        updated = put.json()
        assert updated["values"]["daily_review_limit"] == 3
        assert updated["values"]["exam_day_limit_factor"] == 2.0
        assert updated["sources"]["daily_review_limit"] == "file"
        assert updated["file_source"] == "data"

        # 不重启：同进程下一次请求立即生效
        due_after = await client.get("/api/reviews/due")
        assert due_after.json()["daily_limit"] == 3

        written = json.loads(
            (Path(settings.data_dir) / "app-config.json").read_text(encoding="utf-8")
        )
        assert written["daily_review_limit"] == 3
        assert "daily_recitation_limit" not in written, "默认值不落盘"


async def test_invalid_put_is_422_and_leaves_file_untouched(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use(tmp_path, monkeypatch, settings)
    path = Path(settings.data_dir) / "app-config.json"

    async with _client(factory, settings) as client:
        baseline = await client.put("/api/config", json={"daily_review_limit": 7})
        assert baseline.status_code == 200, baseline.text
        before = path.read_text(encoding="utf-8")

        for payload in (
            {"daily_review_limit": 0},
            {"daily_review_limit": 201},
            {"daily_review_limit": 2.5},
            {"daily_review_limit": True},
            {"daily_recitation_limit": 21},
            {"exam_day_limit_factor": 0.5},
            {"exam_day_limit_factor": 3.5},
            {"exam_day_limit_factor": True},
            {"setup_completed": "yes"},
            {"setup_completed": 1},
            {"setup_completed": 0},
            {"setup_completed": None},
            {"unknown_key": 1},
            {},
        ):
            response = await client.put("/api/config", json=payload)
            assert response.status_code == 422, (payload, response.text)
            assert path.read_text(encoding="utf-8") == before, payload


async def test_config_requires_parent(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use(tmp_path, monkeypatch, settings)

    async with _client(factory, settings, unlock=False) as client:
        assert (await client.get("/api/config")).status_code == 403
        assert (
            await client.put("/api/config", json={"daily_review_limit": 3})
        ).status_code == 403

    assert not (Path(settings.data_dir) / "app-config.json").exists()


async def test_setup_status_is_public_and_follows_completion(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use(tmp_path, monkeypatch, settings)

    async with _client(factory, settings, unlock=False) as client:
        initial = await client.get("/api/setup/status")
        assert initial.status_code == 200, initial.text
        # 该测试 app 不跑 lifespan，seed 未装载 → 默认 False（见 test_seed_status.py）
        assert initial.json() == {
            "setup_completed": False,
            "seed_loaded": False,
            "seed_error": None,
        }
        assert (
            await client.put("/api/config", json={"setup_completed": True})
        ).status_code == 403

        unlocked = await client.post("/api/session/pin/set", json={"pin": PIN})
        assert unlocked.status_code == 200, unlocked.text

        put = await client.put(
            "/api/config",
            json={"daily_review_limit": 3, "setup_completed": True},
        )
        assert put.status_code == 200, put.text
        assert put.json()["values"]["setup_completed"] is True
        assert put.json()["sources"]["setup_completed"] == "file"

        status = await client.get("/api/setup/status")
        assert status.status_code == 200, status.text
        assert status.json() == {
            "setup_completed": True,
            "seed_loaded": False,
            "seed_error": None,
        }

        due = await client.get("/api/reviews/due")
        assert due.status_code == 200, due.text
        assert due.json()["daily_limit"] == 3

    written = json.loads(
        (Path(settings.data_dir) / "app-config.json").read_text(encoding="utf-8")
    )
    assert written["setup_completed"] is True
    assert written["daily_review_limit"] == 3


async def test_legacy_repo_config_is_read_only_and_saves_to_data(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use(tmp_path, monkeypatch, settings)
    legacy = tmp_path / "repo" / "config" / "app-config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"daily_review_limit": 4, "exam_day_limit_factor": 2}),
        encoding="utf-8",
    )
    before = legacy.read_bytes()

    async with _client(factory, settings) as client:
        body = (await client.get("/api/config")).json()
        assert body["legacy"] is True
        assert body["file_source"] == "legacy"
        assert body["read_path"] == str(legacy)
        assert body["hint"] and "建议" in body["hint"]
        assert body["values"]["daily_review_limit"] == 4

        put = await client.put(
            "/api/config", json={"daily_recitation_limit": 8}
        )
        assert put.status_code == 200, put.text
        assert put.json()["legacy"] is False
        assert put.json()["values"]["daily_review_limit"] == 4

    assert legacy.read_bytes() == before, "兼容回退路径只读"
    written = json.loads(
        (Path(settings.data_dir) / "app-config.json").read_text(encoding="utf-8")
    )
    assert written == {
        "daily_review_limit": 4,
        "exam_day_limit_factor": 2,
        "daily_recitation_limit": 8,
    }


async def test_concurrent_puts_never_leave_half_written_json(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    factory = _migrated(settings)
    _use(tmp_path, monkeypatch, settings)

    async with _client(factory, settings) as client:
        responses = await asyncio.gather(
            *(
                client.put(
                    "/api/config", json={"daily_review_limit": (index % 10) + 1}
                )
                for index in range(20)
            )
        )
        assert all(response.status_code == 200 for response in responses)

    payload = json.loads(
        (Path(settings.data_dir) / "app-config.json").read_text(encoding="utf-8")
    )
    assert 1 <= payload["daily_review_limit"] <= 10


def test_backup_includes_runtime_config_and_restore_keeps_values(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path)
    _migrated(settings)
    data_dir = Path(settings.data_dir)
    (data_dir / "app-config.json").write_text(
        json.dumps({"daily_review_limit": 12, "daily_recitation_limit": 6}),
        encoding="utf-8",
    )

    result = create_backup(settings)

    with zipfile.ZipFile(result.path) as zf:
        assert "app-config.json" in zf.namelist()
        entry = next(
            item for item in result.manifest["files"] if item["path"] == "app-config.json"
        )
        assert entry["sha256"] == hashlib.sha256(zf.read("app-config.json")).hexdigest()
        restored = zf.read("app-config.json")

    restored_dir = tmp_path / "restored"
    restored_dir.mkdir()
    (restored_dir / "app-config.json").write_bytes(restored)
    restored_settings = Settings(
        data_dir=restored_dir,
        db_path=restored_dir / "wengu.db",
        seeds_dir=tmp_path / "seeds",
    )
    assert runtime_config.daily_review_limit(restored_settings) == 12
    assert runtime_config.daily_recitation_limit(restored_settings) == 6
