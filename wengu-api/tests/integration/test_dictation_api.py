"""P3-4 英语默写集成测试：生成→回录→到期→毕业全链 + 迁移 0024 可逆。

钉死的口径：
- 判分主体是家长红笔，系统零判分代码：回录逐条复用 review_item()/decide()，
  同一 fixture 同一输入下批量与单条 review 端点逐项相等（复用性自证）；
- 卷面与孩子可达 API 一律不含 answer（字段与值双层断言）；
- open→recorded 单向状态机：重复提交 409 且不产生第二条事实；
- 缺失/停用条目跳过并在响应中报告；同日已有自评幂等返回既有事实；
- 错词只写 recitation_reviews / learning_events，错题四表全表内容不变；
- 生成与回录挂 require_parent（403），卷面读接口对孩子开放。
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy.exc
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine, get_session
from app.main import create_app
from app.models import (
    Attempt,
    Mistake,
    MistakeVersion,
    RecitationItem,
    RecitationReview,
    ReviewSchedule,
)
from app.models.recitation import DictationSheet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.schema import CreateTable

API_DIR = Path(__file__).resolve().parents[2]
PIN = "2468"
BASE = date(2026, 11, 1)

pytestmark = pytest.mark.integration


def _alembic_config(db_path: Path) -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def _migrated(tmp_path: Path) -> async_sessionmaker:
    db_path = tmp_path / "dictation.db"
    command.upgrade(_alembic_config(db_path), "head")
    engine = create_sqlite_engine(db_path)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _client(
    factory: async_sessionmaker, *, unlock: bool = True
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if unlock:
            response = await client.post(
                "/api/session/pin/set", json={"pin": PIN}
            )
            if response.status_code == 403:
                response = await client.post(
                    "/api/session/unlock", json={"pin": PIN}
                )
            assert response.status_code == 200, response.text
        yield client


async def _create(
    client: AsyncClient,
    prompt: str,
    *,
    subject: str = "英语",
    answer: str | None = None,
    unit: str | None = "U1",
) -> dict:
    response = await client.post(
        "/api/recitations",
        json={"subject": subject, "prompt": prompt, "answer": answer, "unit": unit},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _sheet(client: AsyncClient, item_ids: list[int], **kwargs) -> dict:
    response = await client.post(
        "/api/recitations/sheets", json={"item_ids": item_ids, **kwargs}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _record(
    client: AsyncClient,
    sheet_id: int,
    results: list[dict],
    *,
    reviewed_on: date | None = None,
) -> dict:
    payload: dict = {"results": results}
    if reviewed_on is not None:
        payload["reviewed_on"] = reviewed_on.isoformat()
    response = await client.post(
        f"/api/recitations/sheets/{sheet_id}/results", json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _review(
    client: AsyncClient, item_id: int, verdict: str, reviewed_on: date
) -> dict:
    response = await client.post(
        f"/api/recitations/{item_id}/review",
        json={"verdict": verdict, "reviewed_on": reviewed_on.isoformat()},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_no_answer(payload: dict, answer_values: list[str]) -> None:
    """字段层与值层双断言：响应任何深度都不出现 answer 键或答案值。"""

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert "answer" not in key.lower()
                walk(value)
        elif isinstance(node, list):
            for entry in node:
                walk(entry)
        elif isinstance(node, str):
            for value in answer_values:
                assert value not in node

    walk(payload)


async def _snapshot(factory: async_sessionmaker) -> dict:
    async with factory() as session:
        return {
            model.__tablename__: [
                tuple(getattr(row, column.name) for column in model.__table__.columns)
                for row in (await session.execute(select(model))).scalars().all()
            ]
            for model in (Mistake, MistakeVersion, Attempt, ReviewSchedule)
        }


async def test_sheet_create_and_read_never_leak_answer(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha", answer="甲释义")
        beta = await _create(client, "beta", answer="乙释义")
        gamma = await _create(client, "gamma", answer="丙释义")
        detail = await _sheet(
            client, [beta["id"], alpha["id"], gamma["id"]]
        )
        sheet = detail["sheet"]
        assert sheet["item_ids"] == [beta["id"], alpha["id"], gamma["id"]]
        assert sheet["status"] == "open"
        assert sheet["recorded_on"] is None
        assert sheet["subject"] == "英语"
        assert sheet["unit"] == "U1"
        assert [item["prompt"] for item in detail["items"]] == [
            "beta",
            "alpha",
            "gamma",
        ]
        assert detail["missing_item_ids"] == []
        _assert_no_answer(detail, ["甲释义", "乙释义", "丙释义"])

        listed = await client.get("/api/recitations/sheets")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        _assert_no_answer(listed.json(), ["甲释义", "乙释义", "丙释义"])

    async with _client(factory, unlock=False) as child:
        response = await child.get(f"/api/recitations/sheets/{sheet['id']}")
        assert response.status_code == 200, response.text
        _assert_no_answer(response.json(), ["甲释义", "乙释义", "丙释义"])
        listed = await child.get("/api/recitations/sheets")
        assert listed.status_code == 200


async def test_sheet_write_endpoints_require_parent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        detail = await _sheet(client, [alpha["id"]])
    async with _client(factory, unlock=False) as child:
        created = await child.post(
            "/api/recitations/sheets", json={"item_ids": [alpha["id"]]}
        )
        assert created.status_code == 403
        recorded = await child.post(
            f"/api/recitations/sheets/{detail['sheet']['id']}/results",
            json={"results": [{"item_id": alpha["id"], "verdict": "remembered"}]},
        )
        assert recorded.status_code == 403


async def test_sheet_create_validation(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        chemistry = await _create(client, "化学词", subject="化学")
        retired = await _create(client, "retired-word")
        patched = await client.patch(
            f"/api/recitations/{retired['id']}", json={"status": "retired"}
        )
        assert patched.status_code == 200

        for item_ids in (
            [],
            [alpha["id"], alpha["id"]],
            [999],
            [retired["id"]],
            [alpha["id"], chemistry["id"]],
        ):
            response = await client.post(
                "/api/recitations/sheets", json={"item_ids": item_ids}
            )
            assert response.status_code == 422, response.text
        listed = await client.get("/api/recitations/sheets")
        assert listed.json()["total"] == 0


async def test_sheet_create_rejects_over_cap(tmp_path) -> None:
    """201 个 item_ids 必须 422（手写字面值，不随 MAX_SHEET_ITEMS 漂移）。"""

    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        response = await client.post(
            "/api/recitations/sheets", json={"item_ids": list(range(1, 202))}
        )
        assert response.status_code == 422, response.text
        listed = await client.get("/api/recitations/sheets")
        assert listed.json()["total"] == 0


async def test_full_chain_record_due_and_graduate(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha", answer="甲释义")
        beta = await _create(client, "beta", answer="乙释义")
        gamma = await _create(client, "gamma", answer="丙释义")
        detail = await _sheet(client, [alpha["id"], beta["id"], gamma["id"]])
        sheet_id = detail["sheet"]["id"]

        report = await _record(
            client,
            sheet_id,
            [
                {"item_id": gamma["id"], "verdict": "remembered"},
                {"item_id": alpha["id"], "verdict": "forgot"},
                {"item_id": beta["id"], "verdict": "remembered"},
            ],
            reviewed_on=BASE,
        )
        assert report["sheet"]["status"] == "recorded"
        assert report["sheet"]["recorded_on"] == BASE.isoformat()
        assert report["skipped"] == []
        by_id = {entry["item_id"]: entry for entry in report["results"]}
        assert [entry["item_id"] for entry in report["results"]] == [
            alpha["id"],
            beta["id"],
            gamma["id"],
        ]
        assert by_id[alpha["id"]]["verdict"] == "forgot"
        assert by_id[alpha["id"]]["rung"] == 0
        assert by_id[alpha["id"]]["scheduled_next"] == (BASE + timedelta(days=1)).isoformat()
        assert by_id[alpha["id"]]["graduated"] is False
        assert by_id[beta["id"]]["rung"] == 1
        assert by_id[beta["id"]]["scheduled_next"] == (BASE + timedelta(days=3)).isoformat()
        assert by_id[gamma["id"]]["rung"] == 1
        _assert_no_answer(report, ["甲释义", "乙释义", "丙释义"])

        due_today = await client.get(
            "/api/recitations/due", params={"today": BASE.isoformat()}
        )
        assert due_today.json()["due_total"] == 0
        due_tomorrow = await client.get(
            "/api/recitations/due",
            params={"today": (BASE + timedelta(days=1)).isoformat()},
        )
        assert [entry["item"]["id"] for entry in due_tomorrow.json()["items"]] == [
            alpha["id"]
        ]

        second = await _sheet(client, [alpha["id"]])
        report2 = await _record(
            client,
            second["sheet"]["id"],
            [{"item_id": alpha["id"], "verdict": "remembered"}],
            reviewed_on=BASE + timedelta(days=1),
        )
        entry = report2["results"][0]
        assert entry["rung"] == 1
        assert entry["scheduled_next"] == (BASE + timedelta(days=4)).isoformat()

        for offset, rung in ((4, 2), (11, 3), (25, 4)):
            outcome = await _review(
                client, alpha["id"], "remembered", BASE + timedelta(days=offset)
            )
            assert outcome["rung"] == rung
        final = await _sheet(client, [alpha["id"]])
        report3 = await _record(
            client,
            final["sheet"]["id"],
            [{"item_id": alpha["id"], "verdict": "remembered"}],
            reviewed_on=BASE + timedelta(days=55),
        )
        graduated = report3["results"][0]
        assert graduated["rung"] == 4
        assert graduated["scheduled_next"] is None
        assert graduated["graduated"] is True
        due_after = await client.get(
            "/api/recitations/due",
            params={"today": (BASE + timedelta(days=55)).isoformat()},
        )
        assert alpha["id"] not in [
            entry["item"]["id"] for entry in due_after.json()["items"]
        ]


async def test_batch_results_match_single_review_endpoint(tmp_path) -> None:
    """复用性自证：同一 fixture 同一输入，批量与单条逐项相等（DoD 对照表）。"""

    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        singles = [
            await _create(client, prompt)
            for prompt in ("alpha", "beta", "gamma")
        ]
        batches = [
            await _create(client, prompt)
            for prompt in ("delta", "epsilon", "zeta")
        ]
        for item in singles + batches:
            await _review(client, item["id"], "forgot", BASE)
            await _review(client, item["id"], "remembered", BASE + timedelta(days=1))

        verdicts = ("remembered", "forgot", "remembered")
        day = BASE + timedelta(days=4)
        single_outcomes = [
            await _review(client, item["id"], verdict, day)
            for item, verdict in zip(singles, verdicts, strict=True)
        ]
        detail = await _sheet(client, [item["id"] for item in batches])
        report = await _record(
            client,
            detail["sheet"]["id"],
            [
                {"item_id": item["id"], "verdict": verdict}
                for item, verdict in zip(batches, verdicts, strict=True)
            ],
            reviewed_on=day,
        )
        assert len(report["results"]) == 3
        for single, batch in zip(single_outcomes, report["results"], strict=True):
            assert batch["verdict"] == single["verdict"]
            assert batch["rung"] == single["rung"]
            assert batch["scheduled_next"] == single["scheduled_next"]
            assert batch["graduated"] == single["graduated"]
            assert batch["created"] == single["created"]

        expected = ((2, 11), (1, 7), (2, 11))
        for entry, (rung, offset) in zip(report["results"], expected, strict=True):
            assert entry["rung"] == rung
            assert entry["scheduled_next"] == (BASE + timedelta(days=offset)).isoformat()

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(RecitationReview).order_by(RecitationReview.id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 18
    for single_row, batch_row in zip(rows[12:15], rows[15:18], strict=True):
        assert (
            single_row.verdict,
            single_row.rung,
            single_row.reviewed_on,
            single_row.scheduled_next,
        ) == (
            batch_row.verdict,
            batch_row.rung,
            batch_row.reviewed_on,
            batch_row.scheduled_next,
        )


async def test_repeat_submit_is_409_without_duplicate_facts(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        detail = await _sheet(client, [alpha["id"]])
        sheet_id = detail["sheet"]["id"]
        payload = {
            "results": [{"item_id": alpha["id"], "verdict": "forgot"}],
            "reviewed_on": BASE.isoformat(),
        }
        first = await client.post(
            f"/api/recitations/sheets/{sheet_id}/results", json=payload
        )
        assert first.status_code == 200
        again = await client.post(
            f"/api/recitations/sheets/{sheet_id}/results", json=payload
        )
        assert again.status_code == 409
        assert "已回录" in again.json()["detail"]

    async with factory() as session:
        reviews = (await session.execute(select(RecitationReview))).scalars().all()
        assert len(reviews) == 1
        sheet = await session.get(DictationSheet, sheet_id)
        assert sheet.status == "recorded"
        assert sheet.recorded_on == BASE


async def test_missing_and_retired_items_are_skipped_and_reported(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        beta = await _create(client, "beta")
        gamma = await _create(client, "gamma")
        detail = await _sheet(client, [alpha["id"], beta["id"], gamma["id"]])
        sheet_id = detail["sheet"]["id"]
        patched = await client.patch(
            f"/api/recitations/{beta['id']}", json={"status": "retired"}
        )
        assert patched.status_code == 200

    async with factory() as session, session.begin():
        await session.execute(
            delete(RecitationItem).where(RecitationItem.id == gamma["id"])
        )

    async with _client(factory) as client:
        fetched = await client.get(f"/api/recitations/sheets/{sheet_id}")
        assert fetched.status_code == 200
        body = fetched.json()
        assert body["missing_item_ids"] == [gamma["id"]]
        assert [item["item_id"] for item in body["items"]] == [
            alpha["id"],
            beta["id"],
        ]
        assert body["items"][1]["status"] == "retired"

        report = await _record(
            client,
            sheet_id,
            [
                {"item_id": alpha["id"], "verdict": "remembered"},
                {"item_id": beta["id"], "verdict": "forgot"},
                {"item_id": gamma["id"], "verdict": "forgot"},
            ],
            reviewed_on=BASE,
        )
        assert [entry["item_id"] for entry in report["results"]] == [alpha["id"]]
        assert report["skipped"] == [
            {"item_id": beta["id"], "reason": "retired"},
            {"item_id": gamma["id"], "reason": "missing"},
        ]
        assert report["sheet"]["status"] == "recorded"

    async with factory() as session:
        reviews = (await session.execute(select(RecitationReview))).scalars().all()
        assert len(reviews) == 1
        assert reviews[0].item_id == alpha["id"]


async def test_results_validation_rolls_back_and_keeps_sheet_open(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        outsider = await _create(client, "outsider")
        detail = await _sheet(client, [alpha["id"]])
        sheet_id = detail["sheet"]["id"]
        for results in (
            [],
            [{"item_id": outsider["id"], "verdict": "remembered"}],
            [
                {"item_id": alpha["id"], "verdict": "remembered"},
                {"item_id": alpha["id"], "verdict": "forgot"},
            ],
            [{"item_id": alpha["id"], "verdict": "uncertain"}],
        ):
            response = await client.post(
                f"/api/recitations/sheets/{sheet_id}/results",
                json={"results": results, "reviewed_on": BASE.isoformat()},
            )
            assert response.status_code == 422, response.text
        fetched = await client.get(f"/api/recitations/sheets/{sheet_id}")
        assert fetched.json()["sheet"]["status"] == "open"

    async with factory() as session:
        reviews = (await session.execute(select(RecitationReview))).scalars().all()
        assert reviews == []


async def test_same_day_prior_self_review_is_idempotent(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        prior = await _review(client, alpha["id"], "remembered", BASE)
        assert prior["created"] is True
        detail = await _sheet(client, [alpha["id"]])
        report = await _record(
            client,
            detail["sheet"]["id"],
            [{"item_id": alpha["id"], "verdict": "forgot"}],
            reviewed_on=BASE,
        )
        entry = report["results"][0]
        assert entry["created"] is False
        assert entry["verdict"] == "remembered"
        assert entry["rung"] == prior["rung"]
        assert entry["scheduled_next"] == prior["scheduled_next"]

    async with factory() as session:
        reviews = (await session.execute(select(RecitationReview))).scalars().all()
        assert len(reviews) == 1


async def test_dictation_never_touches_mistake_tables(tmp_path) -> None:
    factory = _migrated(tmp_path)
    before = await _snapshot(factory)
    async with _client(factory) as client:
        alpha = await _create(client, "alpha")
        detail = await _sheet(client, [alpha["id"]])
        await _record(
            client,
            detail["sheet"]["id"],
            [{"item_id": alpha["id"], "verdict": "forgot"}],
            reviewed_on=BASE,
        )
    after = await _snapshot(factory)
    assert after == before


async def test_sheet_not_found_and_list_filter(tmp_path) -> None:
    factory = _migrated(tmp_path)
    async with _client(factory) as client:
        missing_get = await client.get("/api/recitations/sheets/999")
        assert missing_get.status_code == 404
        missing_post = await client.post(
            "/api/recitations/sheets/999/results",
            json={"results": [{"item_id": 1, "verdict": "remembered"}]},
        )
        assert missing_post.status_code == 404

        alpha = await _create(client, "alpha")
        first = await _sheet(client, [alpha["id"]])
        second = await _sheet(client, [alpha["id"]])
        await _record(
            client,
            first["sheet"]["id"],
            [{"item_id": alpha["id"], "verdict": "remembered"}],
            reviewed_on=BASE,
        )
        open_only = await client.get(
            "/api/recitations/sheets", params={"status": "open"}
        )
        assert open_only.status_code == 200
        assert [sheet["id"] for sheet in open_only.json()["items"]] == [
            second["sheet"]["id"]
        ]
        recorded_only = await client.get(
            "/api/recitations/sheets", params={"status": "recorded"}
        )
        assert [sheet["id"] for sheet in recorded_only.json()["items"]] == [
            first["sheet"]["id"]
        ]
        bad_status = await client.get(
            "/api/recitations/sheets", params={"status": "done"}
        )
        assert bad_status.status_code == 422


def _tables(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            return set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def _master_ddl(db_path: Path, involved: set[str]) -> dict[str, str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
            " WHERE sql IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return {
        f"{kind}:{name}": sql
        for kind, name, table, sql in rows
        if table in involved
    }


def test_0024_dictation_sheets_up_down_up(tmp_path) -> None:
    """0024：默写卷表可逆；status/recorded_on 一致性由 CHECK 在库层兜底。"""

    db_path = tmp_path / "dictation-migrate.db"
    config = _alembic_config(db_path)

    command.upgrade(config, "0023_learning_events_occurred_at")
    assert "dictation_sheets" not in _tables(db_path)

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {
                column["name"]: column["nullable"]
                for column in inspector.get_columns("dictation_sheets")
            }
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints("dictation_sheets")
            }
        assert columns == {
            "id": False,
            "created_on": False,
            "created_by": False,
            "subject": False,
            "unit": True,
            "item_ids": False,
            "status": False,
            "recorded_on": True,
        }
        assert checks == {
            "ck_dictation_sheets_status",
            "ck_dictation_sheets_recorded_on",
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO dictation_sheets"
                    " (created_on, created_by, subject, item_ids)"
                    " VALUES ('2026-11-20', 'parent', '英语', '[1,2]')"
                )
            )
            row = connection.execute(
                text("SELECT status, recorded_on FROM dictation_sheets")
            ).one()
            assert tuple(row) == ("open", None)
        with (
            engine.begin() as connection,
            pytest.raises(sqlalchemy.exc.IntegrityError),
        ):
            connection.execute(
                text(
                    "INSERT INTO dictation_sheets"
                    " (created_on, created_by, subject, item_ids, status)"
                    " VALUES ('2026-11-20', 'parent', '英语', '[1]', 'done')"
                )
            )
        with (
            engine.begin() as connection,
            pytest.raises(sqlalchemy.exc.IntegrityError),
        ):
            connection.execute(
                text(
                    "INSERT INTO dictation_sheets"
                    " (created_on, created_by, subject, item_ids, status)"
                    " VALUES ('2026-11-20', 'parent', '英语', '[1]', 'recorded')"
                )
            )
        with (
            engine.begin() as connection,
            pytest.raises(sqlalchemy.exc.IntegrityError),
        ):
            connection.execute(
                text(
                    "INSERT INTO dictation_sheets"
                    " (created_on, created_by, subject, item_ids, recorded_on)"
                    " VALUES ('2026-11-20', 'parent', '英语', '[1]', '2026-11-20')"
                )
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO dictation_sheets"
                    " (created_on, created_by, subject, item_ids, status, recorded_on)"
                    " VALUES ('2026-11-20', 'parent', '英语', '[1]', 'recorded',"
                    " '2026-11-20')"
                )
            )
    finally:
        engine.dispose()

    command.downgrade(config, "0023_learning_events_occurred_at")
    assert "dictation_sheets" not in _tables(db_path)

    command.upgrade(config, "head")
    assert "dictation_sheets" in _tables(db_path)


def test_0024_dictation_sheets_ddl_is_byte_identical(tmp_path) -> None:
    """0024 用 op.create_table 显式建表：回退再升级与首次升级、ORM 模型逐字一致。"""

    db_path = tmp_path / "dictation-ddl.db"
    config = _alembic_config(db_path)
    involved = {"dictation_sheets"}

    command.upgrade(config, "0023_learning_events_occurred_at")
    assert _master_ddl(db_path, involved) == {}

    command.upgrade(config, "head")
    before = _master_ddl(db_path, involved)
    assert set(before) == {"table:dictation_sheets"}

    model_engine = create_engine("sqlite://")
    try:
        compiled = str(CreateTable(DictationSheet.__table__).compile(model_engine)).strip()
        assert before["table:dictation_sheets"] == compiled
    finally:
        model_engine.dispose()

    command.downgrade(config, "0023_learning_events_occurred_at")
    assert _master_ddl(db_path, involved) == {}

    command.upgrade(config, "head")
    assert _master_ddl(db_path, involved) == before
