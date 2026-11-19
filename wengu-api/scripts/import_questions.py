"""P1-10 一次性转换脚本：cn-math-taxonomy questions.json → seeds/data/questions.json。

开发者本地运行（不进容器、不进运行时）：
    cd wengu-api && python -m scripts.import_questions --src ../../cn-math-taxonomy

产出（随仓库分发，CC BY-NC 4.0，questions_source.json 内嵌署名）：
    seeds/data/questions.json          按 --grades 学段带收录的题库（topicId ∈ seeds/data/topics.json）
    seeds/data/questions_source.json   上游 URL / License / NC 声明 / 导入日期 / 计数
    seeds/data/figures_sha256.json     配图逐段 sha256 完整性清单（键=<题 id>:main / <题 id>:choice:<key>）

学段过滤参数驱动（P5-10）：--grades primary,junior,senior 全量；默认 junior（7-9）可复现可回退。
SVG 净化前移到构建期（P5-16 路线 B）：figure 与 choices[].figure 写盘前过 sanitize_svg，
装载侧（app/seed/bank.py）只验 sha256、不再重复净化；家长题路径仍在装载/入库期净化。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.seed.svg import sanitize_svg

UPSTREAM_URL = "https://github.com/xiaoyang111222/cn-math-taxonomy"
UPSTREAM_LICENSE = "CC BY-NC 4.0"
NC_STATEMENT = "限个人非商用：署名 + 非商业使用（CC BY-NC 4.0 §3(a)）"

SUBJECT_BY_PREFIX = {"cnm_": "数学", "cne_": "英语", "cnp_": "物理"}
QUESTION_TYPES = {"choice", "numeric", "short", "self"}
# 学段带（P5-10 参数驱动，与 import_seed.py 同口径）：1-6 小学 / 7-9 初中 / 10-16 高中（"册"）。
GRADE_BANDS = {"primary": range(1, 7), "junior": range(7, 10), "senior": range(10, 17)}
BAND_ORDER = ("primary", "junior", "senior")
BAND_LABEL = {"primary": "小学", "junior": "初中", "senior": "高中"}
DEFAULT_BANDS = ("junior",)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "seeds" / "data"


class QuestionConvertError(ValueError):
    pass


@dataclass
class ConvertResult:
    questions: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    figure_hashes: dict[str, str] = field(default_factory=dict)


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


def parse_bands(spec: str) -> tuple[str, ...]:
    names = [part.strip() for part in spec.split(",") if part.strip()]
    if not names:
        raise QuestionConvertError("--grades 不能为空")
    unknown = sorted(set(names) - set(GRADE_BANDS))
    if unknown:
        raise QuestionConvertError(f"未知学段带: {unknown}（预期 {sorted(GRADE_BANDS)}）")
    return tuple(b for b in BAND_ORDER if b in set(names))


def grades_of(bands: tuple[str, ...]) -> set[int]:
    allowed: set[int] = set()
    for band in bands:
        allowed.update(GRADE_BANDS[band])
    return allowed


def convert(
    questions: list[dict], topics: list[dict], bands: tuple[str, ...] = DEFAULT_BANDS
) -> ConvertResult:
    allowed = grades_of(bands)
    junior = {
        t["id"]: t
        for t in topics
        if isinstance(t, dict) and isinstance(t.get("id"), str) and t.get("grade") in allowed
    }
    by_subject: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    by_band: dict[str, int] = {b: 0 for b in bands}
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
        for band in bands:
            if junior[topic_id].get("grade") in GRADE_BANDS[band]:
                by_band[band] += 1
                break
        if question["difficulty"]:
            by_difficulty[question["difficulty"]] = by_difficulty.get(question["difficulty"], 0) + 1
        with_figure += 1 if question["figure"] else 0
        choice_figures += sum(1 for c in question["choices"] if c.get("figure"))
        with_verify += 1 if question["verify"] else 0

    out.sort(key=lambda q: q["id"])
    figure_hashes: dict[str, str] = {}
    for question in out:
        if question["figure"]:
            figure_hashes[f"{question['id']}:main"] = _sha256(question["figure"])
        for choice in question["choices"]:
            if choice.get("figure"):
                figure_hashes[f"{question['id']}:choice:{choice['key']}"] = _sha256(
                    choice["figure"]
                )
    topics_without = sorted(set(junior) - {q["topic_id"] for q in out})
    return ConvertResult(
        questions=out,
        stats={
            "questions_total_upstream": len(questions),
            "questions_imported": len(out),
            "questions_by_subject": dict(sorted(by_subject.items())),
            "questions_by_type": dict(sorted(by_type.items())),
            "questions_by_difficulty": dict(sorted(by_difficulty.items())),
            "questions_by_band": by_band,
            "grade_bands": list(bands),
            "questions_with_figure": with_figure,
            "choice_figures": choice_figures,
            "figure_segments": len(figure_hashes),
            "questions_with_verify": with_verify,
            "questions_out_of_scope": out_of_scope,
            "topics_referenced": len(junior) - len(topics_without),
            "topics_without_questions": len(topics_without),
        },
        figure_hashes=figure_hashes,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
            choice["figure"] = sanitize_svg(item["figure"])
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
        "figure": sanitize_svg(raw.get("figure")),
        "explanation": raw.get("explanation") if isinstance(raw.get("explanation"), str) else "",
        "verify": verify,
        "percent": raw.get("percent") is True,
        "fixed_from_source": raw.get("fixed_from_source")
        if isinstance(raw.get("fixed_from_source"), str)
        else None,
    }


def upstream_commit(src: Path, override: str | None = None) -> str | None:
    if override:
        return override
    try:
        commit = (
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
        commit = None
    if commit is None:
        print(
            f"警告：{src} 探测不到 git commit（无 .git 或非 git 仓库），upstream_commit 写 null；"
            "zip 来源请显式传 --upstream-commit <sha>，严禁按导入日期猜测。",
            file=sys.stderr,
        )
    return commit


def write_out(
    out_dir: Path, result: ConvertResult, src: Path, commit_override: str | None = None
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    bands = tuple(result.stats.get("grade_bands") or DEFAULT_BANDS)
    allowed = grades_of(bands)
    label = "+".join(BAND_LABEL[b] for b in bands)
    scope = f"grade {min(allowed)}-{max(allowed)}（{label}）"
    name = (
        "cn-math-taxonomy questions（全量：小学+初中+高中）"
        if set(bands) == set(GRADE_BANDS)
        else f"cn-math-taxonomy questions（{label}部分）"
    )
    _write_json(out_dir / "questions.json", result.questions)
    _write_json(
        out_dir / "figures_sha256.json", dict(sorted(result.figure_hashes.items()))
    )
    _write_json(
        out_dir / "questions_source.json",
        {
            "name": name,
            "upstream_url": UPSTREAM_URL,
            "upstream_commit": upstream_commit(src, commit_override),
            "upstream_license": UPSTREAM_LICENSE,
            "nc_statement": NC_STATEMENT,
            "imported_at": date.today().isoformat(),
            "imported_by": "wengu-api/scripts/import_questions.py",
            "filter": (
                f"topicId ∈ seeds/data/topics.json（{label} "
                f"{result.stats.get('topics_referenced', 0) + result.stats.get('topics_without_questions', 0)} 点）"
            ),
            "grade_semantics_note": f"上游 grade 10-16 语义为'册'（高中）；本次收录：{scope}",
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
    parser.add_argument(
        "--upstream-commit",
        default=None,
        help="显式指定上游快照 commit SHA（zip 来源无 .git 时必传；探测失败写 null，不猜）",
    )
    parser.add_argument(
        "--grades",
        default="junior",
        help="学段带逗号分隔：primary,junior,senior（默认 junior=7-9，可复现可回退）",
    )
    args = parser.parse_args(argv)

    if not (args.src / "data" / "questions.json").exists():
        print(f"错误：{args.src} 下找不到 data/questions.json", file=sys.stderr)
        return 1
    if not (args.out / "topics.json").exists():
        print(f"错误：{args.out} 下找不到 topics.json", file=sys.stderr)
        return 1

    bands = parse_bands(args.grades)
    result = convert(load_upstream(args.src), load_topics(args.out), bands=bands)
    write_out(args.out, result, args.src, commit_override=args.upstream_commit)
    print(json.dumps(result.stats, ensure_ascii=False, indent=1))
    print(f"已写入 {args.out / 'questions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
