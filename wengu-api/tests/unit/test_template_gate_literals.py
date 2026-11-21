"""P3-5 折入轮回退守卫：转录模板 v4 的指令级字面钉死（纯文本，不建库、不联网）。

守四件事：
1. 「不进本」两条口径 bullet 字面在场（删任一条即红）；
2. subject / 前缀两张硬编码清单字面不得回潮；
3. frontmatter version 字面 == 4，且《知识点目录》仍指向 topics_junior.tsv；
4. 示例 JSON 至少含一条 cnc_ 开头的 suggested_topic_id（语文 few-shot 防删）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = REPO_ROOT / "docs" / "templates" / "doubao_transcribe_v1.md"


def _template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_gate_bullets_present() -> None:
    text = _template()
    assert "不进错题本的题一律不转录" in text
    assert "独立可判分短小题照旧转录" in text


def test_no_hardcoded_subject_or_prefix_lists() -> None:
    text = _template()
    assert "数学 | 英语 | 语文 | 物理 | 化学" not in text
    assert "cnm_*/cne_*/cnp_*" not in text


def test_version_literal_and_catalog_pointer() -> None:
    text = _template()
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    version_lines = [line for line in frontmatter.splitlines() if line.startswith("version:")]
    assert version_lines == ["version: 4"]
    assert "《知识点目录》" in text
    assert "topics_junior.tsv" in text


def test_yuwen_example_present() -> None:
    text = _template()
    ids = re.findall(r'"suggested_topic_id"\s*:\s*"([^"]+)"', text)
    assert any(tid.startswith("cnc_") for tid in ids)
