"""提取质量前置闸门（P1-4，AGENTS §5 一等公民）。

模型只负责"提"，本模块用确定性规则决定这条提取结果能否进入 P1-5 判分链路：
题目残缺 / 含 〔?〕 / 作答为空 → manual_review，绝不自动放行；
依赖图形的题 → figure_dependent，可回显但不参与自动判分与复习；
其余 → ready_for_grading（Phase 0 边界表未回填时，P1-5 仍按待确认保守处理）。

闸门只做判定，不判对错、不调用模型。所有字段按不可信输入清洗。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.providers.base import ExtractedProblem
from app.services.ingestion import PLACEHOLDER_MARK, clean_text

EXTRACT_PROMPT_ID = "extract_problem"

SOURCE_SLICE = "slice"
SOURCE_WHOLE_PAGE = "whole_page"
SOURCE_KINDS = frozenset({SOURCE_SLICE, SOURCE_WHOLE_PAGE})

GATE_READY = "ready_for_grading"
GATE_MANUAL = "manual_review"
GATE_FIGURE = "figure_dependent"

REASON_PROBLEM_EMPTY = "problem_empty"
REASON_PROBLEM_INCOMPLETE = "problem_incomplete"
REASON_COMPLETENESS_UNKNOWN = "completeness_unknown"
REASON_PLACEHOLDER = "placeholder"
REASON_ANSWER_EMPTY = "student_answer_empty"
REASON_FIGURE = "figure_dependency"
REASON_WHOLE_PAGE = "whole_page_unsegmented"

# 单题裁图正常远低于上限；整页兜底放宽但仍有硬顶，超限整条拒收（不静默截断）。
MAX_PROBLEM_TEXT_CHARS = 8000
MAX_ANSWER_CHARS = 2000

_MANUAL_REASONS = frozenset(
    {
        REASON_PROBLEM_EMPTY,
        REASON_PROBLEM_INCOMPLETE,
        REASON_COMPLETENESS_UNKNOWN,
        REASON_PLACEHOLDER,
        REASON_ANSWER_EMPTY,
        REASON_WHOLE_PAGE,
    }
)

# 确定性关键词规则：只认指涉图形的措辞，不认"图形"这种普通名词（避免误伤）。
_FIGURE_PATTERN = re.compile(
    r"【依赖图形】"
    r"|如下图|如上图|如图|见图|下图|上图|左图|右图|图中|图所示|图示"
    r"|图\s*[0-9①-⑳甲乙丙丁]"
)


class ExtractionRejected(ValueError):
    """输入超出硬上限，整条拒收（错误进逐条报告，不落库）。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class GateDecision:
    problem_text: str
    student_answer: str | None
    confidence: float | None
    problem_complete: bool | None
    gate_status: str
    review_reasons: tuple[str, ...]
    figure_keywords: tuple[str, ...]


def detect_figure_keywords(text: str) -> tuple[str, ...]:
    """返回命中的图形指涉关键词（去重、保序）；无命中返回空元组。"""

    return tuple(dict.fromkeys(_FIGURE_PATTERN.findall(text)))


def apply_extraction_gate(
    extracted: ExtractedProblem, *, source_kind: str
) -> GateDecision:
    """对单条提取结果做确定性闸门判定；超长输入直接拒收。"""

    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"未知 source_kind: {source_kind!r}")

    problem_text = clean_text(extracted.problem_text or "")
    answer = (clean_text(extracted.student_answer) if extracted.student_answer else "") or None

    if len(problem_text) > MAX_PROBLEM_TEXT_CHARS:
        raise ExtractionRejected("problem_text_too_long")
    if answer is not None and len(answer) > MAX_ANSWER_CHARS:
        raise ExtractionRejected("student_answer_too_long")

    reasons: list[str] = []
    if not problem_text:
        reasons.append(REASON_PROBLEM_EMPTY)
    if extracted.problem_complete is False:
        reasons.append(REASON_PROBLEM_INCOMPLETE)
    elif extracted.problem_complete is not True:
        # 模型漏字段/类型不可信 → 不赌，交人工
        reasons.append(REASON_COMPLETENESS_UNKNOWN)
    if PLACEHOLDER_MARK in problem_text or (answer and PLACEHOLDER_MARK in answer):
        reasons.append(REASON_PLACEHOLDER)
    if not answer:
        reasons.append(REASON_ANSWER_EMPTY)

    figure_keywords = detect_figure_keywords(problem_text)
    if figure_keywords:
        reasons.append(REASON_FIGURE)
    if source_kind == SOURCE_WHOLE_PAGE:
        # 整页无法切题时可能含多题，绝不把一页当一道题放行
        reasons.append(REASON_WHOLE_PAGE)

    if any(reason in _MANUAL_REASONS for reason in reasons):
        status = GATE_MANUAL
    elif REASON_FIGURE in reasons:
        status = GATE_FIGURE
    else:
        status = GATE_READY

    return GateDecision(
        problem_text=problem_text,
        student_answer=answer,
        confidence=extracted.confidence,
        problem_complete=extracted.problem_complete,
        gate_status=status,
        review_reasons=tuple(reasons),
        figure_keywords=figure_keywords,
    )
