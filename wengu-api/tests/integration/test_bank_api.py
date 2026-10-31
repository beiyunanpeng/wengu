"""P3-1 家长录题通道集成测试：channel 分派、sha256 去重、审核闸门、家长权限。

DoD（TICKETS P3-1）：
1. `agent_transcribe_v1` → ingestion_drafts，`agent_bank_transcribe_v1` → bank_drafts，
   不串表；同报文重投命中 sha256 去重。
2. approve 闸门：缺 answer / verify 非法（import、赋值、属性访问）/ choice answer
   不在选项 / topic_id 不存在 / 纯数值矛盾 一律拒绝入库。
3. 审核面全部 require_parent，未解锁 403；孩子区 HTTP 导入仍拒绝录题通道。
4. 入库题固定 unaudited=true / blind_verified=false，不写 seed JSON。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    BankDraft,
    ImportBatch,
    IngestionDraft,
    KnowledgeSeed,
    ProblemBankItem,
)
from app.services.inbox import PROCESSED_DIR, process_inbox_once
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"

TRANSCRIBE_PAYLOAD = {
    "channel": "agent_transcribe_v1",
    "items": [
        {
            "subject": "数学",
            "problem_text": "计算 (-3)+5",
            "student_answer": "-8",
            "standard_answer": "2",
            "source_ref": "卷子 P12",
        }
    ],
}


def _bank_item(**overrides: object) -> dict:
    item: dict[str, object] = {
        "subject": "数学",
        "topic_id": "cnm_001",
        "type": "numeric",
        "prompt": "计算 3×4",
        "answer": "12",
        "verify": "3*4",
        "source_ref": "校本 P12",
    }
    item.update(overrides)
    return item


def _bank_payload(items: list[dict]) -> dict:
    return {"channel": "agent_bank_transcribe_v1", "items": items}


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "bank-api.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_topics(factory: async_sessionmaker) -> None:
    async with factory() as session:
        session.add_all(
            [
                KnowledgeSeed(
                    id="cnm_001",
                    subject="数学",
                    name="有理数运算",
                    unaudited=True,
                    blind_verified=False,
                ),
                KnowledgeSeed(
                    id="cnm_002",
                    subject="英语",
                    name="词汇",
                    unaudited=True,
                    blind_verified=False,
                ),
            ]
        )
        await session.commit()


async def _count(
    factory: async_sessionmaker, model: type
) -> int:
    async with factory() as session:
        return int(
            await session.scalar(select(func.count()).select_from(model))
        )


async def _drafts(factory: async_sessionmaker) -> list[BankDraft]:
    async with factory() as session:
        return list(
            (
                await session.execute(select(BankDraft).order_by(BankDraft.seq))
            ).scalars()
        )


def _drop(inbox: Path, name: str, payload: dict) -> Path:
    path = inbox / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    directory = tmp_path / "inbox"
    directory.mkdir()
    return directory


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


async def _unlock(client: AsyncClient) -> None:
    status = await client.get("/api/session/status")
    if status.json()["pin_set"]:
        response = await client.post("/api/session/unlock", json={"pin": PIN})
    else:
        response = await client.post("/api/session/pin/set", json={"pin": PIN})
    assert response.status_code == 200, response.text


@pytest.mark.integration
async def test_channels_dispatch_to_separate_tables_and_dedupe(
    tmp_path: Path, inbox: Path
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    _drop(inbox, "transcribe.json", TRANSCRIBE_PAYLOAD)
    bank_payload = _bank_payload([_bank_item()])
    _drop(inbox, "bank.json", bank_payload)

    async with factory() as session:
        reports = await process_inbox_once(session, inbox)

    assert [report.outcome for report in reports] == ["imported", "imported"]
    async with factory() as session:
        batches = {
            batch.channel: batch
            for batch in (await session.execute(select(ImportBatch))).scalars()
        }
        ingestion = (
            (await session.execute(select(IngestionDraft))).scalars().all()
        )
        bank = (await session.execute(select(BankDraft))).scalars().all()
    assert set(batches) == {"agent_transcribe_v1", "agent_bank_transcribe_v1"}
    assert len(ingestion) == 1 and len(bank) == 1
    assert bank[0].import_batch_id == batches["agent_bank_transcribe_v1"].id
    assert bank[0].status == "draft"
    assert json.loads(bank[0].normalized_json)["topic_id"] == "cnm_001"

    # 同报文换名重投：sha256 去重，不新增 batch/draft
    _drop(inbox, "bank-again.json", bank_payload)
    async with factory() as session:
        second = await process_inbox_once(session, inbox)
    assert second[0].outcome == "duplicate"
    assert second[0].batch_id == batches["agent_bank_transcribe_v1"].id
    assert await _count(factory, BankDraft) == 1
    assert await _count(factory, ImportBatch) == 2
    assert (inbox / PROCESSED_DIR / "bank-again.json").exists()

    # 孩子区 HTTP 导入仍拒绝录题通道，不产生草稿
    async with _client(factory) as client:
        rejected = await client.post("/api/imports", json=bank_payload)
    assert rejected.status_code == 422
    assert "监听目录" in rejected.text
    assert await _count(factory, BankDraft) == 1


@pytest.mark.integration
async def test_approve_gates_verify_sandbox_and_insert_flags(
    tmp_path: Path, inbox: Path
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    items = [
        _bank_item(prompt="计算 1+1", answer="", verify="1+1"),
        _bank_item(prompt="计算 2+3", verify="__import__('os')"),
        _bank_item(prompt="计算 2+3", verify="x = 1"),
        _bank_item(prompt="计算 2+3", verify="(1).__class__"),
        _bank_item(prompt="计算 2+2", answer="5", verify="2+2"),
        _bank_item(prompt="计算 3×4", answer="12", verify="3*4"),
        _bank_item(prompt="计算 5+6", answer="", verify=""),
    ]
    _drop(inbox, "gates.json", _bank_payload(items))
    async with factory() as session:
        reports = await process_inbox_once(session, inbox)
    assert reports[0].outcome == "imported"
    drafts = await _drafts(factory)
    assert len(drafts) == len(items)

    async with _client(factory) as client:
        await _unlock(client)

        missing = await client.post(
            f"/api/bank/drafts/{drafts[0].id}/approve", json={}
        )
        assert missing.status_code == 422
        assert missing.json()["detail"]["code"] == "missing_fields"
        assert missing.json()["detail"]["errors"][0]["field"] == "answer"

        filled = await client.post(
            f"/api/bank/drafts/{drafts[0].id}/approve", json={"answer": "2"}
        )
        assert filled.status_code == 200, filled.text
        assert filled.json()["verify_status"] == "verified"

        for draft in drafts[1:4]:
            blocked = await client.post(
                f"/api/bank/drafts/{draft.id}/approve", json={"answer": "5"}
            )
            assert blocked.status_code == 422, blocked.text
            assert blocked.json()["detail"]["code"].startswith("verify_error:")

        mismatch = await client.post(
            f"/api/bank/drafts/{drafts[4].id}/approve", json={}
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["detail"]["code"] == "verify_mismatch"

        verified = await client.post(
            f"/api/bank/drafts/{drafts[5].id}/approve", json={}
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["verify_status"] == "verified"

        unverifiable = await client.post(
            f"/api/bank/drafts/{drafts[6].id}/approve", json={"answer": "11"}
        )
        assert unverifiable.status_code == 200, unverifiable.text
        body = unverifiable.json()
        assert body["verify_status"] == "unverifiable"
        assert body["status"] == "approved"

        again = await client.post(
            f"/api/bank/drafts/{drafts[6].id}/approve", json={}
        )
        assert again.status_code == 409

        rejected = await client.post(f"/api/bank/drafts/{drafts[1].id}/reject")
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        after_reject = await client.post(
            f"/api/bank/drafts/{drafts[1].id}/approve", json={}
        )
        assert after_reject.status_code == 409

        listed = await client.get("/api/bank/drafts", params={"status": "all"})
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["total"] == len(items)
        first = next(item for item in payload["items"] if item["id"] == drafts[5].id)
        assert first["topic_name"] == "有理数运算"
        assert first["status"] == "approved"

    assert await _count(factory, ProblemBankItem) == 3
    async with factory() as session:
        rows = (
            await session.execute(select(ProblemBankItem).order_by(ProblemBankItem.id))
        ).scalars().all()
        first_row = rows[0]
        assert first_row.external_id == f"bank_draft_{drafts[0].id}"
        assert first_row.source == "agent_bank"
        assert first_row.topic_id == "cnm_001"
        assert first_row.question_type == "numeric"
        assert first_row.unaudited is True
        assert first_row.blind_verified is False
        assert first_row.verify_status == "verified"
        assert all(row.verify_status in {"verified", "unverifiable"} for row in rows)
        assert {row.answer for row in rows} == {"2", "12", "11"}


@pytest.mark.integration
async def test_unknown_topic_choice_key_and_manual_entry(
    tmp_path: Path, inbox: Path
) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)

    bad_choice = _bank_item(
        type="choice",
        prompt="1+1 等于？",
        answer="C",
        verify="",
        choices=[{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
    )
    _drop(
        inbox,
        "choice.json",
        _bank_payload(
            [
                _bank_item(topic_id="cnm_404", prompt="未知考点的题"),
                bad_choice,
                _bank_item(prompt="合法题", answer="12", verify="3*4"),
            ]
        ),
    )
    async with factory() as session:
        reports = await process_inbox_once(session, inbox)
    assert reports[0].outcome == "partial"
    assert reports[0].accepted_count == 1
    assert reports[0].error_count == 2
    drafts = await _drafts(factory)
    assert len(drafts) == 1
    assert json.loads(drafts[0].normalized_json)["prompt"] == "合法题"

    async with _client(factory) as client:
        await _unlock(client)

        manual_choice = await client.post(
            "/api/bank/items",
            json={
                "topic_id": "cnm_001",
                "type": "choice",
                "prompt": "1+1 等于？",
                "answer": "C",
                "choices": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
            },
        )
        assert manual_choice.status_code == 422
        assert manual_choice.json()["detail"]["code"] == "normalize_failed"
        assert any(
            "answer_not_in_choices" in error["reason"]
            for error in manual_choice.json()["detail"]["errors"]
        )

        manual_unknown = await client.post(
            "/api/bank/items",
            json={
                "topic_id": "cnm_404",
                "prompt": "未知考点",
                "answer": "1",
            },
        )
        assert manual_unknown.status_code == 422
        assert any(
            "unknown_topic" in error["reason"]
            for error in manual_unknown.json()["detail"]["errors"]
        )

        manual_missing_answer = await client.post(
            "/api/bank/items",
            json={"topic_id": "cnm_001", "prompt": "没有答案的题"},
        )
        assert manual_missing_answer.status_code == 422
        assert manual_missing_answer.json()["detail"]["code"] == "missing_fields"

        manual_bad_verify = await client.post(
            "/api/bank/items",
            json={
                "topic_id": "cnm_001",
                "prompt": "计算 2+2",
                "answer": "4",
                "verify": "__import__('os')",
            },
        )
        assert manual_bad_verify.status_code == 422
        assert manual_bad_verify.json()["detail"]["code"].startswith("verify_error:")

        manual_ok = await client.post(
            "/api/bank/items",
            json={
                "topic_id": "cnm_001",
                "type": "numeric",
                "prompt": "计算 4×5",
                "answer": "20",
                "verify": "4*5",
                "difficulty": "easy",
            },
        )
        assert manual_ok.status_code == 201, manual_ok.text
        created = manual_ok.json()
        assert created["verify_status"] == "verified"
        assert created["external_id"].startswith("manual_")

        # 录题草稿的考点被删后，审核闸门必须重新校验 topic 存在性
        async with factory() as session:
            seed = await session.get(KnowledgeSeed, "cnm_002")
            assert seed is not None
            await session.delete(seed)
            await session.commit()
        orphan = await client.post(
            "/api/bank/items",
            json={
                "topic_id": "cnm_002",
                "prompt": "考点已删除",
                "answer": "1",
            },
        )
        assert orphan.status_code == 422
        approved_orphan = await client.post(
            f"/api/bank/drafts/{drafts[0].id}/approve", json={}
        )
        # cnm_001 仍存在，这题应正常通过
        assert approved_orphan.status_code == 200, approved_orphan.text

    async with factory() as session:
        rows = (
            await session.execute(
                select(ProblemBankItem).where(
                    ProblemBankItem.source == "parent_manual"
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].answer == "20"
        assert rows[0].topic_id == "cnm_001"
        assert rows[0].unaudited is True
        assert rows[0].blind_verified is False


@pytest.mark.integration
async def test_bank_surface_requires_parent(tmp_path: Path, inbox: Path) -> None:
    factory = _migrated(tmp_path)
    await _seed_topics(factory)
    _drop(inbox, "one.json", _bank_payload([_bank_item()]))
    async with factory() as session:
        await process_inbox_once(session, inbox)
    draft = (await _drafts(factory))[0]

    async with _client(factory) as client:
        locked = await client.get("/api/bank/drafts")
        assert locked.status_code == 403
        approve = await client.post(
            f"/api/bank/drafts/{draft.id}/approve", json={"answer": "12"}
        )
        reject = await client.post(f"/api/bank/drafts/{draft.id}/reject")
        manual = await client.post(
            "/api/bank/items",
            json={
                "topic_id": "cnm_001",
                "prompt": "计算 1+1",
                "answer": "2",
            },
        )
        assert [approve.status_code, reject.status_code, manual.status_code] == [
            403,
            403,
            403,
        ]

        await _unlock(client)
        assert (await client.get("/api/bank/drafts")).status_code == 200
    assert await _count(factory, ProblemBankItem) == 0
