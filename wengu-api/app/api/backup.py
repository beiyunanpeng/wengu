"""P5-2 家长区一键备份：导出 / 列表 / 下载（全部家长专属）。

备份含全部错题与事实源，属敏感面，故整只路由挂 `require_parent`。
只做导出与下载；恢复是"整库替换"的停机操作，走 `scripts/restore.ps1`，
本系统不提供运行中热替换 SQLite 的在线恢复。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.session import require_parent
from app.core.config import Settings, get_settings
from app.services.backup import (
    KEEP_BACKUPS,
    BackupError,
    BackupNameError,
    BackupNotFound,
    create_backup,
    list_backups,
    resolve_backup,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backup"], dependencies=[Depends(require_parent)])


class BackupManifestSummary(BaseModel):
    version: int
    created_at: str
    alembic_version: str | None
    counts: dict[str, int]
    file_count: int


class BackupExportResponse(BaseModel):
    filename: str
    sha256: str
    size_bytes: int
    manifest: BackupManifestSummary


class BackupFileInfo(BaseModel):
    filename: str
    created_at: str
    size_bytes: int
    sha256: str


class BackupListResponse(BaseModel):
    items: list[BackupFileInfo]
    total: int
    keep: int


def _summary(manifest: dict[str, Any]) -> BackupManifestSummary:
    return BackupManifestSummary(
        version=int(manifest.get("version", 0)),
        created_at=str(manifest.get("created_at", "")),
        alembic_version=manifest.get("alembic_version"),
        counts={
            str(key): int(value)
            for key, value in (manifest.get("counts") or {}).items()
        },
        file_count=len(manifest.get("files") or []),
    )


@router.post("/api/backup/export", response_model=BackupExportResponse)
async def export_backup(
    settings: Settings = Depends(get_settings),
) -> BackupExportResponse:
    try:
        result = await asyncio.to_thread(create_backup, settings)
    except BackupError as exc:
        logger.warning("请求触发备份失败：%s", exc)
        raise HTTPException(
            status_code=500, detail="备份失败，请检查服务日志"
        ) from exc
    return BackupExportResponse(
        filename=result.path.name,
        sha256=result.sha256,
        size_bytes=result.size_bytes,
        manifest=_summary(result.manifest),
    )


@router.get("/api/backup/list", response_model=BackupListResponse)
async def backup_list(
    settings: Settings = Depends(get_settings),
) -> BackupListResponse:
    items = await asyncio.to_thread(list_backups, settings)
    return BackupListResponse(
        items=[
            BackupFileInfo(
                filename=item.filename,
                created_at=item.created_at,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
            )
            for item in items
        ],
        total=len(items),
        keep=KEEP_BACKUPS,
    )


@router.get("/api/backup/download/{name}")
async def download_backup(
    name: str,
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    try:
        path = resolve_backup(settings, name)
    except BackupNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BackupNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )
