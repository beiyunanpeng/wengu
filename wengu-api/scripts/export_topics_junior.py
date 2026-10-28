"""从已过滤的初中 seed `seeds/data/topics.json` 导出**外部转录模板用的知识点目录** TSV。

用途：`docs/templates/doubao_transcribe_v1.md` 让豆包/千问办公为每题选 `suggested_topic_id`
时，需要一份紧凑的"知识点 id + 名称"清单。本脚本**只做只读投影**——
过滤（grade 7–9）与学科映射已在 P1-1b 的 import_seed.py 完成，这里不重造逻辑。

开发者本地运行（不进容器、不进运行时）：
    python wengu-api/scripts/export_topics_junior.py
    # 可选：--src <seeds/data/topics.json>  --out <docs/templates/topics_junior.tsv>

产出：docs/templates/topics_junior.tsv（UTF-8 无 BOM，制表符分隔，含表头）
列： topic_id | subject | grade | semester | name | domain | chapter
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = PROJECT_ROOT / "seeds" / "data" / "topics.json"
DEFAULT_OUT = PROJECT_ROOT / "docs" / "templates" / "topics_junior.tsv"

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


def export(src: Path, out: Path) -> dict[str, int]:
    topics = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(topics, list) or not topics:
        raise ValueError(f"{src} 应是非空 JSON 数组（先运行 import_seed.py 生成 seed）")

    rows = build_rows(topics)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(COLUMNS)] + ["\t".join(r) for r in rows]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")  # 无 BOM

    by_subject: dict[str, int] = {}
    for r in rows:
        by_subject[r[1]] = by_subject.get(r[1], 0) + 1
    return by_subject


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="初中 topics.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 TSV 路径")
    args = parser.parse_args(argv)

    if not args.src.exists():
        print(f"错误：找不到 {args.src}\n（请先运行 wengu-api/scripts/import_seed.py 生成 seed）", file=sys.stderr)
        return 1

    by_subject = export(args.src, args.out)
    total = sum(by_subject.values())
    print(json.dumps({"total": total, "by_subject": by_subject}, ensure_ascii=False))
    print(f"已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
