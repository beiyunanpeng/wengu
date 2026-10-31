"""P1-7a 复习排期服务：用户触发、事实可重放、写入幂等。

事实源只有两类 learning_events：
- review_scheduled（仅首次排期）记录 subject/ladder/mastery 与初始到期日；
- attempt_correct / attempt_wrong 且 payload.kind="review" 记录每次复习结果。

ReviewState 不落库：derive_review_state() 从 initial_state() 起逐条调用
review_policy.decide() 重放事件；review_schedules 只是派生排期快照，完成前会校验
rung 与重放结果一致。P1-7c 的自动排复习不在本模块开启，schedule_initial() 只由
用户确认 wrong 触发。
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_config import (
    MAX_DAILY_REVIEW_LIMIT,
    daily_review_limit,
    exam_day_limit_factor,
)
from app.judge.normalize import judge_answer
from app.models import (
    Attempt,
    CalendarEvent,
    GradingResult,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    ProblemBankItem,
    ReviewSchedule,
)
from app.models.mistakes import MISTAKE_ACTIVE
from app.seed.bank import BankQuestion
from app.services.bank import (
    AnswerMode,
    BankPick,
    Coverage,
    find_same_type,
    get_bank,
)
from app.services.events import record_event
from app.services.recompute import (
    ATTEMPT_CORRECT,
    ATTEMPT_WRONG,
    mastery,
)
from app.services.recompute import (
    Event as RecomputeEvent,
)
from app.services.review_policy import (
    SUBJECT_LADDERS,
    ReviewState,
    decide,
    initial_state,
    ladder_for,
    review_interval,
)

REVIEW_SCHEDULED = "review_scheduled"
REVIEW_EVENT_KIND = "review"
REVIEW_ATTEMPT_KIND = "review"

AttemptSource = Literal["student_self", "system_quiz"]
DueTask = Literal["quiz", "self_eval", "redo"]
QuizVerdict = Literal["correct", "wrong"]


class ReviewError(Exception):
    pass


class ReviewNotFound(ReviewError):
    pass


class ReviewConflict(ReviewError):
    pass


class ReviewStateError(ReviewError):
    pass


class ReviewSubjectError(ReviewError):
    pass


class ReviewSubjectMissing(ReviewSubjectError):
    pass


class ReviewSubjectUnsupported(ReviewSubjectError):
    pass


class ReviewQuizError(ReviewError):
    pass


class ReviewQuizUnavailable(ReviewQuizError):
    """该错题没有可用同类题 / 已按原题重做完成，不能走考核提交。"""


class ReviewQuizStale(ReviewQuizError):
    """客户端看到的题与当前题库选择不一致（题库热更新），必须刷新。"""


class ReviewQuizInvalid(ReviewQuizError):
    """提交内容不完整（缺作答 / 解答大题缺自评）。"""


class ReviewQuizUncertain(ReviewQuizError):
    """judgeAnswer 无法确定（占位符等），绝不猜对错。"""


@dataclass(frozen=True)
class ReviewFact:
    correct: bool
    completed_on: date
    mastery: float


@dataclass(frozen=True)
class ReviewHistory:
    state: ReviewState
    ladder: tuple[int, ...]


@dataclass(frozen=True)
class QuizFact:
    """完成事件里记录的考核信息（服务端判分结果），用于幂等回放。"""

    question_id: str
    topic_id: str | None
    mode: AnswerMode
    verdict: QuizVerdict
    verify_status: str | None


@dataclass(frozen=True)
class CompleteResult:
    mistake_id: int
    schedule_id: int
    attempt_id: int
    graduated: bool
    state: ReviewState
    mastery: float
    interval_days: int | None
    due_on: date | None
    next_schedule: ReviewSchedule | None
    correct: bool
    source: str = "student_self"
    quiz: QuizFact | None = None


@dataclass(frozen=True)
class ReviewQuizResult:
    completion: CompleteResult
    question: BankQuestion
    mode: AnswerMode
    verdict: QuizVerdict
    seed: int
    pool_size: int


@dataclass(frozen=True)
class DueReview:
    schedule: ReviewSchedule
    mistake: Mistake
    problem_text: str | None
    primary_topic_id: str | None
    task: DueTask
    coverage: Coverage
    bank_gap: bool
    seed: int
    quiz: BankPick | None
    coverage_hint: str | None


@dataclass(frozen=True)
class DueQueue:
    """到期队列快照：只读、不落库；`items` 已按每日上限截断。"""

    items: tuple[DueReview, ...]
    due_total: int
    today_completed: int
    daily_limit: int
    exam_today: bool = False

    @property
    def returned(self) -> int:
        return len(self.items)


async def _get_mistake(session: AsyncSession, mistake_id: int) -> Mistake:
    mistake = await session.get(Mistake, mistake_id)
    if mistake is None:
        raise ReviewNotFound("错题不存在")
    return mistake


async def _latest_version(
    session: AsyncSession, mistake_id: int
) -> MistakeVersion:
    version = (
        await session.execute(
            select(MistakeVersion)
            .where(MistakeVersion.mistake_id == mistake_id)
            .order_by(MistakeVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise ReviewStateError("错题内容版本缺失")
    return version


async def _schedule_by_id(
    session: AsyncSession, mistake_id: int, schedule_id: int
) -> ReviewSchedule:
    schedule = await session.get(ReviewSchedule, schedule_id)
    if schedule is None or schedule.mistake_id != mistake_id:
        raise ReviewNotFound("排期不存在")
    return schedule


async def _open_schedule(
    session: AsyncSession, mistake_id: int
) -> ReviewSchedule | None:
    rows = (
        await session.scalars(
            select(ReviewSchedule)
            .where(
                ReviewSchedule.mistake_id == mistake_id,
                ReviewSchedule.completed_at.is_(None),
            )
            .order_by(ReviewSchedule.id)
        )
    ).all()
    if len(rows) > 1:
        raise ReviewStateError("同一错题存在多条未完成排期")
    return rows[0] if rows else None


async def _schedule_for_event(
    session: AsyncSession, event_id: int
) -> ReviewSchedule | None:
    return (
        await session.execute(
            select(ReviewSchedule).where(ReviewSchedule.source_event_id == event_id)
        )
    ).scalar_one_or_none()


async def _insert_schedule(
    session: AsyncSession, schedule: ReviewSchedule
) -> ReviewSchedule:
    """唯一索引兜底：重试/并发命中时返回已有排期。"""

    try:
        async with session.begin_nested():
            session.add(schedule)
            await session.flush()
        return schedule
    except IntegrityError:
        existing = await _schedule_for_event(session, schedule.source_event_id)
        if existing is None:
            existing = await _open_schedule(session, schedule.mistake_id)
        if existing is None:
            raise
        return existing


def _decode_payload(event: LearningEvent) -> dict[str, Any]:
    if not event.payload:
        raise ReviewStateError("复习事件缺少 payload")
    try:
        data = json.loads(event.payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReviewStateError("复习事件 payload 非法") from exc
    if not isinstance(data, dict):
        raise ReviewStateError("复习事件 payload 必须是对象")
    return data


def _confirmed_concepts(version: MistakeVersion) -> tuple[int, ...]:
    if version.confirmed_by is None:
        return ()
    try:
        raw = json.loads(version.confirmed_concept_ids_json)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(raw, list):
        return ()
    return tuple(
        sorted(
            {
                item
                for item in raw
                if isinstance(item, int) and not isinstance(item, bool)
            }
        )
    )


def _category_id(version: MistakeVersion) -> str | None:
    if version.confirmed_by is not None:
        return version.confirmed_category_id
    return version.suggested_category_id


async def _resolve_subject(
    session: AsyncSession,
    mistake: Mistake,
    version: MistakeVersion,
    *,
    subject_hint: str | None = None,
) -> tuple[str, str]:
    grading = await session.get(GradingResult, mistake.source_grading_id)
    if grading is not None and grading.problem_bank_id is not None:
        item = await session.get(ProblemBankItem, grading.problem_bank_id)
        if item is not None and item.subject.strip():
            return item.subject.strip(), "problem_bank"

    category_id = _category_id(version)
    if category_id:
        seed = await session.get(KnowledgeSeed, category_id)
        if seed is not None and seed.subject.strip():
            source = (
                "confirmed_category"
                if version.confirmed_by is not None
                else "suggested_category"
            )
            return seed.subject.strip(), source

    # 未确认主考点时，用转录草稿自带的学科定阶梯（只决定复习节奏，不等于挂知识点）
    hint = (subject_hint or "").strip()
    if hint in SUBJECT_LADDERS:
        return hint, "source_subject"

    raise ReviewSubjectMissing(
        "无法确定学科，未创建错题与复习排期："
        "请先关联题库题目或补全知识点分类后重试"
    )


def _ladder_for_subject(subject: str) -> tuple[int, ...]:
    try:
        return ladder_for(subject)
    except ValueError as exc:
        raise ReviewSubjectUnsupported(
            f"{exc}；未创建错题与复习排期"
        ) from None


async def _mastery_for(
    session: AsyncSession, concept_ids: Sequence[int]
) -> float:
    if not concept_ids:
        return 0.0
    rows = (await session.scalars(select(LearningEvent))).all()
    events = [
        RecomputeEvent(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]
    return min(mastery(events, concept_id) for concept_id in concept_ids)


def _ladder_from_event(event: LearningEvent) -> tuple[int, ...]:
    payload = _decode_payload(event)
    raw = payload.get("ladder")
    if (
        not isinstance(raw, list)
        or not raw
        or any(
            isinstance(step, bool) or not isinstance(step, int) or step < 1
            for step in raw
        )
    ):
        raise ReviewStateError("首次排期事件 ladder 非法")
    return tuple(raw)


def _review_fact(event: LearningEvent) -> ReviewFact | None:
    payload = _decode_payload(event)
    if payload.get("kind") != REVIEW_EVENT_KIND:
        return None
    correct = payload.get("correct")
    if not isinstance(correct, bool):
        raise ReviewStateError("复习事件缺少 correct")
    raw_date = payload.get("completed_on")
    if not isinstance(raw_date, str):
        raise ReviewStateError("复习事件缺少 completed_on")
    try:
        completed_on = date.fromisoformat(raw_date)
    except ValueError:
        raise ReviewStateError("复习事件 completed_on 非法") from None
    raw_mastery = payload.get("mastery", 0.0)
    if isinstance(raw_mastery, bool) or not isinstance(
        raw_mastery, int | float
    ):
        raise ReviewStateError("复习事件 mastery 非法")
    return ReviewFact(
        correct=correct,
        completed_on=completed_on,
        mastery=float(raw_mastery),
    )


def replay_review_state(
    facts: Sequence[ReviewFact], ladder: tuple[int, ...]
) -> ReviewState:
    """纯重放：同 facts + ladder 必得同 state；毕业后不允许再出现事件。"""

    state = initial_state()
    for index, fact in enumerate(facts):
        try:
            decision = decide(
                state,
                correct=fact.correct,
                completed_on=fact.completed_on,
                mastery=fact.mastery,
                ladder=ladder,
            )
        except ValueError as exc:
            raise ReviewStateError(str(exc)) from None
        state = decision.state
        if decision.graduated and index < len(facts) - 1:
            raise ReviewStateError("毕业后仍有复习事件")
    return state


async def _load_history(
    session: AsyncSession, mistake_id: int
) -> ReviewHistory:
    init = (
        await session.execute(
            select(LearningEvent)
            .where(
                LearningEvent.mistake_id == mistake_id,
                LearningEvent.type == REVIEW_SCHEDULED,
            )
            .order_by(LearningEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if init is None:
        raise ReviewStateError("错题缺少首次排期事件")
    ladder = _ladder_from_event(init)

    events = (
        await session.scalars(
            select(LearningEvent)
            .where(
                LearningEvent.mistake_id == mistake_id,
                LearningEvent.type.in_((ATTEMPT_CORRECT, ATTEMPT_WRONG)),
                LearningEvent.id > init.id,
            )
            .order_by(LearningEvent.occurred_at, LearningEvent.id)
        )
    ).all()
    facts = []
    for event in events:
        fact = _review_fact(event)
        if fact is not None:
            facts.append(fact)
    return ReviewHistory(state=replay_review_state(facts, ladder), ladder=ladder)


async def derive_review_state(
    session: AsyncSession, mistake_id: int
) -> ReviewState:
    """当前复习状态 = 首次排期后的复习作答事件重放结果（不读易变列）。"""

    return (await _load_history(session, mistake_id)).state


async def schedule_initial(
    session: AsyncSession,
    mistake_id: int,
    completed_on: date,
    *,
    actor: Literal["student", "parent"] = "student",
    now: datetime | None = None,
    subject_hint: str | None = None,
) -> ReviewSchedule:
    """用户确认 wrong 后建首次排期；同一错题最多一次。

    首次排期不调用 decide(correct=False)：initial_state() 的 times_wrong=1 已经
    代表首次答错，再消费一次会把同一事实计两遍。首次到期日直接用
    review_interval(第一档, mastery, times_wrong=1) 计算。
    """

    if actor not in ("student", "parent"):
        raise ReviewConflict("只有 student/parent 可以排复习")
    mistake = await _get_mistake(session, mistake_id)
    if mistake.status != MISTAKE_ACTIVE:
        raise ReviewConflict("已作废错题不能排复习")

    existing = (
        await session.execute(
            select(ReviewSchedule)
            .where(ReviewSchedule.mistake_id == mistake_id)
            .order_by(ReviewSchedule.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    version = await _latest_version(session, mistake_id)
    subject, subject_source = await _resolve_subject(
        session, mistake, version, subject_hint=subject_hint
    )
    ladder = _ladder_for_subject(subject)
    mastery_value = await _mastery_for(
        session, _confirmed_concepts(version)
    )

    state = initial_state()
    base_days = ladder[state.rung]
    interval = review_interval(
        base_days, mastery=mastery_value, times_wrong=state.times_wrong
    )
    due_on = completed_on + timedelta(days=interval)
    moment = now or datetime.now(UTC)

    event, _ = await record_event(
        session,
        REVIEW_SCHEDULED,
        actor,
        idempotency_key=f"review:schedule:{mistake_id}:init",
        mistake_id=mistake_id,
        payload={
            "mistake_id": mistake_id,
            "kind": "initial",
            "subject": subject,
            "subject_source": subject_source,
            "ladder": list(ladder),
            "ladder_source": subject_source,
            "mastery": mastery_value,
            "rung": state.rung,
            "times_wrong": state.times_wrong,
            "trailing_correct": state.trailing_correct,
            "base_interval_days": base_days,
            "interval_days": interval,
            "due_on": due_on.isoformat(),
            "trigger": "user_confirmed_wrong",
        },
    )

    schedule = await _schedule_for_event(session, event.id)
    if schedule is not None:
        return schedule

    payload = _decode_payload(event)
    event_due = payload.get("due_on")
    if isinstance(event_due, str):
        with contextlib.suppress(ValueError):
            due_on = date.fromisoformat(event_due)
    event_rung = payload.get("rung")
    event_base = payload.get("base_interval_days")
    if isinstance(event_rung, int) and not isinstance(event_rung, bool):
        state = ReviewState(
            rung=event_rung,
            times_wrong=state.times_wrong,
            trailing_correct=state.trailing_correct,
        )
    if isinstance(event_base, int) and not isinstance(event_base, bool):
        base_days = event_base

    schedule = ReviewSchedule(
        mistake_id=mistake_id,
        rung=state.rung,
        base_interval_days=base_days,
        due_date=due_on,
        source_event_id=event.id,
        created_at=moment,
    )
    return await _insert_schedule(session, schedule)


def _state_from_payload(payload: dict[str, Any]) -> ReviewState:
    values: list[int] = []
    for key in ("rung_after", "times_wrong_after", "trailing_correct_after"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ReviewStateError(f"完成事件缺少 {key}")
        values.append(value)
    return ReviewState(*values)


def _date_from_payload(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReviewStateError("完成事件日期非法")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ReviewStateError("完成事件日期非法") from None


def _mastery_from_payload(payload: dict[str, Any]) -> float:
    value = payload.get("mastery", 0.0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ReviewStateError("完成事件 mastery 非法")
    return float(value)


def _correct_from_payload(payload: dict[str, Any]) -> bool:
    value = payload.get("correct")
    if not isinstance(value, bool):
        raise ReviewStateError("完成事件缺少 correct")
    return value


def _quiz_fact(payload: dict[str, Any]) -> QuizFact | None:
    question_id = payload.get("quiz_question_id")
    if question_id is None:
        return None
    if not isinstance(question_id, str) or not question_id:
        raise ReviewStateError("考核事件 quiz_question_id 非法")
    mode = payload.get("quiz_mode")
    verdict = payload.get("quiz_verdict")
    if mode not in ("system", "self_eval") or verdict not in ("correct", "wrong"):
        raise ReviewStateError("考核事件 quiz_mode/quiz_verdict 非法")
    topic_id = payload.get("quiz_topic_id")
    if topic_id is not None and not isinstance(topic_id, str):
        raise ReviewStateError("考核事件 quiz_topic_id 非法")
    verify_status = payload.get("quiz_verify_status")
    if verify_status is not None and not isinstance(verify_status, str):
        raise ReviewStateError("考核事件 quiz_verify_status 非法")
    return QuizFact(
        question_id=question_id,
        topic_id=topic_id,
        mode=mode,
        verdict=verdict,
        verify_status=verify_status,
    )


async def _completed_result(
    session: AsyncSession,
    *,
    schedule: ReviewSchedule,
    event: LearningEvent,
) -> CompleteResult:
    payload = _decode_payload(event)
    if payload.get("kind") != REVIEW_EVENT_KIND:
        raise ReviewStateError("排期完成事件类型不匹配")
    attempt = (
        await session.execute(
            select(Attempt).where(Attempt.learning_event_id == event.id)
        )
    ).scalar_one_or_none()
    if attempt is None:
        raise ReviewStateError("排期完成事件缺少 attempts 记录")
    next_schedule = await _schedule_for_event(session, event.id)
    graduated = payload.get("graduated")
    if not isinstance(graduated, bool):
        raise ReviewStateError("完成事件缺少 graduated")
    if graduated and next_schedule is not None:
        raise ReviewStateError("已毕业但存在下一次排期")
    if not graduated and next_schedule is None:
        raise ReviewStateError("未毕业但缺少下一次排期")
    interval = payload.get("interval_days")
    interval_days = (
        interval
        if isinstance(interval, int) and not isinstance(interval, bool)
        else None
    )
    return CompleteResult(
        mistake_id=schedule.mistake_id,
        schedule_id=schedule.id,
        attempt_id=attempt.id,
        graduated=graduated,
        state=_state_from_payload(payload),
        mastery=_mastery_from_payload(payload),
        interval_days=interval_days,
        due_on=_date_from_payload(payload.get("due_on")),
        next_schedule=next_schedule,
        correct=_correct_from_payload(payload),
        source=attempt.source,
        quiz=_quiz_fact(payload),
    )


async def complete_attempt(
    session: AsyncSession,
    mistake_id: int,
    *,
    schedule_id: int,
    correct: bool,
    completed_on: date,
    actor: Literal["student", "parent"] = "student",
    source: AttemptSource = "student_self",
    now: datetime | None = None,
    extra_payload: Mapping[str, Any] | None = None,
) -> CompleteResult:
    """完成一次复习：写 attempt 事件 + attempts 行 + 下一次排期（毕业则不写）。

    `source` 只打标签（student_self 原题重做自评 / system_quiz 系统判考核），
    MVP 两者在掌握度里各计 1 次，暂不加权。`extra_payload` 只允许追加考核溯源
    字段（题目 id/模式/判分结论），核心字段由本函数覆盖，客户端无法借此改写事实。
    """

    if actor not in ("student", "parent"):
        raise ReviewConflict("只有 student/parent 可以完成复习")
    if source not in ("student_self", "system_quiz"):
        raise ReviewConflict("source 只能是 student_self 或 system_quiz")
    mistake = await _get_mistake(session, mistake_id)
    if mistake.status != MISTAKE_ACTIVE:
        raise ReviewConflict("已作废错题不能完成复习")
    schedule = await _schedule_by_id(session, mistake_id, schedule_id)
    event_key = f"review:attempt:{schedule.id}"
    existing_event = (
        await session.execute(
            select(LearningEvent).where(
                LearningEvent.idempotency_key == event_key
            )
        )
    ).scalar_one_or_none()

    if schedule.completed_at is not None or existing_event is not None:
        if existing_event is None:
            raise ReviewStateError("排期已完成但缺少完成事件")
        if schedule.completed_at is None:
            raise ReviewStateError("完成事件已存在但排期未完成")
        return await _completed_result(
            session, schedule=schedule, event=existing_event
        )

    history = await _load_history(session, mistake_id)
    if history.state.rung != schedule.rung:
        raise ReviewStateError("排期档位与事件重放不一致")
    version = await _latest_version(session, mistake_id)
    concept_ids = _confirmed_concepts(version)
    mastery_value = await _mastery_for(session, concept_ids)
    try:
        decision = decide(
            history.state,
            correct=correct,
            completed_on=completed_on,
            mastery=mastery_value,
            ladder=history.ladder,
        )
    except ValueError as exc:
        raise ReviewStateError(str(exc)) from None

    moment = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        **dict(extra_payload or {}),
        "mistake_id": mistake_id,
        "kind": REVIEW_EVENT_KIND,
        "schedule_id": schedule.id,
        "correct": correct,
        "completed_on": completed_on.isoformat(),
        "mastery": mastery_value,
        "source": source,
        "concept_ids": list(concept_ids),
        "rung_before": history.state.rung,
        "times_wrong_before": history.state.times_wrong,
        "trailing_correct_before": history.state.trailing_correct,
        "rung_after": decision.state.rung,
        "times_wrong_after": decision.state.times_wrong,
        "trailing_correct_after": decision.state.trailing_correct,
        "base_interval_days": decision.base_days,
        "interval_days": decision.interval_days,
        "due_on": (
            decision.due_on.isoformat()
            if decision.due_on is not None
            else None
        ),
        "graduated": decision.graduated,
    }
    event, created = await record_event(
        session,
        ATTEMPT_CORRECT if correct else ATTEMPT_WRONG,
        actor,
        idempotency_key=event_key,
        mistake_id=mistake_id,
        payload=payload,
    )
    if not created:
        await session.refresh(schedule)
        if schedule.completed_at is None:
            raise ReviewStateError("完成事件已存在但排期未完成")
        return await _completed_result(
            session, schedule=schedule, event=event
        )

    attempt = Attempt(
        mistake_id=mistake_id,
        learning_event_id=event.id,
        kind=REVIEW_ATTEMPT_KIND,
        source=source,
        answer_text=None,
        is_correct=correct,
        created_at=moment,
    )
    session.add(attempt)
    await session.flush()

    schedule.completed_attempt_id = attempt.id
    schedule.completed_at = moment
    await session.flush()

    next_schedule: ReviewSchedule | None = None
    if not decision.graduated:
        if decision.due_on is None:
            raise ReviewStateError("未毕业但缺少下一次到期日")
        next_schedule = ReviewSchedule(
            mistake_id=mistake_id,
            rung=decision.state.rung,
            base_interval_days=decision.base_days,
            due_date=decision.due_on,
            source_event_id=event.id,
            created_at=moment,
        )
        next_schedule = await _insert_schedule(session, next_schedule)

    return CompleteResult(
        mistake_id=mistake_id,
        schedule_id=schedule.id,
        attempt_id=attempt.id,
        graduated=decision.graduated,
        state=decision.state,
        mastery=mastery_value,
        interval_days=decision.interval_days,
        due_on=decision.due_on,
        next_schedule=next_schedule,
        correct=correct,
        source=source,
        quiz=_quiz_fact(payload),
    )


def quiz_seed(mistake_id: int, schedule_id: int) -> int:
    """到期任务选题种子：同一排期永远同题，跨进程/重启可 replay。"""

    return (mistake_id * 0x9E3779B1 + schedule_id) & 0xFFFFFFFF


def _payload_mapping(raw: Any) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, Mapping) else {}
    return {}


async def _today_completed(session: AsyncSession, today: date) -> int:
    """今日已完成复习数：从事件现算，不读任何易变列。"""

    rows = (
        await session.execute(
            select(LearningEvent.payload).where(
                LearningEvent.type.in_((ATTEMPT_CORRECT, ATTEMPT_WRONG))
            )
        )
    ).all()
    day = today.isoformat()
    return sum(
        1
        for (raw,) in rows
        if (payload := _payload_mapping(raw)).get("kind") == REVIEW_EVENT_KIND
        and payload.get("completed_on") == day
    )


async def _has_exam_today(session: AsyncSession, today: date) -> bool:
    """日历上今天是否有 kind='exam' 的硬事件（唯一影响队列上限的规则）。"""

    row = (
        await session.execute(
            select(CalendarEvent.id)
            .where(CalendarEvent.date == today, CalendarEvent.kind == "exam")
            .limit(1)
        )
    ).first()
    return row is not None


async def due_queue(
    session: AsyncSession,
    today: date,
    limit: int | None = None,
    daily_limit: int | None = None,
) -> DueQueue:
    """今日到期（含逾期）的复习任务；纯查询，不写库。

    排序确定性：先逾期（`due_date` 升序，含更早逾期）再今日，同组按
    `mistake_id`，最后用排期 id 兜底。每日上限默认取运行时配置
    `daily_review_limit`（热加载），超过上限的到期项不返回、只计入 `due_total`；
    `limit` 是调用方额外的硬上限，最终取两者较小值。

    P2-3 唯一的队列改动：日历上今天有 `kind='exam'` 事件时，上限按运行时
    配置 `exam_day_limit_factor` 放大（默认 1.5），仍受 200 收口，并标记
    `exam_today`；竞赛/请假/其它事件不放宽。排序、任务类型、thin/gap 不变。

    v2.5 考核优先/重做兜底：按 `primary_topic_id` 检索 seed 题库——
    命中出"同类题考核"，未命中（无主考点或该知识点 0 题）退回原题重做并标
    `bank_gap`。`coverage=thin` 只是覆盖偏薄提示，仍正常出题、不得当 gap。
    """

    if limit is not None and limit < 1:
        raise ValueError("limit 必须 ≥1")
    cap = daily_review_limit() if daily_limit is None else daily_limit
    if cap < 1:
        raise ValueError("daily_limit 必须 ≥1")
    exam_today = await _has_exam_today(session, today)
    if exam_today:
        cap = min(
            round(cap * exam_day_limit_factor()), MAX_DAILY_REVIEW_LIMIT
        )
    effective = cap if limit is None else min(cap, limit)

    due_filter = (
        ReviewSchedule.completed_at.is_(None),
        ReviewSchedule.due_date <= today,
        Mistake.status == MISTAKE_ACTIVE,
    )
    due_total = int(
        await session.scalar(
            select(func.count())
            .select_from(ReviewSchedule)
            .join(Mistake, Mistake.id == ReviewSchedule.mistake_id)
            .where(*due_filter)
        )
        or 0
    )
    today_completed = await _today_completed(session, today)

    rows = (
        await session.execute(
            select(ReviewSchedule, Mistake, MistakeVersion)
            .join(Mistake, Mistake.id == ReviewSchedule.mistake_id)
            .outerjoin(
                MistakeVersion,
                and_(
                    MistakeVersion.mistake_id == Mistake.id,
                    MistakeVersion.version == Mistake.current_version,
                ),
            )
            .where(*due_filter)
            .order_by(
                ReviewSchedule.due_date, Mistake.id, ReviewSchedule.id
            )
            .limit(effective)
        )
    ).all()

    items: list[DueReview] = []
    for schedule, mistake, version in rows:
        seed = quiz_seed(mistake.id, schedule.id)
        pick = find_same_type(mistake.primary_topic_id, seed)
        if pick.question is None:
            task: DueTask = "redo"
        elif pick.mode == "self_eval":
            task = "self_eval"
        else:
            task = "quiz"
        items.append(
            DueReview(
                schedule=schedule,
                mistake=mistake,
                problem_text=version.problem_text if version is not None else None,
                primary_topic_id=pick.topic_id,
                task=task,
                coverage=pick.coverage,
                bank_gap=pick.bank_gap,
                seed=seed,
                quiz=pick if pick.question is not None else None,
                coverage_hint=(
                    "覆盖偏薄"
                    if task == "quiz" and pick.coverage == "thin"
                    else None
                ),
            )
        )
    return DueQueue(
        items=tuple(items),
        due_total=due_total,
        today_completed=today_completed,
        daily_limit=cap,
        exam_today=exam_today,
    )


async def _attempt_event(
    session: AsyncSession, schedule: ReviewSchedule
) -> LearningEvent | None:
    return (
        await session.execute(
            select(LearningEvent).where(
                LearningEvent.idempotency_key
                == f"review:attempt:{schedule.id}"
            )
        )
    ).scalar_one_or_none()


def _recorded_quiz_result(
    pick: BankPick, completion: CompleteResult
) -> ReviewQuizResult:
    if completion.quiz is None:
        raise ReviewQuizUnavailable("该排期已按原题重做完成，不能按考核回放")
    recorded = get_bank().question(completion.quiz.question_id)
    question = recorded or pick.question
    if question is None:
        raise ReviewQuizUnavailable("题库中已找不到该考核题")
    return ReviewQuizResult(
        completion=completion,
        question=question,
        mode=completion.quiz.mode,
        verdict=completion.quiz.verdict,
        seed=pick.seed,
        pool_size=pick.pool_size,
    )


async def submit_review_quiz(
    session: AsyncSession,
    mistake_id: int,
    *,
    schedule_id: int,
    answer: str | None = None,
    correct: bool | None = None,
    question_id: str | None = None,
    completed_on: date,
    actor: Literal["student", "parent"] = "student",
    now: datetime | None = None,
) -> ReviewQuizResult:
    """到期考核提交：服务端按同一种子重算题目并 judgeAnswer 判分后再落库。

    - 可答题：客户端只传作答 `answer`，`correct` 一律由服务端判分得出
      （客户端传了也忽略），source=system_quiz；
    - 解答大题/依赖题图：客户端必须传自评 `correct`，source=student_self；
    - 同一排期幂等：已完成时按事件记录回放，绝不允许用新答案改写旧结果。
    """

    if actor not in ("student", "parent"):
        raise ReviewConflict("只有 student/parent 可以完成复习")
    mistake = await _get_mistake(session, mistake_id)
    if mistake.status != MISTAKE_ACTIVE:
        raise ReviewConflict("已作废错题不能完成复习")
    schedule = await _schedule_by_id(session, mistake_id, schedule_id)
    seed = quiz_seed(mistake.id, schedule.id)
    pick = find_same_type(mistake.primary_topic_id, seed)

    existing_event = await _attempt_event(session, schedule)
    if schedule.completed_at is not None or existing_event is not None:
        if schedule.completed_at is None or existing_event is None:
            raise ReviewStateError("排期与完成事件状态不一致")
        completion = await _completed_result(
            session, schedule=schedule, event=existing_event
        )
        return _recorded_quiz_result(pick, completion)

    if pick.question is None:
        raise ReviewQuizUnavailable(
            "该错题没有可用同类题，请改用原题重做（task=redo）"
        )
    if question_id is not None and question_id != pick.question.id:
        raise ReviewQuizStale("题目已更新，请刷新到期任务后重试")

    if pick.mode == "system":
        text = (answer or "").strip()
        if not text:
            raise ReviewQuizInvalid("请先作答再提交")
        outcome = judge_answer(
            text,
            pick.question.answer,
            acceptable=pick.question.accept,
            unordered=pick.question.unordered,
        )
        if outcome.verdict == "uncertain":
            raise ReviewQuizUncertain(
                "无法自动判分（作答含不确定内容），请改用原题重做或自评"
            )
        judged_correct = outcome.verdict == "correct"
        verdict: QuizVerdict = (
            "correct" if judged_correct else "wrong"
        )
        source: AttemptSource = "system_quiz"
    else:
        if correct is None:
            raise ReviewQuizInvalid(
                "解答大题需在纸上完成并自评：请传 correct"
            )
        judged_correct = correct
        verdict = "correct" if correct else "wrong"
        source = "student_self"

    completion = await complete_attempt(
        session,
        mistake_id,
        schedule_id=schedule.id,
        correct=judged_correct,
        completed_on=completed_on,
        actor=actor,
        source=source,
        now=now,
        extra_payload={
            "quiz_question_id": pick.question.id,
            "quiz_topic_id": pick.question.topic_id,
            "quiz_mode": pick.mode,
            "quiz_verdict": verdict,
            "quiz_verify_status": pick.question.verify_status,
            "quiz_seed": seed,
        },
    )

    # 并发重试可能命中已存在事件：以记录为准回放，不采用本次判分。
    if completion.quiz is not None and completion.quiz.question_id != pick.question.id:
        return _recorded_quiz_result(pick, completion)
    question = pick.question
    if completion.quiz is not None:
        question = get_bank().question(completion.quiz.question_id) or question
    return ReviewQuizResult(
        completion=completion,
        question=question,
        mode=completion.quiz.mode if completion.quiz is not None else pick.mode,
        verdict=(
            completion.quiz.verdict
            if completion.quiz is not None
            else verdict
        ),
        seed=seed,
        pool_size=pick.pool_size,
    )
