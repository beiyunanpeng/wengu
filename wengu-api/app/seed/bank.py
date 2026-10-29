"""P1-10 内存题库索引：seeds/data/questions.json → topic_id → [题] 倒排。

纪律（AGENTS §2.6 / 设计文档 §14 / §16.D）：
- 题库以 JSON 文件形态随仓库分发，运行时读入内存索引，**不进 SQLite**
  （SQLite 只存动态数据 + external_id 溯源）。
- 装载即不可信输入：结构/字段校验、内联 SVG 白名单净化（app.seed.svg）。
- 每题 `verify` 在装载时过 P1-5 AST 白名单沙箱（app.judge.verify_sandbox）：
  * verified     表达式求出且与答案一致；
  * unverifiable 无 verify / 表达式超出沙箱白名单（上游用了 Fraction、range 等）/
                 选择题选项带单位或文字，无法用数值表达式直接比对；
  * mismatch     纯数值题算出的结果与答案矛盾 → **不装载**（计入 stats.dropped）。
- 空文件/缺文件容忍（语文/化学无题起步），返回空索引而不是阻塞服务。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.config import get_settings
from app.judge.verify_sandbox import SandboxError, verify_answer
from app.seed.svg import sanitize_svg

QUESTION_TYPES = frozenset({"choice", "numeric", "short", "self"})
SUBJECT_BY_PREFIX = {"cnm_": "数学", "cne_": "英语", "cnp_": "物理"}

VerifyStatus = Literal["verified", "unverifiable"]


class BankFormatError(ValueError):
    """题库 JSON 顶层结构非法（fail-fast；不回退到静默空库）。"""


@dataclass(frozen=True)
class BankChoice:
    key: str
    text: str
    figure: str | None = None


@dataclass(frozen=True)
class BankQuestion:
    id: str
    topic_id: str
    subject: str
    type: str
    difficulty: str | None
    prompt: str
    answer: str
    accept: tuple[str, ...]
    choices: tuple[BankChoice, ...]
    unordered: bool
    hide_choice_text: bool
    figure: str | None
    explanation: str
    verify: str | None
    verify_status: VerifyStatus
    verify_reason: str | None
    percent: bool
    unaudited: bool
    blind_verified: bool


@dataclass(frozen=True)
class BankStats:
    total: int
    by_subject: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)
    topics_total: int = 0
    topics_with_questions: int = 0
    verified: int = 0
    unverifiable: int = 0
    verify_reasons: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    figures: int = 0


@dataclass(frozen=True)
class QuestionBank:
    by_topic: dict[str, tuple[BankQuestion, ...]]
    by_id: dict[str, BankQuestion]
    topics: dict[str, dict[str, Any]]
    stats: BankStats

    def questions_for(self, topic_id: str) -> tuple[BankQuestion, ...]:
        return self.by_topic.get(topic_id, ())

    def question(self, question_id: str) -> BankQuestion | None:
        return self.by_id.get(question_id)


def load_bank(seeds_dir: Path | None = None) -> QuestionBank:
    """从 seeds/data 读取题库并建倒排；幂等、纯内存、不触库。"""

    root = Path(seeds_dir) if seeds_dir is not None else get_settings().seeds_dir
    data_dir = root / "data"

    topics_raw = _read_json(data_dir / "topics.json") or []
    questions_raw = _read_json(data_dir / "questions.json") or []
    if not isinstance(topics_raw, list) or not isinstance(questions_raw, list):
        raise BankFormatError("topics.json / questions.json 必须是数组")

    topics = _topic_meta(topics_raw)
    dropped: dict[str, int] = {}
    verify_reasons: dict[str, int] = {}
    by_subject: dict[str, int] = {}
    by_type: dict[str, int] = {}
    grouped: dict[str, list[BankQuestion]] = {}
    by_id: dict[str, BankQuestion] = {}
    verified = unverifiable = figures = 0

    for raw in questions_raw:
        question = _build_question(raw, topics, dropped)
        if question is None:
            continue
        if question.id in by_id:
            _drop(dropped, "duplicate_id")
            continue
        by_id[question.id] = question
        grouped.setdefault(question.topic_id, []).append(question)
        by_subject[question.subject] = by_subject.get(question.subject, 0) + 1
        by_type[question.type] = by_type.get(question.type, 0) + 1
        figures += _figure_count(question)
        if question.verify_status == "verified":
            verified += 1
        else:
            unverifiable += 1
            reason = question.verify_reason or "unknown"
            verify_reasons[reason] = verify_reasons.get(reason, 0) + 1

    by_topic = {
        topic_id: tuple(sorted(items, key=lambda item: item.id))
        for topic_id, items in grouped.items()
    }
    stats = BankStats(
        total=sum(by_subject.values()),
        by_subject=dict(sorted(by_subject.items())),
        by_type=dict(sorted(by_type.items())),
        topics_total=len(topics),
        topics_with_questions=len(by_topic),
        verified=verified,
        unverifiable=unverifiable,
        verify_reasons=dict(sorted(verify_reasons.items())),
        dropped=dict(sorted(dropped.items())),
        figures=figures,
    )
    return QuestionBank(by_topic=by_topic, by_id=by_id, topics=topics, stats=stats)


def _build_question(
    raw: object, topics: dict[str, dict[str, Any]], dropped: dict[str, int]
) -> BankQuestion | None:
    if not isinstance(raw, dict):
        _drop(dropped, "invalid_question")
        return None

    question_id = raw.get("id")
    topic_id = raw.get("topic_id")
    if not isinstance(question_id, str) or not question_id.strip():
        _drop(dropped, "invalid_id")
        return None
    if not isinstance(topic_id, str) or not topic_id.strip():
        _drop(dropped, "invalid_topic")
        return None

    topic = topics.get(topic_id)
    if topics and topic is None:
        _drop(dropped, "unknown_topic")
        return None
    topic = topic or {}

    question_type = raw.get("type")
    if question_type not in QUESTION_TYPES:
        _drop(dropped, "invalid_type")
        return None

    prompt = raw.get("prompt")
    answer = raw.get("answer")
    if not isinstance(prompt, str) or not prompt.strip():
        _drop(dropped, "invalid_prompt")
        return None
    if not isinstance(answer, str) or not answer.strip():
        _drop(dropped, "invalid_answer")
        return None

    accept_raw = raw.get("accept") or []
    if not isinstance(accept_raw, list) or any(not isinstance(x, str) for x in accept_raw):
        _drop(dropped, "invalid_accept")
        return None

    choices_raw = raw.get("choices") or []
    if not isinstance(choices_raw, list):
        _drop(dropped, "invalid_choices")
        return None
    choices = []
    for item in choices_raw:
        if not isinstance(item, dict):
            _drop(dropped, "invalid_choices")
            return None
        key, text = item.get("key"), item.get("text")
        if not isinstance(key, str) or not isinstance(text, str):
            _drop(dropped, "invalid_choices")
            return None
        choices.append(BankChoice(key=key, text=text, figure=sanitize_svg(item.get("figure"))))
    if question_type == "choice" and (
        not choices or answer.strip() not in {choice.key for choice in choices}
    ):
        _drop(dropped, "answer_not_in_choices")
        return None

    subject = topic.get("subject")
    if not isinstance(subject, str) or not subject:
        subject = _subject_of(topic_id)

    verify = raw.get("verify")
    if verify is not None and not isinstance(verify, str):
        _drop(dropped, "invalid_verify")
        return None
    verify_status, verify_reason = _classify_verify(
        verify=verify,
        expected=_expected_answer(question_type, answer, choices),
        accept=tuple(accept_raw),
        unordered=raw.get("unordered") is True,
        question_type=question_type,
    )
    if verify_status == "mismatch":
        _drop(dropped, "verify_mismatch")
        return None

    return BankQuestion(
        id=question_id,
        topic_id=topic_id,
        subject=subject,
        type=question_type,
        difficulty=_optional_str(raw.get("difficulty")),
        prompt=prompt,
        answer=answer,
        accept=tuple(accept_raw),
        choices=tuple(choices),
        unordered=raw.get("unordered") is True,
        hide_choice_text=raw.get("hide_choice_text") is True,
        figure=sanitize_svg(raw.get("figure")),
        explanation=_optional_str(raw.get("explanation")) or "",
        verify=verify,
        verify_status=verify_status,  # type: ignore[arg-type]
        verify_reason=verify_reason,
        percent=raw.get("percent") is True,
        unaudited=bool(topic.get("unaudited", True)),
        blind_verified=bool(topic.get("blind_verified", False)),
    )


def _classify_verify(
    *,
    verify: str | None,
    expected: str | None,
    accept: tuple[str, ...],
    unordered: bool,
    question_type: str,
) -> tuple[str, str | None]:
    if not verify:
        return "unverifiable", "no_verify"
    if expected is None:
        return "unverifiable", "choice_text_missing"
    try:
        outcome = verify_answer(
            verify, expected=expected, acceptable=accept, unordered=unordered
        )
    except SandboxError as exc:
        return "unverifiable", f"sandbox:{exc.reason}"
    if outcome.verdict == "verified":
        return "verified", None
    if outcome.verdict == "unverifiable":
        return "unverifiable", f"sandbox:{outcome.reason}"
    # 选择题选项可能带单位/文字（"90 min"），数值表达式与选项文本不一致时不足以判错；
    # 纯数值/短答题目标答案可直接比较，矛盾即不装载。
    if question_type == "choice":
        return "unverifiable", "choice_text_mismatch"
    return "mismatch", "verify_mismatch"


def _expected_answer(
    question_type: str, answer: str, choices: list[BankChoice]
) -> str | None:
    if question_type != "choice":
        return answer
    for choice in choices:
        if choice.key == answer:
            return choice.text
    return None


def _topic_meta(topics_raw: list[Any]) -> dict[str, dict[str, Any]]:
    topics: dict[str, dict[str, Any]] = {}
    for raw in topics_raw:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        topics[raw["id"]] = raw
    return topics


def _subject_of(topic_id: str) -> str:
    for prefix, subject in SUBJECT_BY_PREFIX.items():
        if topic_id.startswith(prefix):
            return subject
    return "未知"


def _figure_count(question: BankQuestion) -> int:
    return (1 if question.figure else 0) + sum(1 for c in question.choices if c.figure)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _drop(dropped: dict[str, int], reason: str) -> None:
    dropped[reason] = dropped.get(reason, 0) + 1


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
