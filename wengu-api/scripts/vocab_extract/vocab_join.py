"""按“整串精确 → 拆等价子形逐形精确”把 levels  joined 到 ECDICT。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    from scripts.vocab_extract import SeedConvertError
except ModuleNotFoundError:
    try:
        from vocab_extract import SeedConvertError
    except ModuleNotFoundError:
        from __init__ import SeedConvertError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEVELS = PROJECT_ROOT / "seeds" / "vocab" / "levels.json"
DEFAULT_ECDICT = PROJECT_ROOT.parent / "vocab-fetch" / "ECDICT" / "ecdict.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "seeds" / "vocab" / "words.json"
REQUIRED_COLUMNS = {
    "word",
    "phonetic",
    "definition",
    "translation",
    "pos",
    "collins",
    "oxford",
    "tag",
    "bnc",
    "frq",
    "exchange",
}
DETAIL_FIELDS = (
    "phonetic",
    "definition",
    "translation",
    "pos",
    "exchange",
    "collins",
    "oxford",
    "tag",
    "bnc",
    "frq",
)
csv.field_size_limit(10**8)


def equivalent_forms(word: str) -> list[str]:
    candidates = [word.strip()]
    for eq in re.findall(r"=\s*([^)]+)", word):
        candidates.extend(re.split(r"[/,]", eq))
    candidates.extend(re.sub(r"\([^)]*\)", " ", word).split("/"))
    for paren in re.findall(r"\(([^)]*)\)", word):
        if re.match(r"(?i)AmE\s+", paren):
            candidates.extend(re.split(r"[/,]", re.sub(r"(?i)AmE\s+", "", paren)))
        elif re.match(r"(?i)pl\.\s*", paren):
            candidates.extend(re.split(r"[/,]", re.sub(r"(?i)pl\.\s*", "", paren)))
        elif "=" not in paren:
            candidates.extend(re.split(r"[/,]", paren))
    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", candidate).strip().lower()
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def _value(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def all_details_null(row: dict) -> bool:
    return all(row.get(field) is None for field in DETAIL_FIELDS)


def join_levels(levels: dict, ecdict_csv: Path) -> tuple[dict, set[str], list[str]]:
    level_rows = levels["words"]
    candidates = {row["word"]: equivalent_forms(row["word"]) for row in level_rows}
    needed = {candidate for values in candidates.values() for candidate in values}
    matched_rows: dict[str, dict] = {}
    try:
        with ecdict_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = set(reader.fieldnames or [])
            if not columns >= REQUIRED_COLUMNS:
                raise SeedConvertError(f"ECDICT 缺列：{sorted(REQUIRED_COLUMNS - columns)}")
            for record in reader:
                key = (record.get("word") or "").strip().lower()
                if key in needed and key not in matched_rows:
                    matched_rows[key] = record
    except OSError as exc:
        raise SeedConvertError(f"ECDICT 读取失败：{ecdict_csv}") from exc

    words = []
    unmatched: set[str] = set()
    for level in level_rows:
        word = level["word"]
        matched_key = next((key for key in candidates[word] if key in matched_rows), None)
        record = matched_rows.get(matched_key) if matched_key else None
        if record is None:
            unmatched.add(word)
        detail = {field: _value(record.get(field)) if record else None for field in DETAIL_FIELDS}
        tags = (detail["tag"] or "").split()
        words.append(
            {
                "word": word,
                "matched": matched_key,
                "match_kind": (
                    None
                    if matched_key is None
                    else "whole"
                    if matched_key == candidates[word][0]
                    else "equivalent"
                ),
                **detail,
                "exam_badges": {
                    "collins": detail["collins"],
                    "oxford": detail["oxford"],
                    "tags": tags,
                },
            }
        )
    no_detail = sorted(row["word"] for row in words if all_details_null(row))
    counts = {"words": len(words), "matched": len(words) - len(unmatched), "no_detail": len(no_detail)}
    return {
        "meta": {
            "source": "skywind3000/ECDICT",
            "license": "MIT",
            "verbatim": "official-repo",
            "join": "整串精确 → 拆等价子形逐形精确；不做模糊匹配",
            "counts": counts,
        },
        "words": words,
    }, unmatched, no_detail


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels", type=Path, default=DEFAULT_LEVELS)
    parser.add_argument("--ecdict", type=Path, default=DEFAULT_ECDICT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        levels = json.loads(args.levels.read_text(encoding="utf-8"))
        document, unmatched, no_detail = join_levels(levels, args.ecdict)
        _write_json(args.output, document)
    except (OSError, json.JSONDecodeError, KeyError, SeedConvertError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps({"unmatched": sorted(unmatched), "no_detail": no_detail}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
