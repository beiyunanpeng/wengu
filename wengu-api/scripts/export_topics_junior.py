"""导出**外部转录模板用的知识点目录** TSV（仓库 seed + 家长本地自建 seed 合并）。

用途：`docs/templates/doubao_transcribe_v1.md` 让豆包/千问办公为每题选 `suggested_topic_id`
时，需要一份紧凑的"知识点 id + 名称"清单。本脚本**只做只读投影**——
过滤（grade 7–9）与学科映射已在 P1-1b 的 import_seed.py 完成，这里不重造逻辑。

本地自建 seed（语文 `cnl_` / 化学 `cnc_`）按装载器同一顺序合并：
    seeds/local/*.json（开发机）→ <data_dir>/seeds_local/*.json（家长运行时）
坏文件跳过、id 冲突跳过并告警；`seeds/data/topics.json` 只读不改。

开发者本地运行（不进容器、不进运行时）：
    python wengu-api/scripts/export_topics_junior.py
    # 可选：--src <seeds/data/topics.json>  --out <docs/templates/topics_junior.tsv>
    #       --local <额外本地目录，可重复>  --data-dir <运行时 data 目录>

产出：docs/templates/topics_junior.tsv（UTF-8 无 BOM，制表符分隔，含表头）
列： topic_id | subject | grade | semester | name | domain | chapter
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SRC = PROJECT_ROOT / "seeds" / "data" / "topics.json"
DEFAULT_LOCAL_DIR = PROJECT_ROOT / "seeds" / "local"
DEFAULT_DATA_DIR = Path(os.environ.get("WENGU_DATA_DIR", API_DIR / "data"))
DEFAULT_OUT = PROJECT_ROOT / "docs" / "templates" / "topics_junior.tsv"

LOCAL_SUBJECT_PREFIXES = {"语文": "cnl_", "化学": "cnc_"}

COLUMNS = ["topic_id", "subject", "grade", "semester", "name", "domain", "chapter"]


def _cell(value: object) -> str:
    """TSV 单元格清洗：None→空串，去制表符/换行，首尾去空白。"""
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def build_rows(topics: list[dict]) -> list[list[str]]:
    # 排序：学科 → 年级 → id，方便人工与模型按教材顺序浏览
    ordered = sorted(
        topics,
        key=lambda t: (str(t.get("subject", "")), t.get("grade", 0), str(t.get("id", ""))),
    )
    rows: list[list[str]] = []
    for t in ordered:
        rows.append(
            [
                _cell(t.get("id")),
                _cell(t.get("subject")),
                _cell(t.get("grade")),
                _cell(t.get("semester")),
                _cell(t.get("name")),
                _cell(t.get("domain")),
                _cell(t.get("chapter")),
            ]
        )
    return rows


def _local_files(directories: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for directory in directories:
        if not Path(directory).is_dir():
            continue
        for path in sorted(Path(directory).glob("*.json")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(path)
    return files


def load_local_topics(directories: list[Path], taken_ids: set[str]) -> tuple[list[dict], list[str]]:
    """读取本地 seed；坏文件/坏条目/冲突 id 跳过并返回告警（与运行时装载器同语义）。"""

    topics: list[dict] = []
    warnings: list[str] = []
    for path in _local_files(directories):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"跳过本地 seed 文件 {path}：{exc}")
            continue
        if not isinstance(raw, list):
            warnings.append(f"跳过本地 seed 文件 {path}：根节点必须是数组")
            continue
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                warnings.append(f"跳过本地条目（{path.name}）：缺少字符串 id")
                continue
            subject = item.get("subject")
            prefix = LOCAL_SUBJECT_PREFIXES.get(subject) if isinstance(subject, str) else None
            if prefix is None or not isinstance(item.get("name"), str):
                warnings.append(f"跳过本地条目 {item['id']}（{path.name}）：学科/名称非法")
                continue
            if not item["id"].startswith(prefix):
                warnings.append(
                    f"跳过本地条目 {item['id']}（{path.name}）：id 必须以 {prefix} 开头"
                )
                continue
            if item["id"] in taken_ids:
                warnings.append(f"本地 seed id 冲突，已跳过：{item['id']}（{path.name}）")
                continue
            taken_ids.add(item["id"])
            topics.append(item)
    return topics, warnings


def load_topics(src: Path, local_dirs: list[Path] | None = None) -> tuple[list[dict], list[str]]:
    topics = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(topics, list) or not topics:
        raise ValueError(f"{src} 应是非空 JSON 数组（先运行 import_seed.py 生成 seed）")

    taken = {str(t.get("id")) for t in topics if isinstance(t, dict)}
    local_topics, warnings = load_local_topics(local_dirs or [], taken)
    return [*topics, *local_topics], warnings


def export(src: Path, out: Path, local_dirs: list[Path] | None = None) -> dict[str, int]:
    topics, warnings = load_topics(src, local_dirs)
    for message in warnings:
        print(f"警告：{message}", file=sys.stderr)

    rows = build_rows(topics)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(COLUMNS)] + ["\t".join(r) for r in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")  # 无 BOM

    by_subject: dict[str, int] = {}
    for r in rows:
        by_subject[r[1]] = by_subject.get(r[1], 0) + 1
    return by_subject


def _local_directories(args: argparse.Namespace) -> list[Path]:
    directories = [DEFAULT_LOCAL_DIR, Path(args.data_dir) / "seeds_local"]
    directories.extend(args.local or [])
    return directories


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="初中 topics.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 TSV 路径")
    parser.add_argument(
        "--local", type=Path, action="append", default=None, help="额外本地 seed 目录（可重复）"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="运行时 data 目录（读 seeds_local/）"
    )
    args = parser.parse_args(argv)

    if not args.src.exists():
        print(f"错误：找不到 {args.src}\n（请先运行 wengu-api/scripts/import_seed.py 生成 seed）", file=sys.stderr)
        return 1

    by_subject = export(args.src, args.out, _local_directories(args))
    total = sum(by_subject.values())
    print(json.dumps({"total": total, "by_subject": by_subject}, ensure_ascii=False))
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
