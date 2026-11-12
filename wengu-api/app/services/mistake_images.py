"""P1-16 错题原图附件：上传 / 读取 / 删除（孩子区，零模型）。

problem_images 是 mistake_versions 当前版本行上的 JSON 相对路径数组。该表被数据库
触发器钉死为 append-only（UPDATE/DELETE 直接 RAISE），故上传/删除都**追加新版本**承载
更新后的数组、其余内容/标签全量透传并 bump current_version——与 append_label_version
同构，复用 append_mistake_version 这唯一版本写入路径，不原地改、不开第二条路径。
落盘一律 uploads/<mistake_id>/<uuid4>.<ext>——原始文件名绝不进路径；读取/删除都断言
解析结果在 uploads_dir 内。不 OCR、不调模型、不挂 StaticFiles、不收 SVG/HTML。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Mistake, MistakeVersion
from app.services.events import append_mistake_version
from app.services.mistakes import (
    MistakeNotFound,
    get_latest_version,
    get_mistake,
    load_concept_ids,
    load_problem_images,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_MISTAKE = 3

_JPEG = "image/jpeg"
_PNG = "image/png"
_WEBP = "image/webp"

# MIME 白名单 → 落盘扩展名；SVG/HTML 不在表内，一律拒绝（XSS 面）。
ALLOWED_MIME: dict[str, str] = {_JPEG: "jpg", _PNG: "png", _WEBP: "webp"}
_EXT_TO_MIME: dict[str, str] = {ext: mime for mime, ext in ALLOWED_MIME.items()}


class ImageError(ValueError):
    """校验失败，带稳定码；API 转 422 {message, code}。"""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class ImageNotFound(LookupError):
    """错题/序号/文件缺失；API 转 404。"""


def _sniff(data: bytes) -> str | None:
    """只看魔数，不看扩展名/声明类型。"""
    if data.startswith(b"\xff\xd8\xff"):
        return _JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _WEBP
    return None


def _resolve_within_uploads(settings: Settings, rel_path: str) -> Path:
    root = settings.uploads_dir.resolve()
    candidate = (settings.data_dir / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise ImageError("图片路径越界", "image_path_invalid")
    return candidate


def store_image(
    settings: Settings, mistake_id: int, data: bytes, declared_mime: str
) -> str:
    """校验大小/MIME/魔数后落盘，返回相对 data_dir 的路径（与备份 arcname 同形）。"""
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("图片不能超过 5MB", "image_too_large")
    if declared_mime not in ALLOWED_MIME:
        raise ImageError("只接受 JPEG/PNG/WebP 图片", "image_mime_not_allowed")
    if _sniff(data) != declared_mime:
        raise ImageError("图片内容与声明类型不符", "image_magic_mismatch")

    filename = f"{uuid.uuid4()}.{ALLOWED_MIME[declared_mime]}"
    rel_path = f"uploads/{mistake_id}/{filename}"
    target = settings.uploads_dir / str(mistake_id) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel_path


def read_image(settings: Settings, rel_path: str) -> tuple[bytes, str]:
    path = _resolve_within_uploads(settings, rel_path)
    if not path.is_file():
        raise ImageNotFound("图片文件不存在")
    media_type = _EXT_TO_MIME.get(path.suffix.lower().lstrip("."), "application/octet-stream")
    return path.read_bytes(), media_type


async def _mistake_and_version(
    session: AsyncSession, mistake_id: int
) -> tuple[Mistake, MistakeVersion]:
    mistake = await get_mistake(session, mistake_id)
    latest = await get_latest_version(session, mistake_id)
    if latest is None:
        raise MistakeNotFound("错题内容版本缺失")
    return mistake, latest


async def _append_image_version(
    session: AsyncSession,
    mistake: Mistake,
    latest: MistakeVersion,
    images: list[str],
) -> MistakeVersion:
    """追加新版本承载更新后的 problem_images，其余内容/标签全量透传。

    mistake_versions 是 append-only，不能原地改；bump current_version 与改标签同构，
    使详情页/检索（按 max version）与乐观锁（base_version）口径一致。
    """

    version = await append_mistake_version(
        session,
        mistake.id,
        problem_text=latest.problem_text,
        problem_images=json.dumps(images, ensure_ascii=False),
        standard_answer=latest.standard_answer,
        student_answer=latest.student_answer,
        is_correct=latest.is_correct,
        status=latest.status,
        suggested_category_id=latest.suggested_category_id,
        category_confidence=latest.category_confidence,
        suggested_concept_ids=load_concept_ids(latest.suggested_concept_ids_json),
        confirmed_category_id=latest.confirmed_category_id,
        confirmed_concept_ids=load_concept_ids(latest.confirmed_concept_ids_json),
        confirmed_by=latest.confirmed_by,
        suggested_error_cause=latest.suggested_error_cause,
        confirmed_error_cause=latest.confirmed_error_cause,
    )
    mistake.current_version = version.version
    mistake.updated_at = version.created_at
    await session.flush()
    return version


async def add_image(
    session: AsyncSession,
    settings: Settings,
    mistake_id: int,
    *,
    data: bytes,
    declared_mime: str,
) -> MistakeVersion:
    mistake, latest = await _mistake_and_version(session, mistake_id)
    images = load_problem_images(latest.problem_images)
    if len(images) >= MAX_IMAGES_PER_MISTAKE:
        raise ImageError(
            f"每道错题最多 {MAX_IMAGES_PER_MISTAKE} 张原题图", "image_limit_reached"
        )
    rel_path = store_image(settings, mistake_id, data, declared_mime)
    images.append(rel_path)
    return await _append_image_version(session, mistake, latest, images)


async def get_image_for_index(
    session: AsyncSession, settings: Settings, mistake_id: int, index: int
) -> tuple[bytes, str]:
    _, latest = await _mistake_and_version(session, mistake_id)
    images = load_problem_images(latest.problem_images)
    if index < 0 or index >= len(images):
        raise ImageNotFound("图片序号不存在")
    return read_image(settings, images[index])


async def remove_image(
    session: AsyncSession, settings: Settings, mistake_id: int, index: int
) -> MistakeVersion:
    mistake, latest = await _mistake_and_version(session, mistake_id)
    images = load_problem_images(latest.problem_images)
    if index < 0 or index >= len(images):
        raise ImageNotFound("图片序号不存在")
    # 先断言删除路径在 uploads 内，再改数组，越界时不动数据库。
    path = _resolve_within_uploads(settings, images[index])
    images.pop(index)
    version = await _append_image_version(session, mistake, latest, images)
    path.unlink(missing_ok=True)
    return version
