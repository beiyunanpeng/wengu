"""家长自建章级 seed：文件真源（`<data_dir>/seeds_local/topics_<学科>.json`）+ SQLite 副本。

纪律（TICKETS P3-5 前置 / AGENTS §3）：
- 只有语文（`cnl_`）/ 化学（`cnc_`）允许本地录点；上游学科一律拒绝，防搅乱既有 id 空间。
- 文件是唯一真源：先原子写文件，再 upsert `knowledge_seed`；重启后由装载器按文件恢复。
- 本地行固定 `source='local'`、`unaudited=true`、`blind_verified=false`。
- 删除只允许 local 行：从文件移除 + 删行，引用侧（`mistakes.primary_topic_id` /
  `problem_bank.topic_id`）显式置 NULL 并返回受影响计数；历史事实本身不动。
- **id 永不复用**：`<data_dir>/seeds_local/_id_counters.json` 记录每学科已发放过的最大序号，
  只增不减；删除点不回退。下划线开头的文件不是 seed，装载器会跳过。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Concept, KnowledgeSeed, Mistake, PrerequisiteEdge, ProblemBankItem
from app.seed.loader import (
    LOCAL_SOURCE,
    LOCAL_SUBJECT_PREFIXES,
    SeedFormatError,
    next_local_id,
    validate_local_topic,
    write_local_topics,
)

MAX_TOPICS_PER_SUBJECT = 200
MAX_NAME = 40
MAX_GRADE = 9
MIN_GRADE = 7
MAX_CRITERIA_ITEMS = 20
MAX_CRITERIA_LENGTH = 200
COUNTER_FILENAME = "_id_counters.json"

_FILE_LOCK = asyncio.Lock()
logger = logging.getLogger(__name__)


class LocalSeedError(ValueError):
    """本地知识点输入非法（API 映射 422）。"""


class LocalSeedNotFound(LocalSeedError):
    """目标不存在或不是 local 行（API 映射 404）。"""


class LocalSeedConflict(LocalSeedError):
    """删除目标仍被 concepts 等不可解绑数据引用（API 映射 409）。"""


def local_topics_path(settings: Settings, subject: str) -> Path:
    return Path(settings.data_dir) / "seeds_local" / f"topics_{subject}.json"


def id_counters_path(settings: Settings) -> Path:
    return Path(settings.data_dir) / "seeds_local" / COUNTER_FILENAME


def read_id_counters(settings: Settings) -> dict[str, int]:
    """读取"已发放过的最大序号"；文件缺失视为空，内容非法则 fail-closed。"""

    path = id_counters_path(settings)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LocalSeedError(f"id 计数器不可读：{path.name}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise LocalSeedError(f"id 计数器格式错误：{path.name} 应为对象")
    counters: dict[str, int] = {}
    for subject, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LocalSeedError(
                f"id 计数器格式错误：{path.name} 中 {subject!r} 必须是非负整数"
            )
        counters[str(subject)] = value
    return counters


def write_id_counters(settings: Settings, counters: dict[str, int]) -> None:
    """原子写计数器（同目录 tmp + fsync + os.replace）。"""

    path = id_counters_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(dict(sorted(counters.items())), ensure_ascii=False, indent=2) + "\n"
    )
    fd, tmp_name = tempfile.mkstemp(prefix="._counters-", suffix=".tmp", dir=path.parent)
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


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LocalSeedError(f"本地 seed 文件不可读：{path.name}（{exc}）") from exc
    if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
        raise LocalSeedError(f"本地 seed 文件格式错误：{path.name} 应为对象数组")
    return [dict(item) for item in raw]


def _clean_text(value: Any, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LocalSeedError(f"{field} 必须是字符串")
    text = value.strip()
    if len(text) > limit:
        raise LocalSeedError(f"{field} 最长 {limit} 个字符")
    return text or None


def _clean_name(value: Any) -> str:
    name = _clean_text(value, "name", MAX_NAME)
    if not name:
        raise LocalSeedError("name 不能为空")
    return name


def _clean_grade(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise LocalSeedError("grade 必须是 7–9 的整数")
    try:
        grade = int(value)
    except (TypeError, ValueError) as exc:
        raise LocalSeedError("grade 必须是 7–9 的整数") from exc
    if not MIN_GRADE <= grade <= MAX_GRADE:
        raise LocalSeedError(f"grade 只能是 {MIN_GRADE}–{MAX_GRADE}")
    return grade


def _clean_criteria(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise LocalSeedError("mastery_criteria 必须是字符串数组")
    if len(value) > MAX_CRITERIA_ITEMS:
        raise LocalSeedError(f"mastery_criteria 最多 {MAX_CRITERIA_ITEMS} 条")
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item, "mastery_criteria", MAX_CRITERIA_LENGTH)
        if text:
            cleaned.append(text)
    return cleaned or None


def _require_subject(subject: str) -> str:
    if subject not in LOCAL_SUBJECT_PREFIXES:
        raise LocalSeedError(
            f"暂只支持本地自建 {'/'.join(LOCAL_SUBJECT_PREFIXES)} 知识点；"
            "数学/英语/物理请使用仓库 seed"
        )
    return subject


def normalize_fields(data: dict[str, Any], *, subject: str | None = None) -> dict[str, Any]:
    """校验/归一可编辑字段；subject 仅创建时传入。"""

    fields = {
        "name": _clean_name(data.get("name")),
        "grade": _clean_grade(data.get("grade")),
        "semester": _clean_text(data.get("semester"), "semester", 20),
        "chapter": _clean_text(data.get("chapter"), "chapter", 100),
        "domain": _clean_text(data.get("domain"), "domain", 40),
        "description": _clean_text(data.get("description"), "description", 500),
        "mastery_criteria": _clean_criteria(data.get("mastery_criteria")),
        "type": _clean_text(data.get("type"), "type", 20),
    }
    if subject is not None:
        fields["subject"] = _require_subject(subject)
    return fields


def _file_entry(topic_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": topic_id}
    entry.update(fields)
    return entry


def _db_values(entry: dict[str, Any]) -> dict[str, Any]:
    try:
        return validate_local_topic(entry)
    except SeedFormatError as exc:  # 契约错误 → 422
        raise LocalSeedError(str(exc)) from exc


def _entry_from_row(row: KnowledgeSeed) -> dict[str, Any]:
    criteria: Any = None
    if row.mastery_criteria is not None:
        try:
            criteria = json.loads(row.mastery_criteria)
        except ValueError:
            criteria = row.mastery_criteria
    grade: Any = row.grade
    if isinstance(grade, str) and grade.isdigit():
        grade = int(grade)
    return {
        "id": row.id,
        "name": row.name,
        "subject": row.subject,
        "domain": row.domain,
        "grade": grade,
        "semester": row.semester,
        "chapter": row.chapter,
        "type": row.type,
        "description": row.description,
        "mastery_criteria": criteria,
    }


async def _known_ids(session: AsyncSession, prefix: str) -> set[str]:
    ids = (
        await session.execute(
            select(KnowledgeSeed.id).where(KnowledgeSeed.id.like(f"{prefix}%"))
        )
    ).scalars()
    return set(ids)


async def list_local_topics(
    session: AsyncSession, subject: str | None = None
) -> list[KnowledgeSeed]:
    query = select(KnowledgeSeed).where(KnowledgeSeed.source == LOCAL_SOURCE)
    if subject is not None:
        query = query.where(KnowledgeSeed.subject == _require_subject(subject))
    rows = await session.execute(query.order_by(KnowledgeSeed.subject, KnowledgeSeed.id))
    return list(rows.scalars().all())


async def usage_counts(session: AsyncSession, topic_ids: list[str]) -> dict[str, dict[str, int]]:
    """错题/题目引用计数（含作废行；只作展示与删除前确认）。"""

    result = {topic_id: {"mistakes": 0, "problems": 0} for topic_id in topic_ids}
    if not topic_ids:
        return result
    mistake_rows = await session.execute(
        select(Mistake.primary_topic_id, func.count())
        .where(Mistake.primary_topic_id.in_(topic_ids))
        .group_by(Mistake.primary_topic_id)
    )
    for topic_id, count in mistake_rows:
        result[topic_id]["mistakes"] = count
    problem_rows = await session.execute(
        select(ProblemBankItem.topic_id, func.count())
        .where(ProblemBankItem.topic_id.in_(topic_ids))
        .group_by(ProblemBankItem.topic_id)
    )
    for topic_id, count in problem_rows:
        result[topic_id]["problems"] = count
    return result


async def create_local_topic(
    session: AsyncSession, settings: Settings, *, subject: str, data: dict[str, Any]
) -> KnowledgeSeed:
    subject = _require_subject(subject)
    fields = normalize_fields(data, subject=subject)

    count = (
        await session.execute(
            select(func.count())
            .select_from(KnowledgeSeed)
            .where(KnowledgeSeed.source == LOCAL_SOURCE, KnowledgeSeed.subject == subject)
        )
    ).scalar_one()
    if count >= MAX_TOPICS_PER_SUBJECT:
        raise LocalSeedError(
            f"{subject} 本地知识点已达上限 {MAX_TOPICS_PER_SUBJECT}；"
            "章级 40–80 点即可，细粒度请用错题受控生长"
        )

    prefix = LOCAL_SUBJECT_PREFIXES[subject]
    path = local_topics_path(settings, subject)
    async with _FILE_LOCK:
        entries = _read_entries(path)
        taken = {str(entry.get("id")) for entry in entries} | await _known_ids(
            session, prefix
        )
        counters = read_id_counters(settings)
        issued = counters.get(subject, 0)
        topic_id = next_local_id(prefix, taken, issued)
        entry = _file_entry(topic_id, fields)
        values = _db_values(entry)
        # 先预留序号再落盘：即使后续写入失败也只产生空洞，绝不回退复用。
        sequence = int(topic_id[len(prefix) :])
        if sequence > issued:
            counters[subject] = sequence
            write_id_counters(settings, counters)
        write_local_topics(path, [*entries, entry])
        row = KnowledgeSeed(**values)
        session.add(row)
        await session.commit()
    return row


async def update_local_topic(
    session: AsyncSession,
    settings: Settings,
    topic_id: str,
    changes: dict[str, Any],
) -> KnowledgeSeed:
    row = await session.get(KnowledgeSeed, topic_id)
    if row is None or row.source != LOCAL_SOURCE:
        raise LocalSeedNotFound(f"本地知识点不存在或不可修改：{topic_id}")

    patch = {key: value for key, value in changes.items() if key != "subject"}
    if not patch:
        raise LocalSeedError("没有可更新的字段")
    merged = _entry_from_row(row)
    merged.update(normalize_fields({**merged, **patch}))
    merged["id"] = row.id
    values = _db_values(merged)

    path = local_topics_path(settings, row.subject)
    async with _FILE_LOCK:
        entries = _read_entries(path)
        replaced = False
        for index, entry in enumerate(entries):
            if entry.get("id") == topic_id:
                entries[index] = merged
                replaced = True
                break
        if not replaced:
            entries.append(merged)
        write_local_topics(path, entries)
        for key, value in values.items():
            setattr(row, key, value)
        await session.commit()
    return row


async def delete_local_topic(
    session: AsyncSession, settings: Settings, topic_id: str
) -> dict[str, int]:
    row = await session.get(KnowledgeSeed, topic_id)
    if row is None or row.source != LOCAL_SOURCE:
        raise LocalSeedNotFound(f"本地知识点不存在或不可删除：{topic_id}")

    concept_count = (
        await session.execute(
            select(func.count()).select_from(Concept).where(Concept.category_id == topic_id)
        )
    ).scalar_one()
    if concept_count:
        raise LocalSeedConflict(
            f"该知识点仍被 {concept_count} 个细粒度 concept 引用，请先归并或移除后再删除"
        )

    counts = await usage_counts(session, [topic_id])
    path = local_topics_path(settings, row.subject)
    async with _FILE_LOCK:
        entries = _read_entries(path)
        kept = [entry for entry in entries if entry.get("id") != topic_id]
        if len(kept) != len(entries):
            write_local_topics(path, kept)
        await session.execute(
            update(Mistake)
            .where(Mistake.primary_topic_id == topic_id)
            .values(primary_topic_id=None)
        )
        await session.execute(
            update(ProblemBankItem)
            .where(ProblemBankItem.topic_id == topic_id)
            .values(topic_id=None)
        )
        await session.execute(
            delete(PrerequisiteEdge).where(
                (PrerequisiteEdge.parent_id == topic_id)
                | (PrerequisiteEdge.child_id == topic_id)
            )
        )
        await session.delete(row)
        await session.commit()

    usage = counts[topic_id]
    return {"mistakes_unbound": usage["mistakes"], "problems_unbound": usage["problems"]}
