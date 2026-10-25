"""兜底通道：豆包 JSON 导入 → 确定性校验/归一 → import_batches + ingestion_drafts。

导入全程不调模型（AGENTS §5）；sha256 对原始报文去重——
同一文件重复导入返回旧 batch 并置 duplicate=true（"重复导入提醒"）。
坏项跳过并逐条报告（index/field/reason），不静默截断超长内容。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import ImportBatch, IngestionDraft
from app.services.events import create_import_batch
from app.services.ingestion import (
    MAX_BATCH_BODY_BYTES,
    dumps_draft,
    validate_and_normalize,
    validate_envelope,
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
    if len(raw) > MAX_BATCH_BODY_BYTES:
        raise HTTPException(status_code=413, detail="导入报文超过 5MB 上限，请拆分")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {exc.msg}") from None
    try:
        channel, items = validate_envelope(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    result = validate_and_normalize(items)
    if not result.drafts:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "没有可导入的合法题目",
                "errors": [asdict(e) for e in result.errors],
            },
        )

    digest = hashlib.sha256(raw).hexdigest()
    async with session.begin():
        batch, created = await create_import_batch(
            session, channel, digest, item_count=len(result.drafts)
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
    draft_count = (
        await session.execute(
            select(func.count())
            .select_from(IngestionDraft)
            .where(IngestionDraft.import_batch_id == batch.id)
        )
    ).scalar_one()
    return ImportResult(
        batch_id=batch.id,
        status=batch.status,
        duplicate=not created,
        draft_count=draft_count,
        accepted_count=len(result.drafts),
        dropped_unknown_fields=result.dropped_unknown_fields,
        errors=[ImportErrorItem(**asdict(e)) for e in result.errors],
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
