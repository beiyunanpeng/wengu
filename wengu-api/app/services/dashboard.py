"""P2-5 家长看板：只读确定性统计（零模型、无写路径）。

所有数字都从 `learning_events / mistakes / review_schedules / grading_versions`
现算：事件统计与掌握度直接复用 `recompute`（同输入必同输出），掌握度曲线按
过去 N 天逐日回放，同一 `(today, curve_days, 数据库状态)` 必得同一结果。
本模块只有 SELECT，不新增任何写入路径，也不调用模型/网络。

口径（与设计文档 §16 / TICKETS P2-5 对齐）：
- 错题存量：按 `mistakes.status` 分 active / voided；
- 薄弱分布：活跃错题按 `primary_topic_id` 聚合（学科取 seed 的 subject，
  未挂考点单列），不做任何加权；
- 掌握度：只统计当前版本里“已确认”的 concept（与复习排期 min mastery 同源），
  曲线末点 = 各 concept 掌握度的算术平均；样本 < 3 只是看板展示，不据此下结论；
- 到期：活跃错题且排期未完成，`due_date < today` 为逾期、`== today` 为今日；
- 本周完成 / 本周毕业：复习完成事件（`payload.kind="review"`）的 `completed_on`
  落在本周（周一起算）内；毕业总数用 `is_graduated` 从事实推导；
- 题库缺口：活跃错题且存在未完成排期，按主考点检索 seed 题库为空即命中；
- 申诉：`grading_versions.action="appealed"` 的追加版本数（append-only 事实）；
- 作废：当前 voided 错题数 + 作废/撤销事件数（历史留痕，不洗数据）。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Concept,
    GradingVersion,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    MistakeVersion,
    ReviewSchedule,
)
from app.models.mistakes import MISTAKE_ACTIVE, MISTAKE_VOIDED
from app.services.bank import get_bank
from app.services.mistakes import MISTAKE_REACTIVATED_EVENT, MISTAKE_VOIDED_EVENT
from app.services.recompute import (
    ATTEMPT_CORRECT,
    ATTEMPT_WRONG,
    Event,
    is_graduated,
    mastery,
    stats,
)

DEFAULT_CURVE_DAYS = 30
MAX_CURVE_DAYS = 90
REVIEW_EVENT_KIND = "review"
UNASSIGNED_SUBJECT = "未挂考点"


@dataclass(frozen=True)
class TopicWeakness:
    topic_id: str
    name: str | None
    subject: str | None
    active_mistakes: int


@dataclass(frozen=True)
class SubjectWeakness:
    subject: str
    active_mistakes: int


@dataclass(frozen=True)
class ConceptMastery:
    concept_id: int
    name: str
    category_id: str
    category_name: str | None
    mastery: float


@dataclass(frozen=True)
class CurvePoint:
    date: date
    mastery: float


@dataclass(frozen=True)
class BankGapTopic:
    topic_id: str
    name: str | None
    subject: str | None
    active_mistakes: int
    open_schedules: int


@dataclass(frozen=True)
class DashboardSnapshot:
    today: date
    week_start: date
    curve_days: int
    active_mistakes: int
    voided_mistakes: int
    weak_topics: tuple[TopicWeakness, ...]
    weak_subjects: tuple[SubjectWeakness, ...]
    unassigned_active: int
    overall_mastery: float
    concept_mastery: tuple[ConceptMastery, ...]
    mastery_curve: tuple[CurvePoint, ...]
    due_today: int
    due_overdue: int
    due_total: int
    reviews_completed_this_week: int
    graduated_total: int
    graduated_this_week: int
    bank_gap_topics: tuple[BankGapTopic, ...]
    bank_gap_unassigned_open: int
    appeal_count: int
    appealed_gradings: int
    void_events: int
    reactivate_events: int
    event_stats: dict[str, Any]


def _payload(event: Event) -> dict[str, Any]:
    raw = event.payload
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
    else:
        data = raw
    return data if isinstance(data, dict) else {}


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def _review_completed_on(event: Event) -> date | None:
    if event.type not in (ATTEMPT_CORRECT, ATTEMPT_WRONG):
        return None
    payload = _payload(event)
    if payload.get("kind") != REVIEW_EVENT_KIND:
        return None
    raw = payload.get("completed_on")
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_concept_ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(sorted({value for value in values if isinstance(value, int) and not isinstance(value, bool)}))


async def _load_events(session: AsyncSession) -> list[Event]:
    rows = (await session.scalars(select(LearningEvent).order_by(LearningEvent.id))).all()
    return [
        Event(
            type=row.type,
            actor=row.actor,
            mistake_id=row.mistake_id,
            payload=row.payload,
            occurred_at=row.occurred_at,
        )
        for row in rows
    ]


async def _mistake_rows(
    session: AsyncSession,
) -> list[tuple[int, str, str | None]]:
    rows = (await session.execute(select(Mistake.id, Mistake.status, Mistake.primary_topic_id))).all()
    return [(row[0], row[1], row[2]) for row in rows]


async def _confirmed_concept_ids(
    session: AsyncSession,
) -> tuple[int, ...]:
    """当前版本里已确认的 concept 集合（复核与排期 min mastery 同源）。"""

    rows = (
        (
            await session.execute(
                select(MistakeVersion.confirmed_concept_ids_json)
                .join(Mistake, Mistake.id == MistakeVersion.mistake_id)
                .where(
                    MistakeVersion.version == Mistake.current_version,
                    MistakeVersion.confirmed_by.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    ids: set[int] = set()
    for raw in rows:
        ids.update(_parse_concept_ids(raw))
    return tuple(sorted(ids))


async def _concept_mastery(
    session: AsyncSession,
    events: list[Event],
    concept_ids: tuple[int, ...],
) -> tuple[float, tuple[ConceptMastery, ...]]:
    if not concept_ids:
        return 0.0, ()

    concepts = {
        row.id: row for row in (await session.scalars(select(Concept).where(Concept.id.in_(concept_ids)))).all()
    }
    category_ids = {row.category_id for row in concepts.values()}
    categories = (
        {
            row.id: row
            for row in (await session.scalars(select(KnowledgeSeed).where(KnowledgeSeed.id.in_(category_ids)))).all()
        }
        if category_ids
        else {}
    )

    values: list[ConceptMastery] = []
    for concept_id in concept_ids:
        concept = concepts.get(concept_id)
        if concept is None:
            continue
        values.append(
            ConceptMastery(
                concept_id=concept.id,
                name=concept.name,
                category_id=concept.category_id,
                category_name=(categories[concept.category_id].name if concept.category_id in categories else None),
                mastery=mastery(events, concept_id),
            )
        )
    if not values:
        return 0.0, ()
    values.sort(key=lambda item: (item.mastery, item.concept_id))
    overall = sum(item.mastery for item in values) / len(values)
    return overall, tuple(values)


def _mastery_curve(
    events: list[Event],
    concept_ids: tuple[int, ...],
    today: date,
    curve_days: int,
) -> tuple[CurvePoint, ...]:
    """按当前已确认知识点集合逐日回放；无知识点时返回空曲线而不是假 0 线。"""

    if not concept_ids:
        return ()
    timeline = sorted(
        ((_naive(event.occurred_at), event) for event in events),
        key=lambda item: item[0],
    )
    start = today - timedelta(days=curve_days - 1)
    points: list[CurvePoint] = []
    for offset in range(curve_days):
        day = start + timedelta(days=offset)
        cutoff = datetime.combine(day, time.max)
        prefix = [event for moment, event in timeline if moment <= cutoff]
        value = sum(mastery(prefix, concept_id) for concept_id in concept_ids)
        points.append(CurvePoint(date=day, mastery=value / len(concept_ids)))
    return tuple(points)


def _weak_distribution(
    active_topic_counts: Counter[str | None],
    topics: dict[str, KnowledgeSeed],
) -> tuple[
    tuple[TopicWeakness, ...],
    tuple[SubjectWeakness, ...],
    int,
]:
    weak_topics = tuple(
        TopicWeakness(
            topic_id=topic_id,
            name=topics[topic_id].name if topic_id in topics else None,
            subject=topics[topic_id].subject if topic_id in topics else None,
            active_mistakes=count,
        )
        for topic_id, count in sorted(
            ((topic_id, count) for topic_id, count in active_topic_counts.items() if topic_id),
            key=lambda item: (-item[1], item[0]),
        )
    )
    unassigned_active = active_topic_counts.get(None, 0)

    subject_counts: Counter[str] = Counter()
    for topic_id, count in active_topic_counts.items():
        subject = topics[topic_id].subject if topic_id is not None and topic_id in topics else UNASSIGNED_SUBJECT
        subject_counts[subject] += count
    weak_subjects = tuple(
        SubjectWeakness(subject=subject, active_mistakes=count)
        for subject, count in sorted(subject_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return weak_topics, weak_subjects, unassigned_active


async def _due_counts(session: AsyncSession, today: date) -> tuple[int, int, int]:
    due_dates = (
        await session.scalars(
            select(ReviewSchedule.due_date)
            .join(Mistake, Mistake.id == ReviewSchedule.mistake_id)
            .where(
                ReviewSchedule.completed_at.is_(None),
                ReviewSchedule.due_date <= today,
                Mistake.status == MISTAKE_ACTIVE,
            )
        )
    ).all()
    overdue = sum(1 for due in due_dates if due < today)
    due_today = sum(1 for due in due_dates if due == today)
    return due_today, overdue, len(due_dates)


async def _bank_gap(
    session: AsyncSession,
    active_topic_counts: Counter[str | None],
    topics: dict[str, KnowledgeSeed],
) -> tuple[tuple[BankGapTopic, ...], int]:
    """活跃且未完成排期的主考点中，seed 题库零题的清单（due_queue 会退 redo）。"""

    open_topics = (
        (
            await session.execute(
                select(Mistake.primary_topic_id)
                .join(ReviewSchedule, ReviewSchedule.mistake_id == Mistake.id)
                .where(
                    ReviewSchedule.completed_at.is_(None),
                    Mistake.status == MISTAKE_ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    open_counts: Counter[str] = Counter(topic_id for topic_id in open_topics if topic_id)
    unassigned_open = sum(1 for topic_id in open_topics if not topic_id)

    bank = get_bank()
    gaps: list[BankGapTopic] = []
    for topic_id, open_schedules in open_counts.items():
        if bank.questions_for(topic_id):
            continue
        gaps.append(
            BankGapTopic(
                topic_id=topic_id,
                name=topics[topic_id].name if topic_id in topics else None,
                subject=topics[topic_id].subject if topic_id in topics else None,
                active_mistakes=active_topic_counts.get(topic_id, 0),
                open_schedules=open_schedules,
            )
        )
    gaps.sort(key=lambda item: (-item.open_schedules, -item.active_mistakes, item.topic_id))
    return tuple(gaps), unassigned_open


async def _appeal_counts(session: AsyncSession) -> tuple[int, int]:
    appeal_count = int(
        await session.scalar(
            select(func.count()).select_from(GradingVersion).where(GradingVersion.action == "appealed")
        )
        or 0
    )
    appealed_gradings = int(
        await session.scalar(
            select(func.count(func.distinct(GradingVersion.grading_id))).where(GradingVersion.action == "appealed")
        )
        or 0
    )
    return appeal_count, appealed_gradings


async def build_dashboard(
    session: AsyncSession,
    today: date,
    *,
    curve_days: int = DEFAULT_CURVE_DAYS,
) -> DashboardSnapshot:
    """组装看板快照；纯查询，不写库、不调模型。"""

    if curve_days < 1 or curve_days > MAX_CURVE_DAYS:
        raise ValueError(f"curve_days 必须在 1..{MAX_CURVE_DAYS} 之间")

    week_start = today - timedelta(days=today.weekday())
    events = await _load_events(session)
    mistakes = await _mistake_rows(session)
    active_topic_counts: Counter[str | None] = Counter(
        primary_topic_id for _, status, primary_topic_id in mistakes if status == MISTAKE_ACTIVE
    )
    active_mistakes = sum(active_topic_counts.values())
    voided_mistakes = sum(1 for _, status, _ in mistakes if status == MISTAKE_VOIDED)

    topic_ids = {topic_id for topic_id in active_topic_counts if topic_id}
    topics = (
        {
            row.id: row
            for row in (await session.scalars(select(KnowledgeSeed).where(KnowledgeSeed.id.in_(topic_ids)))).all()
        }
        if topic_ids
        else {}
    )
    weak_topics, weak_subjects, unassigned_active = _weak_distribution(active_topic_counts, topics)

    concept_ids = await _confirmed_concept_ids(session)
    overall_mastery, concept_mastery = await _concept_mastery(session, events, concept_ids)
    curve = _mastery_curve(events, concept_ids, today, curve_days)

    due_today, due_overdue, due_total = await _due_counts(session, today)

    week_reviews = [
        event
        for event in events
        if (completed_on := _review_completed_on(event)) is not None and week_start <= completed_on <= today
    ]
    graduated_this_week = sum(1 for event in week_reviews if _payload(event).get("graduated") is True)

    mistake_ids = {event.mistake_id for event in events if event.mistake_id is not None}
    graduated_total = sum(1 for mistake_id in mistake_ids if is_graduated(events, mistake_id))

    bank_gap_topics, bank_gap_unassigned_open = await _bank_gap(session, active_topic_counts, topics)
    appeal_count, appealed_gradings = await _appeal_counts(session)
    void_events = sum(1 for event in events if event.type == MISTAKE_VOIDED_EVENT)
    reactivate_events = sum(1 for event in events if event.type == MISTAKE_REACTIVATED_EVENT)

    return DashboardSnapshot(
        today=today,
        week_start=week_start,
        curve_days=curve_days,
        active_mistakes=active_mistakes,
        voided_mistakes=voided_mistakes,
        weak_topics=weak_topics,
        weak_subjects=weak_subjects,
        unassigned_active=unassigned_active,
        overall_mastery=overall_mastery,
        concept_mastery=concept_mastery,
        mastery_curve=curve,
        due_today=due_today,
        due_overdue=due_overdue,
        due_total=due_total,
        reviews_completed_this_week=len(week_reviews),
        graduated_total=graduated_total,
        graduated_this_week=graduated_this_week,
        bank_gap_topics=bank_gap_topics,
        bank_gap_unassigned_open=bank_gap_unassigned_open,
        appeal_count=appeal_count,
        appealed_gradings=appealed_gradings,
        void_events=void_events,
        reactivate_events=reactivate_events,
        event_stats=stats(events),
    )
