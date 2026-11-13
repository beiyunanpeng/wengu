"""P4-4：seed 装载结果的进程内状态。lifespan 写、公开端点 /api/setup/status 读。

失败只暴露错误类别（loader.classify_seed_error），绝不含题目/路径/堆栈/PII；
服务不因空 seed 崩溃，但界面据此显式降级。不写库、不存易变字段。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedStatus:
    loaded: bool
    error: str | None


_status = SeedStatus(loaded=False, error=None)


def set_seed_status(*, loaded: bool, error: str | None) -> None:
    global _status
    _status = SeedStatus(loaded=loaded, error=error)


def get_seed_status() -> SeedStatus:
    return _status


def reset_seed_status() -> None:
    """测试隔离：回到"尚未装载"的默认态，避免跨测泄漏。"""

    global _status
    _status = SeedStatus(loaded=False, error=None)
