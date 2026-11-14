"""P2-13 学科归并唯一口径：`primary_topic_id` → `knowledge_seed.subject`。

看板学科分布与错题本 `subject` 筛选共用本模块——两处各建一套映射会出现
"卡片显示数学 12 道、点进去 0 道"。独立成模块是因为 dashboard 已 import mistakes，
反向 import 会成环。查不到 seed（含未挂主考点）一律落 `UNASSIGNED_SUBJECT`。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeSeed

UNASSIGNED_SUBJECT = "未挂考点"


def subject_for_topic(
    topic_id: str | None, topics: Mapping[str, KnowledgeSeed]
) -> str:
    if topic_id is not None and topic_id in topics:
        return topics[topic_id].subject
    return UNASSIGNED_SUBJECT


async def load_topics(
    session: AsyncSession, topic_ids: Iterable[str | None]
) -> dict[str, KnowledgeSeed]:
    ids = {topic_id for topic_id in topic_ids if topic_id}
    if not ids:
        return {}
    rows = (
        await session.scalars(select(KnowledgeSeed).where(KnowledgeSeed.id.in_(ids)))
    ).all()
    return {row.id: row for row in rows}
