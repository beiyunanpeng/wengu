"""合并小学、初中正文、初中补充块与高中官方词表。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    from scripts.vocab_extract import SeedConvertError
except ModuleNotFoundError:
    try:
        from vocab_extract import SeedConvertError
    except ModuleNotFoundError:
        from __init__ import SeedConvertError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_UPSTREAM = PROJECT_ROOT / "seeds" / "vocab" / "_upstream"
DEFAULT_OUTPUT = PROJECT_ROOT / "seeds" / "vocab" / "levels.json"
STAGE_ORDER = ("primary", "junior", "senior")


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SeedConvertError(f"词表输入读取失败：{path}") from exc
    if not isinstance(data, dict):
        raise SeedConvertError(f"词表输入必须是 JSON object：{path}")
    return data


def _sorted_forms(forms: set[str]) -> list[str]:
    return sorted(forms, key=lambda value: (value.casefold(), value))


def build_levels(primary: dict, junior: dict, senior: dict, supplement: dict) -> dict:
    merged: dict[str, dict] = {}

    def add(word: str, word_forms: list[str], stage: str, tier: str | None = None, block: str | None = None) -> None:
        word = word.strip()
        if not word:
            raise SeedConvertError("levels 不接受空 word")
        row = merged.setdefault(
            word,
            {
                "word": word,
                "forms": set(),
                "stages": set(),
                "senior_tier": None,
                "block": None,
                "unaudited": False,
            },
        )
        row["forms"].update(word_forms)
        row["forms"].add(word)
        row["forms"].add(word.lower())
        row["stages"].add(stage)
        if stage == "senior" and tier:
            row["senior_tier"] = tier
        if block:
            row["block"] = block
            row["unaudited"] = True

    primary_forms = primary.get("forms") or {}
    for word in primary["words"]:
        add(word, list(primary_forms.get(word) or []), "primary")
    for entry in junior["words"]:
        add(entry["word"], list(entry["forms"]), "junior")
    for entry in senior["words"]:
        add(entry["word"], list(entry["forms"]), "senior", entry.get("tier"))
    for entry in supplement["words"]:
        add(entry["word"], [entry["word"]], "junior", block=entry["category"])

    rows = []
    for row in merged.values():
        rows.append(
            {
                "word": row["word"],
                "forms": _sorted_forms(row["forms"]),
                "stages": [stage for stage in STAGE_ORDER if stage in row["stages"]],
                "senior_tier": row["senior_tier"],
                "block": row["block"],
                "unaudited": row["unaudited"],
            }
        )
    rows.sort(key=lambda row: (row["word"].casefold(), row["word"]))
    stage_counts = Counter(stage for row in rows for stage in row["stages"])
    counts = {
        "union": len(rows),
        "primary": stage_counts["primary"],
        "junior": stage_counts["junior"],
        "senior": stage_counts["senior"],
        "supplement": sum(row["block"] is not None for row in rows),
    }
    return {
        "meta": {
            "scope": "wengu 英语背诵 K-12 范围 base（小学-初中-高中封顶）",
            "sources": {
                "primary": "vickysy/kebiao-english 小学二级（official-repo，MIT）",
                "junior": "正文 derived-from-transcription；补充块 OCR + unaudited",
                "senior": "普通高中英语课程标准 2017版2020修订（official-pdf-verbatim）",
            },
            "counts": counts,
            "normalization": "word 保留官方标注形态与大小写；仅合并完全相同的 word",
            "join": "ECDICT 整串精确 → 拆等价子形逐形精确",
        },
        "words": rows,
    }


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=DEFAULT_UPSTREAM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        document = build_levels(
            _load(args.upstream / "vocab-level2.json"),
            _load(args.upstream / "kebiao-level3-1600.json"),
            _load(args.upstream / "gsenior-2020-OFFICIAL.json"),
            _load(args.upstream / "kebiao-junior-supplement.json"),
        )
        _write_json(args.output, document)
    except (OSError, KeyError, TypeError, SeedConvertError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(document["meta"]["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
