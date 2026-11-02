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
from app.schemas.quiz import QuizQuestionView, quiz_view
from app.services.practice import (
    MAX_PRACTICE_COUNT,
    MAX_SEED,
    PracticeAnswer,
    PracticeInvalid,
    PracticeMistakeNotFound,
    start_practice,
    submit_practice,
)

router = APIRouter(tags=["practice"])


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
    topic_id: str | None
    seed: int | None
    created_at: datetime


class PracticeListResponse(BaseModel):
    items: list[PracticeRecordInfo]
    total: int
    limit: int
    offset: int


class PracticeClearResponse(BaseModel):
    deleted: int


class PracticeStartRequest(BaseModel):
    mistake_id: int | None = Field(default=None, ge=1)
    topic_id: str | None = Field(default=None, min_length=1, max_length=64)
    count: int = Field(default=3, ge=1, le=MAX_PRACTICE_COUNT)
    seed: int | None = Field(default=None, ge=0, le=MAX_SEED)


class PracticeStartResponse(BaseModel):
    topic_id: str | None
    seed: int
    count: int
    coverage: Literal["ok", "thin", "gap"]
    answerable_total: int
    pool_total: int
    bank_gap: bool
    message: str | None
    items: list[QuizQuestionView]


class PracticeSubmitItem(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)
    answer: str | None = Field(default=None, max_length=2000)
    correct: bool | None = None


class PracticeSubmitRequest(BaseModel):
    topic_id: str = Field(min_length=1, max_length=64)
    seed: int = Field(ge=0, le=MAX_SEED)
    count: int = Field(default=3, ge=1, le=MAX_PRACTICE_COUNT)
    mistake_id: int | None = Field(default=None, ge=1)
    items: list[PracticeSubmitItem] = Field(
        min_length=1, max_length=MAX_PRACTICE_COUNT
    )


class PracticeAnswerInfo(BaseModel):
    question_id: str
    mode: Literal["system", "self_eval"]
    status: Literal["correct", "wrong", "uncertain", "skipped"]
    practice_record_id: int | None
    reused: bool = False


class PracticeSubmitResponse(BaseModel):
    topic_id: str
    seed: int
    count: int
    items: list[PracticeAnswerInfo]
    correct: int
    wrong: int


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
        topic_id=row.topic_id,
        seed=row.seed,
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


async def _fetch_records(
    session: AsyncSession,
    *,
    source_mistake_id: int | None,
    problem_bank_id: int | None,
    kind: str | None,
    topic_id: str | None,
    seed: int | None,
    limit: int,
    offset: int,
) -> PracticeListResponse:
    conditions = []
    if source_mistake_id is not None:
        conditions.append(PracticeRecord.source_mistake_id == source_mistake_id)
    if problem_bank_id is not None:
        conditions.append(PracticeRecord.problem_bank_id == problem_bank_id)
    if kind is not None:
        conditions.append(PracticeRecord.kind == kind)
    if topic_id is not None:
        conditions.append(PracticeRecord.topic_id == topic_id)
    if seed is not None:
        conditions.append(PracticeRecord.seed == seed)

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


@router.get("/api/practice-records", response_model=PracticeListResponse)
async def list_practice_records(
    source_mistake_id: int | None = Query(default=None, ge=1),
    problem_bank_id: int | None = Query(default=None, ge=1),
    kind: Literal["variant", "extra"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PracticeListResponse:
    return await _fetch_records(
        session,
        source_mistake_id=source_mistake_id,
        problem_bank_id=problem_bank_id,
        kind=kind,
        topic_id=None,
        seed=None,
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


@router.post("/api/practice/start", response_model=PracticeStartResponse)
async def start_practice_endpoint(
    payload: PracticeStartRequest,
    session: AsyncSession = Depends(get_session),
) -> PracticeStartResponse:
    """抽同类题加练卷；孩子区可用，无主考点/题库缺口时返回空卷与提示。"""

    try:
        result = await start_practice(
            session,
            mistake_id=payload.mistake_id,
            topic_id=payload.topic_id,
            count=payload.count,
            seed=payload.seed,
        )
    except PracticeMistakeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except PracticeInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    paper = result.paper
    pool_size = paper.pool_total if paper is not None else 0
    return PracticeStartResponse(
        topic_id=result.topic_id,
        seed=result.seed,
        count=result.count,
        coverage=paper.coverage if paper is not None else "gap",
        answerable_total=paper.answerable_total if paper is not None else 0,
        pool_total=pool_size,
        bank_gap=result.empty,
        message=result.message,
        items=[
            quiz_view(
                item.question,
                mode=item.mode,
                seed=result.seed,
                pool_size=pool_size,
            )
            for item in result.items
        ],
    )


@router.post("/api/practice/submit", response_model=PracticeSubmitResponse)
async def submit_practice_endpoint(
    payload: PracticeSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> PracticeSubmitResponse:
    """服务端判客观题、收自评题结论；只写 practice_records，不回答案钥匙。"""

    async with session.begin():
        try:
            result = await submit_practice(
                session,
                topic_id=payload.topic_id,
                seed=payload.seed,
                count=payload.count,
                answers=[
                    PracticeAnswer(
                        question_id=entry.question_id,
                        answer=entry.answer,
                        correct=entry.correct,
                    )
                    for entry in payload.items
                ],
                mistake_id=payload.mistake_id,
            )
        except PracticeMistakeNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except PracticeInvalid as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    return PracticeSubmitResponse(
        topic_id=result.topic_id,
        seed=result.seed,
        count=result.count,
        items=[
            PracticeAnswerInfo(
                question_id=item.question_id,
                mode=item.mode,
                status=item.status,
                practice_record_id=item.practice_record_id,
                reused=item.reused,
            )
            for item in result.items
        ],
        correct=result.correct,
        wrong=result.wrong,
    )


@router.get("/api/practice", response_model=PracticeListResponse)
async def list_practice(
    mistake_id: int | None = Query(default=None, ge=1),
    kind: Literal["variant", "extra"] | None = None,
    topic_id: str | None = Query(default=None, min_length=1, max_length=64),
    seed: int | None = Query(default=None, ge=0, le=MAX_SEED),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PracticeListResponse:
    """回看加练记录；可按 `(topic_id, seed)` 过滤出"这一组"。只读派生表。"""

    return await _fetch_records(
        session,
        source_mistake_id=mistake_id,
        problem_bank_id=None,
        kind=kind,
        topic_id=topic_id,
        seed=seed,
        limit=limit,
        offset=offset,
    )


@router.delete("/api/practice", response_model=PracticeClearResponse)
async def clear_practice(
    session: AsyncSession = Depends(get_session),
) -> PracticeClearResponse:
    """整表清空加练记录；不触碰错题、事件、掌握度与复习排期。"""

    async with session.begin():
        result = await session.execute(delete(PracticeRecord))
        return PracticeClearResponse(deleted=result.rowcount or 0)
