"""P1-10/P1-11 同类题检索与组卷：同 topic_id + mulberry32 固定种子，可 replay。

设计文档 §16.D：同类题只按 `primary_topic_id` 检索、每次 1 题；检索不到返回空 +
`bank_gap=true`（P1-7a 据此退回原题重做），绝不让 LLM 编题。P1-11 起"能考就考"：
先取**可自动判分**的题（客观/数值/短答、且不依赖题图），没有才退回非可答题并标记
`mode=self_eval`（纸上做 → 拍已批改 → 自评）。

确定性纪律（AGENTS §5）：mulberry32 与上游 JS 逐位一致（uint32 语义），
同样 `(topic_id, seed)` 在任意进程、任意装载顺序下命中同一题；`replay` / `replay_paper`
重算并校验，数据热更新导致候选池变化时抛 `BankReplayError` 而不是静默换题。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

from app.seed.bank import BankQuestion, QuestionBank, load_bank

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


_CACHE: QuestionBank | None = None


def get_bank() -> QuestionBank:
    """进程内单例索引（JSON 真源，首次调用装载；测试可用 reset_bank_cache）。"""

    global _CACHE
    if _CACHE is None:
        _CACHE = load_bank()
    return _CACHE


def reset_bank_cache() -> None:
    global _CACHE
    _CACHE = None


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
    """按记录重算同一选择；不一致直接失败（确定性回归/申诉用）。"""

    again = find_same_type(pick.topic_id, pick.seed, bank=bank)
    if again != pick:
        raise BankReplayError(
            f"重放不一致：topic={pick.topic_id!r} seed={pick.seed} "
            f"recorded={pick.question_id!r} replayed={again.question_id!r}"
        )
    return again


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
    """按记录重算同一张卷；不一致直接失败。"""

    again = paper_picks(paper.topic_id, paper.seed, paper.requested, bank=bank)
    if again != paper:
        raise BankReplayError(
            f"组卷重放不一致：topic={paper.topic_id!r} seed={paper.seed} "
            f"count={paper.requested} recorded={[i.question.id for i in paper.items]!r} "
            f"replayed={[i.question.id for i in again.items]!r}"
        )
    return again
