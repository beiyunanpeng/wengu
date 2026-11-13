"""pytest 公共设置。

- 固定会话密钥：避免测试期间在仓库 `data/` 下生成 `.session_secret`，
  且让 `services.session` 的签名 cookie 在不同测试文件间保持一致。
- 每个测试前后清空 PIN 解锁限流的内存计数（进程内状态，否则会串测）。
- 每个测试前后清空题库缓存：`get_runtime_bank` 会合并当次临时库的
  `problem_bank` 行，缓存跨测试复用会读到上一个库的家长题。
- 每个测试前后重置 seed 装载状态（进程内单例，否则会串测）。
- 每个测试前后重置 save_config 文件锁：避免模块级 asyncio.Lock 跨测试循环绑定。
- 每个测试结束前释放它创建的数据库引擎：aiosqlite 的工作线程若在
  事件循环关闭后才收尾，会抛 `RuntimeError: Event loop is closed`。
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import app.core.database as database
import app.core.runtime_config as runtime_config
import pytest
import sqlalchemy

os.environ.setdefault("WENGU_SESSION_SECRET", "pytest-session-secret")

from app.seed.state import reset_seed_status
from app.services.bank import reset_bank_cache
from app.services.session import reset_all


class _EngineRegistry:
    def __init__(self) -> None:
        self.async_engines: list[Any] = []
        self.sync_engines: list[Any] = []
        self.active = False


_REGISTRY = _EngineRegistry()
_ORIGINAL_CREATE_SQLITE_ENGINE = database.create_sqlite_engine
_ORIGINAL_CREATE_ENGINE = sqlalchemy.create_engine


def _tracking_create_sqlite_engine(*args: Any, **kwargs: Any) -> Any:
    engine = _ORIGINAL_CREATE_SQLITE_ENGINE(*args, **kwargs)
    if _REGISTRY.active:
        _REGISTRY.async_engines.append(engine)
    return engine


def _tracking_create_engine(*args: Any, **kwargs: Any) -> Any:
    engine = _ORIGINAL_CREATE_ENGINE(*args, **kwargs)
    if _REGISTRY.active:
        _REGISTRY.sync_engines.append(engine)
    return engine


# 必须在测试模块 import 之前替换，才能覆盖 `from ... import create_sqlite_engine`
# / `from sqlalchemy import create_engine` 的直接绑定（conftest 先于收集加载）。
database.create_sqlite_engine = _tracking_create_sqlite_engine
sqlalchemy.create_engine = _tracking_create_engine


def _pytest_temp_root() -> Path:
    # 与 `_pytest.tmpdir.getbasetemp()` 的默认根同算法（含 PYTEST_DEBUG_TEMPROOT 覆盖）
    temproot = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir())
    return temproot.resolve() / f"pytest-of-{getpass.getuser()}"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Windows 上先清掉死掉的 pytest-current 链接。

    `cleanup_dead_symlinks()` 在 atexit 里对每个符号链接调 `resolve().exists()`
    且不捕获异常；链接被 ACL 锁死或目标不可达时 WinError 5 会直接冒出，之后每次
    运行都刷一次 Traceback，编号目录也永远清不下去。这里在 pytest 自己的清理之前
    把死链接移除（目录符号链接必须用 `os.rmdir`）；连链接都删不掉时整根移开保留现场。
    """
    if sys.platform != "win32" or config.option.basetemp:
        return
    root = _pytest_temp_root()
    link = root / "pytest-current"
    if not link.is_symlink():
        return
    try:
        healthy = link.resolve().exists()
    except OSError:
        healthy = False  # 解析失败与 atexit 崩溃同源，走下面的修复
    if healthy:
        return
    try:
        os.rmdir(link)
    except OSError:
        stale = root.with_name(f"{root.name}.stale-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}")
        os.rename(root, stale)
        print(f"[p0-5] cannot remove {link}; moved temp root to {stale} for this run", file=sys.stderr)


@pytest.fixture(autouse=True)
async def _dispose_test_engines() -> AsyncIterator[None]:
    _REGISTRY.active = True
    try:
        yield
    finally:
        _REGISTRY.active = False
        async_engines = _REGISTRY.async_engines
        sync_engines = _REGISTRY.sync_engines
        _REGISTRY.async_engines = []
        _REGISTRY.sync_engines = []
        for engine in async_engines:
            try:
                await engine.dispose()
            except Exception as exc:  # teardown 不得改变断言结果
                print(f"[p0-4] async engine dispose failed: {exc!r}")
        for engine in sync_engines:
            try:
                engine.dispose()
            except Exception as exc:  # teardown 不得改变断言结果
                print(f"[p0-4] sync engine dispose failed: {exc!r}")


@pytest.fixture(autouse=True)
def _reset_pin_throttle() -> None:
    reset_all()
    yield
    reset_all()


@pytest.fixture(autouse=True)
def _reset_bank_cache() -> None:
    reset_bank_cache()
    yield
    reset_bank_cache()


@pytest.fixture(autouse=True)
def _reset_seed_status() -> None:
    reset_seed_status()
    yield
    reset_seed_status()


@pytest.fixture(autouse=True)
def _reset_config_file_lock() -> None:
    # to_thread 让出后并发写会把模块级锁绑到首个竞争循环，跨测试须换新锁避免串循环。
    runtime_config._FILE_LOCK = asyncio.Lock()
    yield
    runtime_config._FILE_LOCK = asyncio.Lock()
