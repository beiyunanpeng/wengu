"""P1-7a 复习 API：只读到期队列 + 用户主动完成一次复习。

排期只由用户确认 wrong 时创建（P1-6 写入路径内），本模块不提供自动排期入口。
v2.5 到期任务考核优先/重做兜底：能按主考点检索到同类题就给"quiz"，
否则给"redo"（原题重做自评）并标 `bank_gap`；`thin` 只是覆盖偏薄提示。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.review import (
    ReviewConflict,
    ReviewNotFound,
    ReviewStateError,
    ReviewSubjectError,
    complete_attempt,
    due_queue,
)

router = APIRouter(tags=["reviews"])


class ScheduleInfo(BaseModel):
    id: int
    due_date: date
    rung: int
    base_interval_days: int


class QuizChoiceInfo(BaseModel):
    key: str
    text: str
    figure: str | None


class QuizQuestionInfo(BaseModel):
    question_id: str
    topic_id: str
    subject: str
    type: str
    difficulty: str
    prompt: str
    choices: list[QuizChoiceInfo]
    figure: str | None
    seed: int
    pool_size: int


class DueReviewItem(BaseModel):
    schedule_id: int
    mistake_id: int
    due_date: date
    rung: int
    base_interval_days: int
    problem_text: str | None
    primary_topic_id: str | None
    task: Literal["quiz", "redo"]
    coverage: Literal["ok", "thin", "gap"]
    bank_gap: bool
    coverage_hint: str | None
    quiz: QuizQuestionInfo | None


class DueReviewResponse(BaseModel):
    items: list[DueReviewItem]
    total: int
    today: date
    limit: int


class CompleteRequest(BaseModel):
    schedule_id: int = Field(ge=1)
    correct: bool
    completed_on: date | None = None
    actor: Literal["student", "parent"] = "student"
    source: Literal["student_self", "system_quiz"] = "student_self"


class ReviewStateInfo(BaseModel):
    rung: int
    times_wrong: int
    trailing_correct: int


class CompleteResponse(BaseModel):
    mistake_id: int
    schedule_id: int
    attempt_id: int
    graduated: bool
    mastery: float
    interval_days: int | None
    due_on: date | None
    state: ReviewStateInfo
    next_schedule: ScheduleInfo | None
    source: str


@router.get("/api/reviews/due", response_model=DueReviewResponse)
async def due_reviews(
    today: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> DueReviewResponse:
    day = today or date.today()
    async with session.begin():
        rows = await due_queue(session, day, limit=limit)
        items = [
            DueReviewItem(
                schedule_id=row.schedule.id,
                mistake_id=row.mistake.id,
                due_date=row.schedule.due_date,
                rung=row.schedule.rung,
                base_interval_days=row.schedule.base_interval_days,
                problem_text=row.problem_text,
                primary_topic_id=row.primary_topic_id,
                task=row.task,
                coverage=row.coverage,
                bank_gap=row.bank_gap,
                coverage_hint=row.coverage_hint,
                quiz=(
                    QuizQuestionInfo(
                        question_id=row.quiz.question.id,
                        topic_id=row.quiz.question.topic_id,
                        subject=row.quiz.question.subject,
                        type=row.quiz.question.type,
                        difficulty=row.quiz.question.difficulty,
                        prompt=row.quiz.question.prompt,
                        choices=[
                            QuizChoiceInfo(
                                key=choice.key,
                                text=choice.text,
                                figure=choice.figure,
                            )
                            for choice in row.quiz.question.choices
                        ],
                        figure=row.quiz.question.figure,
                        seed=row.quiz.seed,
                        pool_size=row.quiz.pool_size,
                    )
                    if row.quiz is not None and row.quiz.question is not None
                    else None
                ),
            )
            for row in rows
        ]
    return DueReviewResponse(
        items=items, total=len(items), today=day, limit=limit
    )


@router.post(
    "/api/reviews/{mistake_id}/complete", response_model=CompleteResponse
)
async def complete_review(
    mistake_id: int,
    payload: CompleteRequest,
    session: AsyncSession = Depends(get_session),
) -> CompleteResponse:
    completed_on = payload.completed_on or date.today()
    async with session.begin():
        try:
            result = await complete_attempt(
                session,
                mistake_id,
                schedule_id=payload.schedule_id,
                correct=payload.correct,
                completed_on=completed_on,
                actor=payload.actor,
                source=payload.source,
            )
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ReviewSubjectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except (ReviewConflict, ReviewStateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    return CompleteResponse(
        mistake_id=result.mistake_id,
        schedule_id=result.schedule_id,
        attempt_id=result.attempt_id,
        graduated=result.graduated,
        mastery=result.mastery,
        interval_days=result.interval_days,
        due_on=result.due_on,
        state=ReviewStateInfo(
            rung=result.state.rung,
            times_wrong=result.state.times_wrong,
            trailing_correct=result.state.trailing_correct,
        ),
        next_schedule=(
            ScheduleInfo(
                id=result.next_schedule.id,
                due_date=result.next_schedule.due_date,
                rung=result.next_schedule.rung,
                base_interval_days=result.next_schedule.base_interval_days,
            )
            if result.next_schedule is not None
            else None
        ),
        source=result.source,
    )
