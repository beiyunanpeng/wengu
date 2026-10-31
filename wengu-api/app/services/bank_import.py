"""P3-1 空白真题录题通道：外部 agent 转录 → 确定性校验/归一 → bank_drafts。

红线（AGENTS §5 / 设计文档 §16）：外部 agent 只会"转录照片里已有的答案"，
绝不解题生成标准答案；照片没有答案就留空，由家长在审核页补填。
本模块只做确定性校验，不调模型、不判分、不自动入库。

两段闸门：
1. 导入时 `normalize_bank_items`：长度/类型/枚举/topic_id 存在性/选择题 key；
   坏项逐条进 errors，不静默截断。
2. 审核时 `check_approvable` + `classify_verify`：必填齐全（缺 answer 拒绝）、
   AST 白名单沙箱核验、纯数值矛盾拒绝；无 verify / 表达式不可核验记 unverifiable。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.judge.verify_sandbox import SandboxError, verify_answer
from app.seed.svg import sanitize_svg
from app.services.ingestion import (
    MAX_BATCH_BODY_BYTES,
    MAX_ITEMS_PER_BATCH,
    PLACEHOLDER_MARK,
    ItemError,
    clean_text,
)

BANK_CHANNEL = "agent_bank_transcribe_v1"
QUESTION_TYPES = frozenset({"choice", "numeric", "short", "self"})
MAX_CHOICES = 20
MAX_ACCEPTABLE = 50
MAX_CHOICE_TEXT = 500
MAX_ACCEPTABLE_TEXT = 200
MAX_FIGURE_CHARS = 20_000

BANK_FIELD_LIMITS: dict[str, int] = {
    "subject": 20,
    "topic_id": 64,
    "type": 16,
    "difficulty": 20,
    "prompt": 2000,
    "answer": 500,
    "verify": 2000,
    "source_ref": 200,
}

_BANK_KEYS = frozenset(
    {
        "subject",
        "topic_id",
        "type",
        "difficulty",
        "prompt",
        "answer",
        "acceptable",
        "unordered",
        "verify",
        "choices",
        "figure",
        "source_ref",
        "hide_choice_text",
        "percent",
    }
)


@dataclass
class BankNormalizationResult:
    drafts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[ItemError] = field(default_factory=list)
    dropped_unknown_fields: int = 0


class BankVerifyError(ValueError):
    """审核闸门拒绝入库；`reason` 是稳定错误码，不含题目正文。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def validate_bank_envelope(payload: Any) -> list[Any]:
    """校验录题封套，返回 items；非法即抛 ValueError（整批拒绝）。"""

    if not isinstance(payload, dict):
        raise ValueError("body 必须是 JSON 对象：{channel, items}")
    channel = payload.get("channel")
    if channel != BANK_CHANNEL:
        raise ValueError(f"录题通道 channel 必须是 {BANK_CHANNEL!r}，实际 {channel!r}")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    if not items:
        raise ValueError("items 为空，无可导入内容")
    if len(items) > MAX_ITEMS_PER_BATCH:
        raise ValueError(
            f"单批上限 {MAX_ITEMS_PER_BATCH} 题，当前 {len(items)} 题，请拆分"
        )
    return items


def normalize_bank_items(
    items: list[Any], topics: Mapping[str, str]
) -> BankNormalizationResult:
    """逐项校验 + 归一化；坏项进 errors（跳过），不抛异常。

    `topics` = {topic_id: subject}，来自 `knowledge_seed`；topic_id 不存在即拒绝。
    """

    result = BankNormalizationResult()
    for index, raw in enumerate(items):
        normalized, errors = normalize_bank_item(index, raw, topics)
        if errors:
            result.errors.extend(errors)
            continue
        assert normalized is not None
        if isinstance(raw, dict):
            result.dropped_unknown_fields += sum(
                1 for key in raw if key not in _BANK_KEYS
            )
        result.drafts.append(
            {
                "seq": index,
                "normalized": normalized,
                "has_placeholder": _has_placeholder(normalized),
            }
        )
    return result


def normalize_bank_item(
    index: int, raw: Any, topics: Mapping[str, str]
) -> tuple[dict[str, Any] | None, list[ItemError]]:
    """单题归一化；重复字段/结构错误全部收集后返回。"""

    errors: list[ItemError] = []

    def add(field_name: str, reason: str) -> None:
        errors.append(ItemError(index, field_name, reason))

    if not isinstance(raw, dict):
        add("item", "不是对象")
        return None, errors

    topic_id = _text(raw.get("topic_id"))
    if not topic_id:
        add("topic_id", "知识点必填（必须是 knowledge_seed 中的 id）")
    elif topic_id not in topics:
        add("topic_id", "unknown_topic: 知识点不存在于 knowledge_seed")

    subject_raw = _text(raw.get("subject"))
    if len(subject_raw) > BANK_FIELD_LIMITS["subject"]:
        add("subject", f"超长 {len(subject_raw)} > {BANK_FIELD_LIMITS['subject']}")
    subject = topics.get(topic_id, "") if topic_id in topics else ""
    if not subject:
        subject = subject_raw

    question_type = _text(raw.get("type"))
    if question_type not in QUESTION_TYPES:
        add("type", "必须是 choice / numeric / short / self")

    values: dict[str, str] = {}
    for name in ("prompt", "answer", "verify", "difficulty", "source_ref"):
        value = _text(raw.get(name))
        limit = BANK_FIELD_LIMITS[name]
        if len(value) > limit:
            add(name, f"超长 {len(value)} > {limit}，未导入")
        values[name] = value

    prompt = values["prompt"]
    if not prompt:
        add("prompt", "题目为空（必填）")

    acceptable, acceptable_errors = _normalize_acceptable(
        index, raw.get("acceptable")
    )
    errors.extend(acceptable_errors)
    if len(acceptable) > MAX_ACCEPTABLE:
        add("acceptable", f"最多 {MAX_ACCEPTABLE} 个可接受答案")

    unordered_raw = raw.get("unordered")
    if unordered_raw is None:
        unordered = False
    elif isinstance(unordered_raw, bool):
        unordered = unordered_raw
    else:
        add("unordered", "必须是布尔值")
        unordered = False

    choices, choice_errors = _normalize_choices(index, raw.get("choices"))
    errors.extend(choice_errors)
    keys = {choice["key"] for choice in choices}
    if question_type == "choice":
        if not choices:
            add("choices", "选择题必须有选项")
        if len(keys) != len(choices):
            add("choices", "选项 key 重复")
        if values["answer"] and values["answer"] not in keys:
            add("answer", "answer_not_in_choices: 答案必须是选项 key 之一")

    figure = raw.get("figure")
    if isinstance(figure, str) and len(figure) > MAX_FIGURE_CHARS:
        add("figure", f"图形超长 > {MAX_FIGURE_CHARS}")
        sanitized_figure = None
    else:
        sanitized_figure = sanitize_svg(figure)

    hide_choice_text = raw.get("hide_choice_text") is True
    percent = raw.get("percent") is True

    if errors:
        return None, errors

    normalized = {
        "subject": subject,
        "topic_id": topic_id,
        "type": question_type,
        "difficulty": values["difficulty"],
        "prompt": prompt,
        "answer": values["answer"],
        "acceptable": acceptable,
        "unordered": unordered,
        "verify": values["verify"],
        "choices": choices,
        "figure": sanitized_figure,
        "source_ref": values["source_ref"],
        "hide_choice_text": hide_choice_text,
        "percent": percent,
    }
    return normalized, errors


def check_approvable(normalized: Mapping[str, Any]) -> list[ItemError]:
    """审核必填闸门：题目/答案/知识点齐全且无占位；选择题 answer 必须命中选项。"""

    errors: list[ItemError] = []

    def add(field_name: str, reason: str) -> None:
        errors.append(ItemError(0, field_name, reason))

    prompt = _text(normalized.get("prompt"))
    if not prompt:
        add("prompt", "题目为空，不能入库")
    elif PLACEHOLDER_MARK in prompt:
        add("prompt", "placeholder: 题目含〔?〕，请补全后再入库")

    topic_id = _text(normalized.get("topic_id"))
    if not topic_id:
        add("topic_id", "知识点必填：请选择 knowledge_seed 中的 topic_id")

    answer = _text(normalized.get("answer"))
    if not answer:
        add("answer", "missing_answer: 缺标准答案，请按答案册/教师版补填")
    elif PLACEHOLDER_MARK in answer:
        add("answer", "placeholder: 答案含〔?〕，请补全后再入库")

    for alias in _string_list(normalized.get("acceptable")):
        if PLACEHOLDER_MARK in alias:
            add("acceptable", "placeholder: 可接受答案含〔?〕")
            break

    if normalized.get("type") == "choice":
        keys = {
            _text(choice.get("key"))
            for choice in _choices(normalized.get("choices"))
            if isinstance(choice, dict)
        }
        if not keys:
            add("choices", "选择题必须有选项")
        elif answer and answer not in keys:
            add("answer", "answer_not_in_choices: 答案必须是选项 key 之一")

    return errors


def classify_verify(normalized: Mapping[str, Any]) -> tuple[str, str | None]:
    """审核时跑 AST 白名单沙箱：verified / unverifiable；纯数值矛盾抛错拒绝。

    - 无 verify 或含占位符 → unverifiable（不阻塞入库，但 UI 标"未经核验"）。
    - 表达式非法（import/赋值/属性访问等）→ BankVerifyError（拒绝入库）。
    - 求值结果与答案矛盾：选择题记 unverifiable（选项可能带文字/单位），
      数值/短答/解答题拒绝入库（防"表达式与答案不符"的错题入库）。
    """

    verify = _text(normalized.get("verify"))
    answer = _text(normalized.get("answer"))
    if not verify or PLACEHOLDER_MARK in verify:
        return "unverifiable", "no_verify"

    expected: str | None = answer
    if normalized.get("type") == "choice":
        expected = None
        for choice in _choices(normalized.get("choices")):
            if isinstance(choice, dict) and _text(choice.get("key")) == answer:
                expected = _text(choice.get("text"))
                break
        if expected is None:
            return "unverifiable", "choice_text_missing"

    try:
        outcome = verify_answer(
            verify,
            expected=expected,
            acceptable=tuple(_string_list(normalized.get("acceptable"))),
            unordered=normalized.get("unordered") is True,
        )
    except SandboxError as exc:
        raise BankVerifyError(f"verify_error:{exc.reason}") from None

    if outcome.verdict == "verified":
        return "verified", None
    if outcome.verdict == "uncertain":
        return "unverifiable", outcome.reason
    if normalized.get("type") == "choice":
        return "unverifiable", "choice_text_mismatch"
    raise BankVerifyError("verify_mismatch")


def dumps_bank_draft(normalized: dict[str, Any]) -> str:
    """草稿 JSON 稳定序列化（内部统计键不落库）。"""

    payload = {key: value for key, value in normalized.items() if not key.startswith("__")}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _has_placeholder(normalized: Mapping[str, Any]) -> bool:
    texts = [
        _text(normalized.get("prompt")),
        _text(normalized.get("answer")),
        _text(normalized.get("verify")),
        _text(normalized.get("source_ref")),
        *_string_list(normalized.get("acceptable")),
    ]
    for choice in _choices(normalized.get("choices")):
        if isinstance(choice, dict):
            texts.append(_text(choice.get("text")))
    return any(PLACEHOLDER_MARK in text for text in texts)


def _normalize_acceptable(
    index: int, raw: Any
) -> tuple[list[str], list[ItemError]]:
    errors: list[ItemError] = []
    if raw is None:
        return [], errors
    if not isinstance(raw, list):
        return [], [ItemError(index, "acceptable", "必须是字符串数组")]
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            errors.append(ItemError(index, "acceptable", "必须是字符串数组"))
            continue
        value = clean_text(item)
        if len(value) > MAX_ACCEPTABLE_TEXT:
            errors.append(
                ItemError(
                    index,
                    "acceptable",
                    f"超长 {len(value)} > {MAX_ACCEPTABLE_TEXT}",
                )
            )
            continue
        if value:
            values.append(value)
    return values, errors


def _normalize_choices(
    index: int, raw: Any
) -> tuple[list[dict[str, Any]], list[ItemError]]:
    errors: list[ItemError] = []
    if raw is None:
        return [], errors
    if not isinstance(raw, list):
        return [], [ItemError(index, "choices", "必须是数组")]
    if len(raw) > MAX_CHOICES:
        return [], [ItemError(index, "choices", f"最多 {MAX_CHOICES} 个选项")]
    choices: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            errors.append(ItemError(index, "choices", "选项必须是对象"))
            continue
        key = _text(item.get("key"))
        text = clean_text(item["text"]) if isinstance(item.get("text"), str) else ""
        if not key:
            errors.append(ItemError(index, "choices", "选项 key 为空"))
            continue
        if len(key) > 8:
            errors.append(ItemError(index, "choices", "选项 key 超长 > 8"))
            continue
        if not text:
            errors.append(ItemError(index, "choices", "选项 text 为空"))
            continue
        if len(text) > MAX_CHOICE_TEXT:
            errors.append(
                ItemError(index, "choices", f"选项 text 超长 > {MAX_CHOICE_TEXT}")
            )
            continue
        figure = item.get("figure")
        if isinstance(figure, str) and len(figure) > MAX_FIGURE_CHARS:
            errors.append(ItemError(index, "choices", "选项图形超长"))
            continue
        choices.append(
            {"key": key, "text": text, "figure": sanitize_svg(figure)}
        )
    return choices, errors


def _text(value: Any) -> str:
    return clean_text(value) if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _choices(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# 与 ingestion 共用同一批上限，避免两套导入常量漂移
__all__ = [
    "BANK_CHANNEL",
    "BANK_FIELD_LIMITS",
    "BankNormalizationResult",
    "BankVerifyError",
    "MAX_BATCH_BODY_BYTES",
    "MAX_ITEMS_PER_BATCH",
    "check_approvable",
    "classify_verify",
    "dumps_bank_draft",
    "normalize_bank_item",
    "normalize_bank_items",
    "validate_bank_envelope",
]
