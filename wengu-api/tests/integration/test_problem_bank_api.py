"""P1-5 题库入库闸门：verify 必填、AST 沙箱 mismatch=0 才入库；坏项逐条拒绝。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import ProblemBankItem
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "bank.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


def _client(factory: async_sessionmaker) -> AsyncClient:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _item(external_id: str = "m-001", **overrides) -> dict:
    payload = {
        "external_id": external_id,
        "subject": "数学",
        "problem_text": "3×4=?",
        "answer": "12",
        "verify": "3*4",
    }
    payload.update(overrides)
    return payload


async def _count(factory: async_sessionmaker) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count(ProblemBankItem.id))))


@pytest.mark.integration
async def test_verified_item_is_stored_and_fetchable(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        imported = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item(acceptable=["十二"], unordered=False)]},
        )
        body = imported.json()
        fetched = await client.get(
            f"/api/problem-bank/items/{body['results'][0]['problem_bank_id']}"
        )

    assert imported.status_code == 200
    assert body["accepted_count"] == 1
    assert body["skipped_count"] == 0
    assert body["rejected_count"] == 0
    assert body["verify_pass_rate"] == 1.0
    assert body["results"][0]["status"] == "accepted"
    assert await _count(factory) == 1

    assert fetched.status_code == 200
    item = fetched.json()
    assert item["external_id"] == "m-001"
    assert item["answer"] == "12"
    assert item["acceptable_answers"] == ["十二"]
    assert item["verify"] == "3*4"
    assert item["verify_status"] == "verified"


@pytest.mark.integration
async def test_verify_mismatch_and_unsafe_expression_are_rejected(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        mismatch = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item("m-bad-answer", verify="3*5")]},
        )
        unsafe = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item("m-unsafe", verify="__import__('os')")]},
        )
        attribute = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item("m-attr", verify="(1).bit_length()")]},
        )

    for response, reason in (
        (mismatch, "verify_mismatch"),
        (unsafe, "verify_error:forbidden_name"),
        (attribute, "verify_error:forbidden_node:Attribute"),
    ):
        assert response.status_code == 422
        assert response.json()["detail"]["results"][0]["reason"] == reason
    assert await _count(factory) == 0


@pytest.mark.integration
async def test_placeholder_control_chars_and_missing_verify_are_rejected(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        placeholder = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item("m-ph", problem_text="3×〔?〕=?")]},
        )
        control = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item("m-ctrl", answer="1\x002")]},
        )
        no_verify = await client.post(
            "/api/problem-bank/import",
            json={"items": [{k: v for k, v in _item("m-no-verify").items() if k != "verify"}]},
        )
        not_dict = await client.post(
            "/api/problem-bank/import", json={"items": ["not-an-item"]}
        )

    bodies = {
        "placeholder": placeholder.json()["detail"]["results"][0]["reason"],
        "control": control.json()["detail"]["results"][0]["reason"],
        "no_verify": no_verify.json()["detail"]["results"][0]["reason"],
        "not_dict": not_dict.json()["detail"]["results"][0]["reason"],
    }
    assert bodies == {
        "placeholder": "placeholder",
        "control": "invalid_control_char",
        "no_verify": "invalid:verify",
        "not_dict": "invalid:item",
    }
    assert placeholder.status_code == 422
    assert not_dict.status_code == 422
    assert await _count(factory) == 0


@pytest.mark.integration
async def test_external_id_idempotency_and_conflict(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        first = await client.post("/api/problem-bank/import", json={"items": [_item()]})
        same = await client.post("/api/problem-bank/import", json={"items": [_item()]})
        changed = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item(answer="13", verify="3*4")]},
        )
        in_batch = await client.post(
            "/api/problem-bank/import",
            json={"items": [_item("m-batch"), _item("m-batch")]},
        )

    assert first.json()["accepted_count"] == 1
    assert same.status_code == 200
    assert same.json()["skipped_count"] == 1
    assert same.json()["results"][0]["reason"] == "duplicate"
    assert changed.status_code == 422
    assert changed.json()["detail"]["results"][0]["reason"] == "external_id_conflict"
    assert in_batch.json()["accepted_count"] == 1
    assert in_batch.json()["results"][1]["reason"] == "duplicate_in_batch"
    assert await _count(factory) == 2  # m-001 + m-batch


@pytest.mark.integration
async def test_verify_vars_are_evaluated_in_sandbox(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        good = await client.post(
            "/api/problem-bank/import",
            json={
                "items": [
                    _item(
                        "m-vars",
                        problem_text="长方形长 a 宽 3，面积多少？",
                        answer="12",
                        verify="a*3",
                        verify_vars={"a": 4},
                    )
                ]
            },
        )
        bad = await client.post(
            "/api/problem-bank/import",
            json={
                "items": [
                    _item(
                        "m-vars-bad",
                        verify="a*3",
                        verify_vars={"a": None},
                    )
                ]
            },
        )

    assert good.json()["accepted_count"] == 1
    assert bad.status_code == 422
    assert bad.json()["detail"]["results"][0]["reason"] == "verify_error:variables_bad_type"
    assert await _count(factory) == 1


@pytest.mark.integration
async def test_mixed_batch_reports_pass_rate_and_partial_import(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.post(
            "/api/problem-bank/import",
            json={
                "items": [
                    _item("m-1"),
                    _item("m-2", verify="4*3"),
                    _item("m-3", verify="3*5"),
                    _item("m-4", problem_text="3×〔?〕=?"),
                ]
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 4
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 2
    assert body["verify_pass_rate"] == pytest.approx(2 / 3)
    assert [r["status"] for r in body["results"]] == [
        "accepted",
        "accepted",
        "rejected",
        "rejected",
    ]
    assert await _count(factory) == 2  # 坏项不会连坐好项

    async with factory() as session:
        stored = (await session.scalars(select(ProblemBankItem))).all()
    assert {row.external_id for row in stored} == {"m-1", "m-2"}
    assert all(json.loads(row.acceptable_answers_json) == [] for row in stored)


@pytest.mark.integration
async def test_unknown_item_returns_404(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.get("/api/problem-bank/items/999")

    assert response.status_code == 404
