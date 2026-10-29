"""P1-10 一次性转换脚本：cn-math-taxonomy questions.json → seeds/data/questions.json。

开发者本地运行（不进容器、不进运行时）：
    python wengu-api/scripts/import_questions.py --src D:/MyProducts/StudyDesk/cn-math-taxonomy-main

产出（随仓库分发，CC BY-NC 4.0，questions_source.json 内嵌署名）：
    seeds/data/questions.json          初中段题库（topicId ∈ seeds/data/topics.json）
    seeds/data/questions_source.json   上游 URL / License / NC 声明 / 导入日期 / 计数
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

UPSTREAM_URL = "https://github.com/xiaoyang111222/cn-math-taxonomy"
UPSTREAM_LICENSE = "CC BY-NC 4.0"
NC_STATEMENT = "限个人非商用：署名 + 非商业使用（CC BY-NC 4.0 §3(a)）"

SUBJECT_BY_PREFIX = {"cnm_": "数学", "cne_": "英语", "cnp_": "物理"}
QUESTION_TYPES = {"choice", "numeric", "short", "self"}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "seeds" / "data"


class QuestionConvertError(ValueError):
    pass


@dataclass
class ConvertResult:
    questions: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def load_upstream(src: Path) -> list[dict]:
    path = src / "data" / "questions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise QuestionConvertError("上游 questions.json 必须是数组")
    return data


def load_topics(out_dir: Path) -> list[dict]:
    path = out_dir / "topics.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise QuestionConvertError("seeds/data/topics.json 必须是数组")
    return data


def subject_of(topic_id: str) -> str:
    for prefix, subject in SUBJECT_BY_PREFIX.items():
        if topic_id.startswith(prefix):
            return subject
    raise QuestionConvertError(f"未知学科前缀: {topic_id}（预期 {sorted(SUBJECT_BY_PREFIX)}）")


def convert(questions: list[dict], topics: list[dict]) -> ConvertResult:
    junior = {t["id"]: t for t in topics if isinstance(t, dict) and isinstance(t.get("id"), str)}
    by_subject: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    out: list[dict] = []
    out_of_scope = 0
    with_figure = choice_figures = with_verify = 0

    for raw in questions:
        topic_id = raw.get("topicId")
        if topic_id not in junior:
            out_of_scope += 1
            continue
        question = _convert_question(raw, junior[topic_id])
        out.append(question)
        by_subject[question["subject"]] = by_subject.get(question["subject"], 0) + 1
        by_type[question["type"]] = by_type.get(question["type"], 0) + 1
        if question["difficulty"]:
            by_difficulty[question["difficulty"]] = by_difficulty.get(question["difficulty"], 0) + 1
        with_figure += 1 if question["figure"] else 0
        choice_figures += sum(1 for c in question["choices"] if c.get("figure"))
        with_verify += 1 if question["verify"] else 0

    out.sort(key=lambda q: q["id"])
    topics_without = sorted(set(junior) - {q["topic_id"] for q in out})
    return ConvertResult(
        questions=out,
        stats={
            "questions_total_upstream": len(questions),
            "questions_imported": len(out),
            "questions_by_subject": dict(sorted(by_subject.items())),
            "questions_by_type": dict(sorted(by_type.items())),
            "questions_by_difficulty": dict(sorted(by_difficulty.items())),
            "questions_with_figure": with_figure,
            "choice_figures": choice_figures,
            "questions_with_verify": with_verify,
            "questions_out_of_scope": out_of_scope,
            "topics_referenced": len(junior) - len(topics_without),
            "topics_without_questions": len(topics_without),
        },
    )


def _convert_question(raw: dict, topic: dict) -> dict:
    question_id = raw.get("id")
    topic_id = raw.get("topicId")
    if not isinstance(question_id, str) or not question_id:
        raise QuestionConvertError(f"题目缺少 id: {raw!r:.120}")
    if not isinstance(topic_id, str) or not topic_id:
        raise QuestionConvertError(f"题目 {question_id} 缺少 topicId")
    for key in ("prompt", "answer"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise QuestionConvertError(f"题目 {question_id} 的 {key} 必须是非空字符串")
    question_type = raw.get("type")
    if question_type not in QUESTION_TYPES:
        raise QuestionConvertError(f"题目 {question_id} 的 type 非法: {question_type!r}")

    accept = raw.get("accept") or []
    if not isinstance(accept, list) or any(not isinstance(item, str) for item in accept):
        raise QuestionConvertError(f"题目 {question_id} 的 accept 必须是字符串数组")
    choices_raw = raw.get("choices") or []
    if not isinstance(choices_raw, list):
        raise QuestionConvertError(f"题目 {question_id} 的 choices 必须是数组")
    choices = []
    for item in choices_raw:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise QuestionConvertError(f"题目 {question_id} 的选项结构非法")
        if not isinstance(item.get("text"), str):
            raise QuestionConvertError(f"题目 {question_id} 的选项缺少 text")
        choice = {"key": item["key"], "text": item["text"]}
        if item.get("figure") is not None:
            choice["figure"] = item["figure"]
        choices.append(choice)
    if question_type == "choice" and raw.get("answer") not in {c["key"] for c in choices}:
        raise QuestionConvertError(f"题目 {question_id} 的 answer 不在选项 key 中")

    verify = raw.get("verify")
    if verify is not None and not isinstance(verify, str):
        raise QuestionConvertError(f"题目 {question_id} 的 verify 必须是字符串")

    return {
        "id": question_id,
        "topic_id": topic_id,
        "subject": subject_of(topic_id),
        "unaudited": bool(topic.get("unaudited", True)),
        "blind_verified": bool(topic.get("blind_verified", False)),
        "type": question_type,
        "difficulty": raw.get("difficulty") if isinstance(raw.get("difficulty"), str) else None,
        "prompt": raw["prompt"],
        "answer": raw["answer"],
        "accept": list(accept),
        "choices": choices,
        "unordered": raw.get("unordered") is True,
        "hide_choice_text": raw.get("hideChoiceText") is True,
        "figure": raw.get("figure"),
        "explanation": raw.get("explanation") if isinstance(raw.get("explanation"), str) else "",
        "verify": verify,
        "percent": raw.get("percent") is True,
        "fixed_from_source": raw.get("fixed_from_source")
        if isinstance(raw.get("fixed_from_source"), str)
        else None,
    }


def upstream_commit(src: Path) -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "-C", str(src), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
            or None
        )
    except OSError:
        return None


def write_out(out_dir: Path, result: ConvertResult, src: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "questions.json", result.questions)
    _write_json(
        out_dir / "questions_source.json",
        {
            "name": "cn-math-taxonomy questions（初中部分）",
            "upstream_url": UPSTREAM_URL,
            "upstream_commit": upstream_commit(src),
            "upstream_license": UPSTREAM_LICENSE,
            "nc_statement": NC_STATEMENT,
            "imported_at": date.today().isoformat(),
            "imported_by": "wengu-api/scripts/import_questions.py",
            "filter": "topicId ∈ seeds/data/topics.json（初中 664 点）",
            "counts": result.stats,
        },
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, required=True, help="cn-math-taxonomy 仓库路径")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录")
    args = parser.parse_args(argv)

    if not (args.src / "data" / "questions.json").exists():
        print(f"错误：{args.src} 下找不到 data/questions.json", file=sys.stderr)
        return 1
    if not (args.out / "topics.json").exists():
        print(f"错误：{args.out} 下找不到 topics.json", file=sys.stderr)
        return 1

    result = convert(load_upstream(args.src), load_topics(args.out))
    write_out(args.out, result, args.src)
    print(json.dumps(result.stats, ensure_ascii=False, indent=1))
    print(f"已写入 {args.out / 'questions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
