"""P2-5 家长看板 API：纯只读确定性统计。

只有 GET：不提供任何写入/清空入口，也不触发模型或网络调用（统计逻辑全部在
`services.dashboard` 里对本地事实表做 SELECT）。孩子与家长看到同一份数据，
不做角色过滤、不做实时推送/锁屏/问责。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.services.dashboard import (
    DEFAULT_CURVE_DAYS,
    MAX_CURVE_DAYS,
    DashboardSnapshot,
    build_dashboard,
)

router = APIRouter(tags=["dashboard"])


class TopicWeaknessView(BaseModel):
    topic_id: str
    name: str | None
    subject: str | None
    active_mistakes: int


class SubjectWeaknessView(BaseModel):
    subject: str
    active_mistakes: int


class ConceptMasteryView(BaseModel):
    concept_id: int
    name: str
    category_id: str
    category_name: str | None
    mastery: float


class CurvePointView(BaseModel):
    date: date
    mastery: float


class InventoryView(BaseModel):
    active: int
    voided: int
    unassigned_active: int


class MasteryView(BaseModel):
    overall: float
    concepts: list[ConceptMasteryView]
    curve: list[CurvePointView]
    curve_days: int


class DueView(BaseModel):
    today: int
    overdue: int
    total: int


class CompletionView(BaseModel):
    reviews_this_week: int
    graduated_total: int
    graduated_this_week: int


class BankGapTopicView(BaseModel):
    topic_id: str
    name: str | None
    subject: str | None
    active_mistakes: int
    open_schedules: int


class BankGapView(BaseModel):
    topics: list[BankGapTopicView]
    unassigned_open: int


class GovernanceView(BaseModel):
    appeal_count: int
    appealed_gradings: int
    void_events: int
    reactivate_events: int


class EventStatsView(BaseModel):
    total_events: int
    by_type: dict[str, int]
    attempts_correct: int
    attempts_wrong: int
    attempt_accuracy: float | None


class StreakDayView(BaseModel):
    date: date
    done: bool


class StreakView(BaseModel):
    today_done: bool
    current_streak: int
    longest_streak: int
    learning_days_total: int
    recent_days: list[StreakDayView]


class DashboardResponse(BaseModel):
    today: date
    week_start: date
    inventory: InventoryView
    weak_topics: list[TopicWeaknessView]
    weak_subjects: list[SubjectWeaknessView]
    mastery: MasteryView
    due: DueView
    completion: CompletionView
    bank_gap: BankGapView
    governance: GovernanceView
    event_stats: EventStatsView
    streak: StreakView
    pomodoros_today: int
    focus_minutes_this_week: int


def _to_response(snapshot: DashboardSnapshot) -> DashboardResponse:
    return DashboardResponse(
        today=snapshot.today,
        week_start=snapshot.week_start,
        inventory=InventoryView(
            active=snapshot.active_mistakes,
            voided=snapshot.voided_mistakes,
            unassigned_active=snapshot.unassigned_active,
        ),
        weak_topics=[
            TopicWeaknessView(
                topic_id=item.topic_id,
                name=item.name,
                subject=item.subject,
                active_mistakes=item.active_mistakes,
            )
            for item in snapshot.weak_topics
        ],
        weak_subjects=[
            SubjectWeaknessView(subject=item.subject, active_mistakes=item.active_mistakes)
            for item in snapshot.weak_subjects
        ],
        mastery=MasteryView(
            overall=snapshot.overall_mastery,
            concepts=[
                ConceptMasteryView(
                    concept_id=item.concept_id,
                    name=item.name,
                    category_id=item.category_id,
                    category_name=item.category_name,
                    mastery=item.mastery,
                )
                for item in snapshot.concept_mastery
            ],
            curve=[CurvePointView(date=item.date, mastery=item.mastery) for item in snapshot.mastery_curve],
            curve_days=snapshot.curve_days,
        ),
        due=DueView(
            today=snapshot.due_today,
            overdue=snapshot.due_overdue,
            total=snapshot.due_total,
        ),
        completion=CompletionView(
            reviews_this_week=snapshot.reviews_completed_this_week,
            graduated_total=snapshot.graduated_total,
            graduated_this_week=snapshot.graduated_this_week,
        ),
        bank_gap=BankGapView(
            topics=[
                BankGapTopicView(
                    topic_id=item.topic_id,
                    name=item.name,
                    subject=item.subject,
                    active_mistakes=item.active_mistakes,
                    open_schedules=item.open_schedules,
                )
                for item in snapshot.bank_gap_topics
            ],
            unassigned_open=snapshot.bank_gap_unassigned_open,
        ),
        governance=GovernanceView(
            appeal_count=snapshot.appeal_count,
            appealed_gradings=snapshot.appealed_gradings,
            void_events=snapshot.void_events,
            reactivate_events=snapshot.reactivate_events,
        ),
        event_stats=EventStatsView(**snapshot.event_stats),
        streak=StreakView(
            today_done=snapshot.streak.today_done,
            current_streak=snapshot.streak.current_streak,
            longest_streak=snapshot.streak.longest_streak,
            learning_days_total=snapshot.streak.learning_days_total,
            recent_days=[StreakDayView(date=day.date, done=day.done) for day in snapshot.streak.recent_days],
        ),
        pomodoros_today=snapshot.pomodoros_today,
        focus_minutes_this_week=snapshot.focus_minutes_this_week,
    )


@router.get("/api/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    today: date | None = Query(default=None),
    curve_days: int = Query(default=DEFAULT_CURVE_DAYS, ge=1, le=MAX_CURVE_DAYS),
    session: AsyncSession = Depends(get_session),
) -> DashboardResponse:
    """只读看板快照；同一 `today/curve_days` 与数据库状态必得同一结果。"""

    snapshot = await build_dashboard(session, today or date.today(), curve_days=curve_days)
    return _to_response(snapshot)
