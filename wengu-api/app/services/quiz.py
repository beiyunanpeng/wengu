"""手动组卷考核服务（P1-11）：家长选知识点 → 确定性抽题 → 服务端判分入库。

纪律：
- 判分只用确定性 `judge_answer`（答案钥匙来自 seed 题库），绝不调模型；
- 可答题必须传作答、由服务端判；解答大题/依赖题图降级自评（source=student_self）；
- 结果写 attempts（kind=quiz，mistake_id 可空），**绝不新建错题本条目**；
- 掌握度按该知识点下已确认、未归并的 concepts 归属，事件可整体重放；
- 幂等键 `quiz:paper:{topic}:{seed}:{question}`：同一张卷重复交卷不重复计分；
  attempts 是可从事件重建的派生行，整表清空后重新交卷会补回明细。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.judge.normalize import judge_answer
from app.models import Attempt, Concept, LearningEvent
from app.seed.bank import BankQuestion
from app.services.bank import (
    AnswerMode,
    PaperPick,
    get_bank,
    paper_picks,
)
from app.services.events import record_event
from app.services.recompute import ATTEMPT_CORRECT, ATTEMPT_WRONG

QuizVerdict = Literal["correct", "wrong"]
PaperStatus = Literal["correct", "wrong", "uncertain", "skipped"]

PAPER_EVENT_KIND = "quiz"
PAPER_EVENT_SCOPE = "paper"
PAPER_ATTEMPT_KIND = "quiz"


class QuizError(ValueError):
    pass


class QuizTopicNotFound(QuizError):
    pass


class QuizQuestionNotInPaper(QuizError):
    pass


class QuizDuplicateQuestion(QuizError):
    pass


class QuizInvalid(QuizError):
    pass


@dataclass(frozen=True)
class PaperAnswer:
    question_id: str
    answer: str | None = None
    correct: bool | None = None


@dataclass(frozen=True)
class PaperAnswerResult:
    question_id: str
    mode: AnswerMode
    status: PaperStatus
    attempt_id: int | None
    replayed: bool


@dataclass(frozen=True)
class PaperSubmitResult:
    topic_id: str
    seed: int
    completed_on: date
    items: tuple[PaperAnswerResult, ...]

    @property
    def correct(self) -> int:
        return sum(1 for item in self.items if item.status == "correct")

    @property
    def wrong(self) -> int:
        return sum(1 for item in self.items if item.status == "wrong")


def build_paper(topic_id: str, seed: int, count: int) -> PaperPick:
    """组卷快照（纯内存）；未知知识点在此拦下，避免空卷被当成题库缺口。"""

    bank = get_bank()
    if topic_id not in bank.topics:
        raise QuizTopicNotFound("知识点不存在")
    return paper_picks(topic_id, seed, count, bank=bank)


async def _concepts_for_topic(session: AsyncSession, topic_id: str) -> list[int]:
    """该知识点下已确认且未归并的 concepts：掌握度按它们归属（多概念取最小）。"""

    rows = (
        await session.scalars(
            select(Concept.id).where(
                Concept.category_id == topic_id,
                Concept.merged_into_id.is_(None),
            )
        )
    ).all()
    return sorted(int(row) for row in rows)


def _paper_key(topic_id: str, seed: int, question_id: str) -> str:
    return f"quiz:paper:{topic_id}:{seed}:{question_id}"


def _decode(event: LearningEvent) -> dict:
    if not event.payload:
        return {}
    try:
        data = json.loads(event.payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


async def _attempt_for_event(
    session: AsyncSession, event: LearningEvent
) -> Attempt | None:
    """取事件对应的 attempts 行；被整表清空后按事件重建（派生数据可修复）。"""

    attempt = (
        await session.execute(
            select(Attempt).where(Attempt.learning_event_id == event.id)
        )
    ).scalar_one_or_none()
    if attempt is not None:
        return attempt
    payload = _decode(event)
    source = payload.get("source")
    is_correct = payload.get("correct")
    if source not in ("student_self", "system_quiz") or not isinstance(is_correct, bool):
        return None
    attempt = Attempt(
        mistake_id=None,
        learning_event_id=event.id,
        problem_bank_id=None,
        kind=PAPER_ATTEMPT_KIND,
        source=source,
        answer_text=None,
        is_correct=is_correct,
        created_at=event.occurred_at,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def _replayed_result(
    session: AsyncSession,
    event: LearningEvent,
    question: BankQuestion,
) -> PaperAnswerResult:
    payload = _decode(event)
    verdict = payload.get("quiz_verdict")
    mode = payload.get("quiz_mode")
    attempt = await _attempt_for_event(session, event)
    return PaperAnswerResult(
        question_id=question.id,
        mode=mode if mode in ("system", "self_eval") else "system",
        status="correct" if verdict == "correct" else "wrong",
        attempt_id=attempt.id if attempt is not None else None,
        replayed=True,
    )


def _judge_system(question: BankQuestion, answer: str) -> PaperAnswerResult:
    outcome = judge_answer(
        answer,
        question.answer,
        acceptable=question.accept,
        unordered=question.unordered,
    )
    if outcome.verdict == "uncertain":
        return PaperAnswerResult(
            question_id=question.id,
            mode="system",
            status="uncertain",
            attempt_id=None,
            replayed=False,
        )
    return PaperAnswerResult(
        question_id=question.id,
        mode="system",
        status="correct" if outcome.verdict == "correct" else "wrong",
        attempt_id=None,
        replayed=False,
    )


async def submit_paper(
    session: AsyncSession,
    *,
    topic_id: str,
    seed: int,
    count: int,
    answers: Sequence[PaperAnswer],
    completed_on: date,
    actor: Literal["student", "parent"] = "student",
    now: datetime | None = None,
) -> PaperSubmitResult:
    """逐题判分入库；空白作答记为 skipped（不写事件、不影响掌握度）。"""

    if actor not in ("student", "parent"):
        raise QuizInvalid("只有 student/parent 可以提交考核")
    paper = build_paper(topic_id, seed, count)
    by_id = {item.question.id: item for item in paper.items}

    seen: set[str] = set()
    for entry in answers:
        if entry.question_id in seen:
            raise QuizDuplicateQuestion("同一题只允许提交一次")
        seen.add(entry.question_id)
        if entry.question_id not in by_id:
            raise QuizQuestionNotInPaper("题目不属于该试卷，请重新组卷")

    concept_ids = await _concepts_for_topic(session, topic_id)
    moment = now or datetime.now(UTC)
    results: list[PaperAnswerResult] = []

    for entry in answers:
        item = by_id[entry.question_id]
        question = item.question
        key = _paper_key(topic_id, seed, question.id)
        existing = (
            await session.execute(
                select(LearningEvent).where(
                    LearningEvent.idempotency_key == key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            results.append(await _replayed_result(session, existing, question))
            continue

        if item.mode == "system":
            text = (entry.answer or "").strip()
            if not text:
                results.append(
                    PaperAnswerResult(
                        question_id=question.id,
                        mode="system",
                        status="skipped",
                        attempt_id=None,
                        replayed=False,
                    )
                )
                continue
            judged = _judge_system(question, text)
            if judged.status == "uncertain":
                results.append(judged)
                continue
            is_correct = judged.status == "correct"
            source = "system_quiz"
        else:
            if entry.correct is None:
                if not (entry.answer or "").strip():
                    results.append(
                        PaperAnswerResult(
                            question_id=question.id,
                            mode="self_eval",
                            status="skipped",
                            attempt_id=None,
                            replayed=False,
                        )
                    )
                    continue
                raise QuizInvalid("解答大题需在纸上完成并自评：请传 correct")
            is_correct = entry.correct
            source = "student_self"

        verdict: QuizVerdict = "correct" if is_correct else "wrong"
        payload = {
            "kind": PAPER_EVENT_KIND,
            "scope": PAPER_EVENT_SCOPE,
            "source": source,
            "correct": is_correct,
            "completed_on": completed_on.isoformat(),
            "concept_ids": concept_ids,
            "quiz_question_id": question.id,
            "quiz_topic_id": topic_id,
            "quiz_mode": item.mode,
            "quiz_verdict": verdict,
            "quiz_verify_status": question.verify_status,
            "quiz_seed": seed,
        }
        event, created = await record_event(
            session,
            ATTEMPT_CORRECT if is_correct else ATTEMPT_WRONG,
            actor,
            idempotency_key=key,
            mistake_id=None,
            payload=payload,
        )
        if not created:
            results.append(await _replayed_result(session, event, question))
            continue

        attempt = Attempt(
            mistake_id=None,
            learning_event_id=event.id,
            problem_bank_id=None,
            kind=PAPER_ATTEMPT_KIND,
            source=source,
            answer_text=None,
            is_correct=is_correct,
            created_at=moment,
        )
        session.add(attempt)
        await session.flush()
        results.append(
            PaperAnswerResult(
                question_id=question.id,
                mode=item.mode,
                status=verdict,
                attempt_id=attempt.id,
                replayed=False,
            )
        )

    return PaperSubmitResult(
        topic_id=topic_id,
        seed=seed,
        completed_on=completed_on,
        items=tuple(results),
    )
