from __future__ import annotations

import pytest
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.integration
async def test_health_ok(tmp_path) -> None:
    engine = create_sqlite_engine(tmp_path / "health.db")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def override_session():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_session] = override_session
    try:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        await engine.dispose()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "wengu-api",
        "version": "0.0.0",
        "database": "ok",
    }


@pytest.mark.integration
async def test_health_reports_database_failure() -> None:
    application = create_app()

    async def broken_session():
        yield _BrokenSession()

    application.dependency_overrides[get_session] = broken_session

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


class _BrokenSession:
    async def execute(self, *_args, **_kwargs) -> None:
        raise OperationalError("SELECT 1", {}, Exception("database is gone"))
