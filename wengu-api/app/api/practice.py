"""P1-6 practice_records 派生表 API：变式/加练作答的独立回看。

严格隔离：不写 learning_events/attempts，不改 mistakes，不进复习排期，
不影响掌握度；整表可清空。题目文本可引用 problem_bank，也可自由记录。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import Mistake, PracticeRecord, ProblemBankItem

router = APIRouter(tags=["practice-records"])


class PracticeCreateRequest(BaseModel):
    kind: Literal["variant", "extra"]
    source_mistake_id: int | None = Field(default=None, ge=1)
    problem_bank_id: int | None = Field(default=None, ge=1)
    problem_text: str | None = Field(default=None, max_length=5000)
    student_answer: str | None = Field(default=None, max_length=5000)
    is_correct: bool | None = None


class PracticeRecordInfo(BaseModel):
    id: int
    source_mistake_id: int | None
    problem_bank_id: int | None
    kind: str
    problem_text: str
    student_answer: str | None
    is_correct: bool | None
    created_at: datetime


class PracticeListResponse(BaseModel):
    items: list[PracticeRecordInfo]
    total: int
    limit: int
    offset: int


class PracticeClearResponse(BaseModel):
    deleted: int


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _info(row: PracticeRecord) -> PracticeRecordInfo:
    return PracticeRecordInfo(
        id=row.id,
        source_mistake_id=row.source_mistake_id,
        problem_bank_id=row.problem_bank_id,
        kind=row.kind,
        problem_text=row.problem_text,
        student_answer=row.student_answer,
        is_correct=row.is_correct,
        created_at=_naive_utc(row.created_at),
    )


@router.post("/api/practice-records", response_model=PracticeRecordInfo)
async def create_practice_record(
    payload: PracticeCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> PracticeRecordInfo:
    async with session.begin():
        if (
            payload.source_mistake_id is not None
            and await session.get(Mistake, payload.source_mistake_id) is None
        ):
            raise HTTPException(status_code=404, detail="错题不存在")

        problem_text = (payload.problem_text or "").strip()
        if payload.problem_bank_id is not None:
            bank_item = await session.get(
                ProblemBankItem, payload.problem_bank_id
            )
            if bank_item is None:
                raise HTTPException(status_code=404, detail="题库条目不存在")
            problem_text = bank_item.problem_text

        if not problem_text:
            raise HTTPException(
                status_code=422, detail="problem_text 与 problem_bank_id 至少提供一个"
            )

        row = PracticeRecord(
            source_mistake_id=payload.source_mistake_id,
            problem_bank_id=payload.problem_bank_id,
            kind=payload.kind,
            problem_text=problem_text,
            student_answer=payload.student_answer,
            is_correct=payload.is_correct,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return _info(row)


@router.get("/api/practice-records", response_model=PracticeListResponse)
async def list_practice_records(
    source_mistake_id: int | None = Query(default=None, ge=1),
    problem_bank_id: int | None = Query(default=None, ge=1),
    kind: Literal["variant", "extra"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PracticeListResponse:
    conditions = []
    if source_mistake_id is not None:
        conditions.append(PracticeRecord.source_mistake_id == source_mistake_id)
    if problem_bank_id is not None:
        conditions.append(PracticeRecord.problem_bank_id == problem_bank_id)
    if kind is not None:
        conditions.append(PracticeRecord.kind == kind)

    total = (
        await session.execute(
            select(func.count())
            .select_from(PracticeRecord)
            .where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(PracticeRecord)
            .where(*conditions)
            .order_by(PracticeRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return PracticeListResponse(
        items=[_info(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/api/practice-records", response_model=PracticeClearResponse)
async def clear_practice_records(
    session: AsyncSession = Depends(get_session),
) -> PracticeClearResponse:
    async with session.begin():
        result = await session.execute(delete(PracticeRecord))
        return PracticeClearResponse(deleted=result.rowcount or 0)
