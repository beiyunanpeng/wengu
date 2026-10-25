"""兜底通道（豆包 JSON 导入）的确定性校验与归一化——导入全程不调模型。

宽松解析层（AGENTS §5）：先救导出 JSON 的常见抖动（控制字符、空白），
再按字段规则严格校验；坏项跳过并逐条报告，不静默截断超长内容。
归一化产物写 ingestion_drafts，与主通道将来 P1-4 提取产出的草稿共用同一张表。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_ITEMS_PER_BATCH = 500
MAX_BATCH_BODY_BYTES = 5 * 1024 * 1024

# 归一化草稿的字段契约（版本化模板见 docs；改语义须同步模板与前端确认流）
FIELD_LIMITS: dict[str, int] = {
    "subject": 20,
    "problem_text": 2000,
    "student_answer": 500,
    "source_ref": 200,
    "captured_at": 30,
}
STRING_FIELDS = tuple(FIELD_LIMITS)
PLACEHOLDER_MARK = "〔?〕"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass
class ItemError:
    index: int
    field: str
    reason: str


@dataclass
class NormalizationResult:
    drafts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ItemError] = field(default_factory=list)
    dropped_unknown_fields: int = 0


def clean_text(value: str) -> str:
    """去控制字符（保留 \\n \\t）、首尾空白归一。"""

    return _CONTROL_CHARS.sub("", value).strip()


def validate_envelope(payload: Any) -> tuple[str, list[Any]]:
    """校验导入封套，返回 (channel, items)。非法即抛 ValueError（整批拒绝）。"""

    if not isinstance(payload, dict):
        raise ValueError("body 必须是 JSON 对象：{channel, items}")
    channel = payload.get("channel")
    if channel != "doubao_json":
        raise ValueError(f"不支持的 channel: {channel!r}（仅支持 doubao_json）")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    if not items:
        raise ValueError("items 为空，无可导入内容")
    if len(items) > MAX_ITEMS_PER_BATCH:
        raise ValueError(f"单批上限 {MAX_ITEMS_PER_BATCH} 题，当前 {len(items)} 题，请拆分")
    return channel, items


def validate_and_normalize(items: list[Any]) -> NormalizationResult:
    """逐项确定性校验 + 归一化；坏项进 errors（跳过），不抛异常。"""

    result = NormalizationResult()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            result.errors.append(ItemError(index, "item", "不是对象"))
            continue
        normalized: dict[str, Any] = {}
        has_error = False
        for name, limit in FIELD_LIMITS.items():
            value = item.get(name)
            if value is None:
                normalized[name] = ""
                continue
            if not isinstance(value, str):
                result.errors.append(ItemError(index, name, "必须是字符串"))
                has_error = True
                break
            value = clean_text(value)
            if len(value) > limit:
                result.errors.append(
                    ItemError(index, name, f"超长 {len(value)} > {limit}，未导入")
                )
                has_error = True
                break
            normalized[name] = value
        if has_error:
            continue
        if not normalized["problem_text"]:
            result.errors.append(ItemError(index, "problem_text", "题目为空（必填）"))
            continue
        result.dropped_unknown_fields += sum(
            1 for key in item if key not in FIELD_LIMITS
        )
        result.drafts.append(
            {
                "seq": index,
                "normalized": normalized,
                "has_placeholder": PLACEHOLDER_MARK
                in (normalized["problem_text"] + normalized["student_answer"]),
                "is_incomplete": not normalized["student_answer"],
            }
        )
    return result


def dumps_draft(normalized: dict[str, Any]) -> str:
    """草稿 JSON 稳定序列化（键序固定，重放可比对）。"""

    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)
