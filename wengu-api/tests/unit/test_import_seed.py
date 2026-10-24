"""P1-1b 转换脚本：过滤/标签/字段直映/跨边界丢弃统计。"""

from __future__ import annotations

import json

import pytest
from scripts.import_seed import convert, subject_of, write_out

TOPICS = [
    {"id": "cnm_001", "name": "有理数", "domain": "数与代数", "grade": 7, "semester": "上",
     "chapter": "七上 第1章", "type": "conceptual", "description": "d",
     "mastery_criteria": ["c1"], "diagnostic_question": {"question": "q", "answer": "a"},
     "standards": [{"id": "s", "confidence": "exact"}], "external": False,
     "root_reason": "rr"},
    {"id": "cne_j001", "name": "单词重音", "domain": "语音", "grade": 8, "semester": "上",
     "chapter": "ch", "type": "procedural", "description": "d",
     "mastery_criteria": [], "diagnostic_question": None, "standards": [],
     "external": False, "root_reason": None},
    {"id": "cnp_001", "name": "机械运动", "domain": "运动和相互作用", "grade": 9,
     "semester": "上", "chapter": "ch", "type": "conceptual", "description": "d",
     "mastery_criteria": [], "diagnostic_question": None, "standards": [],
     "external": False, "root_reason": None},
    {"id": "cnm_p001", "name": "小学点", "domain": "数与代数", "grade": 3,
     "semester": "上", "chapter": "ch", "type": "conceptual", "description": "d",
     "mastery_criteria": [], "diagnostic_question": None, "standards": [],
     "external": False, "root_reason": None},
    {"id": "cnm_h001", "name": "高中点", "domain": "数与代数", "grade": 10,
     "semester": "上", "chapter": "ch", "type": "conceptual", "description": "d",
     "mastery_criteria": [], "diagnostic_question": None, "standards": [],
     "external": False, "root_reason": None},
]

DEPS = [
    {"topicId": "cne_j001", "prerequisiteId": "cnm_001", "strength": "hard",
     "reason": "跨学科先修（测试用）"},
    {"topicId": "cnm_001", "prerequisiteId": "cnm_p001", "strength": "soft",
     "reason": "小学先修：应被丢弃"},
    {"topicId": "cnp_001", "prerequisiteId": "cne_j001", "strength": "soft",
     "reason": "r"},
]


@pytest.mark.unit
def test_convert_filters_junior_and_tags() -> None:
    result = convert(TOPICS, DEPS)

    assert result.stats["topics_imported"] == 3
    assert result.stats["topics_by_subject"] == {"数学": 1, "英语": 1, "物理": 1}
    by_id = {t["id"]: t for t in result.topics}

    math = by_id["cnm_001"]
    assert math["subject"] == "数学"
    assert math["unaudited"] is True
    assert math["blind_verified"] is True  # 仅数学二遍盲解
    assert math["root_reason"] == "rr"  # 规格外字段透传进 JSON 不丢信息

    assert by_id["cne_j001"]["blind_verified"] is False
    assert by_id["cnp_001"]["blind_verified"] is False

    assert all(t["grade"] in (7, 8, 9) for t in result.topics)


@pytest.mark.unit
def test_convert_keeps_only_both_endpoints_junior_edges() -> None:
    result = convert(TOPICS, DEPS)
    assert result.stats["dependencies_imported"] == 2
    assert result.stats["dependencies_dropped_cross_boundary"] == 1

    kept = {(e["topic_id"], e["prerequisite_id"]) for e in result.dependencies}
    assert kept == {("cne_j001", "cnm_001"), ("cnp_001", "cne_j001")}
    edge = result.dependencies[0]
    assert set(edge.keys()) == {"topic_id", "prerequisite_id", "strength", "reason"}


@pytest.mark.unit
def test_subject_of_unknown_prefix_raises() -> None:
    with pytest.raises(Exception, match="未知学科前缀"):
        subject_of("xyz_001")


@pytest.mark.unit
def test_write_out_emits_source_attribution(tmp_path) -> None:
    result = convert(TOPICS, DEPS)
    write_out(tmp_path, result, src=tmp_path)  # src 非 git 仓库 → commit 为 None

    source = json.loads((tmp_path / "_source.json").read_text(encoding="utf-8"))
    assert source["upstream_url"] == "https://github.com/xiaoyang111222/cn-math-taxonomy"
    assert source["upstream_license"] == "CC BY-NC 4.0"
    assert "非商用" in source["nc_statement"]
    assert source["counts"]["topics_imported"] == 3
    # 数组按 id 排序，保证产出确定性（git diff 可审）
    topics = json.loads((tmp_path / "topics.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in topics] == sorted(t["id"] for t in topics)
