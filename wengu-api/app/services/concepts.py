"""细粒度 concept 受控生长：优先复用、显式创建、人工归并（P1-6）。

不自动创建 AI 标签；名称/别名在 category 内大小写与空白归一后查重；
归并只写 merged_into_id 与别名，不改写 append-only 的错题版本历史。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.judge.normalize import PLACEHOLDER
from app.models import Concept, ConceptAlias, KnowledgeSeed

MAX_NAME_LENGTH = 50
MAX_ALIASES = 10


class ConceptError(ValueError):
    pass


class CategoryNotFound(LookupError):
    pass


class ConceptNotFound(LookupError):
    pass


class ConceptConflict(ConceptError):
    pass


class ConceptMerged(ConceptConflict):
    pass


@dataclass(frozen=True)
class ConceptResult:
    concept: Concept
    aliases: tuple[str, ...]
    reused: bool


def clean_concept_name(value: str) -> str:
    if not isinstance(value, str):
        raise ConceptConflict("概念名称必须是字符串")
    text = unicodedata.normalize("NFKC", value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ConceptConflict("概念名称不能为空")
    if len(text) > MAX_NAME_LENGTH:
        raise ConceptConflict(f"概念名称不能超过 {MAX_NAME_LENGTH} 字")
    if PLACEHOLDER in text:
        raise ConceptConflict("概念名称不能包含占位符")
    if any(unicodedata.category(char).startswith("C") for char in text):
        raise ConceptConflict("概念名称不能包含控制字符")
    return text


def _match_key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


async def _aliases_for(
    session: AsyncSession, concept_ids: Sequence[int]
) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {concept_id: [] for concept_id in concept_ids}
    if not concept_ids:
        return result
    rows = (
        await session.execute(
            select(ConceptAlias.concept_id, ConceptAlias.alias).where(
                ConceptAlias.concept_id.in_(concept_ids)
            )
        )
    ).all()
    for concept_id, alias in rows:
        result.setdefault(concept_id, []).append(alias)
    return result


async def _category_concepts(
    session: AsyncSession, category_id: str
) -> tuple[list[Concept], dict[int, list[str]]]:
    concepts = list(
        (
            await session.execute(
                select(Concept).where(
                    Concept.category_id == category_id,
                    Concept.merged_into_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    aliases = await _aliases_for(session, [concept.id for concept in concepts])
    return concepts, aliases


def _key_map(
    concepts: Sequence[Concept], aliases: dict[int, list[str]]
) -> dict[str, set[int]]:
    mapping: dict[str, set[int]] = {}
    for concept in concepts:
        for value in (concept.name, *aliases.get(concept.id, [])):
            key = _match_key(value)
            if key:
                mapping.setdefault(key, set()).add(concept.id)
    return mapping


async def _require_category(session: AsyncSession, category_id: str) -> KnowledgeSeed:
    category = await session.get(KnowledgeSeed, category_id)
    if category is None:
        raise CategoryNotFound("知识点 category 不存在")
    return category


async def create_or_reuse_concept(
    session: AsyncSession,
    *,
    name: str,
    category_id: str,
    actor: str,
    aliases: Iterable[str] = (),
) -> ConceptResult:
    """按名称/别名在 category 内复用；无匹配才显式创建（来源=student/parent）。"""

    if actor not in ("student", "parent"):
        raise ConceptConflict("只有 student/parent 可以创建概念")
    cleaned_name = clean_concept_name(name)
    cleaned_aliases: list[str] = []
    for raw in aliases:
        alias = clean_concept_name(raw)
        if _match_key(alias) != _match_key(cleaned_name) and alias not in cleaned_aliases:
            cleaned_aliases.append(alias)
    if len(cleaned_aliases) > MAX_ALIASES:
        raise ConceptConflict(f"别名不能超过 {MAX_ALIASES} 个")

    await _require_category(session, category_id)
    concepts, existing_aliases = await _category_concepts(session, category_id)
    key_map = _key_map(concepts, existing_aliases)

    candidate_ids: set[int] = set()
    for value in (cleaned_name, *cleaned_aliases):
        candidate_ids.update(key_map.get(_match_key(value), set()))
    if len(candidate_ids) > 1:
        raise ConceptConflict("名称/别名在同一 category 内指向多个概念，请先人工归并")

    if candidate_ids:
        concept_id = next(iter(candidate_ids))
        concept = next(item for item in concepts if item.id == concept_id)
        updated_aliases = await _append_aliases(
            session,
            concept=concept,
            aliases=(cleaned_name, *cleaned_aliases),
            existing_aliases=existing_aliases.get(concept.id, []),
            key_map=key_map,
        )
        return ConceptResult(
            concept=concept,
            aliases=tuple(updated_aliases),
            reused=True,
        )

    concept = Concept(
        name=cleaned_name,
        category_id=category_id,
        source=actor,
        status="confirmed",
        merged_into_id=None,
        created_at=datetime.now(UTC),
    )
    try:
        async with session.begin_nested():
            session.add(concept)
            await session.flush()
            for alias in cleaned_aliases:
                session.add(ConceptAlias(concept_id=concept.id, alias=alias))
            await session.flush()
    except IntegrityError:
        existing = (
            await session.execute(
                select(Concept).where(
                    Concept.name == cleaned_name,
                    Concept.category_id == category_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        existing_aliases = await _aliases_for(session, [existing.id])
        return ConceptResult(
            concept=existing,
            aliases=tuple(existing_aliases.get(existing.id, [])),
            reused=True,
        )
    return ConceptResult(concept=concept, aliases=tuple(cleaned_aliases), reused=False)


async def _append_aliases(
    session: AsyncSession,
    *,
    concept: Concept,
    aliases: Iterable[str],
    existing_aliases: Sequence[str],
    key_map: dict[str, set[int]],
) -> list[str]:
    updated = list(existing_aliases)
    existing_keys = {_match_key(alias) for alias in existing_aliases}
    for alias in aliases:
        key = _match_key(alias)
        if not key or key == _match_key(concept.name) or key in existing_keys:
            continue
        owners = key_map.get(key, set())
        if owners - {concept.id}:
            raise ConceptConflict("别名已属于同 category 的其他概念，请先人工归并")
        session.add(ConceptAlias(concept_id=concept.id, alias=alias))
        existing_keys.add(key)
        updated.append(alias)
    await session.flush()
    return updated


async def list_concepts(
    session: AsyncSession,
    *,
    category_id: str | None = None,
    q: str | None = None,
    limit: int = 20,
) -> list[tuple[Concept, list[str]]]:
    stmt = select(Concept).where(Concept.merged_into_id.is_(None))
    if category_id:
        stmt = stmt.where(Concept.category_id == category_id)
    concepts = list((await session.execute(stmt)).scalars().all())
    aliases = await _aliases_for(session, [concept.id for concept in concepts])

    if q:
        key = _match_key(q)
        if key:
            concepts = [
                concept
                for concept in concepts
                if key in _match_key(concept.name)
                or any(key in _match_key(alias) for alias in aliases.get(concept.id, []))
            ]
    concepts.sort(key=lambda concept: (concept.name, concept.id))
    return [(concept, aliases.get(concept.id, [])) for concept in concepts[:limit]]


async def get_concept_with_aliases(
    session: AsyncSession, concept_id: int
) -> tuple[Concept, list[str]]:
    concept = await session.get(Concept, concept_id)
    if concept is None:
        raise ConceptNotFound("概念不存在")
    aliases = await _aliases_for(session, [concept_id])
    return concept, aliases.get(concept_id, [])


async def merge_concepts(
    session: AsyncSession,
    *,
    source_id: int,
    target_id: int,
    actor: str,
) -> tuple[Concept, Concept, int]:
    """人工确认归并：源概念标 merged_into_id，名称/别名并入目标；历史不重写。"""

    if actor not in ("student", "parent"):
        raise ConceptConflict("只有 student/parent 可以归并概念")
    if source_id == target_id:
        raise ConceptConflict("不能把概念归并到自己")
    source = await session.get(Concept, source_id)
    target = await session.get(Concept, target_id)
    if source is None or target is None:
        raise ConceptNotFound("概念不存在")
    if source.merged_into_id is not None:
        raise ConceptMerged("源概念已经归并")
    if target.merged_into_id is not None:
        raise ConceptMerged("目标概念已经归并，请选择最终概念")
    if source.category_id != target.category_id:
        raise ConceptConflict("只能在同一 category 内归并")

    concepts, existing_aliases = await _category_concepts(session, target.category_id)
    key_map = _key_map(
        [concept for concept in concepts if concept.id != source.id], existing_aliases
    )
    source_aliases = existing_aliases.get(source.id, [])
    target_aliases = existing_aliases.get(target.id, [])
    target_keys = {_match_key(alias) for alias in target_aliases}
    target_keys.add(_match_key(target.name))

    aliases_to_add: list[str] = []
    for alias in (source.name, *source_aliases):
        key = _match_key(alias)
        if not key or key in target_keys:
            continue
        owners = key_map.get(key, set())
        if owners - {target.id}:
            raise ConceptConflict(f"别名「{alias}」与其他概念冲突，请先归并那个概念")
        aliases_to_add.append(alias)
        target_keys.add(key)

    source.merged_into_id = target.id
    for alias in aliases_to_add:
        session.add(ConceptAlias(concept_id=target.id, alias=alias))
    await session.flush()
    return source, target, len(aliases_to_add)


def _canonical(by_id: dict[int, Concept], concept_id: int) -> Concept | None:
    current = by_id.get(concept_id)
    seen: set[int] = set()
    while current is not None and current.merged_into_id is not None:
        if current.id in seen:
            return None
        seen.add(current.id)
        current = by_id.get(current.merged_into_id)
    return current


async def resolve_concept_map(
    session: AsyncSession, concept_ids: Iterable[int]
) -> dict[int, Concept]:
    """原始 id → 沿 merged_into_id 解析出的最终概念（批量查询一次）。"""

    wanted = {concept_id for concept_id in concept_ids if isinstance(concept_id, int)}
    if not wanted:
        return {}
    by_id = {
        concept.id: concept
        for concept in (await session.execute(select(Concept))).scalars().all()
    }
    resolved: dict[int, Concept] = {}
    for concept_id in wanted:
        canonical = _canonical(by_id, concept_id)
        if canonical is not None:
            resolved[concept_id] = canonical
    return resolved


async def resolve_concepts(
    session: AsyncSession, concept_ids: Iterable[int]
) -> list[Concept]:
    """把历史版本里的 concept id 沿 merged_into_id 解析到最终概念并去重。"""

    resolved = await resolve_concept_map(session, concept_ids)
    return sorted(set(resolved.values()), key=lambda concept: concept.id)


async def concept_family_ids(session: AsyncSession, concept_id: int) -> set[int]:
    """返回最终概念 + 所有已归并到它的源概念 id（供检索展开）。"""

    by_id = {
        concept.id: concept
        for concept in (await session.execute(select(Concept))).scalars().all()
    }
    canonical = _canonical(by_id, concept_id)
    if canonical is None:
        return set()
    family = {canonical.id}
    for candidate in by_id.values():
        if candidate.id == canonical.id:
            continue
        if _canonical(by_id, candidate.id) is canonical:
            family.add(candidate.id)
    return family
