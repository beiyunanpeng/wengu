"""P2-4 本地家长 PIN：scrypt 哈希 + HMAC 签名 cookie（不做登录/账号体系）。

设计边界（硬约束）：
- PIN 只挡"家长区"（组卷 / 审核题库 / 改配置 / 作废），孩子区免 PIN；
- **PIN 不是安全边界，只防误入**：公网暴露前必须先加真鉴权与用户隔离，或走
  Tailscale（P5-3）；本模块不引入用户体系 / 多租户 / 账号密码登录；
- PIN 只存 `user_role(role='parent').pin_hash`（scrypt + 随机盐），不存明文；
- 会话 = 轻量签名 cookie（HMAC-SHA256，TTL 12h），密钥来自
  `WENGU_SESSION_SECRET`；缺省时首启生成随机值写入本地文件（试用够用，
  多实例/公网部署必须显式配置）；
- 解锁失败按来源内存限流：连续错 ≥5 次锁 60s（重启清零可接受）。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.users import UserRole

logger = logging.getLogger(__name__)

PARENT_ROLE = "parent"
COOKIE_NAME = "wengu_parent"
TOKEN_VERSION = "v1"
COOKIE_TTL = timedelta(hours=12)

MAX_FAILURES = 5
LOCK_SECONDS = 60.0

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

MIN_DIGIT_PIN = 4
MAX_DIGIT_PIN = 8
MIN_FREE_PIN = 6
MAX_FREE_PIN = 20


class PinValidationError(ValueError):
    """PIN 格式不合法（不记录 PIN 内容本身）。"""


class PinAlreadySet(Exception):
    """已设置 PIN；修改前必须先解锁家长区。"""


def validate_pin(pin: str) -> None:
    """4–8 位数字，或 6–20 位任意非空白字符。"""

    if not isinstance(pin, str):
        raise PinValidationError("PIN 必须是字符串")
    if not pin or pin != pin.strip() or any(ord(ch) < 32 for ch in pin):
        raise PinValidationError("PIN 不能包含空白或控制字符")
    if pin.isdigit() and MIN_DIGIT_PIN <= len(pin) <= MAX_DIGIT_PIN:
        return
    if MIN_FREE_PIN <= len(pin) <= MAX_FREE_PIN:
        return
    raise PinValidationError("PIN 需为 4–8 位数字，或 6–20 位任意字符")


def hash_pin(pin: str) -> str:
    """`scrypt$N$r$p$salt$hash`；参数随哈希保存，便于日后调参而不破坏旧值。"""

    validate_pin(pin)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_pin_hash(stored: str | None, pin: str) -> bool:
    if not stored or not isinstance(pin, str):
        return False
    try:
        scheme, n_raw, r_raw, p_raw, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            pin.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_raw),
            r=int(r_raw),
            p=int(p_raw),
            dklen=len(expected),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


async def _parent_row(session: AsyncSession) -> UserRole | None:
    return await session.get(UserRole, PARENT_ROLE)


async def pin_is_set(session: AsyncSession) -> bool:
    row = await _parent_row(session)
    return bool(row and row.pin_hash)


async def set_pin(
    session: AsyncSession,
    pin: str,
    *,
    actor: str = "parent",
    replace: bool = False,
    now: datetime | None = None,
) -> UserRole:
    """写入 scrypt 哈希；已设置过且 `replace=False` 时抛 `PinAlreadySet`。"""

    if actor != PARENT_ROLE:
        raise PinValidationError("只有家长角色可以设置 PIN")
    validate_pin(pin)
    moment = now or datetime.now(UTC)
    row = await _parent_row(session)
    if row is not None and row.pin_hash and not replace:
        raise PinAlreadySet("家长 PIN 已设置：请先解锁家长区再修改")
    if row is None:
        row = UserRole(role=PARENT_ROLE, pin_hash=None, created_at=moment)
        session.add(row)
    row.pin_hash = hash_pin(pin)
    row.updated_at = moment
    await session.flush()
    return row


async def verify_pin(session: AsyncSession, pin: str) -> bool:
    row = await _parent_row(session)
    if row is None or not row.pin_hash:
        return False
    return verify_pin_hash(row.pin_hash, pin)


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: float = 0.0


_ATTEMPTS: dict[str, _Attempts] = {}


def is_locked(source: str, *, now: float | None = None) -> bool:
    entry = _ATTEMPTS.get(source)
    if entry is None:
        return False
    return entry.locked_until > (time.monotonic() if now is None else now)


def register_failure(source: str, *, now: float | None = None) -> bool:
    """累计一次失败；返回 True 表示本次触发锁定（调用方应回 429）。"""

    moment = time.monotonic() if now is None else now
    entry = _ATTEMPTS.setdefault(source, _Attempts())
    if entry.locked_until > moment:
        return True
    entry.failures += 1
    if entry.failures >= MAX_FAILURES:
        entry.failures = 0
        entry.locked_until = moment + LOCK_SECONDS
        return True
    return False


def reset_failures(source: str) -> None:
    _ATTEMPTS.pop(source, None)


def reset_all() -> None:
    """测试用：清空内存限流状态（生产单进程无需调用）。"""

    _ATTEMPTS.clear()


def session_secret() -> bytes:
    """优先级：环境变量 → `.env`/Settings → 本地密钥文件（首启生成）。"""

    from_env = os.environ.get("WENGU_SESSION_SECRET", "").strip()
    if from_env:
        return from_env.encode("utf-8")
    settings = get_settings()
    configured = (settings.session_secret or "").strip()
    if configured:
        return configured.encode("utf-8")
    path = settings.data_dir / ".session_secret"
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing.encode("utf-8")
    value = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    with suppress(OSError):
        os.chmod(path, 0o600)
    logger.warning(
        "WENGU_SESSION_SECRET 未设置：已生成随机密钥写入 %s（试用够用；"
        "多实例或公网部署必须显式配置）",
        path,
    )
    return value.encode("utf-8")


def issue_token(*, now: datetime | None = None, ttl: timedelta = COOKIE_TTL) -> str:
    moment = now or datetime.now(UTC)
    expires = int(moment.timestamp() + ttl.total_seconds())
    payload = f"{TOKEN_VERSION}.{expires}"
    signature = hmac.new(
        session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}.{signature}"


def token_valid(token: str | None, *, now: datetime | None = None) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        return False
    payload = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(
        session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, parts[2]):
        return False
    try:
        expires = int(parts[1])
    except ValueError:
        return False
    moment = now or datetime.now(UTC)
    return expires > moment.timestamp()
