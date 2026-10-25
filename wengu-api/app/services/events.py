"""幂等写入骨架：重复导入/重试/重启不产生重复错题·事件·计数（AGENTS §5）。

所有函数共享一个模式：唯一约束做最终防线，命中冲突时返回已存在的行。
调用方负责外层事务（session.begin()）；幂等冲突用 SAVEPOINT 消化，不污染外层事务。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImportBatch, LearningEvent, MistakeVersion, PhotoCapture


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _insert_or_fetch(
    session: AsyncSession,
    entity: Any,
    conflict_where: Any,
) -> tuple[Any, bool]:
    """SAVEPOINT 内 flush；唯一约束冲突 → 回滚到 savepoint 并取回已有行。"""

    try:
        async with session.begin_nested():
            session.add(entity)
            await session.flush()
        return entity, True
    except IntegrityError:
        existing = (await session.execute(conflict_where)).scalar_one()
        return existing, False


async def record_event(
    session: AsyncSession,
    event_type: str,
    actor: str,
    *,
    idempotency_key: str,
    mistake_id: int | None = None,
    payload: Mapping[str, Any] | str | None = None,
) -> tuple[LearningEvent, bool]:
    """append-only 事实写入。同 idempotency_key 重放 → 返回已有事件，created=False。"""

    if isinstance(payload, Mapping):
        payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    event = LearningEvent(
        type=event_type,
        actor=actor,
        mistake_id=mistake_id,
        payload=payload,
        occurred_at=_utcnow(),
        idempotency_key=idempotency_key,
    )
    conflict_where = select(LearningEvent).where(
        LearningEvent.idempotency_key == idempotency_key
    )
    return await _insert_or_fetch(session, event, conflict_where)


async def create_import_batch(
    session: AsyncSession,
    channel: str,
    sha256: str,
    *,
    filename: str | None = None,
    item_count: int | None = None,
) -> tuple[ImportBatch, bool]:
    """sha256 去重：同一文件重复导入返回旧 batch（P1-3 '重复导入提醒'的根基）。"""

    batch = ImportBatch(
        channel=channel,
        sha256=sha256,
        filename=filename,
        item_count=item_count,
        created_at=_utcnow(),
    )
    conflict_where = select(ImportBatch).where(ImportBatch.sha256 == sha256)
    return await _insert_or_fetch(session, batch, conflict_where)


async def create_photo_capture(
    session: AsyncSession,
    sha256: str,
    *,
    stored_path: str,
    original_name: str | None = None,
    source: str = "phone",
    status: str = "pending",
) -> tuple[PhotoCapture, bool]:
    """sha256 去重：同一照片重传/重试/重启返回旧行（P1-3 幂等落库）。"""

    capture = PhotoCapture(
        sha256=sha256,
        stored_path=stored_path,
        original_name=original_name,
        source=source,
        status=status,
        created_at=_utcnow(),
    )
    conflict_where = select(PhotoCapture).where(PhotoCapture.sha256 == sha256)
    return await _insert_or_fetch(session, capture, conflict_where)


async def append_mistake_version(
    session: AsyncSession,
    mistake_id: int,
    *,
    problem_text: str | None = None,
    problem_images: str | None = None,
    standard_answer: str | None = None,
    student_answer: str | None = None,
    is_correct: bool | None = None,
    status: str = "pending",
    suggested_category_id: str | None = None,
    category_confidence: float | None = None,
    suggested_concept_ids: Sequence[int] | None = None,
    confirmed_category_id: str | None = None,
    confirmed_concept_ids: Sequence[int] | None = None,
    confirmed_by: str | None = None,
    suggested_error_cause: str | None = None,
    confirmed_error_cause: str | None = None,
) -> MistakeVersion:
    """只追加版本：version = max+1（单写实例内安全），UNIQUE 约束做最终防线。"""

    def _ids_json(values: Sequence[int] | None) -> str:
        if values is None:
            return "[]"
        return json.dumps(sorted({int(value) for value in values}), ensure_ascii=False)

    current_max = (
        await session.execute(
            select(MistakeVersion.version)
            .where(MistakeVersion.mistake_id == mistake_id)
            .order_by(MistakeVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    version = MistakeVersion(
        mistake_id=mistake_id,
        version=(current_max or 0) + 1,
        problem_text=problem_text,
        problem_images=problem_images,
        standard_answer=standard_answer,
        student_answer=student_answer,
        is_correct=is_correct,
        status=status,
        suggested_category_id=suggested_category_id,
        category_confidence=category_confidence,
        suggested_concept_ids_json=_ids_json(suggested_concept_ids),
        confirmed_category_id=confirmed_category_id,
        confirmed_concept_ids_json=_ids_json(confirmed_concept_ids),
        confirmed_by=confirmed_by,
        suggested_error_cause=suggested_error_cause,
        confirmed_error_cause=confirmed_error_cause,
        created_at=_utcnow(),
    )
    session.add(version)
    await session.flush()
    return version
