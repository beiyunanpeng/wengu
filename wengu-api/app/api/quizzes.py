"""P1-11 家长手动组卷 API：选知识点 → 出 1..N 题 → 提交后服务端判分。

安全红线与复习考核一致：题面走 `quiz_view`，绝不下发
`answer / accept / explanation / verify`；`correct` 只由服务端 judgeAnswer 得出，
解答大题/依赖题图降级自评（source=student_self）。考核结果写 attempts
（kind=quiz），不新建错题本条目。
"""

from __future__ import annotations

import secrets
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session import require_parent
from app.core.database import get_session
from app.schemas.quiz import QuizQuestionView, quiz_view
from app.services.bank import get_bank, is_answerable
from app.services.quiz import (
    PaperAnswer,
    QuizDuplicateQuestion,
    QuizInvalid,
    QuizQuestionNotInPaper,
    QuizTopicNotFound,
    build_paper,
    submit_paper,
)

router = APIRouter(tags=["quizzes"])

MAX_PAPER_COUNT = 20
MAX_SEED = 0xFFFFFFFF


class QuizTopicInfo(BaseModel):
    topic_id: str
    name: str
    subject: str
    domain: str | None
    grade: str | None
    semester: str | None
    total: int
    answerable: int


class QuizTopicListResponse(BaseModel):
    items: list[QuizTopicInfo]
    total: int
    limit: int
    offset: int


class QuizPaperResponse(BaseModel):
    topic_id: str
    seed: int
    count: int
    coverage: Literal["ok", "thin", "gap"]
    bank_gap: bool
    shortfall: bool
    answerable_total: int
    pool_total: int
    items: list[QuizQuestionView]


class PaperAnswerKeyItem(BaseModel):
    question_id: str
    mode: Literal["system", "self_eval"]
    answer: str
    acceptable_answers: list[str]


class PaperAnswerKeyResponse(BaseModel):
    topic_id: str
    seed: int
    count: int
    items: list[PaperAnswerKeyItem]


class PaperSubmitAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)
    answer: str | None = Field(default=None, max_length=2000)
    correct: bool | None = None


class PaperSubmitRequest(BaseModel):
    topic_id: str = Field(min_length=1, max_length=64)
    seed: int = Field(ge=0, le=MAX_SEED)
    count: int = Field(ge=1, le=MAX_PAPER_COUNT)
    answers: list[PaperSubmitAnswer] = Field(min_length=1, max_length=MAX_PAPER_COUNT)
    completed_on: date | None = None
    actor: Literal["student", "parent"] = "student"


class PaperAnswerInfo(BaseModel):
    question_id: str
    mode: Literal["system", "self_eval"]
    status: Literal["correct", "wrong", "uncertain", "skipped"]
    attempt_id: int | None
    replayed: bool


class PaperSubmitResponse(BaseModel):
    topic_id: str
    seed: int
    completed_on: date
    items: list[PaperAnswerInfo]
    correct: int
    wrong: int


@router.get("/api/quizzes/topics", response_model=QuizTopicListResponse)
async def quiz_topics(
    subject: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> QuizTopicListResponse:
    """可组卷的知识点（内存题库，无 DB、无模型调用）。"""

    bank = get_bank()
    keyword = (q or "").strip()
    rows: list[QuizTopicInfo] = []
    for topic_id, meta in bank.topics.items():
        questions = bank.questions_for(topic_id)
        if not questions:
            continue
        meta_subject = str(meta.get("subject") or "")
        name = str(meta.get("name") or topic_id)
        if subject and meta_subject != subject:
            continue
        if keyword and keyword not in name:
            continue
        rows.append(
            QuizTopicInfo(
                topic_id=topic_id,
                name=name,
                subject=meta_subject,
                domain=_optional(meta.get("domain")),
                grade=_optional(meta.get("grade")),
                semester=_optional(meta.get("semester")),
                total=len(questions),
                answerable=sum(1 for item in questions if is_answerable(item)),
            )
        )
    rows.sort(key=lambda item: (item.subject, item.topic_id))
    return QuizTopicListResponse(
        items=rows[offset : offset + limit],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/quizzes/paper",
    response_model=QuizPaperResponse,
    dependencies=[Depends(require_parent)],
)
async def quiz_paper(
    topic_id: str = Query(min_length=1, max_length=64),
    count: int = Query(default=3, ge=1, le=MAX_PAPER_COUNT),
    seed: int | None = Query(default=None, ge=0, le=MAX_SEED),
) -> QuizPaperResponse:
    """抽一张卷；不传 seed 时随机生成并回传，之后用同 seed 重放同一张卷。"""

    chosen = seed if seed is not None else secrets.randbits(32)
    try:
        paper = build_paper(topic_id, chosen, count)
    except QuizTopicNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return QuizPaperResponse(
        topic_id=paper.topic_id,
        seed=paper.seed,
        count=count,
        coverage=paper.coverage,
        bank_gap=paper.bank_gap,
        shortfall=paper.shortfall,
        answerable_total=paper.answerable_total,
        pool_total=paper.pool_total,
        items=[
            quiz_view(
                item.question,
                mode=item.mode,
                seed=paper.seed,
                pool_size=paper.pool_total,
            )
            for item in paper.items
        ],
    )


@router.get(
    "/api/quizzes/paper/answers",
    response_model=PaperAnswerKeyResponse,
    dependencies=[Depends(require_parent)],
)
async def quiz_paper_answers(
    topic_id: str = Query(min_length=1, max_length=64),
    count: int = Query(default=3, ge=1, le=MAX_PAPER_COUNT),
    seed: int = Query(ge=0, le=MAX_SEED),
) -> PaperAnswerKeyResponse:
    """家长答案钥匙：按同 topic/seed/count 重建同一张卷，只回正答与可接受别名。

    孩子侧组卷接口永远不下发答案；本端点挂 `require_parent`，仅供打印页的
    “家长答案页”使用。仍不返回 `explanation / verify`，避免扩大泄漏面。
    """

    try:
        paper = build_paper(topic_id, seed, count)
    except QuizTopicNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return PaperAnswerKeyResponse(
        topic_id=paper.topic_id,
        seed=paper.seed,
        count=count,
        items=[
            PaperAnswerKeyItem(
                question_id=item.question.id,
                mode=item.mode,
                answer=item.question.answer,
                acceptable_answers=list(item.question.accept),
            )
            for item in paper.items
        ],
    )


@router.post("/api/quizzes/paper/submit", response_model=PaperSubmitResponse)
async def submit_quiz_paper(
    payload: PaperSubmitRequest,
    session: AsyncSession = Depends(get_session),
) -> PaperSubmitResponse:
    completed_on = payload.completed_on or date.today()
    async with session.begin():
        try:
            result = await submit_paper(
                session,
                topic_id=payload.topic_id,
                seed=payload.seed,
                count=payload.count,
                answers=[
                    PaperAnswer(
                        question_id=entry.question_id,
                        answer=entry.answer,
                        correct=entry.correct,
                    )
                    for entry in payload.answers
                ],
                completed_on=completed_on,
                actor=payload.actor,
            )
        except QuizTopicNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except (
            QuizQuestionNotInPaper,
            QuizDuplicateQuestion,
            QuizInvalid,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    return PaperSubmitResponse(
        topic_id=result.topic_id,
        seed=result.seed,
        completed_on=result.completed_on,
        items=[
            PaperAnswerInfo(
                question_id=item.question_id,
                mode=item.mode,
                status=item.status,
                attempt_id=item.attempt_id,
                replayed=item.replayed,
            )
            for item in result.items
        ],
        correct=result.correct,
        wrong=result.wrong,
    )


def _optional(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
