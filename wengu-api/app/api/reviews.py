"""P1-7a 复习 API：只读到期队列 + 用户主动完成一次复习 + 同类题考核提交。

排期只由用户确认 wrong 时创建（P1-6 写入路径内），本模块不提供自动排期入口。
v2.5 到期任务考核优先/重做兜底：能按主考点检索到同类题就给"quiz"，
解答大题/依赖题图给"self_eval"，否则给"redo"（原题重做自评）并标 `bank_gap`；
`thin` 只是覆盖偏薄提示。

安全红线：题面一律走 `schemas.quiz.quiz_view`，绝不下发
`answer / accept / explanation / verify`；`POST /quiz` 的 `correct` 由服务端
judgeAnswer 得出，`POST /complete` 只接受客户端自评（source=student_self）。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.quiz import QuizQuestionView, quiz_view
from app.services.review import (
    CompleteResult,
    ReviewConflict,
    ReviewError,
    ReviewNotFound,
    ReviewQuizInvalid,
    ReviewQuizStale,
    ReviewQuizUnavailable,
    ReviewQuizUncertain,
    ReviewStateError,
    ReviewSubjectError,
    complete_attempt,
    due_queue,
    submit_review_quiz,
)

router = APIRouter(tags=["reviews"])


class ScheduleInfo(BaseModel):
    id: int
    due_date: date
    rung: int
    base_interval_days: int


class DueReviewItem(BaseModel):
    schedule_id: int
    mistake_id: int
    due_date: date
    rung: int
    base_interval_days: int
    problem_text: str | None
    primary_topic_id: str | None
    task: Literal["quiz", "self_eval", "redo"]
    coverage: Literal["ok", "thin", "gap"]
    bank_gap: bool
    coverage_hint: str | None
    quiz: QuizQuestionView | None


class DueReviewResponse(BaseModel):
    items: list[DueReviewItem]
    due_total: int
    returned: int
    today_completed: int
    daily_limit: int
    exam_today: bool
    today: date
    limit: int


class CompleteRequest(BaseModel):
    """原题重做自评入口：只接受客户端自评，不接受 system_quiz 结果。"""

    schedule_id: int = Field(ge=1)
    correct: bool
    completed_on: date | None = None
    actor: Literal["student", "parent"] = "student"
    source: Literal["student_self"] = "student_self"


class ReviewQuizRequest(BaseModel):
    """同类题考核提交：可答题只传作答，解答大题自评传 correct。"""

    schedule_id: int = Field(ge=1)
    question_id: str | None = Field(default=None, max_length=80)
    answer: str | None = Field(default=None, max_length=2000)
    correct: bool | None = None
    completed_on: date | None = None
    actor: Literal["student", "parent"] = "student"


class ReviewStateInfo(BaseModel):
    rung: int
    times_wrong: int
    trailing_correct: int


class CompleteResponse(BaseModel):
    mistake_id: int
    schedule_id: int
    attempt_id: int
    graduated: bool
    correct: bool
    mastery: float
    interval_days: int | None
    due_on: date | None
    state: ReviewStateInfo
    next_schedule: ScheduleInfo | None
    source: str


class ReviewQuizResponse(BaseModel):
    completion: CompleteResponse
    question: QuizQuestionView
    mode: Literal["system", "self_eval"]
    verdict: Literal["correct", "wrong"]


def _schedule_info(schedule) -> ScheduleInfo:
    return ScheduleInfo(
        id=schedule.id,
        due_date=schedule.due_date,
        rung=schedule.rung,
        base_interval_days=schedule.base_interval_days,
    )


def _complete_response(result: CompleteResult) -> CompleteResponse:
    return CompleteResponse(
        mistake_id=result.mistake_id,
        schedule_id=result.schedule_id,
        attempt_id=result.attempt_id,
        graduated=result.graduated,
        correct=result.correct,
        mastery=result.mastery,
        interval_days=result.interval_days,
        due_on=result.due_on,
        state=ReviewStateInfo(
            rung=result.state.rung,
            times_wrong=result.state.times_wrong,
            trailing_correct=result.state.trailing_correct,
        ),
        next_schedule=(
            _schedule_info(result.next_schedule)
            if result.next_schedule is not None
            else None
        ),
        source=result.source,
    )


@router.get("/api/reviews/due", response_model=DueReviewResponse)
async def due_reviews(
    today: date | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> DueReviewResponse:
    day = today or date.today()
    async with session.begin():
        queue = await due_queue(session, day, limit=limit)
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
                    quiz_view(
                        row.quiz.question,
                        mode=row.quiz.mode,
                        seed=row.quiz.seed,
                        pool_size=row.quiz.pool_size,
                    )
                    if row.quiz is not None and row.quiz.question is not None
                    else None
                ),
            )
            for row in queue.items
        ]
    return DueReviewResponse(
        items=items,
        due_total=queue.due_total,
        returned=queue.returned,
        today_completed=queue.today_completed,
        daily_limit=queue.daily_limit,
        exam_today=queue.exam_today,
        today=day,
        limit=limit,
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

    return _complete_response(result)


@router.post(
    "/api/reviews/{mistake_id}/quiz", response_model=ReviewQuizResponse
)
async def complete_review_quiz(
    mistake_id: int,
    payload: ReviewQuizRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewQuizResponse:
    """提交同类题考核：服务端重算题目并 judgeAnswer 判分，绝不信任客户端 correct。"""

    completed_on = payload.completed_on or date.today()
    async with session.begin():
        try:
            result = await submit_review_quiz(
                session,
                mistake_id,
                schedule_id=payload.schedule_id,
                answer=payload.answer,
                correct=payload.correct,
                question_id=payload.question_id,
                completed_on=completed_on,
                actor=payload.actor,
            )
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (ReviewQuizInvalid, ReviewQuizUncertain) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except (
            ReviewQuizUnavailable,
            ReviewQuizStale,
            ReviewConflict,
            ReviewStateError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ReviewError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    completion = result.completion
    return ReviewQuizResponse(
        completion=_complete_response(completion),
        question=quiz_view(
            result.question,
            mode=result.mode,
            seed=result.seed,
            pool_size=result.pool_size,
        ),
        mode=result.mode,
        verdict=result.verdict,
    )
