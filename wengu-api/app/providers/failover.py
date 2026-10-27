"""Provider 故障转移的错误分类与聚合异常（AGENTS §4：至少两家互备）。

只按“可用性”决定是否切下一家：账户/额度/鉴权、限流、网络/5xx、配置缺失。
模型返回 200 但内容不可解析属质量问题，不切备——切了也白费钱。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.providers.http import ProviderHttpError, ProviderResponseError
from app.providers.registry import ProviderConfigError

ACCOUNT = "account"
QUOTA = "quota"
RATE_LIMIT = "rate_limit"
NETWORK = "network"
CONFIG = "config"
QUALITY = "quality"
UNKNOWN = "unknown"

_TRANSFERABLE = frozenset({ACCOUNT, QUOTA, RATE_LIMIT, NETWORK, CONFIG})
_AGGREGATE_PRIORITY = (ACCOUNT, QUOTA, CONFIG, RATE_LIMIT, NETWORK, UNKNOWN, QUALITY)


def classify_provider_error(exc: BaseException) -> str:
    if isinstance(exc, ProviderHttpError):
        status = exc.status
        if status is None:
            return NETWORK
        if status in (401, 403):
            return ACCOUNT
        if status == 402:
            return QUOTA
        if status == 429:
            return RATE_LIMIT
        if status == 404:
            return CONFIG  # 模型未开通/端点不存在，属配置类
        if status in (408, 425) or 500 <= status <= 599:
            return NETWORK
        return UNKNOWN
    if isinstance(exc, ProviderResponseError):
        return QUALITY
    if isinstance(exc, ProviderConfigError):
        return CONFIG
    return UNKNOWN


def is_transferable(kind: str) -> bool:
    return kind in _TRANSFERABLE


@dataclass(frozen=True)
class ProviderAttempt:
    provider: str
    status: str
    error_kind: str | None
    latency_ms: int
    attempt_index: int


class AllProvidersFailed(RuntimeError):
    """有序列表全部尝试完仍失败；带上可查询/可呈现的尝试链。"""

    def __init__(
        self,
        task: str,
        *,
        attempts: list[ProviderAttempt],
        attempt_group: str,
    ) -> None:
        self.task = task
        self.attempts = tuple(attempts)
        self.attempt_group = attempt_group
        self.kind = next(
            (
                kind
                for kind in _AGGREGATE_PRIORITY
                if any(attempt.error_kind == kind for attempt in self.attempts)
            ),
            UNKNOWN,
        )
        detail = ", ".join(
            f"{attempt.provider}({attempt.error_kind or attempt.status})"
            for attempt in self.attempts
        )
        super().__init__(f"全部 provider 失败（{task}）: {detail}")

    @property
    def config_only(self) -> bool:
        """全部是配置缺失（无真实调用）；API 用它保留 503 语义。"""

        return bool(self.attempts) and all(
            attempt.error_kind == CONFIG for attempt in self.attempts
        )
