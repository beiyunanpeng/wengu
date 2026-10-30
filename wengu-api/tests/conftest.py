"""pytest 公共设置。

- 固定会话密钥：避免测试期间在仓库 `data/` 下生成 `.session_secret`，
  且让 `services.session` 的签名 cookie 在不同测试文件间保持一致。
- 每个测试前后清空 PIN 解锁限流的内存计数（进程内状态，否则会串测）。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("WENGU_SESSION_SECRET", "pytest-session-secret")

from app.services.session import reset_all


@pytest.fixture(autouse=True)
def _reset_pin_throttle() -> None:
    reset_all()
    yield
    reset_all()
