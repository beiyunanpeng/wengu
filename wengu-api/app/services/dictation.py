"""P3-4 英语默写：卷面快照 + 页内勾选回录（判分主体是家长红笔，系统零判分代码）。

只写 dictation_sheets 与既有 recitation_reviews / learning_events——回录逐条调用
`recitation.review_item()`，decide() 二档调度原样复用，批量与单条自评天然一致；
错词不进错题本，不碰 mistakes / mistake_versions / attempts / review_schedules。
卷面投影与孩子可达 API 一律不含 answer：提示只取 prompt。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecitationItem
from app.models.recitation import DictationSheet
from app.services.dictation_audio import validate_audio_ref
from app.services.recitation import (
    ITEM_ACTIVE,
    VERDICTS,
    RecitationConflict,
    RecitationInvalid,
    RecitationNotFound,
    review_item,
)

SHEET_OPEN = "open"
SHEET_RECORDED = "recorded"
SHEET_STATUSES = (SHEET_OPEN, SHEET_RECORDED)

MAX_SHEET_ITEMS = 200
MAX_LIST_LIMIT = 200

SKIP_MISSING = "missing"
SKIP_RETIRED = "retired"


def normalize_item_ids(raw: Sequence[int]) -> tuple[int, ...]:
    """非空、正整数、不重复；词序按提交顺序固化。"""

    if not raw:
        raise RecitationInvalid("item_ids 不能为空")
    if len(raw) > MAX_SHEET_ITEMS:
        raise RecitationInvalid(f"一张默写卷最多 {MAX_SHEET_ITEMS} 个条目")
    seen: set[int] = set()
    for item_id in raw:
        if isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
            raise RecitationInvalid("item_ids 必须是正整数")
        if item_id in seen:
            raise RecitationInvalid("item_ids 不能重复")
        seen.add(item_id)
    return tuple(raw)


def validate_results(
    item_ids: Sequence[int], results: Sequence[tuple[int, str]]
) -> tuple[tuple[int, str], ...]:
    """校验归属 + 二档 + 不重复；按卷面词序重排，回录顺序因此确定。"""

    if not results:
        raise RecitationInvalid("results 不能为空")
    known = set(item_ids)
    by_id: dict[int, str] = {}
    for item_id, verdict in results:
        if item_id not in known:
            raise RecitationInvalid(f"条目 {item_id} 不属于本卷")
        if verdict not in VERDICTS:
            raise RecitationInvalid(f"verdict 只能是 {VERDICTS}")
        if item_id in by_id:
            raise RecitationInvalid(f"条目 {item_id} 重复提交")
        by_id[item_id] = verdict
    return tuple((item_id, by_id[item_id]) for item_id in item_ids if item_id in by_id)


def ensure_open(status: str) -> None:
    """状态机只有 open→recorded 一条边；已回录的卷拒绝重复提交。"""

    if status != SHEET_OPEN:
        raise RecitationConflict("本卷已回录，不能重复提交")


@dataclass(frozen=True)
class SheetItem:
    """卷面条目投影：只有提示，没有 answer 字段（定案⑤）。"""

    item_id: int
    prompt: str
    unit: str | None
    status: str


@dataclass(frozen=True)
class SheetDetail:
    sheet: DictationSheet
    items: tuple[SheetItem, ...]
    missing_item_ids: tuple[int, ...]


@dataclass(frozen=True)
class SheetList:
    sheets: tuple[DictationSheet, ...]
    total: int


@dataclass(frozen=True)
class ResultOutcome:
    item_id: int
    prompt: str
    verdict: str
    review_id: int
    rung: int
    reviewed_on: date
    scheduled_next: date | None
    graduated: bool
    created: bool


@dataclass(frozen=True)
class SkippedResult:
    item_id: int
    reason: str


@dataclass(frozen=True)
class RecordReport:
    sheet: DictationSheet
    results: tuple[ResultOutcome, ...]
    skipped: tuple[SkippedResult, ...]


def project_items(
    item_ids: Sequence[int], items_by_id: Mapping[int, RecitationItem]
) -> tuple[tuple[SheetItem, ...], tuple[int, ...]]:
    """按固化词序投影卷面；已删除条目单列 missing，不猜内容。"""

    views: list[SheetItem] = []
    missing: list[int] = []
    for item_id in item_ids:
        item = items_by_id.get(item_id)
        if item is None:
            missing.append(item_id)
            continue
        views.append(
            SheetItem(
                item_id=item.id,
                prompt=item.prompt,
                unit=item.unit,
                status=item.status,
            )
        )
    return tuple(views), tuple(missing)


def sheet_item_ids(sheet: DictationSheet) -> tuple[int, ...]:
    return tuple(int(item_id) for item_id in json.loads(sheet.item_ids))


async def create_sheet(
    session: AsyncSession,
    *,
    item_ids: Sequence[int],
    unit: str | None = None,
    audio_ref: str | None = None,
    audio_dir: Path | None = None,
    created_by: str = "parent",
    today: date | None = None,
) -> DictationSheet:
    """生成卷面：全部条目必须存在且 active；学科必须一致，unit 缺省取公共单元。

    P3-4b：audio_ref 非空时校验文件在 audio_dir 内且嗅探通过（AudioError → 422）；
    一卷一音频，默写卷留空。
    """

    ordered = normalize_item_ids(item_ids)
    if audio_ref is not None:
        assert audio_dir is not None
        audio_ref = validate_audio_ref(audio_dir, audio_ref)
    rows = (
        (
            await session.execute(
                select(RecitationItem).where(RecitationItem.id.in_(ordered))
            )
        )
        .scalars()
        .all()
    )
    by_id = {item.id: item for item in rows}
    missing = [item_id for item_id in ordered if item_id not in by_id]
    if missing:
        raise RecitationInvalid(f"条目不存在：{missing}")
    inactive = [
        item_id for item_id in ordered if by_id[item_id].status != ITEM_ACTIVE
    ]
    if inactive:
        raise RecitationInvalid(f"条目已停用：{inactive}")
    subjects = {by_id[item_id].subject for item_id in ordered}
    if len(subjects) != 1:
        raise RecitationInvalid("一张默写卷只能含同一学科的条目")
    if unit is None:
        units = {by_id[item_id].unit for item_id in ordered}
        if len(units) == 1:
            unit = next(iter(units))
    sheet = DictationSheet(
        created_on=today or date.today(),
        created_by=created_by,
        subject=next(iter(subjects)),
        unit=unit,
        item_ids=json.dumps(list(ordered)),
        status=SHEET_OPEN,
        recorded_on=None,
        audio_ref=audio_ref,
    )
    session.add(sheet)
    await session.flush()
    return sheet


async def list_sheets(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SheetList:
    if status is not None and status not in SHEET_STATUSES:
        raise RecitationInvalid(f"status 只能是 {SHEET_STATUSES}")
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise RecitationInvalid(f"limit 必须在 1..{MAX_LIST_LIMIT}")
    if offset < 0:
        raise RecitationInvalid("offset 不能为负")
    stmt = select(DictationSheet)
    count_stmt = select(func.count()).select_from(DictationSheet)
    if status is not None:
        stmt = stmt.where(DictationSheet.status == status)
        count_stmt = count_stmt.where(DictationSheet.status == status)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(DictationSheet.id.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return SheetList(sheets=tuple(rows), total=total)


async def get_sheet(session: AsyncSession, sheet_id: int) -> SheetDetail:
    sheet = await session.get(DictationSheet, sheet_id)
    if sheet is None:
        raise RecitationNotFound("默写卷不存在")
    ids = sheet_item_ids(sheet)
    rows = (
        (
            await session.execute(
                select(RecitationItem).where(RecitationItem.id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    views, missing = project_items(ids, {item.id: item for item in rows})
    return SheetDetail(sheet=sheet, items=views, missing_item_ids=missing)


async def record_results(
    session: AsyncSession,
    sheet_id: int,
    *,
    results: Sequence[tuple[int, str]],
    reviewed_on: date,
    actor: str = "parent",
    now: datetime | None = None,
) -> RecordReport:
    """页内勾选回录：逐条复用 review_item()（decide() 原样），整批一个事务。

    缺失/停用条目跳过并在报告中列明；同日已有自评的条目幂等返回既有事实。
    调用方负责事务边界（API 层 session.begin()），任何异常整批回滚。
    """

    sheet = await session.get(DictationSheet, sheet_id)
    if sheet is None:
        raise RecitationNotFound("默写卷不存在")
    ensure_open(sheet.status)
    ids = sheet_item_ids(sheet)
    ordered = validate_results(ids, results)
    rows = (
        (
            await session.execute(
                select(RecitationItem).where(RecitationItem.id.in_(ids))
            )
        )
        .scalars()
        .all()
    )
    by_id = {item.id: item for item in rows}
    outcomes: list[ResultOutcome] = []
    skipped: list[SkippedResult] = []
    for item_id, verdict in ordered:
        item = by_id.get(item_id)
        if item is None:
            skipped.append(SkippedResult(item_id=item_id, reason=SKIP_MISSING))
            continue
        if item.status != ITEM_ACTIVE:
            skipped.append(SkippedResult(item_id=item_id, reason=SKIP_RETIRED))
            continue
        outcome = await review_item(
            session,
            item_id,
            verdict=verdict,
            reviewed_on=reviewed_on,
            actor=actor,
            now=now,
        )
        review = outcome.review
        outcomes.append(
            ResultOutcome(
                item_id=item_id,
                prompt=item.prompt,
                verdict=review.verdict,
                review_id=review.id,
                rung=review.rung,
                reviewed_on=review.reviewed_on,
                scheduled_next=review.scheduled_next,
                graduated=review.scheduled_next is None,
                created=outcome.created,
            )
        )
    sheet.status = SHEET_RECORDED
    sheet.recorded_on = reviewed_on
    await session.flush()
    return RecordReport(sheet=sheet, results=tuple(outcomes), skipped=tuple(skipped))
