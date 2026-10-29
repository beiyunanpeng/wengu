"""监听目录导入引擎（v2.5 主入本通道，TICKETS P1-3d）。

后台扫描 `data/inbox/*.json`（`WENGU_INBOX_DIR` 可配）→ 复用 ingestion 的
确定性校验/归一化 → `import_batches`（sha256 对原始报文去重）+ `ingestion_drafts`
→ 源文件归档到 `.processed/`。导入全程不调模型、不判分、不建错题、不自动转正
（转正必过核对页，Phase 0 闸门）。

可靠性：处理成功才归档——停机/崩溃时文件留在 inbox，重启补扫；半成品文件
（写入未落盘，JSON 解析失败且文件过新）留待下轮，超时按 invalid 归档，不丢文件。
日志只记文件名/计数/错误定位（index/field/reason），绝不记题目全文与答案。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import IngestionDraft
from app.services.events import create_import_batch
from app.services.ingestion import (
    MAX_BATCH_BODY_BYTES,
    ItemError,
    dumps_draft,
    validate_and_normalize,
    validate_envelope,
)

logger = logging.getLogger(__name__)

INBOX_SCAN_INTERVAL_SECONDS = 2.0
# 外部 agent 写入文件的落盘稳定窗口：JSON 非法且文件比该值新 → 留待下轮再试
_WRITE_SETTLE_SECONDS = 5.0

PROCESSED_DIR = ".processed"


class PayloadTooLargeError(ValueError):
    """报文超过单批上限。"""


class PayloadJsonError(ValueError):
    """JSON 解析失败。"""


class PayloadEnvelopeError(ValueError):
    """封套非法（channel/items 不符契约）。"""


class NoValidItemsError(ValueError):
    """逐项校验后没有任何可导入题目。"""

    def __init__(self, errors: list[ItemError]) -> None:
        super().__init__("没有可导入的合法题目")
        self.errors = errors


@dataclass
class IngestOutcome:
    batch_id: int
    status: str
    duplicate: bool
    draft_count: int
    accepted_count: int
    dropped_unknown_fields: int
    errors: list[ItemError] = field(default_factory=list)


async def ingest_raw_payload(
    session: AsyncSession, raw: bytes, *, filename: str | None = None
) -> IngestOutcome:
    """HTTP 导入与目录监听共用的落库核心：校验 → 去重 → batch + 草稿。

    草稿只进 `ingestion_drafts`（status=draft），绝不自动转正。
    """

    if len(raw) > MAX_BATCH_BODY_BYTES:
        raise PayloadTooLargeError("导入报文超过 5MB 上限，请拆分")
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PayloadJsonError(f"JSON 解析失败: {exc.msg}") from None
    try:
        channel, items = validate_envelope(payload)
    except ValueError as exc:
        raise PayloadEnvelopeError(str(exc)) from None

    result = validate_and_normalize(items)
    if not result.drafts:
        raise NoValidItemsError(result.errors)

    digest = hashlib.sha256(raw).hexdigest()
    async with session.begin():
        batch, created = await create_import_batch(
            session, channel, digest, filename=filename, item_count=len(result.drafts)
        )
        if created:
            batch.status = "imported" if not result.errors else "partial"
            for draft in result.drafts:
                session.add(
                    IngestionDraft(
                        import_batch_id=batch.id,
                        seq=draft["seq"],
                        normalized_json=dumps_draft(draft["normalized"]),
                        has_placeholder=draft["has_placeholder"],
                        is_incomplete=draft["is_incomplete"],
                        created_at=datetime.now(UTC),
                    )
                )
        # 计数查询必须在外层事务内：在外部执行会 autobegin 挂起事务，
        # 同一 session 处理多文件时下一个 begin() 直接 InvalidRequestError
        draft_count = (
            await session.execute(
                select(func.count())
                .select_from(IngestionDraft)
                .where(IngestionDraft.import_batch_id == batch.id)
            )
        ).scalar_one()
    return IngestOutcome(
        batch_id=batch.id,
        status=batch.status,
        duplicate=not created,
        draft_count=draft_count,
        accepted_count=len(result.drafts),
        dropped_unknown_fields=result.dropped_unknown_fields,
        errors=list(result.errors),
    )


@dataclass
class InboxFileReport:
    filename: str
    outcome: str  # imported | partial | duplicate | invalid | retry
    batch_id: int | None = None
    accepted_count: int = 0
    error_count: int = 0


def _unique_target(directory: Path, name: str) -> Path:
    target = directory / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for counter in range(2, 1000):
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"归档重名无法消解: {name}")


def _archive(path: Path, inbox_dir: Path, *, invalid: bool) -> Path:
    directory = inbox_dir / PROCESSED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{path.stem}.invalid{path.suffix}" if invalid else path.name
    target = _unique_target(directory, name)
    shutil.move(str(path), str(target))
    return target


async def process_inbox_file(
    session: AsyncSession, path: Path, inbox_dir: Path
) -> InboxFileReport:
    raw = await asyncio.to_thread(path.read_bytes)
    try:
        outcome = await ingest_raw_payload(session, raw, filename=path.name)
    except PayloadTooLargeError as exc:
        report = InboxFileReport(path.name, "invalid", error_count=1)
        logger.warning("inbox 文件超限归档: %s（%s）", path.name, exc)
        _archive(path, inbox_dir, invalid=True)
    except NoValidItemsError as exc:
        report = InboxFileReport(
            path.name, "invalid", error_count=len(exc.errors)
        )
        logger.warning(
            "inbox 文件无合法题目归档: %s（%d 项错误）", path.name, len(exc.errors)
        )
        _archive(path, inbox_dir, invalid=True)
    except (PayloadJsonError, PayloadEnvelopeError) as exc:
        age = time.time() - path.stat().st_mtime
        if age < _WRITE_SETTLE_SECONDS:
            # 可能是外部 agent 尚未写完，下轮再试
            return InboxFileReport(path.name, "retry")
        report = InboxFileReport(path.name, "invalid", error_count=1)
        logger.warning("inbox 非法报文归档: %s（%s）", path.name, exc)
        _archive(path, inbox_dir, invalid=True)
    else:
        report = InboxFileReport(
            path.name,
            "duplicate" if outcome.duplicate else outcome.status,
            batch_id=outcome.batch_id,
            accepted_count=outcome.accepted_count,
            error_count=len(outcome.errors),
        )
        for error in outcome.errors:
            logger.info(
                "inbox 坏项 %s #%d %s: %s",
                path.name,
                error.index,
                error.field,
                error.reason,
            )
        _archive(path, inbox_dir, invalid=False)
    return report


async def process_inbox_once(
    session: AsyncSession, inbox_dir: Path
) -> list[InboxFileReport]:
    """扫一轮 inbox（顶层 *.json，不含 .processed/）；文件名排序保证确定性。"""

    reports: list[InboxFileReport] = []
    for path in sorted(inbox_dir.glob("*.json")):
        try:
            reports.append(await process_inbox_file(session, path, inbox_dir))
        except Exception:
            logger.exception("inbox 文件处理异常（保留原文件下轮重试）: %s", path.name)
    return reports


async def inbox_watcher(
    session_factory: async_sessionmaker[AsyncSession],
    inbox_dir: Path,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float = INBOX_SCAN_INTERVAL_SECONDS,
) -> None:
    """后台扫描循环；未处理文件永远在 inbox，停机不丢、重启补扫。"""

    while True:
        try:
            async with session_factory() as session:
                await process_inbox_once(session, inbox_dir)
        except Exception:
            logger.exception("inbox 扫描失败，下轮继续")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
        break
