"""兜底通道集成测试：豆包 JSON 导入 → 校验/归一 → batch+草稿落库，重复导入提醒。

DoD（TICKETS P1-3）：确定性校验/归一、import_batches(sha256 去重) 重复导入提醒、
ingestion_drafts 与主通道共用草稿结构；导入全程不调模型。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import ImportBatch, IngestionDraft
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

VALID_PAYLOAD = {
    "channel": "doubao_json",
    "items": [
        {
            "subject": "数学",
            "problem_text": "计算 (-3)+5",
            "student_answer": "2",
            "source_ref": "校本练习 P12",
            "captured_at": "2026-10-24",
        },
        {
            "subject": "英语",
            "problem_text": "默写 〔?〕 apple",
            "student_answer": "",
        },
    ],
}


def _migrated(tmp_path: Path) -> tuple[Path, async_sessionmaker]:
    db_path = tmp_path / "imports.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return db_path, async_sessionmaker(engine, expire_on_commit=False)


def _make_client(factory: async_sessionmaker) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.integration
async def test_import_valid_payload_creates_batch_and_drafts(tmp_path) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(factory) as client:
        response = await client.post(
            "/api/imports", content=json.dumps(VALID_PAYLOAD, ensure_ascii=False)
        )
    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False
    assert body["status"] == "imported"
    assert body["draft_count"] == 2
    assert body["accepted_count"] == 2
    assert body["errors"] == []

    async with factory() as session:
        batch = (await session.execute(select(ImportBatch))).scalar_one()
        assert batch.id == body["batch_id"]
        assert batch.channel == "doubao_json"
        assert batch.item_count == 2
        drafts = (
            (
                await session.execute(
                    select(IngestionDraft).order_by(IngestionDraft.seq)
                )
            )
            .scalars()
            .all()
        )
        assert [d.seq for d in drafts] == [0, 1]
        assert drafts[0].has_placeholder is False
        assert drafts[1].has_placeholder is True
        assert drafts[1].is_incomplete is True
        normalized = json.loads(drafts[0].normalized_json)
        assert normalized["problem_text"] == "计算 (-3)+5"
        assert normalized["student_answer"] == "2"


@pytest.mark.integration
async def test_duplicate_import_returns_existing_batch(tmp_path) -> None:
    """同一报文重复导入（重试/重启等价）→ 原 batch + duplicate 提醒，草稿不重写。"""

    _, factory = _migrated(tmp_path)
    raw = json.dumps(VALID_PAYLOAD, ensure_ascii=False)
    async with _make_client(factory) as client:
        first = await client.post("/api/imports", content=raw)
        second = await client.post("/api/imports", content=raw)
    assert first.status_code == second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["batch_id"] == first.json()["batch_id"]
    assert second.json()["draft_count"] == 2

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(ImportBatch))
        ).scalar_one() == 1
        assert (
            await session.execute(select(func.count()).select_from(IngestionDraft))
        ).scalar_one() == 2


@pytest.mark.integration
async def test_partial_import_skips_bad_items_with_report(tmp_path) -> None:
    payload = {
        "channel": "doubao_json",
        "items": [
            {"problem_text": "好题", "student_answer": "A"},
            {"problem_text": ""},  # 必填缺失
            {"problem_text": "x" * 2001},  # 超长不静默截断
        ],
    }
    _, factory = _migrated(tmp_path)
    async with _make_client(factory) as client:
        response = await client.post(
            "/api/imports", content=json.dumps(payload, ensure_ascii=False)
        )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "partial"
    assert body["accepted_count"] == 1
    assert {(e["index"], e["field"]) for e in body["errors"]} == {
        (1, "problem_text"),
        (2, "problem_text"),
    }

    async with factory() as session:
        draft = (
            await session.execute(select(IngestionDraft))
        ).scalars().one()
        assert draft.seq == 0  # 保留原始序号，错误可定位


@pytest.mark.integration
async def test_all_bad_items_rejected_without_batch(tmp_path) -> None:
    payload = {"channel": "doubao_json", "items": [{"problem_text": ""}]}
    _, factory = _migrated(tmp_path)
    async with _make_client(factory) as client:
        response = await client.post(
            "/api/imports", content=json.dumps(payload, ensure_ascii=False)
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["errors"][0]["field"] == "problem_text"

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(ImportBatch))
        ).scalar_one() == 0


@pytest.mark.integration
async def test_malformed_and_oversized_bodies(tmp_path) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(factory) as client:
        bad_json = await client.post("/api/imports", content="{not json")
        wrong_channel = await client.post(
            "/api/imports",
            content=json.dumps({"channel": "x", "items": [{"problem_text": "a"}]}),
        )
        items_not_list = await client.post(
            "/api/imports",
            content=json.dumps({"channel": "doubao_json", "items": "oops"}),
        )
    assert bad_json.status_code == 400
    assert wrong_channel.status_code == 422
    assert items_not_list.status_code == 422


@pytest.mark.integration
async def test_oversized_body_rejected(tmp_path) -> None:
    from app.services.ingestion import MAX_BATCH_BODY_BYTES

    _, factory = _migrated(tmp_path)
    big = "x" * (MAX_BATCH_BODY_BYTES + 1)
    async with _make_client(factory) as client:
        response = await client.post("/api/imports", content=big)
    assert response.status_code == 413


@pytest.mark.integration
async def test_get_batch_and_drafts_endpoints(tmp_path) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(factory) as client:
        created = (
            await client.post(
                "/api/imports",
                content=json.dumps(VALID_PAYLOAD, ensure_ascii=False),
            )
        ).json()
        batch = await client.get(f"/api/imports/{created['batch_id']}")
        drafts = await client.get(f"/api/imports/{created['batch_id']}/drafts")
        missing_batch = await client.get("/api/imports/999")
        missing_drafts = await client.get("/api/imports/999/drafts")

    assert batch.status_code == 200
    assert batch.json()["channel"] == "doubao_json"
    assert batch.json()["item_count"] == 2
    assert drafts.status_code == 200
    body = drafts.json()
    assert body["total"] == 2
    first = body["drafts"][0]
    assert first["seq"] == 0
    assert first["normalized"]["subject"] == "数学"
    assert first["status"] == "draft"
    assert missing_batch.status_code == 404
    assert missing_drafts.status_code == 404


@pytest.mark.integration
async def test_inbox_info_is_read_only_and_not_shadowed_by_batch_route(tmp_path) -> None:
    _, factory = _migrated(tmp_path)
    async with _make_client(factory) as client:
        response = await client.get("/api/imports/inbox")

    assert response.status_code == 200
    body = response.json()
    assert body["path"]
    assert "agent_transcribe_v1" in body["channels"]
    assert body["max_items"] == 500
    assert body["max_body_bytes"] == 5 * 1024 * 1024
