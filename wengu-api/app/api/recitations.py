"""P3-3a 英语背诵 API：家长维护条目，孩子按记忆阶梯自评。

读接口（列表 / 到期）对孩子开放；条目新增与编辑挂 `require_parent`。
自评只写 `learning_events` 与 `recitation_reviews`，不写错题本/attempts/排期，
因此掌握度与复习队列不受影响；同日重复提交幂等返回既有结果。

P3-4 默写卷：生成与回录挂 `require_parent`（判分主体是家长红笔）；卷面读接口
对孩子开放但只含提示词序，响应一律不含 answer。回录逐条复用 review_item()，
错词只走 recitation_reviews 重默循环，不进错题本。

P3-4b 听写音频：音频列表与播放对孩子开放（听写必须让孩子听）；播放走 index 化
端点返回 bytes + 嗅探 media_type + no-store，不挂 StaticFiles；挂接只在生成时
校验（文件在 audio_dir 内 + 魔数嗅探），不提供改挂端点。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.models import RecitationItem
from app.models.recitation import DictationSheet
from app.services.dictation import (
    MAX_SHEET_ITEMS,
    RecordReport,
    SheetDetail,
    create_sheet,
    get_sheet,
    list_sheets,
    record_results,
    sheet_item_ids,
)
from app.services.dictation_audio import (
    MAX_AUDIO_NAME_CHARS,
    AudioError,
    AudioNotFound,
    list_audio,
    load_audio,
)
from app.services.recitation import (
    MAX_CANDIDATES,
    RecitationConflict,
    RecitationDuplicate,
    RecitationInvalid,
    RecitationNotFound,
    ReviewOutcome,
    candidate_words,
    create_item,
    due_items,
    list_items,
    review_item,
    update_item,
)
from app.services.recitation_import import (
    MAX_IMPORT_BODY_BYTES,
    MAX_UNIT_CHARS,
    ImportRejected,
    add_candidate_words,
    import_items,
)

router = APIRouter(tags=["recitations"])

ItemStatus = Literal["active", "retired"]
Verdict = Literal["remembered", "forgot"]


class ItemView(BaseModel):
    id: int
    subject: str
    prompt: str
    answer: str | None
    unit: str | None
    status: ItemStatus
    created_by: str
    created_at: datetime


class ItemListResponse(BaseModel):
    items: list[ItemView]
    total: int


class CreateItemRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=500)
    answer: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=80)


class UpdateItemRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=500)
    answer: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=80)
    status: ItemStatus | None = None


class DueItemView(BaseModel):
    item: ItemView
    rung: int
    scheduled_next: date | None
    graduated: bool
    reviewed_on: date | None


class DueListResponse(BaseModel):
    items: list[DueItemView]
    due_total: int
    returned: int
    limit: int
    today: date


class ReviewRequest(BaseModel):
    verdict: Verdict
    reviewed_on: date | None = None
    actor: Literal["student", "parent"] = "student"


class ReviewResponse(BaseModel):
    item: ItemView
    review_id: int
    event_id: int
    verdict: Verdict
    rung: int
    reviewed_on: date
    scheduled_next: date | None
    graduated: bool
    created: bool


class ImportRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=80)
    text: str


SheetStatus = Literal["open", "recorded"]


class SheetView(BaseModel):
    id: int
    created_on: date
    created_by: str
    subject: str
    unit: str | None
    item_ids: list[int]
    status: SheetStatus
    recorded_on: date | None
    audio_ref: str | None


class SheetItemView(BaseModel):
    """卷面条目：只有提示，没有 answer 字段（P3-4 定案⑤）。"""

    item_id: int
    prompt: str
    unit: str | None
    status: ItemStatus


class SheetDetailResponse(BaseModel):
    sheet: SheetView
    items: list[SheetItemView]
    missing_item_ids: list[int]


class SheetListResponse(BaseModel):
    items: list[SheetView]
    total: int
    limit: int
    offset: int


class CreateSheetRequest(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=MAX_SHEET_ITEMS)
    unit: str | None = Field(default=None, max_length=80)
    audio_ref: str | None = Field(default=None, max_length=MAX_AUDIO_NAME_CHARS)


class AudioEntryView(BaseModel):
    index: int
    name: str
    size_bytes: int


class AudioListResponse(BaseModel):
    items: list[AudioEntryView]
    truncated: bool


class SheetResultEntry(BaseModel):
    item_id: int
    verdict: Verdict


class RecordResultsRequest(BaseModel):
    results: list[SheetResultEntry] = Field(min_length=1, max_length=MAX_SHEET_ITEMS)
    reviewed_on: date | None = None


class SheetResultView(BaseModel):
    item_id: int
    prompt: str
    verdict: Verdict
    review_id: int
    rung: int
    reviewed_on: date
    scheduled_next: date | None
    graduated: bool
    created: bool


class SheetSkippedView(BaseModel):
    item_id: int
    reason: Literal["missing", "retired"]


class RecordResultsResponse(BaseModel):
    sheet: SheetView
    results: list[SheetResultView]
    skipped: list[SheetSkippedView]


class ImportDuplicateView(BaseModel):
    line: int
    prompt: str


class ImportErrorView(BaseModel):
    line: int
    field: str | None = None
    reason: str


class ImportResponse(BaseModel):
    imported: int
    duplicates: list[ImportDuplicateView]
    errors: list[ImportErrorView]


class CandidateWordView(BaseModel):
    word: str
    mistake_count: int


class CandidateBatchRequest(BaseModel):
    words: list[str] = Field(min_length=1, max_length=MAX_CANDIDATES)
    unit: str | None = Field(default=None, max_length=MAX_UNIT_CHARS)


class CandidateCreatedView(BaseModel):
    id: int
    prompt: str


class CandidateBatchResponse(BaseModel):
    imported: int
    created: list[CandidateCreatedView]
    duplicates: list[ImportDuplicateView]
    errors: list[ImportErrorView]


def _item_view(item: RecitationItem) -> ItemView:
    return ItemView(
        id=item.id,
        subject=item.subject,
        prompt=item.prompt,
        answer=item.answer,
        unit=item.unit,
        status=item.status,
        created_by=item.created_by,
        created_at=item.created_at,
    )


def _review_response(outcome: ReviewOutcome) -> ReviewResponse:
    review = outcome.review
    return ReviewResponse(
        item=_item_view(outcome.item),
        review_id=review.id,
        event_id=outcome.event.id,
        verdict=review.verdict,
        rung=review.rung,
        reviewed_on=review.reviewed_on,
        scheduled_next=review.scheduled_next,
        graduated=review.scheduled_next is None,
        created=outcome.created,
    )


def _sheet_view(sheet: DictationSheet) -> SheetView:
    return SheetView(
        id=sheet.id,
        created_on=sheet.created_on,
        created_by=sheet.created_by,
        subject=sheet.subject,
        unit=sheet.unit,
        item_ids=list(sheet_item_ids(sheet)),
        status=sheet.status,
        recorded_on=sheet.recorded_on,
        audio_ref=sheet.audio_ref,
    )


def _sheet_detail_response(detail: SheetDetail) -> SheetDetailResponse:
    return SheetDetailResponse(
        sheet=_sheet_view(detail.sheet),
        items=[
            SheetItemView(
                item_id=item.item_id,
                prompt=item.prompt,
                unit=item.unit,
                status=item.status,
            )
            for item in detail.items
        ],
        missing_item_ids=list(detail.missing_item_ids),
    )


def _record_response(report: RecordReport) -> RecordResultsResponse:
    return RecordResultsResponse(
        sheet=_sheet_view(report.sheet),
        results=[
            SheetResultView(
                item_id=outcome.item_id,
                prompt=outcome.prompt,
                verdict=outcome.verdict,
                review_id=outcome.review_id,
                rung=outcome.rung,
                reviewed_on=outcome.reviewed_on,
                scheduled_next=outcome.scheduled_next,
                graduated=outcome.graduated,
                created=outcome.created,
            )
            for outcome in report.results
        ],
        skipped=[
            SheetSkippedView(item_id=entry.item_id, reason=entry.reason)
            for entry in report.skipped
        ],
    )


@router.get("/api/recitations", response_model=ItemListResponse)
async def get_recitations(
    subject: str | None = Query(default=None, max_length=80),
    status: ItemStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> ItemListResponse:
    async with session.begin():
        try:
            result = await list_items(
                session,
                subject=subject,
                status=status,
                limit=limit,
                offset=offset,
            )
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return ItemListResponse(
        items=[_item_view(item) for item in result.items],
        total=result.total,
    )


@router.get("/api/recitations/due", response_model=DueListResponse)
async def get_due_recitations(
    today: date | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> DueListResponse:
    day = today or date.today()
    async with session.begin():
        try:
            due = await due_items(session, day, limit=limit)
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except RecitationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
    return DueListResponse(
        items=[
            DueItemView(
                item=_item_view(entry.item),
                rung=entry.state.rung,
                scheduled_next=entry.state.scheduled_next,
                graduated=entry.state.graduated,
                reviewed_on=entry.state.reviewed_on,
            )
            for entry in due.items
        ],
        due_total=due.due_total,
        returned=due.returned,
        limit=due.limit,
        today=day,
    )


@router.get("/api/recitations/audio", response_model=AudioListResponse)
async def list_dictation_audio(
    settings: Settings = Depends(get_settings),
) -> AudioListResponse:
    """列出 data/audio/ 内合法音频（家长手动放入）；目录不存在 = 空列表。"""

    result = list_audio(settings.audio_dir)
    return AudioListResponse(
        items=[
            AudioEntryView(
                index=entry.index, name=entry.name, size_bytes=entry.size_bytes
            )
            for entry in result.entries
        ],
        truncated=result.truncated,
    )


@router.post(
    "/api/recitations/sheets",
    response_model=SheetDetailResponse,
    dependencies=[Depends(require_parent)],
)
async def create_dictation_sheet(
    payload: CreateSheetRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SheetDetailResponse:
    """生成默写/听写卷（家长）：词序按提交顺序固化；响应不含 answer。

    可选 audio_ref 挂接听写音频：文件必须在 audio_dir 内且魔数嗅探通过，
    否则 422 {message, code}；一卷一音频，不提供改挂。
    """

    async with session.begin():
        try:
            sheet = await create_sheet(
                session,
                item_ids=payload.item_ids,
                unit=payload.unit,
                audio_ref=payload.audio_ref,
                audio_dir=settings.audio_dir,
            )
            detail = await get_sheet(session, sheet.id)
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except AudioError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": str(exc), "code": exc.code},
            ) from None
    return _sheet_detail_response(detail)


@router.get("/api/recitations/sheets", response_model=SheetListResponse)
async def list_dictation_sheets(
    status: SheetStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SheetListResponse:
    async with session.begin():
        try:
            result = await list_sheets(
                session, status=status, limit=limit, offset=offset
            )
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return SheetListResponse(
        items=[_sheet_view(sheet) for sheet in result.sheets],
        total=result.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/recitations/sheets/{sheet_id}", response_model=SheetDetailResponse
)
async def get_dictation_sheet(
    sheet_id: int,
    session: AsyncSession = Depends(get_session),
) -> SheetDetailResponse:
    """卷面详情对孩子开放：只有提示与词序，响应不含 answer（定案⑤）。"""

    async with session.begin():
        try:
            detail = await get_sheet(session, sheet_id)
        except RecitationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
    return _sheet_detail_response(detail)


@router.get("/api/dictation/sheets/{sheet_id}/audio")
async def get_dictation_sheet_audio(
    sheet_id: int,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """孩子区播放听写音频：bytes + 嗅探 media_type + no-store（与原题图端点同构）。

    卷无 audio_ref / 文件被移走都返回 404 稳定码，绝不 500。
    """

    async with session.begin():
        sheet = await session.get(DictationSheet, sheet_id)
    if sheet is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "默写卷不存在", "code": "sheet_not_found"},
        )
    if sheet.audio_ref is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "本卷未挂接听写音频", "code": "audio_not_attached"},
        )
    try:
        data, media_type = load_audio(settings.audio_dir, sheet.audio_ref)
    except AudioNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": str(exc), "code": exc.code},
        ) from None
    except AudioError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "code": exc.code},
        ) from None
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/api/recitations/sheets/{sheet_id}/results",
    response_model=RecordResultsResponse,
    dependencies=[Depends(require_parent)],
)
async def record_dictation_results(
    sheet_id: int,
    payload: RecordResultsRequest,
    session: AsyncSession = Depends(get_session),
) -> RecordResultsResponse:
    """页内勾选回录（家长）：逐条复用 review_item/decide()，整批一个事务。

    open→recorded 单向状态机，重复提交 409；缺失/停用条目跳过并在响应中报告。
    """

    reviewed_on = payload.reviewed_on or date.today()
    async with session.begin():
        try:
            report = await record_results(
                session,
                sheet_id,
                results=[(entry.item_id, entry.verdict) for entry in payload.results],
                reviewed_on=reviewed_on,
                actor="parent",
            )
        except RecitationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RecitationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _record_response(report)


@router.get(
    "/api/recitations/candidates",
    response_model=list[CandidateWordView],
    dependencies=[Depends(require_parent)],
)
async def get_recitation_candidates(
    limit: int = Query(default=MAX_CANDIDATES, ge=1, le=MAX_CANDIDATES),
    session: AsyncSession = Depends(get_session),
) -> list[CandidateWordView]:
    """从 active 英语错题现算候选词；只读，不写任何表。"""

    async with session.begin():
        try:
            candidates = await candidate_words(session, limit=limit)
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return [
        CandidateWordView(
            word=entry.word, mistake_count=entry.mistake_count
        )
        for entry in candidates
    ]


@router.post(
    "/api/recitations/candidates/batch",
    response_model=CandidateBatchResponse,
    dependencies=[Depends(require_parent)],
)
async def add_recitation_candidates(
    payload: CandidateBatchRequest,
    session: AsyncSession = Depends(get_session),
) -> CandidateBatchResponse:
    """家长勾选后入库；answer 留空，重复词逐条报告且不覆盖已有条目。"""

    async with session.begin():
        try:
            report = await add_candidate_words(
                session, words=payload.words, unit=payload.unit
            )
        except ImportRejected as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "批量入库被拒绝",
                    "line": exc.line,
                    "field": exc.field,
                    "reason": str(exc),
                },
            ) from None
    return CandidateBatchResponse(
        imported=report.imported,
        created=[
            CandidateCreatedView(id=item.id, prompt=item.prompt)
            for item in report.created
        ],
        duplicates=[
            ImportDuplicateView(line=row.line, prompt=row.prompt)
            for row in report.duplicates
        ],
        errors=[
            ImportErrorView(
                line=issue.line, field=issue.field, reason=issue.reason
            )
            for issue in report.issues
        ],
    )


@router.post(
    "/api/recitations/import",
    response_model=ImportResponse,
    dependencies=[Depends(require_parent)],
)
async def import_recitations(
    payload: ImportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ImportResponse:
    raw = await request.body()
    if len(raw) > MAX_IMPORT_BODY_BYTES:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "导入被拒绝",
                "line": None,
                "field": "text",
                "reason": f"请求体超过 {MAX_IMPORT_BODY_BYTES // 1024}KB",
            },
        )
    async with session.begin():
        try:
            report = await import_items(
                session, subject=payload.subject, text=payload.text
            )
        except ImportRejected as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "导入被拒绝",
                    "line": exc.line,
                    "field": exc.field,
                    "reason": str(exc),
                },
            ) from None
    return ImportResponse(
        imported=report.imported,
        duplicates=[
            ImportDuplicateView(line=row.line, prompt=row.prompt)
            for row in report.duplicates
        ],
        errors=[
            ImportErrorView(
                line=issue.line, field=issue.field, reason=issue.reason
            )
            for issue in report.issues
        ],
    )


@router.post(
    "/api/recitations",
    response_model=ItemView,
    dependencies=[Depends(require_parent)],
)
async def create_recitation(
    payload: CreateItemRequest,
    session: AsyncSession = Depends(get_session),
) -> ItemView:
    async with session.begin():
        try:
            item = await create_item(
                session,
                subject=payload.subject,
                prompt=payload.prompt,
                answer=payload.answer,
                unit=payload.unit,
                created_by="parent",
            )
        except RecitationDuplicate as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _item_view(item)


@router.patch(
    "/api/recitations/{item_id}",
    response_model=ItemView,
    dependencies=[Depends(require_parent)],
)
async def patch_recitation(
    item_id: int,
    payload: UpdateItemRequest,
    session: AsyncSession = Depends(get_session),
) -> ItemView:
    async with session.begin():
        try:
            item = await update_item(
                session,
                item_id,
                prompt=payload.prompt,
                answer=payload.answer,
                unit=payload.unit,
                status=payload.status,
            )
        except RecitationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RecitationDuplicate as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _item_view(item)


@router.post(
    "/api/recitations/{item_id}/review", response_model=ReviewResponse
)
async def review_recitation(
    item_id: int,
    payload: ReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    reviewed_on = payload.reviewed_on or date.today()
    async with session.begin():
        try:
            outcome = await review_item(
                session,
                item_id,
                verdict=payload.verdict,
                reviewed_on=reviewed_on,
                actor=payload.actor,
            )
        except RecitationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except RecitationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RecitationInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _review_response(outcome)
