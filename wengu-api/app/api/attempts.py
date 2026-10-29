"""attempts 只读回看（P1-6 DoD）：按 source 过滤（system_quiz / student_self / manual）。

attempts 是派生作答明细，本模块只查询、不写入——写入仍由复习完成与
考核闭环（P1-11）负责；查询页不触发任何模型调用或排期变更。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Attempt, MistakeVersion, ProblemBankItem

router = APIRouter(tags=["attempts"])


class AttemptInfo(BaseModel):
    id: int
    mistake_id: int
    kind: str
    source: str
    problem_bank_id: int | None
    answer_text: str | None
    is_correct: bool
    problem_text: str | None
    created_at: datetime


class AttemptListResponse(BaseModel):
    items: list[AttemptInfo]
    total: int
    limit: int
    offset: int


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


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
    mistake_ids = {row.mistake_id for row in rows if row.problem_bank_id is None}
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

    return AttemptListResponse(
        items=[
            AttemptInfo(
                id=row.id,
                mistake_id=row.mistake_id,
                kind=row.kind,
                source=row.source,
                problem_bank_id=row.problem_bank_id,
                answer_text=row.answer_text,
                is_correct=row.is_correct,
                problem_text=(
                    bank_texts.get(row.problem_bank_id)
                    if row.problem_bank_id is not None
                    else mistake_texts.get(row.mistake_id)
                ),
                created_at=_naive_utc(row.created_at),
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
