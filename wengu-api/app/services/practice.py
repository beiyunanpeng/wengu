"""P3-2 同类题加练：只写 `practice_records` 派生表，绝不碰事实源。

硬不变量（AGENTS §5 / §6）：
- 加练只写 `practice_records`（kind='variant'）：**不写 attempts、不产生 attempt_* 事件、
  不新建错题、不影响掌握度/复习排期/打卡**；整表可清空。
- 抽题复用 `paper_picks`（同 topic + mulberry32 固定种子），同 `(topic, seed, count)`
  重放同一张卷；题面走 `quiz_view`，绝不下发 answer/accept/explanation/verify。
- 客观题由服务端 `judge_answer` 判分，客户端 `correct` 一律忽略；解答题/依赖图题
  降级 `self_eval`，由孩子在卷面自评后回传 `correct`。
- 提交幂等：`dedup_key = variant:{topic_id}:{seed}:{question_id}` 有部分唯一索引；
  同题重复提交不新增行，回看已有行并标 `reused=true`。

加练是孩子自主行为，服务层不检查家长角色；API 也不挂 `require_parent`。
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.judge.normalize import judge_answer
from app.models import Mistake, PracticeRecord, ProblemBankItem
from app.seed.bank import BankQuestion
from app.services.bank import (
    AnswerMode,
    PaperItem,
    PaperPick,
    get_runtime_bank,
    paper_picks,
)

MAX_PRACTICE_COUNT = 10
MAX_SEED = 0xFFFFFFFF
EMPTY_MESSAGE = "该知识点暂无同类题"
PRACTICE_KIND = "variant"


class PracticeError(ValueError):
    pass


class PracticeMistakeNotFound(PracticeError):
    pass


class PracticeInvalid(PracticeError):
    pass


@dataclass(frozen=True)
class PracticeAnswer:
    question_id: str
    answer: str | None = None
    correct: bool | None = None


@dataclass(frozen=True)
class PracticeStartResult:
    topic_id: str | None
    seed: int
    count: int
    paper: PaperPick | None
    message: str | None

    @property
    def items(self) -> tuple[PaperItem, ...]:
        return self.paper.items if self.paper is not None else ()

    @property
    def empty(self) -> bool:
        return self.paper is None or not self.paper.items


@dataclass(frozen=True)
class PracticeAnswerResult:
    question_id: str
    mode: AnswerMode
    status: str
    practice_record_id: int | None
    reused: bool = False


@dataclass(frozen=True)
class PracticeSubmitResult:
    topic_id: str
    seed: int
    count: int
    items: tuple[PracticeAnswerResult, ...]

    @property
    def correct(self) -> int:
        return sum(1 for item in self.items if item.status == "correct")

    @property
    def wrong(self) -> int:
        return sum(1 for item in self.items if item.status == "wrong")


async def start_practice(
    session: AsyncSession,
    *,
    mistake_id: int | None = None,
    topic_id: str | None = None,
    count: int = 3,
    seed: int | None = None,
) -> PracticeStartResult:
    """解析练点并抽一张同类题卷；无主考点/题库缺口返回空结果与提示，不报错。"""

    if (mistake_id is None) == (topic_id is None):
        raise PracticeInvalid("mistake_id 与 topic_id 必须且只能提供一个")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_PRACTICE_COUNT:
        raise PracticeInvalid(f"count 必须是 1..{MAX_PRACTICE_COUNT} 的整数")
    chosen_seed = secrets.randbits(32) if seed is None else seed
    if isinstance(chosen_seed, bool) or not isinstance(chosen_seed, int) or not 0 <= chosen_seed <= MAX_SEED:
        raise PracticeInvalid("seed 必须是 32 位无符号整数")

    resolved_topic: str | None
    if mistake_id is not None:
        mistake = await session.get(Mistake, mistake_id)
        if mistake is None:
            raise PracticeMistakeNotFound("错题不存在")
        resolved_topic = mistake.primary_topic_id or None
    else:
        cleaned = (topic_id or "").strip()
        resolved_topic = cleaned or None

    if not resolved_topic:
        return PracticeStartResult(
            topic_id=None,
            seed=chosen_seed,
            count=count,
            paper=None,
            message=EMPTY_MESSAGE,
        )

    bank = await get_runtime_bank(session)
    paper = paper_picks(resolved_topic, chosen_seed, count, bank=bank)
    return PracticeStartResult(
        topic_id=resolved_topic,
        seed=chosen_seed,
        count=count,
        paper=paper,
        message=None if paper.items else EMPTY_MESSAGE,
    )


def _judge(question: BankQuestion, answer: str) -> str:
    outcome = judge_answer(
        answer,
        question.answer,
        acceptable=question.accept,
        unordered=question.unordered,
    )
    if outcome.verdict == "uncertain":
        return "uncertain"
    return "correct" if outcome.verdict == "correct" else "wrong"


def _dedup_key(topic_id: str, seed: int, question_id: str) -> str:
    return f"{PRACTICE_KIND}:{topic_id}:{seed}:{question_id}"


def _stored_status(row: PracticeRecord) -> str:
    if row.is_correct is None:
        return "skipped"
    return "correct" if row.is_correct else "wrong"


async def _find_dedup(
    session: AsyncSession, dedup_key: str
) -> PracticeRecord | None:
    return await session.scalar(
        select(PracticeRecord).where(PracticeRecord.dedup_key == dedup_key).limit(1)
    )


async def _bank_row_ids(
    session: AsyncSession, question_ids: Sequence[str]
) -> dict[str, int]:
    """题 id（external_id）→ problem_bank 主键；seed 题没有 DB 行则不出现。"""

    if not question_ids:
        return {}
    rows = (
        await session.execute(
            select(ProblemBankItem.external_id, ProblemBankItem.id).where(
                ProblemBankItem.external_id.in_(question_ids)
            )
        )
    ).all()
    return {str(external): int(pk) for external, pk in rows}


async def submit_practice(
    session: AsyncSession,
    *,
    topic_id: str,
    seed: int,
    count: int,
    answers: Sequence[PracticeAnswer],
    mistake_id: int | None = None,
    now: datetime | None = None,
) -> PracticeSubmitResult:
    """逐题判分后写 `practice_records`；绝不写事件/attempts/错题。

    客观题：客户端 `correct` 忽略，服务端按题库答案判；
    自评题：收 `correct`，空白且未自评视为 skipped（不落行）。
    """

    cleaned_topic = (topic_id or "").strip()
    if not cleaned_topic:
        raise PracticeInvalid("topic_id 不能为空")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_PRACTICE_COUNT:
        raise PracticeInvalid(f"count 必须是 1..{MAX_PRACTICE_COUNT} 的整数")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise PracticeInvalid("seed 必须是 32 位无符号整数")
    if mistake_id is not None and await session.get(Mistake, mistake_id) is None:
        raise PracticeMistakeNotFound("错题不存在")

    bank = await get_runtime_bank(session)
    paper = paper_picks(cleaned_topic, seed, count, bank=bank)
    if not paper.items:
        raise PracticeInvalid(EMPTY_MESSAGE)
    by_id = {item.question.id: item for item in paper.items}

    seen: set[str] = set()
    for entry in answers:
        if entry.question_id in seen:
            raise PracticeInvalid("同一题只允许提交一次")
        seen.add(entry.question_id)
        if entry.question_id not in by_id:
            raise PracticeInvalid("题目不属于该练习卷，请重新抽题")

    bank_ids = await _bank_row_ids(session, list(by_id))
    moment = now or datetime.now(UTC)
    results: list[PracticeAnswerResult] = []

    for entry in answers:
        item = by_id[entry.question_id]
        question = item.question
        text = (entry.answer or "").strip()
        dedup_key = _dedup_key(cleaned_topic, seed, question.id)

        existing = await _find_dedup(session, dedup_key)
        if existing is not None:
            results.append(
                PracticeAnswerResult(
                    question_id=question.id,
                    mode=item.mode,
                    status=_stored_status(existing),
                    practice_record_id=existing.id,
                    reused=True,
                )
            )
            continue

        if item.mode == "system":
            if not text:
                results.append(
                    PracticeAnswerResult(
                        question_id=question.id,
                        mode="system",
                        status="skipped",
                        practice_record_id=None,
                    )
                )
                continue
            status = _judge(question, text)
            if status == "uncertain":
                results.append(
                    PracticeAnswerResult(
                        question_id=question.id,
                        mode="system",
                        status="uncertain",
                        practice_record_id=None,
                    )
                )
                continue
            is_correct = status == "correct"
        else:
            if entry.correct is None:
                if not text:
                    results.append(
                        PracticeAnswerResult(
                            question_id=question.id,
                            mode="self_eval",
                            status="skipped",
                            practice_record_id=None,
                        )
                    )
                    continue
                raise PracticeInvalid("解答大题需在纸上完成并自评：请传 correct")
            status = "correct" if entry.correct else "wrong"
            is_correct = entry.correct

        row = PracticeRecord(
            source_mistake_id=mistake_id,
            problem_bank_id=bank_ids.get(question.id),
            kind=PRACTICE_KIND,
            problem_text=question.prompt,
            student_answer=text or None,
            is_correct=is_correct,
            topic_id=cleaned_topic,
            seed=seed,
            dedup_key=dedup_key,
            created_at=moment,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            # 并发重复提交：唯一索引兜底，回看已有行。
            existing = await _find_dedup(session, dedup_key)
            if existing is None:
                raise
            results.append(
                PracticeAnswerResult(
                    question_id=question.id,
                    mode=item.mode,
                    status=_stored_status(existing),
                    practice_record_id=existing.id,
                    reused=True,
                )
            )
            continue
        results.append(
            PracticeAnswerResult(
                question_id=question.id,
                mode=item.mode,
                status=status,
                practice_record_id=row.id,
            )
        )

    return PracticeSubmitResult(
        topic_id=cleaned_topic,
        seed=seed,
        count=count,
        items=tuple(results),
    )
