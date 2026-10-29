"""监听目录导入引擎集成测试（TICKETS P1-3d / 批次②）。

DoD：合法 JSON 进 inbox → 生成草稿并归档、报告 accepted_count/errors[]；
同内容再投命中 sha256 去重（duplicate=true）；坏项逐条报 index/field/reason、
不静默截断；非法 JSON 稳定窗口内重试、超时按 invalid 归档；未处理文件留在
inbox（停机不丢），下一轮补处理。全程不调模型、不自动转正。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.database import create_sqlite_engine
from app.models import ImportBatch, IngestionDraft
from app.services.inbox import (
    PROCESSED_DIR,
    inbox_watcher,
    process_inbox_once,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

API_DIR = Path(__file__).resolve().parents[2]

VALID_PAYLOAD = {
    "channel": "agent_transcribe_v1",
    "items": [
        {
            "subject": "数学",
            "problem_text": "计算 (-3)+5",
            "student_answer": "2",
            "standard_answer": "2",
            "source_ref": "卷子 P12",
            "captured_at": "2026-10-28",
        },
        {
            "subject": "英语",
            "problem_text": "默写 〔?〕 apple",
            "student_answer": "",
            "standard_answer": "apple",
        },
    ],
}


def _migrated(tmp_path: Path) -> tuple[Path, async_sessionmaker]:
    db_path = tmp_path / "inbox.db"
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(db_path)
    return db_path, async_sessionmaker(engine, expire_on_commit=False)


def _drop(inbox: Path, name: str, payload: dict) -> Path:
    path = inbox / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    directory = tmp_path / "inbox"
    directory.mkdir()
    return directory


@pytest.mark.integration
async def test_valid_file_imported_archived_with_drafts(
    tmp_path: Path, inbox: Path
) -> None:
    _, factory = _migrated(tmp_path)
    _drop(inbox, "batch-a.json", VALID_PAYLOAD)

    async with factory() as session:
        reports = await process_inbox_once(session, inbox)

    assert len(reports) == 1
    report = reports[0]
    assert report.filename == "batch-a.json"
    assert report.outcome == "imported"
    assert report.batch_id is not None
    assert report.accepted_count == 2
    assert report.error_count == 0

    # 源文件归档，inbox 清空
    assert not (inbox / "batch-a.json").exists()
    archived = inbox / PROCESSED_DIR / "batch-a.json"
    assert archived.exists()

    async with factory() as session:
        batch = (await session.execute(select(ImportBatch))).scalar_one()
        assert batch.id == report.batch_id
        assert batch.channel == "agent_transcribe_v1"
        assert batch.filename == "batch-a.json"
        drafts = (
            (
                await session.execute(
                    select(IngestionDraft).order_by(IngestionDraft.seq)
                )
            )
            .scalars()
            .all()
        )
        assert [d.status for d in drafts] == ["draft", "draft"]  # 不自动转正
        assert drafts[0].is_incomplete is False
        assert drafts[1].has_placeholder is True


@pytest.mark.integration
async def test_same_content_redrop_hits_dedup(
    tmp_path: Path, inbox: Path
) -> None:
    """同内容再投（重命名也算）→ 旧 batch + duplicate=true，草稿不重写。"""

    _, factory = _migrated(tmp_path)
    _drop(inbox, "first.json", VALID_PAYLOAD)
    async with factory() as session:
        first = await process_inbox_once(session, inbox)
    assert first[0].outcome == "imported"

    _drop(inbox, "second.json", VALID_PAYLOAD)  # 不同文件名、同内容
    async with factory() as session:
        second = await process_inbox_once(session, inbox)
    assert second[0].outcome == "duplicate"
    assert second[0].batch_id == first[0].batch_id

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(ImportBatch))
        ).scalar_one() == 1
        assert (
            await session.execute(select(func.count()).select_from(IngestionDraft))
        ).scalar_one() == 2
    # 两份源文件都归档，重名自动加序号
    processed = inbox / PROCESSED_DIR
    assert (processed / "first.json").exists()
    assert (processed / "second.json").exists()


@pytest.mark.integration
async def test_bad_items_reported_without_truncation(
    tmp_path: Path, inbox: Path
) -> None:
    payload = {
        "channel": "agent_transcribe_v1",
        "items": [
            {"problem_text": "好题", "student_answer": "A", "standard_answer": "A"},
            {"problem_text": ""},  # 必填缺失
            {"problem_text": "x" * 2001},  # 超长跳过而非截断
        ],
    }
    _, factory = _migrated(tmp_path)
    _drop(inbox, "partial.json", payload)

    async with factory() as session:
        reports = await process_inbox_once(session, inbox)

    assert reports[0].outcome == "partial"
    assert reports[0].accepted_count == 1
    assert reports[0].error_count == 2
    async with factory() as session:
        draft = (await session.execute(select(IngestionDraft))).scalars().one()
        assert draft.seq == 0  # 坏项被跳过，序号保留可定位
        batch = (await session.execute(select(ImportBatch))).scalar_one()
        assert batch.status == "partial"
    assert (inbox / PROCESSED_DIR / "partial.json").exists()


@pytest.mark.integration
async def test_invalid_json_retries_then_archived_as_invalid(
    tmp_path: Path, inbox: Path
) -> None:
    """半成品文件（刚写入、JSON 非法）留待下轮；超时后按 invalid 归档，不丢文件。"""

    _, factory = _migrated(tmp_path)
    path = inbox / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    async with factory() as session:
        reports = await process_inbox_once(session, inbox)
    assert reports[0].outcome == "retry"
    assert path.exists()  # 仍在 inbox，下轮补扫

    # 模拟写入早已结束：回拨 mtime 越过稳定窗口
    old = 1_000_000.0
    os.utime(path, (old, old))
    async with factory() as session:
        reports = await process_inbox_once(session, inbox)
    assert reports[0].outcome == "invalid"
    assert not path.exists()
    assert (inbox / PROCESSED_DIR / "broken.invalid.json").exists()

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(ImportBatch))
        ).scalar_one() == 0  # 坏报文不产生 batch


@pytest.mark.integration
async def test_unprocessed_file_survives_and_is_picked_up_next_scan(
    tmp_path: Path, inbox: Path
) -> None:
    """停机等价：文件落在 inbox 但本轮未处理 → 下轮补处理（不丢、不重复）。"""

    _, factory = _migrated(tmp_path)
    _drop(inbox, "late.json", VALID_PAYLOAD)
    # 第一轮不调用 process_inbox_once——模拟服务停机期间文件到达

    async with factory() as session:
        reports = await process_inbox_once(session, inbox)  # 重启后首轮补扫
    assert reports[0].outcome == "imported"
    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(IngestionDraft))
        ).scalar_one() == 2


@pytest.mark.integration
async def test_multiple_files_in_one_scan_share_session(
    tmp_path: Path, inbox: Path
) -> None:
    """同一 session 一轮扫多文件：前一个文件的落库不得挂起事务卡死后续文件。"""

    _, factory = _migrated(tmp_path)
    second = {
        "channel": "agent_transcribe_v1",
        "items": [{"problem_text": "另一道题", "student_answer": "B", "standard_answer": "B"}],
    }
    _drop(inbox, "a.json", VALID_PAYLOAD)
    _drop(inbox, "b.json", second)

    async with factory() as session:
        reports = await process_inbox_once(session, inbox)

    assert [r.filename for r in reports] == ["a.json", "b.json"]
    assert [r.outcome for r in reports] == ["imported", "imported"]
    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(ImportBatch))
        ).scalar_one() == 2
        assert (
            await session.execute(select(func.count()).select_from(IngestionDraft))
        ).scalar_one() == 3


@pytest.mark.integration
async def test_watcher_loop_processes_file_and_stops(
    tmp_path: Path, inbox: Path
) -> None:
    _, factory = _migrated(tmp_path)
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        inbox_watcher(factory, inbox, stop_event, interval_seconds=0.2)
    )
    try:
        _drop(inbox, "watched.json", VALID_PAYLOAD)
        for _ in range(50):  # 最多 ~10s 等 watcher 扫到
            await asyncio.sleep(0.2)
            if not (inbox / "watched.json").exists():
                break
        assert not (inbox / "watched.json").exists()
        assert (inbox / PROCESSED_DIR / "watched.json").exists()
    finally:
        stop_event.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async with factory() as session:
        assert (
            await session.execute(select(func.count()).select_from(IngestionDraft))
        ).scalar_one() == 2


@pytest.mark.integration
async def test_import_never_calls_models(tmp_path: Path, inbox: Path, monkeypatch) -> None:
    from app.services import ai_gateway

    def _boom(*args, **kwargs):  # pragma: no cover - 被调用即失败
        raise AssertionError("导入链路不允许触发模型调用")

    monkeypatch.setattr(ai_gateway.AiGateway, "extract_problem", _boom)
    monkeypatch.setattr(ai_gateway.AiGateway, "grade", _boom)
    monkeypatch.setattr(ai_gateway.AiGateway, "solve_explain", _boom)

    _, factory = _migrated(tmp_path)
    _drop(inbox, "no-model.json", VALID_PAYLOAD)
    async with factory() as session:
        reports = await process_inbox_once(session, inbox)
    assert reports[0].outcome == "imported"
