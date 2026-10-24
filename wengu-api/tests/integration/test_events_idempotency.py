"""幂等写入骨架集成测试：重复事件/重复导入/版本追加，真实走迁移后的 SQLite。

验证 TICKETS P1-1 DoD：重复导入/重试/重启不产生重复错题·事件·计数。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine
from app.models import ImportBatch, LearningEvent
from app.services.events import (
    append_mistake_version,
    create_import_batch,
    record_event,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "events.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_sqlite_engine(db_path)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.integration
async def test_record_event_idempotent_by_key(session_factory) -> None:
    async with session_factory() as session, session.begin():
        event, created = await record_event(
            session, "attempt_correct", "student", idempotency_key="k1", mistake_id=7
        )
        assert created and event.id is not None

        again, created_again = await record_event(
            session, "attempt_correct", "student", idempotency_key="k1", mistake_id=7
        )
        assert not created_again
        assert again.id == event.id  # 同一条，不新增

        other, created_other = await record_event(
            session, "attempt_wrong", "student", idempotency_key="k2", mistake_id=7
        )
        assert created_other and other.id != event.id

    async with session_factory() as session:
        count = (await session.execute(
            select(func.count()).select_from(LearningEvent)
        )).scalar_one()
        assert count == 2


@pytest.mark.integration
async def test_record_event_survives_rollback_boundary(session_factory) -> None:
    """幂等冲突用 SAVEPOINT 消化：同事务内先冲突再写别的不受影响。"""

    async with session_factory() as session, session.begin():
        await record_event(session, "attempt_correct", "student", idempotency_key="dup")
        await record_event(session, "attempt_correct", "student", idempotency_key="dup")
        await record_event(session, "attempt_wrong", "student", idempotency_key="dup2")

    async with session_factory() as session:
        rows = (await session.execute(select(LearningEvent))).scalars().all()
        assert len(rows) == 2
        assert {r.idempotency_key for r in rows} == {"dup", "dup2"}


@pytest.mark.integration
async def test_create_import_batch_dedupes_by_sha256(session_factory) -> None:
    async with session_factory() as session, session.begin():
        batch, created = await create_import_batch(
            session, "doubao_json", "aa" * 32, filename="homework.json", item_count=9
        )
        assert created

        same_batch, created_again = await create_import_batch(
            session, "doubao_json", "aa" * 32, filename="homework.json", item_count=9
        )
        assert not created_again
        assert same_batch.id == batch.id

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(ImportBatch))).scalar_one()
        assert count == 1


@pytest.mark.integration
async def test_append_mistake_version_monotonic(session_factory) -> None:
    async with session_factory() as session, session.begin():
        v1 = await append_mistake_version(session, 100, problem_text="1+1=?", is_correct=None)
        v2 = await append_mistake_version(
            session, 100, problem_text="1+1=?", confirmed_error_cause="计算粗心"
        )
        other = await append_mistake_version(session, 200, problem_text="别的题")

    assert (v1.version, v2.version) == (1, 2)
    assert other.version == 1  # 不同 mistake 独立计数
    assert v2.confirmed_error_cause == "计算粗心"
    assert v2.is_correct is None  # 待确认档默认
