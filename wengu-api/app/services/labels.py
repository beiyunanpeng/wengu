"""错题标签候选：零模型、可解释的确定性匹配（P1-6）。

只在题目原文里匹配已有 knowledge_seed 名称与已有 concept 名称/别名；
匹配不到就留空，不猜、不生成新标签、不调用任何模型。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept, ConceptAlias, KnowledgeSeed

MAX_SUGGESTIONS = 3


@dataclass(frozen=True)
class LabelSuggestions:
    category_id: str | None = None
    concept_ids: tuple[int, ...] = ()


def normalize_label_text(value: str) -> str:
    """NFKC + casefold + 去空白；仅用于匹配，不写回数据库。"""

    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", "", text)


async def suggest_labels(
    session: AsyncSession,
    problem_text: str,
    *,
    subject: str | None = None,
    limit: int = MAX_SUGGESTIONS,
) -> LabelSuggestions:
    """返回最多 1 个粗粒度 category + 同 category 下最多 limit 个 concept。"""

    text = normalize_label_text(problem_text)
    if not text:
        return LabelSuggestions()

    topic_stmt = select(KnowledgeSeed.id, KnowledgeSeed.name)
    if subject:
        topic_stmt = topic_stmt.where(KnowledgeSeed.subject == subject)
    topic_matches: list[tuple[int, str]] = []
    for topic_id, name in (await session.execute(topic_stmt)).all():
        normalized = normalize_label_text(name)
        if len(normalized) >= 2 and normalized in text:
            topic_matches.append((len(normalized), topic_id))
    if not topic_matches:
        return LabelSuggestions()

    topic_matches.sort(key=lambda item: (-item[0], item[1]))
    category_id = topic_matches[0][1]

    concept_rows = (
        await session.execute(
            select(Concept.id, Concept.name).where(
                Concept.category_id == category_id,
                Concept.merged_into_id.is_(None),
            )
        )
    ).all()
    if not concept_rows:
        return LabelSuggestions(category_id=category_id)

    concept_ids = [row.id for row in concept_rows]
    aliases: dict[int, list[str]] = {concept_id: [] for concept_id in concept_ids}
    alias_rows = (
        await session.execute(
            select(ConceptAlias.concept_id, ConceptAlias.alias).where(
                ConceptAlias.concept_id.in_(concept_ids)
            )
        )
    ).all()
    for concept_id, alias in alias_rows:
        aliases.setdefault(concept_id, []).append(alias)

    concept_matches: dict[int, int] = {}
    for concept_id, name in concept_rows:
        for candidate in (name, *aliases.get(concept_id, [])):
            normalized = normalize_label_text(candidate)
            if len(normalized) >= 2 and normalized in text:
                concept_matches[concept_id] = max(
                    concept_matches.get(concept_id, 0), len(normalized)
                )

    ranked = sorted(concept_matches.items(), key=lambda item: (-item[1], item[0]))
    return LabelSuggestions(
        category_id=category_id,
        concept_ids=tuple(concept_id for concept_id, _ in ranked[:limit]),
    )
