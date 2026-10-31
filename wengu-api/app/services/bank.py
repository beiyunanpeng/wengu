"""P1-10/P1-11 同类题检索与组卷：同 topic_id + mulberry32 固定种子，可 replay。

设计文档 §16.D：同类题只按 `primary_topic_id` 检索、每次 1 题；检索不到返回空 +
`bank_gap=true`（P1-7a 据此退回原题重做），绝不让 LLM 编题。P1-11 起"能考就考"：
先取**可自动判分**的题（客观/数值/短答、且不依赖题图），没有才退回非可答题并标记
`mode=self_eval`（纸上做 → 拍已批改 → 自评）。

P3-1b：检索池 = seed JSON 只读主体 + SQLite `problem_bank` 已入库家长题的增量池
（`get_runtime_bank`）。家长题只进 SQLite，绝不回写 seed JSON；合并后整体重算统计，
审核通过/手填直录提交后失效缓存，下一条到期任务即可用新题。

P3-1c：`problem_bank` 软作废（`status='voided'`）——只退出运行时检索池，**不物理删除、
不改写历史**（attempts/events 是 append-only 事实）。家长编辑题面/答案时 id 不变，
`external_id` 也不变，因此历史 attempts 的判分依据不受影响。

确定性纪律（AGENTS §5）：mulberry32 与上游 JS 逐位一致（uint32 语义），
同样 `(topic_id, seed)` 在任意进程、任意装载顺序下命中同一题；`replay` / `replay_paper`
重算并校验，**池增长/作废同样导致候选集合变化**，此时抛 `BankReplayError` 而不是静默换题。
内容修订不算换题：`replay` 按身份（topic/seed/pool_ids/index/question_id/coverage/mode）
比较，同一 id 的题面改写仍可重放（不回溯历史内容）。
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeSeed, ProblemBankItem
from app.seed.bank import (
    QUESTION_TYPES,
    BankChoice,
    BankQuestion,
    BankStats,
    QuestionBank,
    load_bank,
)
from app.seed.svg import sanitize_svg

# 学科题量低于该阈值视为"覆盖薄"（§5 反虚假精确：样本不足不吹保证）。
# 现状：数学 1407 / 英语 1028 正常，物理 368 薄；语文/化学无题 → gap。
THIN_SUBJECT_QUESTIONS = 500

Coverage = Literal["ok", "thin", "gap"]
AnswerMode = Literal["system", "self_eval"]
ANSWERABLE_TYPES = frozenset({"choice", "numeric", "short"})


class BankReplayError(RuntimeError):
    """重放结果与记录不一致（题库被替换/数据漂移），交给上层告警而不是换题。"""


def is_answerable(question: BankQuestion) -> bool:
    """能在页面内作答并由服务端确定性判分的题：客观/数值/短答且不依赖题图。

    题图存在时按 `【依赖图形】` 边界降级自评（AGENTS §5）；选项内联图不影响选择作答。
    """

    return question.type in ANSWERABLE_TYPES and not question.figure


@dataclass(frozen=True)
class BankPick:
    topic_id: str | None
    seed: int
    question: BankQuestion | None
    pool_ids: tuple[str, ...]
    index: int | None
    coverage: Coverage
    mode: AnswerMode = "system"

    @property
    def bank_gap(self) -> bool:
        return self.coverage == "gap"

    @property
    def pool_size(self) -> int:
        return len(self.pool_ids)

    @property
    def question_id(self) -> str | None:
        return self.question.id if self.question is not None else None


@dataclass(frozen=True)
class PaperItem:
    question: BankQuestion
    mode: AnswerMode


@dataclass(frozen=True)
class PaperPick:
    topic_id: str
    seed: int
    requested: int
    items: tuple[PaperItem, ...]
    coverage: Coverage
    answerable_total: int
    pool_total: int

    @property
    def bank_gap(self) -> bool:
        return not self.items

    @property
    def shortfall(self) -> bool:
        return len(self.items) < self.requested

    @property
    def system_count(self) -> int:
        return sum(1 for item in self.items if item.mode == "system")

    @property
    def self_eval_count(self) -> int:
        return sum(1 for item in self.items if item.mode == "self_eval")


_SEED_CACHE: QuestionBank | None = None
_RUNTIME_CACHE: QuestionBank | None = None


def get_bank() -> QuestionBank:
    """仅 seed 题库的进程内索引（JSON 真源，首次调用装载；测试可用 reset_bank_cache）。"""

    global _SEED_CACHE
    if _SEED_CACHE is None:
        _SEED_CACHE = load_bank()
    return _SEED_CACHE


async def get_runtime_bank(session: AsyncSession) -> QuestionBank:
    """运行时检索池 = seed 只读主体 + `problem_bank` 已入库家长题的增量池。

    家长题只写 SQLite，绝不回写 seed JSON；这里把 `problem_bank` 行映射成
    `BankQuestion` 合并进内存索引，统计随之重算（`coverage/thin` 按新池判定）。
    进程内缓存；审核通过 / 手填直录提交后调用 `reset_bank_cache()` 失效。
    """

    global _RUNTIME_CACHE
    if _RUNTIME_CACHE is None:
        _RUNTIME_CACHE = await _load_runtime_bank(session)
    return _RUNTIME_CACHE


def reset_bank_cache() -> None:
    global _SEED_CACHE, _RUNTIME_CACHE
    _SEED_CACHE = None
    _RUNTIME_CACHE = None


async def _load_runtime_bank(session: AsyncSession) -> QuestionBank:
    base = get_bank()
    rows = (
        await session.scalars(
            select(ProblemBankItem)
            .where(
                ProblemBankItem.topic_id.is_not(None),
                ProblemBankItem.status == "active",
            )
            .order_by(ProblemBankItem.id)
        )
    ).all()
    if not rows:
        return base

    dropped = dict(base.stats.dropped)
    dynamic: list[BankQuestion] = []
    seen = set(base.by_id)
    for row in rows:
        question = _dynamic_question(row, seen, dropped)
        if question is None:
            continue
        seen.add(question.id)
        dynamic.append(question)

    extra_topics: dict[str, dict[str, Any]] = {}
    missing = sorted({question.topic_id for question in dynamic} - set(base.topics))
    if missing:
        seeds = (
            await session.scalars(
                select(KnowledgeSeed).where(KnowledgeSeed.id.in_(missing))
            )
        ).all()
        extra_topics = {seed.id: _topic_meta_of(seed) for seed in seeds}

    grouped: dict[str, list[BankQuestion]] = {
        topic_id: list(items) for topic_id, items in base.by_topic.items()
    }
    for question in dynamic:
        grouped.setdefault(question.topic_id, []).append(question)
    by_topic = {
        topic_id: tuple(sorted(items, key=lambda item: item.id))
        for topic_id, items in grouped.items()
    }
    by_id = {**base.by_id, **{question.id: question for question in dynamic}}
    topics = {**base.topics, **extra_topics}
    return QuestionBank(
        by_topic=by_topic,
        by_id=by_id,
        topics=topics,
        stats=_compute_stats(by_topic, topics, dropped),
    )


def _dynamic_question(
    row: ProblemBankItem, seen: set[str], dropped: dict[str, int]
) -> BankQuestion | None:
    """`problem_bank` 行 → BankQuestion；不可信输入校验不过即计入 dropped。"""

    question_id = row.external_id
    if not isinstance(question_id, str) or not question_id.strip():
        _drop(dropped, "db_invalid_id")
        return None
    if question_id in seen:
        _drop(dropped, "db_id_conflict")
        return None

    topic_id = row.topic_id
    if not isinstance(topic_id, str) or not topic_id.strip():
        _drop(dropped, "db_invalid_topic")
        return None
    question_type = row.question_type
    if question_type not in QUESTION_TYPES:
        _drop(dropped, "db_invalid_type")
        return None
    if not isinstance(row.problem_text, str) or not row.problem_text.strip():
        _drop(dropped, "db_invalid_prompt")
        return None
    if not isinstance(row.answer, str) or not row.answer.strip():
        _drop(dropped, "db_invalid_answer")
        return None

    accept = _json_strings(row.acceptable_answers_json)
    if accept is None:
        _drop(dropped, "db_invalid_accept")
        return None
    choices = _dynamic_choices(row.choices_json, dropped)
    if choices is None:
        return None
    if question_type == "choice" and (
        not choices or row.answer.strip() not in {choice.key for choice in choices}
    ):
        _drop(dropped, "db_answer_not_in_choices")
        return None

    verify = row.verify if isinstance(row.verify, str) and row.verify.strip() else None
    verified = row.verify_status == "verified"
    return BankQuestion(
        id=question_id,
        topic_id=topic_id,
        subject=row.subject,
        type=question_type,
        difficulty=row.difficulty,
        prompt=row.problem_text,
        answer=row.answer,
        accept=accept,
        choices=choices,
        unordered=bool(row.unordered),
        hide_choice_text=bool(row.hide_choice_text),
        figure=sanitize_svg(row.figure),
        explanation="",
        verify=verify,
        verify_status="verified" if verified else "unverifiable",
        verify_reason=None if verified else "db_unverified",
        percent=bool(row.percent),
        unaudited=True if row.unaudited is None else bool(row.unaudited),
        blind_verified=bool(row.blind_verified),
    )


def _dynamic_choices(
    raw: str | None, dropped: dict[str, int]
) -> tuple[BankChoice, ...] | None:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        _drop(dropped, "db_invalid_choices")
        return None
    if not isinstance(data, list):
        _drop(dropped, "db_invalid_choices")
        return None
    choices: list[BankChoice] = []
    for item in data:
        if not isinstance(item, dict):
            _drop(dropped, "db_invalid_choices")
            return None
        key, text = item.get("key"), item.get("text")
        if not isinstance(key, str) or not isinstance(text, str):
            _drop(dropped, "db_invalid_choices")
            return None
        choices.append(
            BankChoice(key=key, text=text, figure=sanitize_svg(item.get("figure")))
        )
    return tuple(choices)


def _json_strings(raw: str | None) -> tuple[str, ...] | None:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
        return None
    return tuple(data)


def _topic_meta_of(seed: KnowledgeSeed) -> dict[str, Any]:
    return {
        "id": seed.id,
        "subject": seed.subject,
        "name": seed.name,
        "domain": seed.domain,
        "grade": seed.grade,
        "semester": seed.semester,
        "chapter": seed.chapter,
        "type": seed.type,
        "unaudited": seed.unaudited,
        "blind_verified": seed.blind_verified,
    }


def _compute_stats(
    by_topic: dict[str, tuple[BankQuestion, ...]],
    topics: dict[str, dict[str, Any]],
    dropped: dict[str, int],
) -> BankStats:
    """按合并后的题池整体重算，保证 `coverage/thin` 与题目集合一致。"""

    by_subject: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    verify_reasons: Counter[str] = Counter()
    verified = unverifiable = figures = 0
    for items in by_topic.values():
        for question in items:
            by_subject[question.subject] += 1
            by_type[question.type] += 1
            figures += _figure_count(question)
            if question.verify_status == "verified":
                verified += 1
            else:
                unverifiable += 1
                verify_reasons[question.verify_reason or "unknown"] += 1
    return BankStats(
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


def _figure_count(question: BankQuestion) -> int:
    return (1 if question.figure else 0) + sum(
        1 for choice in question.choices if choice.figure
    )


def _drop(dropped: dict[str, int], reason: str) -> None:
    dropped[reason] = dropped.get(reason, 0) + 1


def mulberry32(seed: int) -> Iterator[float]:
    """JS mulberry32 的逐位移植；seed 按 32 位回绕（与 `a |= 0` 一致）。"""

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed 必须是整数")
    state = seed & 0xFFFFFFFF
    while True:
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = (state ^ (state >> 15)) & 0xFFFFFFFF
        t = (t * ((1 | state) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t = ((t + ((t ^ (t >> 7)) * ((61 | t) & 0xFFFFFFFF))) & 0xFFFFFFFF) ^ t
        yield ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296


def _coverage_for(source: QuestionBank, question: BankQuestion) -> Coverage:
    subject_total = source.stats.by_subject.get(question.subject, 1)
    return "thin" if subject_total < THIN_SUBJECT_QUESTIONS else "ok"


def find_same_type(
    primary_topic_id: str | None, seed: int, *, bank: QuestionBank | None = None
) -> BankPick:
    """按主考点取 1 道同类题；可答题优先，无题知识点返回空 pick + `bank_gap=true`。

    可答题池非空 → `mode="system"`（系统内作答 + judgeAnswer 判分）；
    只有非可答题（解答大题/依赖题图）→ `mode="self_eval"`（纸上做 → 自评）。
    """

    if primary_topic_id is not None and not isinstance(primary_topic_id, str):
        raise TypeError("primary_topic_id 必须是字符串或 None")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed 必须是整数")

    source = bank if bank is not None else get_bank()
    topic_id = primary_topic_id.strip() if primary_topic_id else ""
    full_pool = (
        tuple(sorted(source.questions_for(topic_id), key=lambda item: item.id))
        if topic_id
        else ()
    )
    if not full_pool:
        return BankPick(
            topic_id=topic_id or None,
            seed=seed,
            question=None,
            pool_ids=(),
            index=None,
            coverage="gap",
        )

    answerable = tuple(item for item in full_pool if is_answerable(item))
    pool = answerable or full_pool
    index = int(next(mulberry32(seed)) * len(pool))
    index = min(index, len(pool) - 1)
    return BankPick(
        topic_id=topic_id,
        seed=seed,
        question=pool[index],
        pool_ids=tuple(item.id for item in pool),
        index=index,
        coverage=_coverage_for(source, pool[index]),
        mode="system" if answerable else "self_eval",
    )


def replay(pick: BankPick, *, bank: QuestionBank | None = None) -> BankPick:
    """按记录重算同一选择；不一致直接失败（确定性回归/申诉用）。

    P3-1c：同题内容可被家长修订（id 不变），历史 quiz 记录不得因题面/答案编辑而
    失效。因此这里按**身份**校验（topic/seed/pool_ids/index/question_id/coverage/mode），
    不比较 `BankQuestion` 内容；作废导致 pool 变化仍抛 `BankReplayError`。
    """

    again = find_same_type(pick.topic_id, pick.seed, bank=bank)
    if not _same_pick_identity(pick, again):
        raise BankReplayError(
            f"重放不一致：topic={pick.topic_id!r} seed={pick.seed} "
            f"recorded={pick.question_id!r} replayed={again.question_id!r}"
        )
    return again


def _same_pick_identity(recorded: BankPick, replayed: BankPick) -> bool:
    return (
        recorded.topic_id == replayed.topic_id
        and recorded.seed == replayed.seed
        and recorded.question_id == replayed.question_id
        and recorded.pool_ids == replayed.pool_ids
        and recorded.index == replayed.index
        and recorded.coverage == replayed.coverage
        and recorded.mode == replayed.mode
    )


def _shuffled(items: Sequence[BankQuestion], seed: int) -> list[BankQuestion]:
    """mulberry32 + Fisher-Yates：同种子同顺序，取前 N 项对 N 稳定（组卷前缀稳定）。"""

    pool = list(items)
    rng = mulberry32(seed)
    for index in range(len(pool) - 1, 0, -1):
        swap = min(int(next(rng) * (index + 1)), index)
        pool[index], pool[swap] = pool[swap], pool[index]
    return pool


def paper_picks(
    topic_id: str, seed: int, count: int, *, bank: QuestionBank | None = None
) -> PaperPick:
    """家长手动组卷：可答题排在前、非可答题补位，取 `count` 道不重复的题。

    同一 `(topic_id, seed, count)` 必得同一张卷；`count` 增大只在原卷后追加。
    """

    if not isinstance(topic_id, str) or not topic_id.strip():
        raise TypeError("topic_id 必须是非空字符串")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed 必须是整数")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count 必须是 ≥1 的整数")

    source = bank if bank is not None else get_bank()
    topic = topic_id.strip()
    full_pool = tuple(sorted(source.questions_for(topic), key=lambda item: item.id))
    if not full_pool:
        return PaperPick(
            topic_id=topic,
            seed=seed,
            requested=count,
            items=(),
            coverage="gap",
            answerable_total=0,
            pool_total=0,
        )

    answerable = tuple(item for item in full_pool if is_answerable(item))
    others = tuple(item for item in full_pool if not is_answerable(item))
    ordered = (
        *_shuffled(answerable, seed),
        *_shuffled(others, seed ^ 0x9E3779B9),
    )
    selected = ordered[:count]
    return PaperPick(
        topic_id=topic,
        seed=seed,
        requested=count,
        items=tuple(
            PaperItem(
                question=question,
                mode="system" if is_answerable(question) else "self_eval",
            )
            for question in selected
        ),
        coverage=_coverage_for(source, full_pool[0]),
        answerable_total=len(answerable),
        pool_total=len(full_pool),
    )


def replay_paper(paper: PaperPick, *, bank: QuestionBank | None = None) -> PaperPick:
    """按记录重算同一张卷；不一致直接失败。

    P3-1c 同 `replay`：按身份（题 id 顺序/模式/池大小）比较，内容修订不回溯。
    """

    again = paper_picks(paper.topic_id, paper.seed, paper.requested, bank=bank)
    if not _same_paper_identity(paper, again):
        raise BankReplayError(
            f"组卷重放不一致：topic={paper.topic_id!r} seed={paper.seed} "
            f"count={paper.requested} recorded={[i.question.id for i in paper.items]!r} "
            f"replayed={[i.question.id for i in again.items]!r}"
        )
    return again


def _same_paper_identity(recorded: PaperPick, replayed: PaperPick) -> bool:
    return (
        recorded.topic_id == replayed.topic_id
        and recorded.seed == replayed.seed
        and recorded.requested == replayed.requested
        and recorded.coverage == replayed.coverage
        and recorded.answerable_total == replayed.answerable_total
        and recorded.pool_total == replayed.pool_total
        and tuple((item.question.id, item.mode) for item in recorded.items)
        == tuple((item.question.id, item.mode) for item in replayed.items)
    )
