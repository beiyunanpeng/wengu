"""P3-3a 英语背诵：记忆阶梯自评服务（确定性、事实可重算、同日幂等）。

背诵不是错题也不是作答：本模块只写 learning_events(type='recitation_reviewed',
mistake_id=NULL)、recitation_items 与 recitation_reviews，绝不碰 mistakes /
mistake_versions / attempts / review_schedules，因此掌握度与复习排期不受影响。

阶梯复用 `review_policy.MEMORY_LADDER=(1, 3, 7, 14, 30)`：
- 条目初始 rung=0；`remembered` 进一档，`forgot` 保持当前档（不倒退）；
- 下次到期日一律 `reviewed_on + ladder[rung]`，rung 取本次判定后的档位；
- 已在最高档仍 `remembered` → 毕业：`scheduled_next=NULL`，条目保留但不再排；
- 新的条目（历史零自评）视为今天到期。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_config import daily_recitation_limit
from app.models import LearningEvent, RecitationItem, RecitationReview
from app.services.events import record_event
from app.services.recompute import RECITATION_REVIEWED
from app.services.review_policy import MEMORY_LADDER

ITEM_ACTIVE = "active"
ITEM_RETIRED = "retired"
ITEM_STATUSES = (ITEM_ACTIVE, ITEM_RETIRED)

VERDICT_REMEMBERED = "remembered"
VERDICT_FORGOT = "forgot"
VERDICTS = (VERDICT_REMEMBERED, VERDICT_FORGOT)

MAX_LIST_LIMIT = 200


class RecitationError(Exception):
    pass


class RecitationNotFound(RecitationError):
    pass


class RecitationConflict(RecitationError):
    pass


class RecitationDuplicate(RecitationError):
    pass


class RecitationInvalid(RecitationError, ValueError):
    pass


@dataclass(frozen=True)
class RecitationDecision:
    rung: int
    scheduled_next: date | None
    graduated: bool


@dataclass(frozen=True)
class ItemState:
    """由自评历史重算出的当前状态；`reviewed_on=None` 表示从未自评。"""

    rung: int
    scheduled_next: date | None
    graduated: bool
    reviewed_on: date | None


@dataclass(frozen=True)
class ReviewOutcome:
    item: RecitationItem
    review: RecitationReview
    event: LearningEvent
    created: bool


@dataclass(frozen=True)
class DueItem:
    item: RecitationItem
    state: ItemState


@dataclass(frozen=True)
class DueList:
    items: tuple[DueItem, ...]
    due_total: int
    limit: int

    @property
    def returned(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class ItemList:
    items: tuple[RecitationItem, ...]
    total: int


def decide(
    rung: int,
    verdict: str,
    reviewed_on: date,
    *,
    ladder: tuple[int, ...] = MEMORY_LADDER,
) -> RecitationDecision:
    """纯函数：当前档位 + 本次判定 → 新档位与下次到期日。"""

    if verdict not in VERDICTS:
        raise RecitationInvalid(f"verdict 只能是 {VERDICTS}")
    if not ladder or any(step < 1 for step in ladder):
        raise RecitationInvalid("阶梯必须是正整数序列")
    if rung < 0 or rung >= len(ladder):
        raise RecitationInvalid("rung 超出阶梯范围")

    if verdict == VERDICT_REMEMBERED:
        if rung >= len(ladder) - 1:
            return RecitationDecision(rung=rung, scheduled_next=None, graduated=True)
        next_rung = rung + 1
        return RecitationDecision(
            rung=next_rung,
            scheduled_next=reviewed_on + timedelta(days=ladder[next_rung]),
            graduated=False,
        )

    return RecitationDecision(
        rung=rung,
        scheduled_next=reviewed_on + timedelta(days=ladder[rung]),
        graduated=False,
    )


def replay_state(
    history: Sequence[tuple[date, str]],
    *,
    ladder: tuple[int, ...] = MEMORY_LADDER,
) -> ItemState:
    """按 `(reviewed_on, verdict)` 正序重放；同输入必得同状态。"""

    rung = 0
    scheduled_next: date | None = None
    graduated = False
    reviewed_on: date | None = None
    for day, verdict in history:
        decision = decide(rung, verdict, day, ladder=ladder)
        rung = decision.rung
        scheduled_next = decision.scheduled_next
        graduated = decision.graduated
        reviewed_on = day
    return ItemState(
        rung=rung,
        scheduled_next=scheduled_next,
        graduated=graduated,
        reviewed_on=reviewed_on,
    )


def is_due(state: ItemState, today: date) -> bool:
    if state.reviewed_on is None:
        return True
    if state.graduated or state.scheduled_next is None:
        return False
    return state.scheduled_next <= today


def _normalize_text(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise RecitationInvalid(f"{field} 不能为空")
    return text


def _review_history(reviews: Sequence[RecitationReview]) -> list[tuple[date, str]]:
    return [(row.reviewed_on, row.verdict) for row in reviews]


def _verify_history(reviews: Sequence[RecitationReview]) -> None:
    """存储行必须与事件重算结果一致；不一致说明事实被改写，拒绝继续。"""

    rung = 0
    for row in reviews:
        try:
            decision = decide(rung, row.verdict, row.reviewed_on)
        except RecitationInvalid as exc:
            raise RecitationConflict("自评历史非法") from exc
        if decision.rung != row.rung or decision.scheduled_next != row.scheduled_next:
            raise RecitationConflict("自评历史与阶梯重算不一致")
        rung = decision.rung


async def _get_item(session: AsyncSession, item_id: int) -> RecitationItem:
    item = await session.get(RecitationItem, item_id)
    if item is None:
        raise RecitationNotFound("背诵条目不存在")
    return item


async def _reviews_for(
    session: AsyncSession, item_id: int
) -> list[RecitationReview]:
    return list(
        (
            await session.scalars(
                select(RecitationReview)
                .where(RecitationReview.item_id == item_id)
                .order_by(RecitationReview.reviewed_on, RecitationReview.id)
            )
        ).all()
    )


async def create_item(
    session: AsyncSession,
    *,
    subject: str,
    prompt: str,
    answer: str | None = None,
    unit: str | None = None,
    created_by: str = "parent",
    now: datetime | None = None,
) -> RecitationItem:
    subject = _normalize_text(subject, "subject")
    prompt = _normalize_text(prompt, "prompt")
    cleaned_answer = answer.strip() if isinstance(answer, str) else None
    cleaned_unit = unit.strip() if isinstance(unit, str) else None
    existing = (
        await session.execute(
            select(RecitationItem.id).where(
                RecitationItem.subject == subject,
                RecitationItem.prompt == prompt,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise RecitationDuplicate("同科同条目已存在")

    item = RecitationItem(
        subject=subject,
        prompt=prompt,
        answer=cleaned_answer or None,
        unit=cleaned_unit or None,
        status=ITEM_ACTIVE,
        created_by=created_by,
        created_at=now or datetime.now(UTC),
    )
    try:
        async with session.begin_nested():
            session.add(item)
            await session.flush()
    except IntegrityError as exc:
        raise RecitationDuplicate("同科同条目已存在") from exc
    return item


async def update_item(
    session: AsyncSession,
    item_id: int,
    *,
    prompt: str | None = None,
    answer: str | None = None,
    unit: str | None = None,
    status: str | None = None,
) -> RecitationItem:
    item = await _get_item(session, item_id)
    if status is not None and status not in ITEM_STATUSES:
        raise RecitationInvalid(f"status 只能是 {ITEM_STATUSES}")
    if prompt is not None:
        item.prompt = _normalize_text(prompt, "prompt")
        duplicate = (
            await session.execute(
                select(RecitationItem.id).where(
                    RecitationItem.subject == item.subject,
                    RecitationItem.prompt == item.prompt,
                    RecitationItem.id != item.id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise RecitationDuplicate("同科同条目已存在")
    if answer is not None:
        item.answer = answer.strip() or None
    if unit is not None:
        item.unit = unit.strip() or None
    if status is not None:
        item.status = status
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise RecitationDuplicate("同科同条目已存在") from exc
    return item


async def list_items(
    session: AsyncSession,
    *,
    subject: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ItemList:
    if limit < 1 or limit > MAX_LIST_LIMIT:
        raise RecitationInvalid(f"limit 必须在 1..{MAX_LIST_LIMIT}")
    if offset < 0:
        raise RecitationInvalid("offset 不能为负")
    if status is not None and status not in ITEM_STATUSES:
        raise RecitationInvalid(f"status 只能是 {ITEM_STATUSES}")

    filters = []
    if subject is not None:
        filters.append(RecitationItem.subject == subject.strip())
    if status is not None:
        filters.append(RecitationItem.status == status)

    total = int(
        await session.scalar(
            select(func.count()).select_from(RecitationItem).where(*filters)
        )
        or 0
    )
    rows = (
        await session.scalars(
            select(RecitationItem)
            .where(*filters)
            .order_by(RecitationItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ItemList(items=tuple(rows), total=total)


async def _reviews_by_item(
    session: AsyncSession, item_ids: Sequence[int]
) -> dict[int, list[RecitationReview]]:
    if not item_ids:
        return {}
    rows = (
        await session.scalars(
            select(RecitationReview)
            .where(RecitationReview.item_id.in_(item_ids))
            .order_by(
                RecitationReview.item_id,
                RecitationReview.reviewed_on,
                RecitationReview.id,
            )
        )
    ).all()
    grouped: dict[int, list[RecitationReview]] = {item_id: [] for item_id in item_ids}
    for row in rows:
        grouped.setdefault(row.item_id, []).append(row)
    return grouped


async def due_items(
    session: AsyncSession,
    today: date,
    *,
    limit: int | None = None,
    daily_limit: int | None = None,
) -> DueList:
    """到期背诵条目：新条目与 `scheduled_next <= today` 的活跃条目。

    默认上限取运行时配置 `daily_recitation_limit`（热加载，默认 5、上限 20），
    `limit` 是调用方额外的硬上限，最终取较小值；`due_total` 不受截断影响。
    """

    cap = daily_recitation_limit() if daily_limit is None else daily_limit
    if cap < 1:
        raise RecitationInvalid("daily_limit 必须 ≥1")
    if limit is not None and limit < 1:
        raise RecitationInvalid("limit 必须 ≥1")
    effective = cap if limit is None else min(cap, limit)

    items = (
        await session.scalars(
            select(RecitationItem)
            .where(RecitationItem.status == ITEM_ACTIVE)
            .order_by(RecitationItem.id)
        )
    ).all()
    reviews = await _reviews_by_item(session, [item.id for item in items])

    due: list[DueItem] = []
    for item in items:
        history = reviews.get(item.id, [])
        _verify_history(history)
        state = replay_state(_review_history(history))
        if is_due(state, today):
            due.append(DueItem(item=item, state=state))

    due.sort(
        key=lambda entry: (
            entry.state.scheduled_next or date.min,
            entry.item.id,
        )
    )
    return DueList(
        items=tuple(due[:effective]),
        due_total=len(due),
        limit=effective,
    )


def _payload(event: LearningEvent) -> Mapping[str, Any]:
    if not event.payload:
        return {}
    try:
        data = json.loads(event.payload)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, Mapping) else {}


async def _event_for(
    session: AsyncSession, item_id: int, reviewed_on: date
) -> LearningEvent | None:
    return (
        await session.execute(
            select(LearningEvent).where(
                LearningEvent.idempotency_key
                == f"recitation:{item_id}:{reviewed_on.isoformat()}"
            )
        )
    ).scalar_one_or_none()


async def _existing_review(
    session: AsyncSession, item_id: int, reviewed_on: date
) -> RecitationReview | None:
    return (
        await session.execute(
            select(RecitationReview).where(
                RecitationReview.item_id == item_id,
                RecitationReview.reviewed_on == reviewed_on,
            )
        )
    ).scalar_one_or_none()


async def review_item(
    session: AsyncSession,
    item_id: int,
    *,
    verdict: str,
    reviewed_on: date,
    actor: str = "student",
    now: datetime | None = None,
) -> ReviewOutcome:
    """一次自评：事件与自评行同日唯一；重复提交返回既有结果，不改写。"""

    if verdict not in VERDICTS:
        raise RecitationInvalid(f"verdict 只能是 {VERDICTS}")
    if actor not in ("student", "parent"):
        raise RecitationInvalid("actor 只能是 student 或 parent")
    item = await _get_item(session, item_id)
    if item.status != ITEM_ACTIVE:
        raise RecitationConflict("已停用的背诵条目不能自评")

    existing = await _existing_review(session, item_id, reviewed_on)
    if existing is not None:
        event = await _event_for(session, item_id, reviewed_on)
        if event is None:
            raise RecitationConflict("自评记录缺少对应事件")
        return ReviewOutcome(
            item=item, review=existing, event=event, created=False
        )

    history = await _reviews_for(session, item_id)
    _verify_history(history)
    state = replay_state(_review_history(history))
    decision = decide(state.rung, verdict, reviewed_on)
    moment = now or datetime.now(UTC)

    event, event_created = await record_event(
        session,
        RECITATION_REVIEWED,
        actor,
        idempotency_key=f"recitation:{item_id}:{reviewed_on.isoformat()}",
        mistake_id=None,
        payload={
            "item_id": item_id,
            "verdict": verdict,
            "rung": decision.rung,
            "scheduled_next": (
                decision.scheduled_next.isoformat()
                if decision.scheduled_next is not None
                else None
            ),
            "completed_on": reviewed_on.isoformat(),
        },
    )

    review = RecitationReview(
        item_id=item_id,
        verdict=verdict,
        rung=decision.rung,
        reviewed_on=reviewed_on,
        scheduled_next=decision.scheduled_next,
        event_id=event.id,
        created_at=moment,
    )
    try:
        async with session.begin_nested():
            session.add(review)
            await session.flush()
    except IntegrityError:
        existing = await _existing_review(session, item_id, reviewed_on)
        if existing is None:
            raise
        return ReviewOutcome(
            item=item, review=existing, event=event, created=False
        )

    if not event_created:
        # 事件已存在但自评行缺失（崩溃恢复）：以既有事件记录为准
        payload = _payload(event)
        stored_rung = payload.get("rung")
        stored_next = payload.get("scheduled_next")
        if isinstance(stored_rung, int) and not isinstance(stored_rung, bool):
            review.rung = stored_rung
        if isinstance(stored_next, str):
            review.scheduled_next = date.fromisoformat(stored_next)
        elif stored_next is None:
            review.scheduled_next = None
        await session.flush()
        return ReviewOutcome(
            item=item, review=review, event=event, created=False
        )

    return ReviewOutcome(item=item, review=review, event=event, created=True)
