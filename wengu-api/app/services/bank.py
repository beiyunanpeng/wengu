"""P1-10 同类题检索：同 topic_id + mulberry32 固定种子，固定种子可 replay。

设计文档 §16.D：同类题只按 `primary_topic_id` 检索、每次 1 题；检索不到返回空 +
`bank_gap=true`（P1-7a 据此退回原题重做），绝不让 LLM 编题。

确定性纪律（AGENTS §5）：mulberry32 与上游 JS 逐位一致（uint32 语义），
同样 `(topic_id, seed)` 在任意进程、任意装载顺序下命中同一题；`replay(pick)`
重算并校验，数据热更新导致候选池变化时抛 `BankReplayError` 而不是静默换题。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from app.seed.bank import BankQuestion, QuestionBank, load_bank

# 学科题量低于该阈值视为"覆盖薄"（§5 反虚假精确：样本不足不吹保证）。
# 现状：数学 1407 / 英语 1028 正常，物理 368 薄；语文/化学无题 → gap。
THIN_SUBJECT_QUESTIONS = 500

Coverage = Literal["ok", "thin", "gap"]


class BankReplayError(RuntimeError):
    """重放结果与记录不一致（题库被替换/数据漂移），交给上层告警而不是换题。"""


@dataclass(frozen=True)
class BankPick:
    topic_id: str | None
    seed: int
    question: BankQuestion | None
    pool_ids: tuple[str, ...]
    index: int | None
    coverage: Coverage

    @property
    def bank_gap(self) -> bool:
        return self.coverage == "gap"

    @property
    def pool_size(self) -> int:
        return len(self.pool_ids)

    @property
    def question_id(self) -> str | None:
        return self.question.id if self.question is not None else None


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


def find_same_type(
    primary_topic_id: str | None, seed: int, *, bank: QuestionBank | None = None
) -> BankPick:
    """按主考点取 1 道同类题；无题知识点返回空 pick + `bank_gap=true`。"""

    if primary_topic_id is not None and not isinstance(primary_topic_id, str):
        raise TypeError("primary_topic_id 必须是字符串或 None")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed 必须是整数")

    source = bank if bank is not None else get_bank()
    topic_id = primary_topic_id.strip() if primary_topic_id else ""
    pool = (
        tuple(sorted(source.questions_for(topic_id), key=lambda item: item.id))
        if topic_id
        else ()
    )
    if not pool:
        return BankPick(
            topic_id=topic_id or None,
            seed=seed,
            question=None,
            pool_ids=(),
            index=None,
            coverage="gap",
        )

    index = int(next(mulberry32(seed)) * len(pool))
    index = min(index, len(pool) - 1)
    subject_total = source.stats.by_subject.get(pool[0].subject, len(pool))
    coverage: Coverage = "thin" if subject_total < THIN_SUBJECT_QUESTIONS else "ok"
    return BankPick(
        topic_id=topic_id,
        seed=seed,
        question=pool[index],
        pool_ids=tuple(item.id for item in pool),
        index=index,
        coverage=coverage,
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
