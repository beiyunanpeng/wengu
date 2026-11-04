"""pytest 公共设置。

- 固定会话密钥：避免测试期间在仓库 `data/` 下生成 `.session_secret`，
  且让 `services.session` 的签名 cookie 在不同测试文件间保持一致。
- 每个测试前后清空 PIN 解锁限流的内存计数（进程内状态，否则会串测）。
- 每个测试前后清空题库缓存：`get_runtime_bank` 会合并当次临时库的
  `problem_bank` 行，缓存跨测试复用会读到上一个库的家长题。
- 每个测试结束前释放它创建的数据库引擎：aiosqlite 的工作线程若在
  事件循环关闭后才收尾，会抛 `RuntimeError: Event loop is closed`。
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import app.core.database as database
import pytest
import sqlalchemy

os.environ.setdefault("WENGU_SESSION_SECRET", "pytest-session-secret")

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
