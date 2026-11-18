"""P5-14 英文 README 守卫：定位句逐字一致 / 互链双向 / 数字与许可字面。

断言右侧一律字面串钉死（设计文档 §19-L 纪律①），不从被测文件反算期望值；
与中文侧 test_seed_provenance.test_readme_positioning_in_first_lines 同口径。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# 与 README.md 顶部英文定位句逐字一致（两处不许分叉）；写死在测试里，不从盘上反算。
POSITIONING = (
    "**A local-first mistake-review workbench for Chinese junior-high families"
    " (AI transcription as an optional add-on)** — no grading of real homework,"
    " no generated explanations, zero-model core: confirmed mistake intake →"
    " knowledge tagging → cross-subject spaced review → same-type quizzes →"
    " parent dashboard. Every family runs their own instance; data stays local"
    " by default (the optional external transcription step is documented in"
    " [`PRIVACY.md`](./PRIVACY.md))."
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.unit
def test_positioning_keywords_in_first_lines() -> None:
    head = "\n".join(_read("README-en.md").splitlines()[:12])
    for literal in [
        "local-first",
        "no grading of real homework",
        "no generated explanations",
        "zero-model",
    ]:
        assert literal in head


@pytest.mark.unit
def test_no_ai_workbench_claim() -> None:
    assert "AI learning workbench" not in _read("README-en.md")


@pytest.mark.unit
def test_cross_links_both_directions() -> None:
    assert "README-en.md" in _read("README.md")
    assert "README.md" in _read("README-en.md")


@pytest.mark.unit
def test_positioning_sentence_identical_in_both() -> None:
    assert POSITIONING in _read("README.md")
    assert POSITIONING in _read("README-en.md")


@pytest.mark.unit
def test_seed_counts_literals() -> None:
    text = _read("README-en.md")
    for literal in ["1821", "2917", "7431"]:
        assert literal in text


@pytest.mark.unit
def test_license_literals() -> None:
    text = _read("README-en.md")
    for literal in ["MIT", "CC BY-NC 4.0", "non-commercial", "not OSI"]:
        assert literal in text
