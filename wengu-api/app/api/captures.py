"""主通道：手机拍照 → HTTP 秒传 → 本地存储 → photo_captures 落库（P1-3）。

零模型调用；sha256 幂等去重（重传/重试/重启返回已有行）；
Phase 0 闸门内"触发"只到落库与显式切片为止——不做识别、不做自动入库
（P1-3b 的 items 是预处理产物，P1-4 才消费）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models import PhotoCapture, PhotoCaptureItem
from app.preprocess.ocr import get_ocr_engine
from app.services.events import create_photo_capture
from app.services.slicer import Slice, SliceError, SlicePlan, plan_slices

router = APIRouter(tags=["captures"])

MAX_CAPTURE_BYTES = 20 * 1024 * 1024
_CHUNK = 1024 * 1024
MAX_SLICE_ITEMS = 60  # 超过视为 OCR 噪声失控，拒绝（双页通常 ≤30 题）

# magic bytes 嗅探（声明的 content-type 不可信，以实际字节为准）
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
]
_WEBP_OFFSET = 8
_WEBP_MAGIC = b"WEBP"


def _sniff_image(head: bytes) -> tuple[str, str] | None:
    for signature, ext, mime in _SIGNATURES:
        if head.startswith(signature):
            return ext, mime
    if head[:4] == b"RIFF" and head[_WEBP_OFFSET : _WEBP_OFFSET + 4] == _WEBP_MAGIC:
        return "webp", "image/webp"
    return None


class CaptureCreated(BaseModel):
    capture_id: int
    status: str
    duplicate: bool


class CaptureInfo(BaseModel):
    id: int
    status: str
    source: str
    stored_path: str
    original_name: str | None
    created_at: datetime


class CaptureList(BaseModel):
    total: int
    captures: list[CaptureInfo]


@router.post("/api/captures", response_model=CaptureCreated, status_code=201)
async def upload_capture(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> CaptureCreated:
    settings = get_settings()
    uploads_dir: Path = settings.uploads_dir  # type: ignore[assignment]
    uploads_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = uploads_dir / f".incoming-{uuid.uuid4().hex}"
    hasher = hashlib.sha256()
    head = b""
    size = 0
    try:
        with tmp_path.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_CAPTURE_BYTES:
                    raise HTTPException(status_code=413, detail="照片超过 20MB 上限")
                if len(head) < 16:
                    head += chunk[: 16 - len(head)]
                hasher.update(chunk)
                out.write(chunk)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    sniffed = _sniff_image(head)
    if sniffed is None:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="仅支持 JPEG/PNG/WebP 照片")
    ext, mime = sniffed
    if file.content_type and file.content_type not in (mime, "application/octet-stream"):
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=415, detail=f"声明的 content-type {file.content_type} 与图片字节不符"
        )

    digest = hasher.hexdigest()
    original_name = (file.filename or "").strip()[:200] or None

    # 查与写同处一个事务：先查后写，同内容重传复用旧行不产生孤儿文件
    async with session.begin():
        existing = (
            await session.execute(
                select(PhotoCapture).where(PhotoCapture.sha256 == digest)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing_abs = uploads_dir / existing.stored_path
            if not existing_abs.exists():
                existing_abs.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp_path, existing_abs)  # 自愈：行在文件丢则补写
            else:
                tmp_path.unlink(missing_ok=True)
            return CaptureCreated(
                capture_id=existing.id, status=existing.status, duplicate=True
            )

        month_dir = uploads_dir / datetime.now(UTC).strftime("%Y/%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        final_path = month_dir / f"{digest}.{ext}"
        os.replace(tmp_path, final_path)
        stored_path = final_path.relative_to(uploads_dir).as_posix()
        capture, created = await create_photo_capture(
            session,
            digest,
            stored_path=stored_path,
            original_name=original_name,
        )
    return CaptureCreated(capture_id=capture.id, status=capture.status, duplicate=not created)


@router.get("/api/captures", response_model=CaptureList)
async def list_captures(
    status: Literal["pending", "processed", "discarded"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> CaptureList:
    stmt = select(PhotoCapture).order_by(PhotoCapture.id.desc())
    if status is not None:
        stmt = stmt.where(PhotoCapture.status == status)
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return CaptureList(
        total=len(rows),
        captures=[CaptureInfo.model_validate(r, from_attributes=True) for r in rows],
    )


@router.get("/api/captures/{capture_id}", response_model=CaptureInfo)
async def get_capture(
    capture_id: int, session: AsyncSession = Depends(get_session)
) -> CaptureInfo:
    row = (
        await session.execute(
            select(PhotoCapture).where(PhotoCapture.id == capture_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="capture 不存在")
    return CaptureInfo.model_validate(row, from_attributes=True)


class SliceItemInfo(BaseModel):
    seq: int
    stored_path: str
    bbox: tuple[int, int, int, int]
    anchor_label: str | None
    status: str


class SliceResult(BaseModel):
    capture_id: int
    status: str
    already_sliced: bool
    header_line_count: int
    column_split_x: int | None
    item_count: int
    items: list[SliceItemInfo]


def _item_info(row: PhotoCaptureItem) -> SliceItemInfo:
    x1, y1, x2, y2 = json.loads(row.bbox_json)
    return SliceItemInfo(
        seq=row.seq,
        stored_path=row.stored_path,
        bbox=(x1, y1, x2, y2),
        anchor_label=row.anchor_label,
        status=row.status,
    )


async def _fetch_items(session: AsyncSession, capture_id: int) -> list[PhotoCaptureItem]:
    rows = (
        await session.execute(
            select(PhotoCaptureItem)
            .where(PhotoCaptureItem.photo_capture_id == capture_id)
            .order_by(PhotoCaptureItem.seq)
        )
    ).scalars().all()
    return list(rows)


@router.post("/api/captures/{capture_id}/slice", response_model=SliceResult)
async def slice_capture(
    capture_id: int,
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> SliceResult:
    """本地 OCR 行聚类切题（P1-3b）：不联网、不调 VLM；显式触发、幂等可重切。"""

    # 读事务：取 capture + 已有 items（404/幂等返回都基于这份快照）
    async with session.begin():
        capture = (
            await session.execute(
                select(PhotoCapture).where(PhotoCapture.id == capture_id)
            )
        ).scalar_one_or_none()
        if capture is None:
            raise HTTPException(status_code=404, detail="capture 不存在")
        existing = await _fetch_items(session, capture_id)
    uploads_dir: Path = get_settings().uploads_dir  # type: ignore[assignment]
    image_path = uploads_dir / capture.stored_path
    if not image_path.exists():
        raise HTTPException(status_code=410, detail="母图文件缺失，无法切片")

    if existing and not force:
        return SliceResult(
            capture_id=capture_id,
            status=capture.status,
            already_sliced=True,
            header_line_count=0,
            column_split_x=None,
            item_count=len(existing),
            items=[_item_info(r) for r in existing],
        )

    def _do_slice() -> tuple[SlicePlan, list[tuple[Slice, str]]]:
        from PIL import Image

        engine = get_ocr_engine()
        lines = engine.detect_lines(image_path)
        with Image.open(image_path) as im:
            image_size = im.size
            plan = plan_slices(lines, image_size)
            if len(plan.slices) > MAX_SLICE_ITEMS:
                raise SliceError(f"切出 {len(plan.slices)} 块，超过上限 {MAX_SLICE_ITEMS}，疑似 OCR 噪声")
            month = datetime.now(UTC).strftime("%Y/%m")
            prefix = capture.sha256[:16]
            crops: list[tuple[Slice, str]] = []
            for s in plan.slices:
                rel = f"slices/{month}/{prefix}-{s.seq:02d}.png"
                out = uploads_dir / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                im.crop(s.bbox).save(out, format="PNG")
                crops.append((s, rel))
            return plan, crops

    try:
        plan, crops = await asyncio.to_thread(_do_slice)
    except SliceError as exc:
        # force 重切失败时保留上一次成功的切片结果，不把状态打回失败
        if not existing:
            async with session.begin():
                capture.status = "slice_failed"
        raise HTTPException(status_code=422, detail=str(exc)) from None

    new_paths = {rel for _, rel in crops}
    stale_paths = [r.stored_path for r in existing if r.stored_path not in new_paths]

    now = datetime.now(UTC)
    async with session.begin():
        if force:
            for row in existing:
                await session.delete(row)
            await session.flush()
        for s, rel in crops:
            session.add(
                PhotoCaptureItem(
                    photo_capture_id=capture_id,
                    seq=s.seq,
                    stored_path=rel,
                    bbox_json=json.dumps(list(s.bbox)),
                    anchor_label=s.anchor_label,
                    created_at=now,
                )
            )
        capture.status = "sliced"
    # 重切后题数变少时，清理旧序号裁图，避免磁盘孤儿（DB 行已先删）
    for stale in stale_paths:
        (uploads_dir / stale).unlink(missing_ok=True)
    items = await _fetch_items(session, capture_id)
    return SliceResult(
        capture_id=capture_id,
        status="sliced",
        already_sliced=False,
        header_line_count=plan.header_line_count,
        column_split_x=plan.column_split_x,
        item_count=len(items),
        items=[_item_info(r) for r in items],
    )


@router.get("/api/captures/{capture_id}/items", response_model=SliceResult)
async def list_capture_items(
    capture_id: int, session: AsyncSession = Depends(get_session)
) -> SliceResult:
    capture = (
        await session.execute(
            select(PhotoCapture).where(PhotoCapture.id == capture_id)
        )
    ).scalar_one_or_none()
    if capture is None:
        raise HTTPException(status_code=404, detail="capture 不存在")
    items = await _fetch_items(session, capture_id)
    return SliceResult(
        capture_id=capture_id,
        status=capture.status,
        already_sliced=bool(items),
        header_line_count=0,
        column_split_x=None,
        item_count=len(items),
        items=[_item_info(r) for r in items],
    )
