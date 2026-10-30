"""P2-4 两角色本地 PIN：scrypt 存储、签名 cookie、失败限流、孩子区不受影响。

口径（与 TICKETS P2-4 / 已定决策一致）：
- PIN 只挡家长区（作废 / 题库审核 / 手动组卷），孩子区免 PIN；
- PIN 只存 scrypt 哈希，不存明文；重复设置必须先解锁；
- 会话是 HMAC 签名 cookie（TTL 12h），无 cookie / 被篡改 / 过期一律 403；
- 连续错 5 次锁 60s（内存计数）；孩子端点全程 200；
- 全程无模型/网络调用。
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import UserRole
from app.services.session import (
    COOKIE_NAME,
    issue_token,
    token_valid,
    verify_pin_hash,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
CHILD_READS = (
    "/api/dashboard",
    "/api/reviews/due",
    "/api/mistakes",
    "/api/imports/inbox",
)
PARENT_REQUESTS = (
    ("/api/mistakes/1/void", {"actor": "parent"}),
    ("/api/problem-bank/items/1", None),
    ("/api/quizzes/paper?topic_id=cnm_001", None),
)


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "session.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(factory: async_sessionmaker) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _parent_row(factory: async_sessionmaker) -> UserRole | None:
    async with factory() as session:
        return await session.get(UserRole, "parent")


async def _call(client: AsyncClient, path: str, body: dict | None) -> int:
    if path.startswith("/api/quizzes/paper"):
        return (await client.get(path)).status_code
    if body is None:
        return (await client.get(path)).status_code
    return (await client.post(path, json=body)).status_code


def _boom(*_args, **_kwargs):
    raise AssertionError("看板/会话端点不应发起网络连接")


@pytest.mark.integration
async def test_parent_gate_before_pin_and_child_area_open(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        status = await client.get("/api/session/status")
        assert status.status_code == 200
        assert status.json() == {"pin_set": False, "parent_unlocked": False}

        for path, body in PARENT_REQUESTS:
            status_code = await _call(client, path, body)
            assert status_code == 403, (path, status_code)

        for path in CHILD_READS:
            response = await client.get(path)
            assert response.status_code == 200, (path, response.text)

        unlock = await client.post("/api/session/unlock", json={"pin": PIN})
        assert unlock.status_code == 409

    row = await _parent_row(factory)
    assert row is not None, "迁移 0014 必须补 (role='parent', pin_hash=NULL) 行"
    assert row.pin_hash is None


@pytest.mark.integration
async def test_set_pin_stores_scrypt_and_replace_needs_unlock(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        too_short = await client.post("/api/session/pin/set", json={"pin": "12"})
        assert too_short.status_code == 422

        created = await client.post("/api/session/pin/set", json={"pin": PIN})
        assert created.status_code == 200, created.text
        assert created.json() == {"pin_set": True, "parent_unlocked": True}
        assert client.cookies.get(COOKIE_NAME)

        unlocked_after_set = await client.get("/api/quizzes/paper?topic_id=cnm_001")
        assert unlocked_after_set.status_code == 200, unlocked_after_set.text

    row = await _parent_row(factory)
    assert row is not None and row.pin_hash is not None
    assert row.pin_hash.startswith("scrypt$")
    assert PIN not in row.pin_hash
    assert verify_pin_hash(row.pin_hash, PIN)
    assert not verify_pin_hash(row.pin_hash, "2469")
    first_hash = row.pin_hash

    # 新客户端没有 cookie：不能直接改 PIN
    async with _client(factory) as stranger:
        denied = await stranger.post("/api/session/pin/set", json={"pin": "1357"})
        assert denied.status_code == 403
    assert (await _parent_row(factory)).pin_hash == first_hash

    # 解锁后可重设；盐重新生成，旧 PIN 立即失效
    async with _client(factory) as parent:
        assert (
            await parent.post("/api/session/unlock", json={"pin": PIN})
        ).status_code == 200
        replaced = await parent.post(
            "/api/session/pin/set", json={"pin": "1357"}
        )
        assert replaced.status_code == 200, replaced.text
    row = await _parent_row(factory)
    assert row is not None and row.pin_hash is not None
    assert row.pin_hash != first_hash
    assert verify_pin_hash(row.pin_hash, "1357")
    assert not verify_pin_hash(row.pin_hash, PIN)


@pytest.mark.integration
async def test_unlock_cookie_tamper_expiry_and_lock(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        assert (
            await client.post("/api/session/pin/set", json={"pin": PIN})
        ).status_code == 200

        wrong = await client.post("/api/session/unlock", json={"pin": "0000"})
        assert wrong.status_code == 401

        unlocked = await client.post("/api/session/unlock", json={"pin": PIN})
        assert unlocked.status_code == 200
        assert unlocked.json() == {"pin_set": True, "parent_unlocked": True}
        assert (await client.get("/api/quizzes/paper?topic_id=cnm_001")).status_code == 200

        locked = await client.post("/api/session/lock")
        assert locked.status_code == 200
        assert locked.json() == {"pin_set": True, "parent_unlocked": False}
        assert (await client.get("/api/quizzes/paper?topic_id=cnm_001")).status_code == 403

    # 无 cookie / 篡改 cookie / 过期 token 一律不可用
    good = issue_token()
    async with _client(factory) as client:
        assert (await client.get("/api/quizzes/paper?topic_id=cnm_001")).status_code == 403

        tampered = f"{good[:-1]}{'0' if good[-1] != '0' else '1'}"
        client.cookies.set(COOKIE_NAME, tampered)
        assert (await client.get("/api/quizzes/paper?topic_id=cnm_001")).status_code == 403

    expired = issue_token(now=datetime.now(UTC) - timedelta(hours=13))
    assert token_valid(expired) is False
    assert token_valid(good) is True


@pytest.mark.integration
async def test_unlock_rate_limit_locks_after_five_failures(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        assert (
            await client.post("/api/session/pin/set", json={"pin": PIN})
        ).status_code == 200
        await client.post("/api/session/lock")

        for _ in range(4):
            attempt = await client.post("/api/session/unlock", json={"pin": "0000"})
            assert attempt.status_code == 401

        fifth = await client.post("/api/session/unlock", json={"pin": "0000"})
        assert fifth.status_code == 429
        assert fifth.headers["Retry-After"] == "60"

        # 锁定期间即使 PIN 正确也拒绝，且不签发 cookie
        blocked = await client.post("/api/session/unlock", json={"pin": PIN})
        assert blocked.status_code == 429
        assert client.cookies.get(COOKIE_NAME) is None


@pytest.mark.integration
async def test_session_endpoints_do_not_touch_network(tmp_path, monkeypatch) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        with monkeypatch.context() as guard:
            guard.setattr(socket, "create_connection", _boom)
            guard.setattr(socket.socket, "connect", _boom)
            assert (await client.get("/api/session/status")).status_code == 200
            assert (
                await client.post("/api/session/pin/set", json={"pin": PIN})
            ).status_code == 200
            assert (
                await client.post("/api/session/unlock", json={"pin": PIN})
            ).status_code == 200
            assert (
                await client.get("/api/quizzes/paper?topic_id=cnm_001")
            ).status_code == 200
            assert (await client.post("/api/session/lock")).status_code == 200
