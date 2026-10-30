"""P2-4 PIN 策略纯函数：格式校验、scrypt 哈希、签名 token、失败限流。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.services.session import (
    LOCK_SECONDS,
    MAX_FAILURES,
    PinValidationError,
    hash_pin,
    is_locked,
    issue_token,
    register_failure,
    reset_failures,
    token_valid,
    validate_pin,
    verify_pin_hash,
)


@pytest.mark.parametrize(
    "pin",
    ["1234", "12345678", "abcdef", "abc123", "a" * 20, "123456789"],
)
def test_validate_pin_accepts_documented_shapes(pin: str) -> None:
    validate_pin(pin)


@pytest.mark.parametrize(
    "pin",
    ["", "123", "abcd", "12 34", "\t1234", "a" * 21, "１２"],
)
def test_validate_pin_rejects_short_blank_or_too_long(pin: str) -> None:
    with pytest.raises(PinValidationError):
        validate_pin(pin)


def test_scrypt_hash_is_salted_and_verifiable() -> None:
    first = hash_pin("2468")
    second = hash_pin("2468")
    assert first.startswith("scrypt$")
    assert first != second  # 随机盐
    assert "2468" not in first
    assert verify_pin_hash(first, "2468")
    assert not verify_pin_hash(first, "2469")
    assert not verify_pin_hash("plain-text", "2468")
    assert not verify_pin_hash("scrypt$bad", "2468")
    assert not verify_pin_hash(None, "2468")


def test_signed_token_expires_and_rejects_tampering() -> None:
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    token = issue_token(now=now)
    assert token_valid(token, now=now)
    assert token_valid(token, now=now + timedelta(hours=11))
    assert not token_valid(token, now=now + timedelta(hours=12, seconds=1))
    assert not token_valid(token[:-1] + ("0" if token[-1] != "0" else "1"), now=now)
    assert not token_valid("", now=now)
    assert not token_valid(None, now=now)
    assert not token_valid("v2.9999999999.deadbeef", now=now)


def test_failure_throttle_locks_for_sixty_seconds() -> None:
    reset_failures("t")
    moment = 1000.0
    for _ in range(MAX_FAILURES - 1):
        assert register_failure("t", now=moment) is False
    assert register_failure("t", now=moment) is True
    assert is_locked("t", now=moment)
    assert not is_locked("t", now=moment + LOCK_SECONDS + 1)
    # 锁定结束后重新计数，不会因旧失败立刻再锁
    assert register_failure("t", now=moment + LOCK_SECONDS + 1) is False
    reset_failures("t")
    assert not is_locked("t", now=moment)
