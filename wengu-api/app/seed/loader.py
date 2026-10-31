"""运行时装载器：seeds/data/*.json（分发真源）→ SQLite 装载副本 + 内存索引。

纪律（AGENTS §2.6 / TICKETS P1-1b / P3-5 前置）：
- JSON 文件是 seed 的唯一真源，SQLite knowledge_seed / prerequisite_edges 是装载副本
  （装载副本给 concepts/mistake_versions 提供 FK 锚点与 SQL 检索能力）。
- 幂等可重入：重复装载行数不变；知识点 upsert（有引用挂着的行不删），
  先修边全量同步（JSON 即真源）。
- **多源合并顺序**：`<seeds_dir>/data/topics.json`（仓库 seed，只读）→
  `<seeds_dir>/local/*.json`（开发机分发场景，可选）→
  `<data_dir>/seeds_local/*.json`（家长运行时自建，文件真源）。
  本地条目 id 与上游/先前本地条目冲突即拒绝并记 error 日志；单文件解析失败只跳过该文件。
- 本地条目强制 `source='local'`、`unaudited=true`、`blind_verified=false`。
- 教材包 mappings/*.json 只校验 + 暴露进索引，不写数据库、不随仓库分发数据。
- 化学/语文空 seed 起步：缺文件 / 空数组容忍；契约见 seeds/README.md。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import KnowledgeSeed, PrerequisiteEdge

logger = logging.getLogger(__name__)

MAPPING_STATUSES = {"example", "draft", "reviewed"}
LOCAL_SOURCE = "local"
LOCAL_SUBJECT_PREFIXES = {"语文": "cnl_", "化学": "cnc_"}



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


async def load_seed(
    session: AsyncSession,
    seeds_dir: Path | None = None,
    data_dir: Path | None = None,
) -> SeedIndex:
    """装载（幂等）。事务自包含；空 seed 起步返回空索引。"""

    settings = get_settings()
    root = Path(seeds_dir) if seeds_dir is not None else settings.seeds_dir
    runtime_dir = Path(data_dir) if data_dir is not None else settings.data_dir

    topics_raw = _read_json(root / "data" / "topics.json") or []
    deps_raw = _read_json(root / "data" / "dependencies.json") or []
    source = _read_json(root / "data" / "_source.json")
    if not isinstance(topics_raw, list) or not isinstance(deps_raw, list):
        raise SeedFormatError("topics.json / dependencies.json 必须是数组")

    topics = [_validate_topic(t) for t in topics_raw]
    topic_ids = {t["id"] for t in topics}
    local_topics = read_local_topics(local_seed_files(root, runtime_dir), topic_ids)
    topics.extend(local_topics)
    topic_ids.update(t["id"] for t in local_topics)
    edges = [_validate_edge(d) for d in deps_raw]
    edges = [e for e in edges if e["topic_id"] in topic_ids and e["prerequisite_id"] in topic_ids]
    mappings = load_mappings(root / "mappings")

    async with session.begin():
        await _upsert_topics(session, topics)
        await _sync_edges(session, edges)

    return _build_index(topics, edges, mappings, source)


def local_seed_files(seeds_dir: Path, data_dir: Path) -> list[Path]:
    """本地 seed 文件优先级：开发机 `seeds/local` → 运行时 `<data_dir>/seeds_local`。"""

    files: list[Path] = []
    for directory in (Path(seeds_dir) / "local", Path(data_dir) / "seeds_local"):
        if directory.is_dir():
            files.extend(sorted(directory.glob("*.json")))
    return files


def read_local_topics(
    paths: list[Path], taken_ids: set[str]
) -> list[dict[str, Any]]:
    """读取本地 seed 文件并合并；坏文件/坏条目跳过，id 冲突拒绝且记 error 日志。"""

    merged: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("跳过本地 seed 文件 %s：%s", path, exc)
            continue
        if not isinstance(raw, list):
            logger.warning("跳过本地 seed 文件 %s：根节点必须是数组", path)
            continue
        for item in raw:
            try:
                topic = validate_local_topic(item)
            except SeedFormatError as exc:
                logger.warning("跳过本地 seed 条目（%s）：%s", path.name, exc)
                continue
            if topic["id"] in taken_ids or topic["id"] in merged:
                logger.error(
                    "本地 seed id 与既有知识点冲突，已拒绝：%s（%s）", topic["id"], path.name
                )
                continue
            merged[topic["id"]] = topic
    return list(merged.values())


def validate_local_topic(raw: Any) -> dict[str, Any]:
    """本地条目校验：契约子集 + 学科前缀 + 强制 local 标签。"""

    topic = _validate_topic(raw)
    prefix = LOCAL_SUBJECT_PREFIXES.get(topic["subject"])
    if prefix is None:
        raise SeedFormatError(
            f"本地知识点学科仅支持 {sorted(LOCAL_SUBJECT_PREFIXES)}，实际 {topic['subject']!r}"
        )
    if not topic["id"].startswith(prefix):
        raise SeedFormatError(
            f"本地知识点 id 必须以 {prefix} 开头（学科 {topic['subject']}），实际 {topic['id']!r}"
        )
    topic["source"] = LOCAL_SOURCE
    topic["unaudited"] = True
    topic["blind_verified"] = False
    return topic


def write_local_topics(path: Path, entries: list[dict[str, Any]]) -> None:
    """原子写（同目录 tmp + os.replace），避免半写文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".topics-", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


_ID_SEQUENCE = re.compile(r"^(.+?)(\d+)$")


def next_local_id(prefix: str, taken_ids: set[str]) -> str:
    """按学科前缀 + 递增序号生成 id（cnl_001…），跳过已占用序号。"""

    highest = 0
    for topic_id in taken_ids:
        match = _ID_SEQUENCE.match(topic_id)
        if match and match.group(1) == prefix:
            highest = max(highest, int(match.group(2)))
    return f"{prefix}{highest + 1:03d}"



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
