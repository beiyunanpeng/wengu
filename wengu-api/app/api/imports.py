"""兜底通道：豆包 JSON 导入 → 确定性校验/归一 → import_batches + ingestion_drafts。

导入全程不调模型（AGENTS §5）；sha256 对原始报文去重——
同一文件重复导入返回旧 batch 并置 duplicate=true（"重复导入提醒"）。
坏项跳过并逐条报告（index/field/reason），不静默截断超长内容。
与目录监听（P1-3d services/inbox.py）共用同一个落库核心。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import ImportBatch, IngestionDraft
from app.services.inbox import (
    NoValidItemsError,
    PayloadEnvelopeError,
    PayloadJsonError,
    PayloadTooLargeError,
    ingest_raw_payload,
)

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


@router.get("/api/imports/{batch_id}", response_model=BatchInfo)
async def get_batch(batch_id: int, session: AsyncSession = Depends(get_session)) -> BatchInfo:
    row = (
        await session.execute(select(ImportBatch).where(ImportBatch.id == batch_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="batch 不存在")
    return BatchInfo.model_validate(row, from_attributes=True)


@router.get("/api/imports/{batch_id}/drafts", response_model=DraftList)
async def list_drafts(
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
