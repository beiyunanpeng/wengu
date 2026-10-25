"""确定性重算：掌握度 / 毕业 / 统计一律由 learning_events 事实推导（AGENTS §5）。

纯函数骨架：输入事件序列，输出结果；同输入必同输出，可整体重放。
掌握度具体公式 P1-7 定死（固定阶梯 × 自适应因子），此处是确定性占位实现，
但"由事实推导、不存易变字段"的架构约束从 P1-1 就生效。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

GRADUATION_STREAK = 3  # 抗挫败规则：尾部连续对 ≥3 才毕业（设计文档 §5.4）

ATTEMPT_CORRECT = "attempt_correct"
ATTEMPT_WRONG = "attempt_wrong"


@dataclass(frozen=True)
class Event:
    """重算函数的输入视图（字段对齐 learning_events 表）。"""

    type: str
    actor: str
    mistake_id: int | None = None
    payload: Mapping[str, Any] | None = None
    occurred_at: Any = None  # 排序键；同序列内只需稳定可比


def _payload(event: Event | Mapping[str, Any]) -> Mapping[str, Any]:
    raw = event.payload if isinstance(event, Event) else event.get("payload")
    if raw is None:
        return {}
    if isinstance(raw, str):
        return json.loads(raw) if raw else {}
    return raw  # type: ignore[return-value]


def _events_for_mistake(events: Sequence[Event | Mapping[str, Any]], mistake_id: int) -> list[Any]:
    """同一 mistake 的作答事件，按 occurred_at 稳定排序（重放确定性）。"""

    selected = [e for e in _dedupe_grading_versions(events) if (e.mistake_id if isinstance(e, Event) else e.get("mistake_id")) == mistake_id]
    return sorted(
        selected,
        key=lambda e: (e.occurred_at if isinstance(e, Event) else e.get("occurred_at"), repr(e)),
    )


def _dedupe_grading_versions(
    events: Sequence[Event | Mapping[str, Any]],
) -> list[Event | Mapping[str, Any]]:
    """同一 grading 只保留最高版本：申诉/改判不重复计掌握度与统计。"""

    best: dict[int, tuple[int, int]] = {}
    enriched: list[tuple[int, bool]] = []
    for index, event in enumerate(events):
        payload = _payload(event)
        grading_id = payload.get("grading_id")
        grading_version = payload.get("grading_version")
        valid = (
            isinstance(grading_id, int)
            and not isinstance(grading_id, bool)
            and isinstance(grading_version, int)
            and not isinstance(grading_version, bool)
        )
        if valid:
            candidate = (grading_version, index)
            if grading_id not in best or candidate > best[grading_id]:
                best[grading_id] = candidate
        enriched.append((index, valid))
    keep = {candidate[1] for candidate in best.values()}
    return [
        event
        for index, event in enumerate(events)
        if not enriched[index][1] or index in keep
    ]


def mastery(events: Sequence[Event | Mapping[str, Any]], concept_id: str) -> float:
    """知识点掌握度占位实现：该知识点下历史作答的对错比例，无信号 = 0.0。

    P1-7 将替换为"固定阶梯 × (1+mastery×4) 自适应因子"的正式公式；
    调用方只依赖"输入事件 → 输出数值"的契约，不依赖内部实现。
    """

    correct = wrong = 0
    for event in _dedupe_grading_versions(events):
        event_type = event.type if isinstance(event, Event) else event.get("type")
        if event_type not in (ATTEMPT_CORRECT, ATTEMPT_WRONG):
            continue
        payload = _payload(event)
        if payload.get("concept_id") != concept_id:
            continue
        if event_type == ATTEMPT_CORRECT:
            correct += 1
        else:
            wrong += 1
    total = correct + wrong
    if total == 0:
        return 0.0
    return correct / total


def is_graduated(events: Sequence[Event | Mapping[str, Any]], mistake_id: int) -> bool:
    """毕业 = 尾部连续对 ≥ GRADUATION_STREAK（推导值，绝不落库）。"""

    streak = 0
    for event in _events_for_mistake(events, mistake_id):
        event_type = event.type if isinstance(event, Event) else event.get("type")
        if event_type == ATTEMPT_CORRECT:
            streak += 1
        elif event_type == ATTEMPT_WRONG:
            streak = 0  # 答错不倒退阶梯，只断毕业 streak
    return streak >= GRADUATION_STREAK


def stats(events: Sequence[Event | Mapping[str, Any]]) -> dict[str, Any]:
    """看板统计骨架：按事件类型与对错计数，全部从事实推导。"""

    by_type: dict[str, int] = {}
    attempts_correct = attempts_wrong = 0
    deduped = _dedupe_grading_versions(events)
    for event in deduped:
        event_type = event.type if isinstance(event, Event) else event.get("type")
        by_type[event_type] = by_type.get(event_type, 0) + 1
        if event_type == ATTEMPT_CORRECT:
            attempts_correct += 1
        elif event_type == ATTEMPT_WRONG:
            attempts_wrong += 1
    return {
        "total_events": len(deduped),
        "by_type": by_type,
        "attempts_correct": attempts_correct,
        "attempts_wrong": attempts_wrong,
        "attempt_accuracy": (
            attempts_correct / (attempts_correct + attempts_wrong)
            if (attempts_correct + attempts_wrong)
            else None
        ),
    }
