"""P1-1b 一次性转换脚本：cn-math-taxonomy 上游 → wengu seeds/data/*.json。

开发者本地运行（不进容器、不进运行时）：
    python wengu-api/scripts/import_seed.py --src D:/MyProducts/StudyDesk/cn-math-taxonomy

产出（随 wengu 仓库分发，CC BY-NC 4.0，内嵌 _source.json 署名）：
    seeds/data/topics.json         按 --grades 学段带收录的知识点，snake_case + subject + 质量标签
    seeds/data/dependencies.json   两端点都在装载集内的先修边（hard/soft）
    seeds/data/_source.json        上游 URL / License / NC 声明 / 导入日期 / 计数与丢弃统计

学段过滤参数驱动（P5-10）：--grades primary,junior,senior 全量；默认 junior（7-9）可复现可回退。
blind_verified 仍只给初中数学（仅该子集做过二遍盲解），扩段不伪造质量标签。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

UPSTREAM_URL = "https://github.com/xiaoyang111222/cn-math-taxonomy"
UPSTREAM_LICENSE = "CC BY-NC 4.0"
NC_STATEMENT = "限个人非商用：署名 + 非商业使用（CC BY-NC 4.0 §3(a)）"

SUBJECT_BY_PREFIX = {
    "cnm_": "数学", "cne_": "英语", "cnp_": "物理", "cnc_": "语文", "cnk_": "化学",
    "cnb_": "生物", "cns_": "科学", "cnd_": "道德与法治", "cnh_": "历史", "cng_": "地理",
}
JUNIOR_GRADES = range(7, 10)
# 学段带（P5-10 参数驱动）：上游 grade 1-6 小学 / 7-9 初中 / 10-16 高中（"册"语义）。
GRADE_BANDS = {"primary": range(1, 7), "junior": range(7, 10), "senior": range(10, 17)}
BAND_ORDER = ("primary", "junior", "senior")
BAND_LABEL = {"primary": "小学", "junior": "初中", "senior": "高中"}
DEFAULT_BANDS = ("junior",)

# 12 个核心字段直映（camelCase→snake_case 后同名）；root_reason 不在规格内，
# 仅透传进 JSON 供回溯诊断参考，装载器不写入数据库。
TOPIC_FIELDS = [
    "id",
    "subject",
    "name",
    "domain",
    "grade",
    "semester",
    "chapter",
    "type",
    "description",
    "mastery_criteria",
    "diagnostic_question",
    "standards",
    "external",
    "root_reason",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = PROJECT_ROOT / "seeds" / "data"


@dataclass
class ConvertResult:
    topics: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def load_upstream(src: Path) -> tuple[list[dict], list[dict]]:
    data = src / "data"
    topics = json.loads((data / "topics.json").read_text(encoding="utf-8"))
    deps = json.loads((data / "dependencies.json").read_text(encoding="utf-8"))
    if not isinstance(topics, list) or not isinstance(deps, list):
        raise SeedConvertError("上游 topics.json / dependencies.json 必须是数组")
    return topics, deps


def subject_of(topic_id: str) -> str:
    for prefix, subject in SUBJECT_BY_PREFIX.items():
        if topic_id.startswith(prefix):
            return subject
    raise SeedConvertError(f"未知学科前缀: {topic_id}（预期 {sorted(SUBJECT_BY_PREFIX)}）")


def parse_bands(spec: str) -> tuple[str, ...]:
    """`--grades primary,junior,senior` → 去重、按学段顺序排列的带名元组。"""

    names = [part.strip() for part in spec.split(",") if part.strip()]
    if not names:
        raise SeedConvertError("--grades 不能为空")
    unknown = sorted(set(names) - set(GRADE_BANDS))
    if unknown:
        raise SeedConvertError(f"未知学段带: {unknown}（预期 {sorted(GRADE_BANDS)}）")
    return tuple(b for b in BAND_ORDER if b in set(names))


def grades_of(bands: tuple[str, ...]) -> set[int]:
    allowed: set[int] = set()
    for band in bands:
        allowed.update(GRADE_BANDS[band])
    return allowed


def convert(
    topics: list[dict], deps: list[dict], bands: tuple[str, ...] = DEFAULT_BANDS
) -> ConvertResult:
    allowed = grades_of(bands)
    junior = [t for t in topics if t.get("grade") in allowed]
    junior_ids = {t["id"] for t in junior}

    out_topics = []
    for t in sorted(junior, key=lambda x: x["id"]):
        subject = subject_of(t["id"])
        out_topics.append(
            {
                "id": t["id"],
                "subject": subject,
                "name": t["name"],
                "domain": t.get("domain"),
                "grade": t.get("grade"),
                "semester": t.get("semester"),
                "chapter": t.get("chapter"),
                "type": t.get("type"),
                "description": t.get("description"),
                "mastery_criteria": t.get("mastery_criteria"),
                "diagnostic_question": t.get("diagnostic_question"),
                "standards": t.get("standards"),
                "external": bool(t.get("external", False)),
                # 质量分档标签：全部未教师审核；仅初中数学做过二遍盲解（mismatch=0）。
                # 扩段后小学/高中数学并未盲解，blind_verified 必须仍只给初中数学（P5-10）。
                "unaudited": True,
                "blind_verified": subject == "数学" and t.get("grade") in JUNIOR_GRADES,
                "root_reason": t.get("root_reason"),
            }
        )

    kept, dropped_cross = [], 0
    for d in sorted(deps, key=lambda x: (x["topicId"], x["prerequisiteId"])):
        if d["topicId"] in junior_ids and d["prerequisiteId"] in junior_ids:
            kept.append(
                {
                    "topic_id": d["topicId"],
                    "prerequisite_id": d["prerequisiteId"],
                    "strength": d.get("strength"),
                    "reason": d.get("reason"),
                }
            )
        elif d["topicId"] in junior_ids:
            dropped_cross += 1  # 先修在小学/高中：不装载，小学阶段成为回溯天然停止点

    by_subject: dict[str, int] = {}
    by_band: dict[str, int] = {b: 0 for b in bands}
    for t in out_topics:
        by_subject[t["subject"]] = by_subject.get(t["subject"], 0) + 1
        for band in bands:
            if t.get("grade") in GRADE_BANDS[band]:
                by_band[band] += 1
                break

    result = ConvertResult(topics=out_topics, dependencies=kept)
    result.stats = {
        "topics_total_upstream": len(topics),
        "topics_imported": len(out_topics),
        "topics_by_subject": by_subject,
        "topics_by_band": by_band,
        "grade_bands": list(bands),
        "dependencies_imported": len(kept),
        "dependencies_dropped_cross_boundary": dropped_cross,
    }
    return result


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
        "cn-math-taxonomy（全量：小学+初中+高中）"
        if set(bands) == set(GRADE_BANDS)
        else f"cn-math-taxonomy（{label}部分）"
    )
    _write_json(out_dir / "topics.json", result.topics)
    _write_json(out_dir / "dependencies.json", result.dependencies)
    _write_json(
        out_dir / "_source.json",
        {
            "name": name,
            "upstream_url": UPSTREAM_URL,
            "upstream_commit": upstream_commit(src, commit_override),
            "upstream_license": UPSTREAM_LICENSE,
            "nc_statement": NC_STATEMENT,
            "imported_at": date.today().isoformat(),
            "imported_by": "wengu-api/scripts/import_seed.py",
            "filter": f"{scope}；dependencies 仅保留两端点均在装载集内的边",
            "grade_semantics_note": f"上游 grade 10-16 语义为'册'（高中）；本次收录：{scope}",
            "counts": result.stats,
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


class SeedConvertError(ValueError):
    pass


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

    if not (args.src / "data" / "topics.json").exists():
        print(f"错误：{args.src} 下找不到 data/topics.json", file=sys.stderr)
        return 1

    bands = parse_bands(args.grades)
    result = convert(*load_upstream(args.src), bands=bands)
    write_out(args.out, result, args.src, commit_override=args.upstream_commit)
    print(json.dumps(result.stats, ensure_ascii=False, indent=1))
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
