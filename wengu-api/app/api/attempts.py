"""attempts 只读回看 + 考核明细整表清空（P1-6 / P1-11）。

attempts 是派生作答明细：写入由复习完成与考核闭环负责，本模块只查询/清理。
同类题考核（复习到期与家长手动组卷）记 `kind=quiz`、`source=system_quiz`
或 `student_self`、`mistake_id` 可空；清理只删未被复习排期引用的行，
learning_events 事实源保持 append-only（掌握度仍可由事实重算）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Attempt, LearningEvent, MistakeVersion, ProblemBankItem, ReviewSchedule
from app.services.bank import get_runtime_bank

router = APIRouter(tags=["attempts"])


class AttemptInfo(BaseModel):
    id: int
    mistake_id: int | None
    kind: str
    source: str
    problem_bank_id: int | None
    question_id: str | None
    topic_id: str | None
    answer_text: str | None
    is_correct: bool
    problem_text: str | None
    created_at: datetime


class AttemptListResponse(BaseModel):
    items: list[AttemptInfo]
    total: int
    limit: int
    offset: int


class AttemptClearResponse(BaseModel):
    deleted: int
    kept: int


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _payload(event: LearningEvent | None) -> dict:
    if event is None or not event.payload:
        return {}
    try:
        data = json.loads(event.payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/api/attempts", response_model=AttemptListResponse)
async def list_attempts(
    source: Literal["manual", "student_self", "system_quiz"] | None = None,
    mistake_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> AttemptListResponse:
    conditions = []
    if source is not None:
        conditions.append(Attempt.source == source)
    if mistake_id is not None:
        conditions.append(Attempt.mistake_id == mistake_id)

    total = (
        await session.execute(
            select(func.count()).select_from(Attempt).where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(Attempt)
            .where(*conditions)
            .order_by(Attempt.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    bank_ids = {row.problem_bank_id for row in rows if row.problem_bank_id}
    bank_texts = (
        dict(
            (
                await session.execute(
                    select(ProblemBankItem.id, ProblemBankItem.problem_text).where(
                        ProblemBankItem.id.in_(bank_ids)
                    )
                )
            ).all()
        )
        if bank_ids
        else {}
    )
    mistake_ids = {
        row.mistake_id
        for row in rows
        if row.problem_bank_id is None and row.mistake_id is not None
    }
    mistake_texts: dict[int, str | None] = {}
    if mistake_ids:
        for record in (
            await session.execute(
                select(
                    MistakeVersion.mistake_id,
                    MistakeVersion.problem_text,
                )
                .where(MistakeVersion.mistake_id.in_(mistake_ids))
                .order_by(MistakeVersion.mistake_id, MistakeVersion.version)
            )
        ).all():
            mistake_texts[record.mistake_id] = record.problem_text

    events = {
        event.id: event
        for event in (
            await session.scalars(
                select(LearningEvent).where(
                    LearningEvent.id.in_(
                        [row.learning_event_id for row in rows]
                    )
                )
            )
        ).all()
    }
    bank = await get_runtime_bank(session)
    question_ids: dict[int, str | None] = {}
    topic_ids: dict[int, str | None] = {}
    for row in rows:
        payload = _payload(events.get(row.learning_event_id))
        question_id = payload.get("quiz_question_id")
        topic_id = payload.get("quiz_topic_id")
        question_ids[row.id] = question_id if isinstance(question_id, str) else None
        topic_ids[row.id] = topic_id if isinstance(topic_id, str) else None

    def _problem_text(row: Attempt) -> str | None:
        if row.problem_bank_id is not None:
            return bank_texts.get(row.problem_bank_id)
        question_id = question_ids.get(row.id)
        if question_id:
            question = bank.question(question_id)
            if question is not None:
                return question.prompt
        if row.mistake_id is not None:
            return mistake_texts.get(row.mistake_id)
        return None

    return AttemptListResponse(
        items=[
            AttemptInfo(
                id=row.id,
                mistake_id=row.mistake_id,
                kind=row.kind,
                source=row.source,
                problem_bank_id=row.problem_bank_id,
                question_id=question_ids.get(row.id),
                topic_id=topic_ids.get(row.id),
                answer_text=row.answer_text,
                is_correct=row.is_correct,
                problem_text=_problem_text(row),
                created_at=_naive_utc(row.created_at),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/api/attempts", response_model=AttemptClearResponse)
async def clear_attempts(
    session: AsyncSession = Depends(get_session),
) -> AttemptClearResponse:
    """整表清空派生作答明细；被复习排期引用的行保留（外键约束）。"""

    async with session.begin():
        referenced = select(ReviewSchedule.completed_attempt_id).where(
            ReviewSchedule.completed_attempt_id.is_not(None)
        )
        kept = int(
            await session.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.id.in_(referenced))
            )
            or 0
        )
        result = await session.execute(
            delete(Attempt).where(Attempt.id.not_in(referenced))
        )
        deleted = result.rowcount or 0
    return AttemptClearResponse(deleted=deleted, kept=kept)
