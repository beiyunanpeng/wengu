"""P1-10 题库转换脚本：学段过滤（P5-10 参数驱动，默认 junior）、字段直映、配图计数与署名文件。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.import_questions import (
    QuestionConvertError,
    convert,
    load_topics,
    load_upstream,
    parse_bands,
    subject_of,
    write_out,
)

TOPICS = [
    {"id": "cnm_001", "subject": "数学", "name": "有理数", "grade": 7, "unaudited": True, "blind_verified": True},
    {"id": "cne_j001", "subject": "英语", "name": "单词重音", "grade": 7, "unaudited": True, "blind_verified": False},
]

QUESTIONS = [
    {
        "id": "cnm_001_q2",
        "topicId": "cnm_001",
        "difficulty": "basic",
        "type": "numeric",
        "prompt": "2+2=?",
        "answer": "4",
        "explanation": "因为 2+2=4。",
        "verify": "2+2",
        "accept": ["4.0"],
        "unordered": True,
    },
    {
        "id": "cnm_001_q1",
        "topicId": "cnm_001",
        "difficulty": "basic",
        "type": "choice",
        "prompt": "哪个是偶数？",
        "answer": "A",
        "explanation": "2 是偶数。",
        "hideChoiceText": True,
        "figure": "<svg></svg>",
        "choices": [
            {"key": "A", "text": "2", "figure": "<svg></svg>"},
            {"key": "B", "text": "3"},
        ],
        "percent": True,
    },
    {
        "id": "cne_j001_q1",
        "topicId": "cne_j001",
        "difficulty": "basic",
        "type": "short",
        "prompt": "重音在哪？",
        "answer": "第一音节",
        "explanation": "teacher 重音在第一音节。",
        "fixed_from_source": "补条件",
    },
    {"id": "cnm_p001_q1", "topicId": "cnm_p001", "type": "numeric", "prompt": "小学题", "answer": "1"},
]


@pytest.mark.unit
def test_convert_filters_and_maps_fields() -> None:
    result = convert(QUESTIONS, TOPICS)

    assert result.stats["questions_total_upstream"] == 4
    assert result.stats["questions_imported"] == 3
    assert result.stats["questions_out_of_scope"] == 1
    assert result.stats["questions_by_subject"] == {"数学": 2, "英语": 1}
    assert result.stats["questions_by_type"] == {"choice": 1, "numeric": 1, "short": 1}
    assert result.stats["questions_with_figure"] == 1
    assert result.stats["choice_figures"] == 1
    assert result.stats["questions_with_verify"] == 1
    assert result.stats["topics_without_questions"] == 0
    assert [q["id"] for q in result.questions] == ["cne_j001_q1", "cnm_001_q1", "cnm_001_q2"]

    by_id = {q["id"]: q for q in result.questions}
    numeric = by_id["cnm_001_q2"]
    assert numeric["topic_id"] == "cnm_001"
    assert numeric["subject"] == "数学"
    assert numeric["blind_verified"] is True
    assert numeric["accept"] == ["4.0"]
    assert numeric["unordered"] is True
    assert numeric["hide_choice_text"] is False
    assert numeric["percent"] is False
    assert numeric["fixed_from_source"] is None

    choice = by_id["cnm_001_q1"]
    assert choice["hide_choice_text"] is True
    assert choice["percent"] is True
    assert choice["choices"][0]["figure"] == "<svg></svg>"

    short = by_id["cne_j001_q1"]
    assert short["subject"] == "英语"
    assert short["fixed_from_source"] == "补条件"


@pytest.mark.unit
def test_subject_of_rejects_unknown_prefix() -> None:
    assert subject_of("cnm_001") == "数学"
    with pytest.raises(QuestionConvertError):
        subject_of("xx_001")


@pytest.mark.unit
def test_convert_rejects_malformed_question() -> None:
    broken = [{"id": "cnm_001_q1", "topicId": "cnm_001", "type": "numeric", "prompt": "", "answer": "1"}]
    with pytest.raises(QuestionConvertError):
        convert(broken, TOPICS)


@pytest.mark.unit
def test_write_out_writes_data_and_attribution(tmp_path: Path) -> None:
    src = tmp_path / "upstream"
    (src / "data").mkdir(parents=True)
    (src / "data" / "questions.json").write_text(
        json.dumps(QUESTIONS, ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "seeds" / "data"
    out.mkdir(parents=True)
    (out / "topics.json").write_text(json.dumps(TOPICS, ensure_ascii=False), encoding="utf-8")

    result = convert(load_upstream(src), load_topics(out))
    write_out(out, result, src)

    questions = json.loads((out / "questions.json").read_text(encoding="utf-8"))
    source = json.loads((out / "questions_source.json").read_text(encoding="utf-8"))
    assert len(questions) == 3
    assert source["upstream_license"] == "CC BY-NC 4.0"
    assert source["upstream_url"] == "https://github.com/xiaoyang111222/cn-math-taxonomy"
    assert "非商业" in source["nc_statement"]
    assert source["counts"]["questions_imported"] == 3


@pytest.mark.unit
def test_convert_bands_parameter_drives_scope() -> None:
    """P5-10：收录范围由 bands 参数驱动（默认 junior）；无 grade 的点全量也不收录。"""

    topics = [
        {"id": "cnm_p001", "subject": "数学", "name": "小学点", "grade": 3},
        {"id": "cnm_001", "subject": "数学", "name": "初中点", "grade": 7},
        {"id": "cnm_s001", "subject": "数学", "name": "高中点", "grade": 10},
        {"id": "cnm_x001", "subject": "数学", "name": "无学段点"},
    ]
    questions = [
        {"id": f"{t['id']}_q1", "topicId": t["id"], "type": "numeric", "prompt": "1+1=?", "answer": "2"}
        for t in topics
    ]

    junior = convert(questions, topics)
    assert [q["id"] for q in junior.questions] == ["cnm_001_q1"]
    assert junior.stats["questions_out_of_scope"] == 3

    full = convert(questions, topics, bands=("primary", "junior", "senior"))
    assert [q["id"] for q in full.questions] == ["cnm_001_q1", "cnm_p001_q1", "cnm_s001_q1"]
    assert full.stats["questions_by_band"] == {"primary": 1, "junior": 1, "senior": 1}
    assert full.stats["questions_out_of_scope"] == 1


@pytest.mark.unit
def test_parse_bands_normalizes_and_rejects_unknown() -> None:
    assert parse_bands("senior,primary") == ("primary", "senior")
    with pytest.raises(QuestionConvertError):
        parse_bands("kindergarten")
    with pytest.raises(QuestionConvertError):
        parse_bands("  ")
