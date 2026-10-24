"""运行时装载器：seeds/data/*.json（分发真源）→ SQLite 装载副本 + 内存索引。

纪律（AGENTS §2.6 / TICKETS P1-1b）：
- JSON 文件是 seed 的唯一真源，SQLite knowledge_seed / prerequisite_edges 是装载副本
  （装载副本给 concepts/mistake_versions 提供 FK 锚点与 SQL 检索能力）。
- 幂等可重入：重复装载行数不变；知识点 upsert（有引用挂着的行不删），
  先修边全量同步（JSON 即真源）。
- 教材包 mappings/*.json 只校验 + 暴露进索引，不写数据库、不随仓库分发数据。
- 化学/语文空 seed 起步：缺文件 / 空数组容忍；契约见 seeds/README.md。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import KnowledgeSeed, PrerequisiteEdge

MAPPING_STATUSES = {"example", "draft", "reviewed"}


class SeedFormatError(ValueError):
    """seed 包或教材包 JSON 结构非法（导入即不可信输入，fail-fast）。"""


@dataclass
class SeedIndex:
    """内存索引：运行时按 id 取知识点、沿先修边回溯。"""

    topics: dict[str, dict[str, Any]] = field(default_factory=dict)
    parents: dict[str, list[str]] = field(default_factory=dict)  # child -> [prereq...]
    children: dict[str, list[str]] = field(default_factory=dict)  # parent -> [child...]
    mappings: list[dict[str, Any]] = field(default_factory=list)
    source: dict[str, Any] | None = None

    def prerequisites_of(self, topic_id: str) -> list[str]:
        return self.parents.get(topic_id, [])

    def children_of(self, topic_id: str) -> list[str]:
        return self.children.get(topic_id, [])


async def load_seed(session: AsyncSession, seeds_dir: Path | None = None) -> SeedIndex:
    """装载（幂等）。事务自包含；空 seed 起步返回空索引。"""

    root = Path(seeds_dir) if seeds_dir is not None else get_settings().seeds_dir
    data_dir = root / "data"

    topics_raw = _read_json(data_dir / "topics.json") or []
    deps_raw = _read_json(data_dir / "dependencies.json") or []
    source = _read_json(data_dir / "_source.json")
    if not isinstance(topics_raw, list) or not isinstance(deps_raw, list):
        raise SeedFormatError("topics.json / dependencies.json 必须是数组")

    topics = [_validate_topic(t) for t in topics_raw]
    topic_ids = {t["id"] for t in topics}
    edges = [_validate_edge(d) for d in deps_raw]
    edges = [e for e in edges if e["topic_id"] in topic_ids and e["prerequisite_id"] in topic_ids]
    mappings = load_mappings(root / "mappings")

    async with session.begin():
        await _upsert_topics(session, topics)
        await _sync_edges(session, edges)

    return _build_index(topics, edges, mappings, source)


def load_mappings(mappings_dir: Path) -> list[dict[str, Any]]:
    """教材包机制：校验 + 暴露；数据家长自建（status: example|draft|reviewed）。"""

    if not mappings_dir.is_dir():
        return []
    mappings = []
    for path in sorted(mappings_dir.glob("*.json")):
        raw = _read_json(path)
        if not isinstance(raw, dict):
            raise SeedFormatError(f"{path.name} 必须是对象")
        status = raw.get("status")
        if status not in MAPPING_STATUSES:
            raise SeedFormatError(
                f"{path.name} status 必须是 {sorted(MAPPING_STATUSES)}，实际 {status!r}"
            )
        entries = raw.get("entries", [])
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise SeedFormatError(f"{path.name} entries 必须是对象数组")
        mappings.append(
            {
                "edition": str(raw.get("edition", path.stem)),
                "label": str(raw.get("label", "")),
                "status": status,
                "path": path.name,
                "entry_count": len(entries),
            }
        )
    return mappings


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _validate_topic(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise SeedFormatError(f"知识点缺少字符串 id: {raw!r:.120}")
    if not isinstance(raw.get("subject"), str) or not isinstance(raw.get("name"), str):
        raise SeedFormatError(f"知识点 {raw['id']} 缺少 subject/name")

    def _json(value: Any) -> str | None:
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    return {
        "id": raw["id"],
        "subject": raw["subject"],
        "name": raw["name"],
        "domain": raw.get("domain"),
        "grade": str(raw["grade"]) if raw.get("grade") is not None else None,
        "semester": raw.get("semester"),
        "chapter": raw.get("chapter"),
        "type": raw.get("type"),
        "description": raw.get("description"),
        "mastery_criteria": _json(raw.get("mastery_criteria")),
        "diagnostic_question": _json(raw.get("diagnostic_question")),
        "standards": _json(raw.get("standards")),
        "source": raw.get("source"),
        "unaudited": bool(raw.get("unaudited", True)),
        "blind_verified": bool(raw.get("blind_verified", False)),
    }


def _validate_edge(raw: Any) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("topic_id"), str)
        or not isinstance(raw.get("prerequisite_id"), str)
    ):
        raise SeedFormatError(f"先修边缺少 topic_id/prerequisite_id: {raw!r:.120}")
    return {
        "topic_id": raw["topic_id"],
        "prerequisite_id": raw["prerequisite_id"],
        "edge_type": raw.get("strength") or raw.get("edge_type") or "soft",
        "source": raw.get("source") or "cn-math-taxonomy",
    }


async def _upsert_topics(session: AsyncSession, topics: list[dict[str, Any]]) -> None:
    existing = {
        row.id: row
        for row in (await session.execute(select(KnowledgeSeed))).scalars().all()
    }
    for topic in topics:
        row = existing.get(topic["id"])
        if row is None:
            session.add(KnowledgeSeed(**topic))
        else:
            for key, value in topic.items():
                setattr(row, key, value)


async def _sync_edges(session: AsyncSession, edges: list[dict[str, Any]]) -> None:
    # 先修边只被本表引用：JSON 即真源，全量同步（含删除消失的边）
    await session.execute(delete(PrerequisiteEdge))
    session.add_all(
        PrerequisiteEdge(
            parent_id=e["prerequisite_id"],
            child_id=e["topic_id"],
            edge_type=e["edge_type"],
            source=e["source"],
        )
        for e in edges
    )


def _build_index(
    topics: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    source: dict[str, Any] | None,
) -> SeedIndex:
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    for edge in edges:
        parents.setdefault(edge["topic_id"], []).append(edge["prerequisite_id"])
        children.setdefault(edge["prerequisite_id"], []).append(edge["topic_id"])
    return SeedIndex(
        topics={t["id"]: t for t in topics},
        parents=parents,
        children=children,
        mappings=mappings,
        source=source,
    )
