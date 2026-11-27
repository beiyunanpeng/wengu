"""把课标词表灌入共享背诵池；不触发 API、UI 或自动调度。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime_config import seed_grade_ceiling
from app.models.recitation import RecitationItem
from app.seed.vocab import VocabIndex, VocabWord, load_vocab
from app.services.recitation import RecitationDuplicate, create_item


@dataclass(frozen=True, slots=True)
class VocabSeedReport:
    band: int
    seen: int
    created: int
    duplicate_exact: int
    duplicate_casefold: int
    null_answer: int


async def seed_vocab_items(
    session: AsyncSession,
    *,
    vocab_index: VocabIndex | None = None,
    ceiling: int | None = None,
    now: datetime | None = None,
) -> VocabSeedReport:
    band = seed_grade_ceiling() if ceiling is None else ceiling
    index = load_vocab() if vocab_index is None else vocab_index
    words: tuple[VocabWord, ...] = index.visible(band)
    timestamp = now or datetime.now(UTC)

    async with session.begin_nested():
        existing = await session.execute(
            select(RecitationItem.prompt, RecitationItem.source).where(
                RecitationItem.subject == "英语"
            )
        )
        exact_prompts: set[str] = set()
        casefold_prompts: dict[str, bool] = {}
        for prompt, source in existing:
            exact_prompts.add(prompt)
            folded = prompt.casefold()
            casefold_prompts[folded] = (
                casefold_prompts.get(folded, False) or source != "seed"
            )

        created = 0
        duplicate_exact = 0
        duplicate_casefold = 0
        null_answer = 0
        for word in words:
            if word.word in exact_prompts:
                duplicate_exact += 1
                continue
            folded = word.word.casefold()
            if casefold_prompts.get(folded, False):
                duplicate_casefold += 1
                continue
            try:
                item = await create_item(
                    session,
                    subject="英语",
                    prompt=word.word,
                    answer=word.translation,
                    created_by="seed",
                    source="seed",
                    now=timestamp,
                )
            except RecitationDuplicate:
                duplicate_exact += 1
                continue
            exact_prompts.add(item.prompt)
            casefold_prompts.setdefault(item.prompt.casefold(), False)
            created += 1
            null_answer += item.answer is None

    return VocabSeedReport(
        band=band,
        seen=len(words),
        created=created,
        duplicate_exact=duplicate_exact,
        duplicate_casefold=duplicate_casefold,
        null_answer=null_answer,
    )
