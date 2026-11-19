"""P5-16 配图完整性守卫（路线 B）：篡改→丢弃+计数 / 缺哈希→丢弃 / 家长题仍净化。

seed 题库净化已前移到构建期，装载侧只验 figures_sha256.json 逐段 sha256；
家长题无构建期哈希可验，装载/入库期净化必须保留（行为 + 源码字面双网）。
断言右侧字面钉死（设计文档 §19-L 纪律①）；变异证伪记录见交付报告。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from app.seed.bank import load_bank
from app.services import bank as runtime_bank
from app.services import bank_import

ROOT = Path(__file__).resolve().parents[3]
REAL_DATA = ROOT / "seeds" / "data"

SVG = '<svg viewBox="0 0 8 8"><rect width="8" height="8"></rect></svg>'
EVIL_SVG = (
    '<svg viewBox="0 0 8 8" onload="alert(1)">'
    '<script>alert(1)</script><rect width="8" height="8"/></svg>'
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _main_question(figure: object = SVG) -> dict:
    return {
        "id": "cnm_001_q1",
        "topic_id": "cnm_001",
        "type": "numeric",
        "prompt": "1+1=?",
        "answer": "2",
        "figure": figure,
    }


def _choice_question(figure: object = SVG) -> dict:
    return {
        "id": "cnm_001_q2",
        "topic_id": "cnm_001",
        "type": "choice",
        "prompt": "选一选",
        "answer": "A",
        "choices": [
            {"key": "A", "text": "对", "figure": figure},
            {"key": "B", "text": "错"},
        ],
    }


def _write_seeds(
    tmp_path: Path, questions: list[dict], hashes: dict[str, str]
) -> Path:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    topics = [{"id": "cnm_001", "subject": "数学", "grade": 7}]
    (data / "topics.json").write_text(json.dumps(topics), encoding="utf-8")
    (data / "questions.json").write_text(
        json.dumps(questions, ensure_ascii=False), encoding="utf-8"
    )
    (data / "figures_sha256.json").write_text(json.dumps(hashes), encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_clean_synthetic_bank_keeps_figures_verbatim(tmp_path: Path) -> None:
    seeds = _write_seeds(
        tmp_path,
        [_main_question(), _choice_question()],
        {"cnm_001_q1:main": _hash(SVG), "cnm_001_q2:choice:A": _hash(SVG)},
    )
    bank = load_bank(seeds)
    assert bank.stats.total == 2
    assert bank.stats.dropped == {}
    assert bank.stats.figures == 2
    assert bank.question("cnm_001_q1").figure == SVG
    assert bank.question("cnm_001_q2").choices[0].figure == SVG


@pytest.mark.unit
@pytest.mark.parametrize("slot", ["main", "choice"])
def test_tampered_figure_drops_whole_question(tmp_path: Path, slot: str) -> None:
    """守卫①：图被改一个字符 → 整题丢弃 + figure_hash_mismatch 计数，绝不静默放行。"""

    question = _main_question() if slot == "main" else _choice_question()
    tampered = SVG + " "
    if slot == "main":
        question["figure"] = tampered
        hashes = {"cnm_001_q1:main": _hash(SVG)}
    else:
        question["choices"][0]["figure"] = tampered
        hashes = {"cnm_001_q2:choice:A": _hash(SVG)}
    bank = load_bank(_write_seeds(tmp_path, [question], hashes))
    assert bank.stats.total == 0
    assert bank.stats.dropped == {"figure_hash_mismatch": 1}
    assert bank.question(question["id"]) is None


@pytest.mark.unit
@pytest.mark.parametrize("slot", ["main", "choice"])
def test_missing_hash_drops_whole_question(tmp_path: Path, slot: str) -> None:
    """守卫②：清单缺该段哈希 → 整题丢弃（fail-closed，不当作无图放行）。"""

    question = _main_question() if slot == "main" else _choice_question()
    bank = load_bank(_write_seeds(tmp_path, [question], {}))
    assert bank.stats.total == 0
    assert bank.stats.dropped == {"figure_hash_mismatch": 1}


@pytest.mark.unit
def test_non_string_figure_with_hash_drops_question(tmp_path: Path) -> None:
    question = _main_question(figure={"svg": SVG})
    hashes = {"cnm_001_q1:main": _hash(SVG)}
    bank = load_bank(_write_seeds(tmp_path, [question], hashes))
    assert bank.stats.dropped == {"figure_hash_mismatch": 1}


@pytest.mark.unit
def test_no_figure_needs_no_hash(tmp_path: Path) -> None:
    question = _main_question(figure=None)
    bank = load_bank(_write_seeds(tmp_path, [question], {}))
    assert bank.stats.total == 1
    assert bank.stats.dropped == {}
    assert bank.question("cnm_001_q1").figure is None


# ---------------------------------------------------------------------------
# 仓内真数据：清单逐段自洽 + 篡改一题只丢一题
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_repo_manifest_covers_every_figure_segment() -> None:
    questions = json.loads((REAL_DATA / "questions.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (REAL_DATA / "figures_sha256.json").read_text(encoding="utf-8")
    )
    slots: dict[str, str] = {}
    for question in questions:
        if question.get("figure"):
            slots[f"{question['id']}:main"] = question["figure"]
        for choice in question.get("choices") or []:
            if choice.get("figure"):
                slots[f"{question['id']}:choice:{choice['key']}"] = choice["figure"]
    assert len(manifest) == 267
    assert set(manifest) == set(slots)
    for key, text in slots.items():
        assert manifest[key] == _hash(text), key


@pytest.mark.unit
def test_repo_tamper_one_figure_drops_exactly_one(tmp_path: Path) -> None:
    questions = json.loads((REAL_DATA / "questions.json").read_text(encoding="utf-8"))
    victim = next(q for q in questions if q.get("figure"))
    victim["figure"] = victim["figure"] + " "
    data = tmp_path / "data"
    data.mkdir()
    shutil.copyfile(REAL_DATA / "topics.json", data / "topics.json")
    shutil.copyfile(REAL_DATA / "figures_sha256.json", data / "figures_sha256.json")
    (data / "questions.json").write_text(
        json.dumps(questions, ensure_ascii=False), encoding="utf-8"
    )
    bank = load_bank(tmp_path)
    assert bank.stats.total == 7430
    assert bank.stats.dropped == {"figure_hash_mismatch": 1}
    assert bank.question(victim["id"]) is None


# ---------------------------------------------------------------------------
# 守卫③：家长题路径净化必须保留（行为 + 源码字面双网）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_runtime_dynamic_choices_still_sanitizes() -> None:
    dropped: dict[str, int] = {}
    raw = json.dumps([{"key": "A", "text": "对", "figure": EVIL_SVG}])
    choices = runtime_bank._dynamic_choices(raw, dropped)
    assert dropped == {}
    assert choices is not None and len(choices) == 1
    figure = choices[0].figure
    assert figure and "<svg" in figure
    assert "<script" not in figure
    assert "onload" not in figure
    assert "alert(" not in figure


@pytest.mark.unit
def test_import_normalize_choices_still_sanitizes() -> None:
    choices, errors = bank_import._normalize_choices(
        0, [{"key": "A", "text": "对", "figure": EVIL_SVG}]
    )
    assert errors == []
    assert len(choices) == 1
    figure = choices[0]["figure"]
    assert figure and "<svg" in figure
    assert "<script" not in figure
    assert "onload" not in figure
    assert "alert(" not in figure


@pytest.mark.unit
def test_parent_question_sanitize_call_sites_unchanged() -> None:
    """源码字面网：删掉家长题任一处 sanitize_svg 调用，本测试必红。"""

    runtime_source = Path(runtime_bank.__file__).read_text(encoding="utf-8")
    assert "figure=sanitize_svg(row.figure)" in runtime_source
    assert "figure=sanitize_svg(item.get(\"figure\"))" in runtime_source
    import_source = Path(bank_import.__file__).read_text(encoding="utf-8")
    assert "sanitized_figure = sanitize_svg(figure)" in import_source
    assert '"figure": sanitize_svg(figure)' in import_source
