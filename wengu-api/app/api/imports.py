"""兜底通道：豆包 JSON 导入 → 确定性校验/归一 → import_batches + ingestion_drafts。

导入全程不调模型（AGENTS §5）；sha256 对原始报文去重——
同一文件重复导入返回旧 batch 并置 duplicate=true（"重复导入提醒"）。
坏项跳过并逐条报告（index/field/reason），不静默截断超长内容。
与目录监听（P1-3d services/inbox.py）共用同一个落库核心。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models import ImportBatch, IngestionDraft
from app.services.concepts import CategoryNotFound
from app.services.inbox import (
    NoValidItemsError,
    PayloadEnvelopeError,
    PayloadJsonError,
    PayloadTooLargeError,
    ingest_raw_payload,
)
from app.services.ingestion import MAX_BATCH_BODY_BYTES, MAX_ITEMS_PER_BATCH, SUPPORTED_CHANNELS
from app.services.intake import (
    DraftGateError,
    DraftNotFound,
    list_drafts,
    promote_draft,
)
from app.services.mistakes import MistakeConflict, error_cause_label
from app.services.review import ReviewError, ReviewSubjectError

router = APIRouter(tags=["imports"])


class ImportErrorItem(BaseModel):
    index: int
    field: str
    reason: str


class ImportResult(BaseModel):
    batch_id: int
    status: str
    duplicate: bool
    draft_count: int
    accepted_count: int
    dropped_unknown_fields: int
    errors: list[ImportErrorItem]


class DraftInfo(BaseModel):
    id: int
    seq: int
    status: str
    has_placeholder: bool
    is_incomplete: bool
    normalized: dict


class DraftList(BaseModel):
    total: int
    drafts: list[DraftInfo]


class BatchInfo(BaseModel):
    id: int
    channel: str
    item_count: int | None
    status: str
    created_at: datetime


class IntakeSuggestion(BaseModel):
    topic_id: str | None
    topic_name: str | None
    error_cause: str | None
    error_cause_label: str | None
    source: str | None


class IntakeDraftInfo(BaseModel):
    id: int
    batch_id: int
    filename: str | None
    seq: int
    status: str
    has_placeholder: bool
    is_incomplete: bool
    created_at: datetime
    subject: str
    problem_text: str
    student_answer: str
    standard_answer: str
    source_ref: str
    captured_at: str
    suggestion: IntakeSuggestion
    grading_id: int | None
    mistake_id: int | None


class IntakeDraftList(BaseModel):
    items: list[IntakeDraftInfo]
    total: int
    limit: int
    offset: int


class DraftConfirmRequest(BaseModel):
    primary_topic_id: str | None = Field(default=None, max_length=64)
    standard_answer: str | None = Field(default=None, max_length=500)
    error_cause: str | None = Field(default=None, max_length=32)
    concept_ids: list[int] = Field(default_factory=list, max_length=10)
    question_type: Literal["objective", "process"] = "objective"
    actor: Literal["student", "parent"] = "student"


class DraftConfirmResponse(BaseModel):
    draft_id: int
    grading_id: int
    mistake_id: int
    primary_topic_id: str | None
    standard_answer: str
    due_on: date | None
    already_promoted: bool


class InboxInfo(BaseModel):
    path: str
    channels: list[str]
    max_items: int
    max_body_bytes: int


@router.post("/api/imports", response_model=ImportResult, status_code=201)
async def import_json(
    request: Request, session: AsyncSession = Depends(get_session)
) -> ImportResult:
    raw = await request.body()
    try:
        outcome = await ingest_raw_payload(session, raw)
    except PayloadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except PayloadJsonError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except PayloadEnvelopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except NoValidItemsError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "errors": [asdict(e) for e in exc.errors],
            },
        ) from None
    return ImportResult(
        batch_id=outcome.batch_id,
        status=outcome.status,
        duplicate=outcome.duplicate,
        draft_count=outcome.draft_count,
        accepted_count=outcome.accepted_count,
        dropped_unknown_fields=outcome.dropped_unknown_fields,
        errors=[ImportErrorItem(**asdict(e)) for e in outcome.errors],
    )


@router.get("/api/imports/drafts", response_model=IntakeDraftList)
async def list_intake_drafts(
    status: Literal["draft", "promoted", "all"] = "draft",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> IntakeDraftList:
    """核对页草稿队列：并排回显题目/错答/正答 + 建议值；纯查询。"""

    async with session.begin():
        items, total = await list_drafts(
            session, status=status, limit=limit, offset=offset
        )
        return IntakeDraftList(
            items=[
                IntakeDraftInfo(
                    id=item.draft.id,
                    batch_id=item.draft.import_batch_id,
                    filename=item.filename,
                    seq=item.draft.seq,
                    status=item.draft.status,
                    has_placeholder=item.draft.has_placeholder,
                    is_incomplete=item.draft.is_incomplete,
                    created_at=item.draft.created_at,
                    subject=item.normalized.get("subject", ""),
                    problem_text=item.normalized.get("problem_text", ""),
                    student_answer=item.normalized.get("student_answer", ""),
                    standard_answer=item.normalized.get("standard_answer", ""),
                    source_ref=item.normalized.get("source_ref", ""),
                    captured_at=item.normalized.get("captured_at", ""),
                    suggestion=IntakeSuggestion(
                        topic_id=item.suggested_topic_id,
                        topic_name=item.suggested_topic_name,
                        error_cause=item.suggested_error_cause,
                        error_cause_label=error_cause_label(
                            item.suggested_error_cause
                        ),
                        source=item.suggestion_source,
                    ),
                    grading_id=item.grading_id,
                    mistake_id=item.mistake_id,
                )
                for item in items
            ],
            total=total,
            limit=limit,
            offset=offset,
        )


@router.post(
    "/api/imports/drafts/{draft_id}/confirm", response_model=DraftConfirmResponse
)
async def confirm_intake_draft(
    draft_id: int,
    payload: DraftConfirmRequest,
    session: AsyncSession = Depends(get_session),
) -> DraftConfirmResponse:
    """一键确认转正：建批改单 → 唯一写入路径建错题 → 首次排期（幂等）。"""

    async with session.begin():
        try:
            result = await promote_draft(
                session,
                draft_id,
                primary_topic_id=payload.primary_topic_id,
                standard_answer=payload.standard_answer,
                error_cause=payload.error_cause,
                concept_ids=tuple(payload.concept_ids),
                question_type=payload.question_type,
                actor=payload.actor,
            )
        except DraftNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except DraftGateError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": str(exc), "code": exc.code},
            ) from None
        except (MistakeConflict, CategoryNotFound) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except ReviewSubjectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return DraftConfirmResponse(
            draft_id=result.draft_id,
            grading_id=result.grading_id,
            mistake_id=result.mistake_id,
            primary_topic_id=result.primary_topic_id,
            standard_answer=result.standard_answer,
            due_on=result.due_on,
            already_promoted=result.already_promoted,
        )


@router.get("/api/imports/inbox", response_model=InboxInfo)
async def inbox_info() -> InboxInfo:
    """导入页展示：真实监听目录与单批上限（纯查询，不读库、不调模型）。"""

    settings = get_settings()
    return InboxInfo(
        path=str(settings.inbox_path),
        channels=list(SUPPORTED_CHANNELS),
        max_items=MAX_ITEMS_PER_BATCH,
        max_body_bytes=MAX_BATCH_BODY_BYTES,
    )


@router.get("/api/imports/{batch_id}", response_model=BatchInfo)
async def get_batch(batch_id: int, session: AsyncSession = Depends(get_session)) -> BatchInfo:
    row = (
        await session.execute(select(ImportBatch).where(ImportBatch.id == batch_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="batch 不存在")
    return BatchInfo.model_validate(row, from_attributes=True)


@router.get("/api/imports/{batch_id}/drafts", response_model=DraftList)
async def list_batch_drafts(
    batch_id: int, session: AsyncSession = Depends(get_session)
) -> DraftList:
    exists = (
        await session.execute(
            select(ImportBatch.id).where(ImportBatch.id == batch_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="batch 不存在")
    rows = (
        await session.execute(
            select(IngestionDraft)
            .where(IngestionDraft.import_batch_id == batch_id)
            .order_by(IngestionDraft.seq)
        )
    ).scalars().all()
    return DraftList(
        total=len(rows),
        drafts=[
            DraftInfo(
                id=r.id,
                seq=r.seq,
                status=r.status,
                has_placeholder=r.has_placeholder,
                is_incomplete=r.is_incomplete,
                normalized=json.loads(r.normalized_json),
            )
            for r in rows
        ],
    )
