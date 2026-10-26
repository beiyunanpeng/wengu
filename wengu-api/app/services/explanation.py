"""P1-8 三段式讲解：模式/策略选择、质量闸门与答案泄漏防护（纯函数部分）。

引导 = 定位 focus + 当前层级提示 steps + 巩固动作 consolidation；
完整讲解 = 定位 + 至少两步讲解 + 巩固 + 最终答案。
本模块不调用模型、不写库；上下文读取与事件写入在下方逐步接入。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Concept,
    IngestionDraft,
    KnowledgeSeed,
    LearningEvent,
    Mistake,
    ProblemExtraction,
)
from app.models.mistakes import MISTAKE_ACTIVE
from app.providers.base import CallMeta, Explanation
from app.services.events import record_event
from app.services.extraction import (
    GATE_FIGURE,
    GATE_MANUAL,
    GATE_READY,
    MAX_ANSWER_CHARS,
    MAX_PROBLEM_TEXT_CHARS,
    REASON_COMPLETENESS_UNKNOWN,
    REASON_PROBLEM_EMPTY,
    REASON_PROBLEM_INCOMPLETE,
    REASON_WHOLE_PAGE,
    detect_figure_keywords,
)
from app.services.ingestion import PLACEHOLDER_MARK
from app.services.mistakes import (
    effective_labels,
    error_cause_label,
    get_latest_version,
)
from app.services.review_policy import MEMORY_SUBJECTS

MODE_AUTO = "auto"
MODE_GUIDE = "guide"
MODE_FULL = "full"
MODES = frozenset({MODE_AUTO, MODE_GUIDE, MODE_FULL})
FINAL_MODES = frozenset({MODE_GUIDE, MODE_FULL})

ENTRY_MISTAKE = "mistake"
ENTRY_QUESTION = "question"

CONTEXT_MISTAKE = "mistake"
CONTEXT_EXTRACTION = "problem_extraction"
CONTEXT_DRAFT = "ingestion_draft"
CONTEXT_KINDS = frozenset({CONTEXT_MISTAKE, CONTEXT_EXTRACTION, CONTEXT_DRAFT})
QUESTION_CONTEXT_KINDS = frozenset({CONTEXT_EXTRACTION, CONTEXT_DRAFT})

STRATEGY_BY_ERROR_CAUSE: dict[str, str] = {
    "prerequisite_gap": "prerequisite_bridge",
    "concept_unclear": "concept_explain",
    "method_missing": "method_hint",
    "calculation": "calculation_check",
    "careless": "habit_check",
    "expression": "expression_model",
    "other": "general_guide",
}

MODE_BY_ERROR_CAUSE: dict[str, str] = {
    "prerequisite_gap": MODE_FULL,
    "concept_unclear": MODE_FULL,
    "method_missing": MODE_GUIDE,
    "calculation": MODE_GUIDE,
    "careless": MODE_GUIDE,
    "expression": MODE_GUIDE,
    "other": MODE_GUIDE,
}

STRATEGY_LABELS: dict[str, str] = {
    "prerequisite_bridge": "补前置",
    "concept_explain": "讲概念",
    "method_hint": "给方法",
    "calculation_check": "查计算",
    "habit_check": "查习惯",
    "expression_model": "规范表达",
    "general_guide": "通用引导",
    "general_solve": "解题讲解",
    "recall": "给语境 + 复述",
}

MAX_FOCUS_CHARS = 200
MAX_STEP_CHARS = 600
MAX_STEPS = 8
MAX_TOTAL_STEPS_CHARS = 3000
MAX_CONSOLIDATION_CHARS = 300
MAX_EXPLANATION_ANSWER_CHARS = 500

SAFE_FOCUS = "先看清题目在问什么，再自己试一步。"
SAFE_STEP = "这一步先不揭示答案，回到题目的条件再试一次。"
SAFE_CONSOLIDATION = "把刚才的思路自己复述一遍，再检查关键一步。"

LEAK_ANSWER_FIELD_DROPPED = "answer_field_dropped"
LEAK_STANDARD_ANSWER_MASKED = "standard_answer_masked"
LEAK_ANSWER_PHRASE_MASKED = "answer_phrase_masked"

EXPLANATION_ATTEMPTED = "explanation_attempted"
EXPLANATION_SHOWN = "explanation_shown"

ATTEMPT_KEY = "explanation:attempt:{context_key}:{attempt_id}"
SHOWN_KEY = "explanation:shown:{context_key}:{request_id}"

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_HTML_TAG = re.compile(r"<\s*/?\s*[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?>")
_ANSWER_PHRASE = re.compile(r"(?:答案|最终结果|正确结果)\s*(?:是|为|[:：])")
_PUNCT = re.compile(r"[\s，。；：、,.;:!?！？（）()【】\[\]\"'“”‘’]+")


@dataclass(frozen=True)
class ExplainContext:
    kind: str
    context_id: int
    entry: str
    problem_text: str
    student_answer: str = ""
    standard_answer: str = ""
    subject: str = ""
    category_name: str = ""
    concepts: tuple[str, ...] = ()
    error_cause: str | None = None
    mistake_id: int | None = None

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.context_id}"


@dataclass(frozen=True)
class GatedExplanation:
    focus: str
    steps: tuple[str, ...]
    consolidation: str
    answer: str | None
    leak_flags: tuple[str, ...]


class ExplanationQualityError(ValueError):
    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(",".join(reasons))


class ExplainContextNotFound(LookupError):
    pass


class ExplainContextUnavailable(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def default_mode(context: ExplainContext) -> str:
    if context.entry == ENTRY_QUESTION:
        return MODE_FULL
    if context.subject in MEMORY_SUBJECTS:
        return MODE_GUIDE
    return MODE_BY_ERROR_CAUSE.get(context.error_cause or "", MODE_GUIDE)


def resolve_mode(context: ExplainContext, requested: str) -> str:
    if requested not in MODES:
        raise ValueError(f"未知讲解模式: {requested}")
    if requested == MODE_AUTO:
        return default_mode(context)
    return requested


def choose_strategy(context: ExplainContext) -> str:
    if context.subject in MEMORY_SUBJECTS:
        return "recall"
    if context.entry == ENTRY_QUESTION:
        return "general_solve"
    return STRATEGY_BY_ERROR_CAUSE.get(context.error_cause or "", "general_guide")


def strategy_label(strategy: str) -> str:
    return STRATEGY_LABELS.get(strategy, strategy)


def needs_soft_gate(
    context: ExplainContext,
    *,
    mode: str,
    attempted: bool,
) -> bool:
    return (
        context.entry == ENTRY_MISTAKE
        and mode == MODE_FULL
        and default_mode(context) == MODE_GUIDE
        and not attempted
    )


def next_hint_level(mode: str, hint_level: int) -> int | None:
    if mode != MODE_GUIDE or hint_level >= 3:
        return None
    return hint_level + 1


def prompt_values(
    context: ExplainContext,
    *,
    mode: str,
    strategy: str,
    hint_level: int,
    attempted: bool,
) -> dict[str, str]:
    return {
        "PROBLEM_TEXT": context.problem_text,
        "STUDENT_ANSWER": context.student_answer or "（未提供）",
        "STANDARD_ANSWER": context.standard_answer or "（未提供）",
        "SUBJECT": context.subject or "未知",
        "CATEGORY": context.category_name or "未分类",
        "CONCEPTS": "、".join(context.concepts) or "未标注",
        "ERROR_CAUSE": error_cause_label(context.error_cause) or "未确认",
        "STRATEGY": strategy_label(strategy),
        "CONTEXT_LABEL": "错题订正" if context.entry == ENTRY_MISTAKE else "拍照答疑",
        "HINT_LEVEL": str(hint_level if mode == MODE_GUIDE else 0),
        "ATTEMPTED": "是" if attempted else "否",
    }


def quality_gate(
    explanation: Explanation,
    *,
    mode: str,
    standard_answer: str = "",
) -> GatedExplanation:
    """校验模型输出；引导模式额外丢弃/遮蔽答案，失败抛 ExplanationQualityError。"""

    if mode not in FINAL_MODES:
        raise ValueError(f"质量闸门只接受最终模式: {mode}")

    focus = _clean(explanation.focus)
    steps = tuple(
        step for step in (_clean(raw_step) for raw_step in explanation.steps) if step
    )
    consolidation = _clean(explanation.consolidation)
    answer = _clean(explanation.answer) if explanation.answer is not None else None

    reasons: list[str] = []
    if not focus:
        reasons.append("focus_empty")
    elif len(focus) > MAX_FOCUS_CHARS:
        reasons.append("focus_too_long")

    if not steps or not any(steps):
        reasons.append("steps_empty")
    if len(steps) > MAX_STEPS:
        reasons.append("steps_too_many")
    if any(len(step) > MAX_STEP_CHARS for step in steps):
        reasons.append("step_too_long")
    if sum(len(step) for step in steps) > MAX_TOTAL_STEPS_CHARS:
        reasons.append("steps_too_long")

    if not consolidation:
        reasons.append("consolidation_empty")
    elif len(consolidation) > MAX_CONSOLIDATION_CHARS:
        reasons.append("consolidation_too_long")

    if mode == MODE_FULL:
        if not answer:
            reasons.append("answer_missing")
        elif len(answer) > MAX_EXPLANATION_ANSWER_CHARS:
            reasons.append("answer_too_long")
    if mode == MODE_FULL and len(steps) < 2:
        reasons.append("full_needs_multiple_steps")

    texts = (focus, consolidation, *steps, answer or "")
    if any(PLACEHOLDER_MARK in text for text in texts):
        reasons.append("placeholder")
    if any(_CONTROL_CHARS.search(text) for text in texts):
        reasons.append("control_chars")
    if any(_HTML_TAG.search(text) for text in texts):
        reasons.append("html")

    if reasons:
        raise ExplanationQualityError(tuple(dict.fromkeys(reasons)))

    flags: list[str] = []
    if mode == MODE_GUIDE:
        if answer:
            flags.append(LEAK_ANSWER_FIELD_DROPPED)
        answer = None

        focus, known_hit = _mask_known(focus, standard_answer, SAFE_FOCUS)
        masked_steps: list[str] = []
        steps_known = False
        for step in steps:
            masked, step_hit = _mask_known(step, standard_answer, SAFE_STEP)
            masked_steps.append(masked)
            steps_known = steps_known or step_hit
        consolidation, cons_known = _mask_known(
            consolidation, standard_answer, SAFE_CONSOLIDATION
        )
        if known_hit or steps_known or cons_known:
            flags.append(LEAK_STANDARD_ANSWER_MASKED)

        focus, phrase_hit = _mask_phrase(focus, SAFE_FOCUS)
        phrase_steps: list[str] = []
        for step in masked_steps:
            masked, step_phrase = _mask_phrase(step, SAFE_STEP)
            phrase_steps.append(masked)
            phrase_hit = phrase_hit or step_phrase
        consolidation, cons_phrase = _mask_phrase(consolidation, SAFE_CONSOLIDATION)
        if phrase_hit or cons_phrase:
            flags.append(LEAK_ANSWER_PHRASE_MASKED)
        steps = tuple(phrase_steps)

    return GatedExplanation(
        focus=focus,
        steps=steps,
        consolidation=consolidation,
        answer=answer,
        leak_flags=tuple(dict.fromkeys(flags)),
    )


def _clean(value: str | None) -> str:
    return "" if value is None else str(value).strip()


def _canonical(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return _PUNCT.sub("", text)


def _mask_known(text: str, standard_answer: str, safe: str) -> tuple[str, bool]:
    expected = _canonical(standard_answer)
    if len(expected) < 2:
        return text, False
    if expected in _canonical(text):
        return safe, True
    return text, False


def _mask_phrase(text: str, safe: str) -> tuple[str, bool]:
    if _ANSWER_PHRASE.search(text):
        return safe, True
    return text, False


# ---- 上下文读取（只查询，不调模型） --------------------------------------


async def read_context(
    session: AsyncSession, kind: str, context_id: int
) -> ExplainContext:
    if kind == CONTEXT_MISTAKE:
        return await _read_mistake(session, context_id)
    if kind == CONTEXT_EXTRACTION:
        return await _read_extraction(session, context_id)
    if kind == CONTEXT_DRAFT:
        return await _read_draft(session, context_id)
    raise ExplainContextNotFound("未知讲解上下文")


async def _read_mistake(session: AsyncSession, mistake_id: int) -> ExplainContext:
    mistake = await session.get(Mistake, mistake_id)
    if mistake is None:
        raise ExplainContextNotFound("错题不存在")
    if mistake.status != MISTAKE_ACTIVE:
        raise ExplainContextUnavailable("mistake_voided")
    version = await get_latest_version(session, mistake_id)
    if version is None:
        raise ExplainContextUnavailable("mistake_version_missing")

    problem_text = _explainable_problem(version.problem_text)
    labels = effective_labels(version)
    category: KnowledgeSeed | None = None
    if labels.category_id:
        category = await session.get(KnowledgeSeed, labels.category_id)
    concepts: tuple[str, ...] = ()
    if labels.concept_ids:
        rows = (
            await session.execute(
                select(Concept.id, Concept.name).where(
                    Concept.id.in_(labels.concept_ids)
                )
            )
        ).all()
        names = {row.id: row.name for row in rows}
        concepts = tuple(
            names[concept_id]
            for concept_id in labels.concept_ids
            if concept_id in names
        )
    return ExplainContext(
        kind=CONTEXT_MISTAKE,
        context_id=mistake.id,
        entry=ENTRY_MISTAKE,
        problem_text=problem_text,
        student_answer=_bounded_answer(version.student_answer),
        standard_answer=_bounded_answer(version.standard_answer),
        subject=category.subject if category is not None else "",
        category_name=category.name if category is not None else "",
        concepts=concepts,
        error_cause=labels.error_cause,
        mistake_id=mistake.id,
    )


async def _read_extraction(
    session: AsyncSession, extraction_id: int
) -> ExplainContext:
    row = await session.get(ProblemExtraction, extraction_id)
    if row is None:
        raise ExplainContextNotFound("提取结果不存在")
    if row.gate_status == GATE_FIGURE:
        raise ExplainContextUnavailable("figure_dependency")
    if row.gate_status not in (GATE_READY, GATE_MANUAL):
        raise ExplainContextUnavailable("extraction_gate_unknown")
    if row.gate_status == GATE_MANUAL:
        reasons = _review_reasons(row.review_reasons_json)
        if reasons & {
            REASON_PROBLEM_EMPTY,
            REASON_PROBLEM_INCOMPLETE,
            REASON_COMPLETENESS_UNKNOWN,
            REASON_WHOLE_PAGE,
        }:
            raise ExplainContextUnavailable("extraction_problem_incomplete")

    problem_text = _explainable_problem(row.problem_text)
    return ExplainContext(
        kind=CONTEXT_EXTRACTION,
        context_id=row.id,
        entry=ENTRY_QUESTION,
        problem_text=problem_text,
        student_answer=_bounded_answer(row.student_answer),
    )


async def _read_draft(session: AsyncSession, draft_id: int) -> ExplainContext:
    row = await session.get(IngestionDraft, draft_id)
    if row is None:
        raise ExplainContextNotFound("草稿不存在")
    try:
        data = json.loads(row.normalized_json)
    except json.JSONDecodeError:
        raise ExplainContextUnavailable("draft_invalid") from None
    if not isinstance(data, dict):
        raise ExplainContextUnavailable("draft_invalid")

    problem_text = data.get("problem_text")
    student_answer = data.get("student_answer")
    subject = data.get("subject")
    return ExplainContext(
        kind=CONTEXT_DRAFT,
        context_id=row.id,
        entry=ENTRY_QUESTION,
        problem_text=_explainable_problem(
            problem_text if isinstance(problem_text, str) else ""
        ),
        student_answer=_bounded_answer(
            student_answer if isinstance(student_answer, str) else ""
        ),
        subject=subject if isinstance(subject, str) else "",
    )


def _review_reasons(raw: str) -> set[str]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {item for item in data if isinstance(item, str)}


def _explainable_problem(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        raise ExplainContextUnavailable("problem_text_empty")
    if len(text) > MAX_PROBLEM_TEXT_CHARS:
        raise ExplainContextUnavailable("problem_text_too_long")
    if PLACEHOLDER_MARK in text:
        raise ExplainContextUnavailable("placeholder")
    if detect_figure_keywords(text):
        raise ExplainContextUnavailable("figure_dependency")
    return text


def _bounded_answer(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) > MAX_ANSWER_CHARS or PLACEHOLDER_MARK in text:
        return ""
    return text


# ---- 事实事件（append-only，payload 不含正文/答案） ----------------------


async def has_attempt(session: AsyncSession, context: ExplainContext) -> bool:
    if context.mistake_id is None:
        return False
    stmt = (
        select(LearningEvent.id)
        .where(
            LearningEvent.type == EXPLANATION_ATTEMPTED,
            LearningEvent.mistake_id == context.mistake_id,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def record_attempt(
    session: AsyncSession,
    context: ExplainContext,
    *,
    attempt_id: str,
    mode: str,
    hint_level: int,
) -> tuple[LearningEvent, bool]:
    if mode not in FINAL_MODES:
        raise ValueError(f"attempt 模式必须是 guide/full: {mode}")
    if not 1 <= hint_level <= 3:
        raise ValueError("attempt 层级必须在 1–3")
    payload = {
        "context_kind": context.kind,
        "context_id": context.context_id,
        "mode": mode,
        "hint_level": hint_level,
    }
    return await record_event(
        session,
        EXPLANATION_ATTEMPTED,
        "student",
        idempotency_key=ATTEMPT_KEY.format(
            context_key=context.key, attempt_id=attempt_id
        ),
        mistake_id=context.mistake_id,
        payload=payload,
    )


async def record_shown(
    session: AsyncSession,
    context: ExplainContext,
    *,
    request_id: str,
    mode: str,
    requested_mode: str,
    default_mode: str,
    strategy: str,
    hint_level: int | None,
    attempted: bool,
    soft_gate: bool,
    answer_shown: bool,
    leak_flags: tuple[str, ...],
    meta: CallMeta,
) -> tuple[LearningEvent, bool]:
    payload = {
        "context_kind": context.kind,
        "context_id": context.context_id,
        "entry": context.entry,
        "mode": mode,
        "requested_mode": requested_mode,
        "default_mode": default_mode,
        "strategy": strategy,
        "hint_level": hint_level,
        "attempted": attempted,
        "soft_gate": soft_gate,
        "answer_shown": answer_shown,
        "leak_flags": list(leak_flags),
        "prompt_id": meta.prompt_id,
        "prompt_version": meta.prompt_version,
        "provider": meta.provider,
        "model": meta.model,
        "cache_hit": bool(meta.raw.get("cache_hit")),
    }
    return await record_event(
        session,
        EXPLANATION_SHOWN,
        "student",
        idempotency_key=SHOWN_KEY.format(
            context_key=context.key, request_id=request_id
        ),
        mistake_id=context.mistake_id,
        payload=payload,
    )
