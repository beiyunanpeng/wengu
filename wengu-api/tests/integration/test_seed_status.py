"""P4-4：seed 装载失败显式可观测（真跑 lifespan，不崩溃、不泄漏 PII）。

钉死的口径（AGENTS §5/§9 + 设计文档 §19-E）：
- 坏 seed 文件启动：服务仍能起（/health 200），/api/setup/status 返回
  seed_loaded=false + 安全错误类别（json/format/io），绝不静默降级；
- seed_error 与日志只给类别，绝不含题目文本/绝对路径/堆栈；
- 恢复正常文件后重新启动 → seed_loaded=true、seed_error=null（横幅消失）。

这些用例真跑 app.router.lifespan_context（ASGITransport 默认不触发 lifespan），
用 monkeypatch 把 main/loader/runtime_config 的绑定指向临时 settings 与已迁移库。
"""

from __future__ import annotations

import json
import logging
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
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


class _LogCollector(logging.Handler):
    """直接挂到 app.main logger 收集记录，不依赖 pytest caplog 与 async lifespan 的交互。

    text() 用 Formatter.format（含 exc_info）：若 lifespan 改用 logger.exception，
    堆栈里的题目 repr 会进文本 → PII 守卫断言变红，证伪力保留。
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def text(self) -> str:
        formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
        return "\n".join(formatter.format(record) for record in self.records)


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


def _seed_data_dir(settings: Settings) -> Path:
    data_dir = Path(settings.seeds_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "dependencies.json").write_text("[]", encoding="utf-8")
    return data_dir


@asynccontextmanager
async def _lifespan_client(
    factory: async_sessionmaker, settings: Settings, monkeypatch
) -> AsyncIterator[AsyncClient]:
    """真跑 lifespan：把各模块绑定的 get_settings/get_session_factory 指向临时库。"""

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


async def test_bad_json_seed_degrades_and_service_stays_up(
    tmp_path, monkeypatch
) -> None:
    """① topics.json 是坏 JSON → 服务仍起、seed_loaded=false、类别=json。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    data_dir = _seed_data_dir(settings)
    (data_dir / "topics.json").write_text("[{bad json", encoding="utf-8")

    async with _lifespan_client(factory, settings, monkeypatch) as client:
        status = await client.get("/api/setup/status")
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["seed_loaded"] is False
        assert body["seed_error"] == "json"

        # 服务没崩溃：健康端点照常（DB 可达），复习队列也照常可读。
        health = await client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json()["database"] == "ok"
        due = await client.get("/api/reviews/due")
        assert due.status_code == 200, due.text


async def test_bad_structure_seed_degrades_without_leaking_pii(
    tmp_path, monkeypatch
) -> None:
    """② 知识点缺 id（name 带机密标记）→ 类别=format，端点与日志都不泄漏题目/路径/堆栈。

    强证伪守卫：SeedFormatError 的消息含 raw repr（带题目标记）。若 lifespan 用
    logger.exception 记堆栈，标记会进日志文本 → 本用例变红；logger.error(类别) 不会。
    """

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    data_dir = _seed_data_dir(settings)
    marker = "机密题目文本PII_MARKER"
    (data_dir / "topics.json").write_text(
        json.dumps([{"name": marker, "subject": "数学"}], ensure_ascii=False),
        encoding="utf-8",
    )

    collector = _LogCollector()
    main_logger = logging.getLogger("app.main")
    # _migrated 跑 alembic，其 env.py 的 fileConfig(disable_existing_loggers=True)
    # 会禁用 app.main 并重置 root handlers（摘掉 caplog）。生产里 alembic 独立进程跑、
    # app 日志不受影响；这里重新启用 + 直挂 collector，才能观测 lifespan 的真实日志。
    monkeypatch.setattr(main_logger, "disabled", False)
    main_logger.addHandler(collector)
    try:
        async with _lifespan_client(factory, settings, monkeypatch) as client:
            status = await client.get("/api/setup/status")
            assert status.status_code == 200, status.text
            body = status.json()
            assert body["seed_loaded"] is False
            assert body["seed_error"] == "format"
            # 端点绝不泄漏题目文本与绝对路径。
            assert marker not in status.text
            assert str(tmp_path) not in status.text
    finally:
        main_logger.removeHandler(collector)

    # 日志只记类别：无题目 repr、无堆栈、无绝对路径。
    log_text = collector.text()
    assert "format" in log_text
    assert marker not in log_text
    assert "Traceback" not in log_text
    assert str(tmp_path) not in log_text


async def test_unreadable_seed_degrades_with_io_category(
    tmp_path, monkeypatch
) -> None:
    """③ topics.json 是目录（不可读）→ OSError → 类别=io，服务仍起。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    data_dir = _seed_data_dir(settings)
    (data_dir / "topics.json").mkdir()

    async with _lifespan_client(factory, settings, monkeypatch) as client:
        status = await client.get("/api/setup/status")
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["seed_loaded"] is False
        assert body["seed_error"] == "io"
        health = await client.get("/health")
        assert health.status_code == 200, health.text


async def test_recovery_after_fixing_seed_flips_status_to_loaded(
    tmp_path, monkeypatch
) -> None:
    """④ 坏文件启动=false → 修复后重启=true、error=null（前端横幅据此消失）。"""

    settings = _settings(tmp_path)
    factory = _migrated(settings)
    data_dir = _seed_data_dir(settings)
    topics = data_dir / "topics.json"
    topics.write_text("[{bad json", encoding="utf-8")

    async with _lifespan_client(factory, settings, monkeypatch) as client:
        bad = await client.get("/api/setup/status")
        assert bad.json()["seed_loaded"] is False
        assert bad.json()["seed_error"] == "json"

    topics.write_text(
        json.dumps(
            [{"id": "math_p44_001", "subject": "数学", "name": "P4-4 测试知识点"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async with _lifespan_client(factory, settings, monkeypatch) as client:
        good = await client.get("/api/setup/status")
        assert good.status_code == 200, good.text
        assert good.json()["seed_loaded"] is True
        assert good.json()["seed_error"] is None
