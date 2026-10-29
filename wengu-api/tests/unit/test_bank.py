"""P1-10/P1-11 内存题库：倒排、verify 分类、SVG 净化、固定种子检索、组卷与 replay。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.seed.bank import BankFormatError, load_bank
from app.services.bank import (
    BankReplayError,
    find_same_type,
    is_answerable,
    mulberry32,
    paper_picks,
    replay,
    replay_paper,
)

TOPICS = [
    {"id": "cnm_001", "subject": "数学", "name": "有理数", "unaudited": True, "blind_verified": True},
    {"id": "cnm_002", "subject": "数学", "name": "数轴", "unaudited": True, "blind_verified": False},
    {"id": "cnm_009", "subject": "数学", "name": "没有题的点", "unaudited": True},
    {"id": "cnp_001", "subject": "物理", "name": "机械运动", "unaudited": True},
    {"id": "cne_001", "subject": "英语", "name": "单词重音", "unaudited": True},
]

FIGHTING_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    "<script>alert(1)</script>"
    '<rect x="1" y="1" width="2" height="2" onload="alert(2)"/>'
    "</svg>"
)

QUESTIONS = [
    {"id": "cnm_001_q2", "topic_id": "cnm_001", "type": "numeric", "difficulty": "basic",
     "prompt": "2+2=?", "answer": "4", "explanation": "e", "verify": "2+2"},
    {"id": "cnm_001_q1", "topic_id": "cnm_001", "type": "numeric", "difficulty": "basic",
     "prompt": "2+2=?", "answer": "5", "explanation": "e", "verify": "2+2"},
    {"id": "cnm_001_q3", "topic_id": "cnm_001", "type": "numeric", "difficulty": "advanced",
     "prompt": "Fraction", "answer": "1/2", "explanation": "e", "verify": "Fraction(1,2)"},
    {"id": "cnm_002_q1", "topic_id": "cnm_002", "type": "numeric", "difficulty": "basic",
     "prompt": "3", "answer": "3", "explanation": "e"},
    {"id": "cnm_002_q2", "topic_id": "cnm_002", "type": "numeric", "difficulty": "basic",
     "prompt": "带图", "answer": "7", "explanation": "e", "figure": FIGHTING_SVG},
    {"id": "cnp_001_q1", "topic_id": "cnp_001", "type": "numeric", "difficulty": "basic",
     "prompt": "3*3", "answer": "9", "explanation": "e", "verify": "3*3"},
    {"id": "cne_001_q1", "topic_id": "cne_001", "type": "choice", "difficulty": "basic",
     "prompt": "2+2=?", "answer": "B", "explanation": "e", "verify": "2+2",
     "choices": [
         {"key": "A", "text": "1", "figure": FIGHTING_SVG},
         {"key": "B", "text": "4"},
     ]},
    {"id": "cne_001_q2", "topic_id": "cne_001", "type": "choice", "difficulty": "basic",
     "prompt": "速度", "answer": "B", "explanation": "e", "verify": "90",
     "choices": [{"key": "A", "text": "1"}, {"key": "B", "text": "90 min"}]},
    {"id": "cnm_002_q3", "topic_id": "cnm_002", "type": "numeric", "difficulty": "basic",
     "prompt": "缺答案", "answer": "", "explanation": "e"},
    {"id": "cnm_999_q1", "topic_id": "cnm_999", "type": "numeric", "difficulty": "basic",
     "prompt": "未知知识点", "answer": "1", "explanation": "e"},
    {"id": "cne_001_q3", "topic_id": "cne_001", "type": "choice", "difficulty": "basic",
     "prompt": "答案不在选项", "answer": "D", "explanation": "e",
     "choices": [{"key": "A", "text": "1"}]},
    {"id": "cne_001_q4", "topic_id": "cne_001", "type": "essay", "difficulty": "basic",
     "prompt": "非法题型", "answer": "x", "explanation": "e"},
]


def _write_seed(root: Path, topics: list[dict] | None = None, questions: list[dict] | None = None) -> Path:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "topics.json").write_text(
        json.dumps(TOPICS if topics is None else topics, ensure_ascii=False), encoding="utf-8"
    )
    (root / "data" / "questions.json").write_text(
        json.dumps(QUESTIONS if questions is None else questions, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


@pytest.fixture
def bank(tmp_path: Path):
    return load_bank(_write_seed(tmp_path))


@pytest.mark.unit
def test_inverted_index_groups_and_sorts(bank) -> None:
    assert bank.stats.total == 7
    assert bank.stats.topics_with_questions == 4
    assert [q.id for q in bank.questions_for("cnm_001")] == ["cnm_001_q2", "cnm_001_q3"]
    assert bank.questions_for("cnm_009") == ()
    assert bank.stats.by_subject == {"数学": 4, "物理": 1, "英语": 2}
    assert bank.stats.by_type == {"choice": 2, "numeric": 5}


@pytest.mark.unit
def test_verify_gate_classifies_and_drops_numeric_mismatch(bank) -> None:
    assert bank.stats.verified == 3
    assert bank.stats.unverifiable == 4
    assert bank.stats.dropped == {
        "answer_not_in_choices": 1,
        "invalid_answer": 1,
        "invalid_type": 1,
        "unknown_topic": 1,
        "verify_mismatch": 1,
    }
    assert bank.stats.verify_reasons == {
        "choice_text_mismatch": 1,
        "no_verify": 2,
        "sandbox:forbidden_call": 1,
    }
    status = {q.id: (q.verify_status, q.verify_reason) for q in bank.questions_for("cnm_001")}
    assert status["cnm_001_q2"] == ("verified", None)
    assert status["cnm_001_q3"] == ("unverifiable", "sandbox:forbidden_call")


@pytest.mark.unit
def test_svg_sanitized_for_question_and_choice(bank) -> None:
    by_id = {q.id: q for items in bank.by_topic.values() for q in items}
    figure = by_id["cnm_002_q2"].figure
    assert figure is not None and "viewBox" in figure
    assert "<script" not in figure and "onload" not in figure
    assert "alert(1)" not in figure
    choice_figure = by_id["cne_001_q1"].choices[0].figure
    assert choice_figure is not None and "viewBox" in choice_figure
    assert "<script" not in choice_figure and "onload" not in choice_figure
    assert "alert(1)" not in choice_figure


@pytest.mark.unit
def test_find_same_type_is_deterministic_and_replayable(bank) -> None:
    first = find_same_type("cnm_001", 42, bank=bank)
    second = find_same_type("cnm_001", 42, bank=bank)
    assert first == second
    assert first.question_id == "cnm_001_q3"  # 0.6011 * 2 → 下标 1
    assert first.pool_ids == ("cnm_001_q2", "cnm_001_q3")
    assert first.index == 1
    assert first.bank_gap is False
    assert replay(first, bank=bank) == first


@pytest.mark.unit
def test_gap_for_missing_topic(bank) -> None:
    for topic_id in ("cnm_009", "cnm_999", None):
        pick = find_same_type(topic_id, 1, bank=bank)
        assert pick.bank_gap is True
        assert pick.coverage == "gap"
        assert pick.question is None
        assert pick.pool_ids == ()
        assert pick.pool_size == 0
        assert replay(pick, bank=bank) == pick


@pytest.mark.unit
def test_physics_is_flagged_thin(bank) -> None:
    pick = find_same_type("cnp_001", 7, bank=bank)
    assert pick.coverage == "thin"
    assert pick.question is not None


@pytest.mark.unit
def test_replay_fails_when_pool_changes(tmp_path: Path) -> None:
    bank = load_bank(_write_seed(tmp_path / "a"))
    pick = find_same_type("cnm_001", 42, bank=bank)
    changed = [q for q in QUESTIONS if q["id"] != "cnm_001_q3"]
    other = load_bank(_write_seed(tmp_path / "b", questions=changed))
    with pytest.raises(BankReplayError):
        replay(pick, bank=other)


@pytest.mark.unit
def test_seed_and_topic_type_validation(bank) -> None:
    with pytest.raises(TypeError):
        find_same_type("cnm_001", True, bank=bank)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        find_same_type("cnm_001", "42", bank=bank)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        find_same_type(123, 1, bank=bank)  # type: ignore[arg-type]


@pytest.mark.unit
def test_missing_files_tolerated_and_bad_shape_rejected(tmp_path: Path) -> None:
    empty = load_bank(tmp_path)
    assert empty.stats.total == 0
    assert find_same_type("cnm_001", 1, bank=empty).bank_gap is True

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "questions.json").write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(BankFormatError):
        load_bank(tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("seed", "expected"),
    [
        (0, [0.266429208685, 0.000329745701, 0.223272027448]),
        (1, [0.627073940588, 0.002735721180, 0.527447039960]),
        (42, [0.601103751920, 0.448290558998, 0.852465793490]),
        (4294967295, [0.896422614111, 0.189478256740, 0.715652678162]),
    ],
)
def test_mulberry32_matches_js_reference(seed: int, expected: list[float]) -> None:
    rng = mulberry32(seed)
    assert [next(rng) for _ in range(3)] == pytest.approx(expected, rel=1e-12)


@pytest.mark.unit
def test_mulberry32_wraps_like_js_32bit() -> None:
    rng = mulberry32(-1)
    assert next(rng) == pytest.approx(0.896422614111, rel=1e-12)


QUIZ_TOPICS = [
    {"id": "x_self", "subject": "数学", "name": "解答大题"},
    {"id": "x_mix", "subject": "数学", "name": "混合卷"},
]

QUIZ_QUESTIONS = [
    {"id": "x_self_q1", "topic_id": "x_self", "type": "numeric", "prompt": "带图", "answer": "1",
     "figure": FIGHTING_SVG},
    {"id": "x_self_q2", "topic_id": "x_self", "type": "self", "prompt": "说明理由", "answer": "略"},
    {"id": "x_mix_q1", "topic_id": "x_mix", "type": "numeric", "prompt": "1", "answer": "1"},
    {"id": "x_mix_q2", "topic_id": "x_mix", "type": "numeric", "prompt": "2", "answer": "2"},
    {"id": "x_mix_q3", "topic_id": "x_mix", "type": "numeric", "prompt": "带图", "answer": "3",
     "figure": FIGHTING_SVG},
    {"id": "x_mix_q4", "topic_id": "x_mix", "type": "self", "prompt": "说明理由", "answer": "略"},
]


@pytest.fixture
def quiz_bank(tmp_path: Path):
    return load_bank(
        _write_seed(tmp_path / "quiz", topics=QUIZ_TOPICS, questions=QUIZ_QUESTIONS)
    )


@pytest.mark.unit
def test_answerable_requires_objective_type_without_figure(bank, quiz_bank) -> None:
    by_id = {q.id: q for items in quiz_bank.by_topic.values() for q in items}
    assert is_answerable(by_id["x_mix_q1"]) is True
    assert is_answerable(by_id["x_mix_q3"]) is False  # 依赖题图
    assert is_answerable(by_id["x_mix_q4"]) is False  # 解答大题

    source = {q.id: q for items in bank.by_topic.values() for q in items}
    assert is_answerable(source["cnm_002_q2"]) is False
    assert is_answerable(source["cne_001_q1"]) is True  # 选项内联图仍可作答


@pytest.mark.unit
def test_find_same_type_uses_answerable_pool_first(quiz_bank) -> None:
    pick = find_same_type("x_mix", 3, bank=quiz_bank)
    assert pick.mode == "system"
    assert pick.question_id in {"x_mix_q1", "x_mix_q2"}
    assert set(pick.pool_ids) == {"x_mix_q1", "x_mix_q2"}
    assert replay(pick, bank=quiz_bank) == pick


@pytest.mark.unit
def test_find_same_type_falls_back_to_self_eval(quiz_bank) -> None:
    pick = find_same_type("x_self", 7, bank=quiz_bank)
    assert pick.mode == "self_eval"
    assert pick.question is not None
    assert is_answerable(pick.question) is False
    assert replay(pick, bank=quiz_bank) == pick


@pytest.mark.unit
def test_paper_picks_are_deterministic_distinct_and_prefix_stable(quiz_bank) -> None:
    paper = paper_picks("x_mix", 11, 4, bank=quiz_bank)
    assert paper.system_count == 2
    assert paper.self_eval_count == 2
    ids = [item.question.id for item in paper.items]
    assert len(ids) == len(set(ids)) == 4
    assert set(ids[:2]) == {"x_mix_q1", "x_mix_q2"}  # 可答题排在前
    assert paper_picks("x_mix", 11, 4, bank=quiz_bank) == paper
    assert replay_paper(paper, bank=quiz_bank) == paper

    smaller = paper_picks("x_mix", 11, 2, bank=quiz_bank)
    assert [item.question.id for item in smaller.items] == ids[:2]
    assert smaller.system_count == 2


@pytest.mark.unit
def test_paper_picks_mark_self_eval_only_topic(quiz_bank) -> None:
    paper = paper_picks("x_self", 5, 2, bank=quiz_bank)
    assert paper.answerable_total == 0
    assert paper.pool_total == 2
    assert [item.mode for item in paper.items] == ["self_eval", "self_eval"]
    assert paper.coverage == "thin"  # 测试库题量少，覆盖偏薄


@pytest.mark.unit
def test_paper_gap_and_validation(quiz_bank) -> None:
    gap = paper_picks("x_missing", 1, 3, bank=quiz_bank)
    assert gap.bank_gap is True
    assert gap.coverage == "gap"
    assert gap.items == ()
    assert replay_paper(gap, bank=quiz_bank) == gap

    with pytest.raises(TypeError):
        paper_picks("", 1, 1, bank=quiz_bank)
    with pytest.raises(TypeError):
        paper_picks("x_mix", True, 1, bank=quiz_bank)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        paper_picks("x_mix", 1, 0, bank=quiz_bank)


@pytest.mark.unit
def test_paper_replay_fails_when_pool_changes(tmp_path: Path) -> None:
    first = load_bank(
        _write_seed(tmp_path / "a", topics=QUIZ_TOPICS, questions=QUIZ_QUESTIONS)
    )
    changed = [q for q in QUIZ_QUESTIONS if q["id"] != "x_mix_q3"]
    second = load_bank(
        _write_seed(tmp_path / "b", topics=QUIZ_TOPICS, questions=changed)
    )
    paper = paper_picks("x_mix", 11, 4, bank=first)
    with pytest.raises(BankReplayError):
        replay_paper(paper, bank=second)
