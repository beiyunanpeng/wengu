"""从高中官方 PDF 文字层按行抽取词表，保留多词短语。"""

from __future__ import annotations

import argparse
import json
import re
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
DEFAULT_OUTPUT = PROJECT_ROOT / "seeds" / "vocab" / "_upstream" / "gsenior-2020-OFFICIAL.json"
VOCAB_PAGES_1_BASED = range(125, 191)
TIERS = {0: "义务教育", 1: "必修", 2: "选择性必修"}


def entry(line: str) -> tuple[str, int] | None:
    value = line.strip()
    if not value or re.fullmatch(r"[A-Z]", value):
        return None
    match = re.search(r"\*+$", value)
    stars = len(match.group(0)) if match else 0
    if stars > 2:
        return None
    base = value.rstrip("*").strip()
    base = re.sub(r"\s+[A-Za-z]$", "", base)
    base = re.sub(r"(?<=[a-z])[A-Z]$", "", base)
    noparen = re.sub(r"\([^)]*\)", " ", base)
    tokens = [token for token in re.split(r"\s+", noparen) if token]
    if len(tokens) > 2 or len(noparen.strip()) > 24:
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z \-'/\.]*", noparen.strip()):
        return None
    return base, stars


def forms_of(base: str) -> list[str]:
    out = {base.lower()}
    noparen = re.sub(r"\([^)]*\)", " ", base)
    for part in noparen.split("/"):
        value = re.sub(r"[^A-Za-z0-9 \-']", " ", part)
        value = re.sub(r"\s+", " ", value).strip().lower()
        if value:
            out.add(value)
    for paren in re.findall(r"\(([^)]*)\)", base):
        match = re.search(r"(?i)AmE\s+(.+)", paren)
        if match:
            for part in re.split(r"[/,]", match.group(1)):
                value = re.sub(r"[^A-Za-z0-9 \-']", " ", part)
                value = re.sub(r"\s+", " ", value).strip().lower()
                if value:
                    out.add(value)
    return sorted(out)


def build_records(lines: list[str]) -> list[dict]:
    records = []
    seen: set[tuple[str, int]] = set()
    for line in lines:
        parsed = entry(line)
        if parsed is None:
            continue
        base, stars = parsed
        key = (base, stars)
        if key in seen:
            continue
        seen.add(key)
        forms = forms_of(base)
        if forms:
            records.append({"word": base, "forms": forms, "tier": TIERS[stars]})
    return records


def build_document(records: list[dict]) -> dict:
    return {
        "meta": {
            "source": "普通高中英语课程标准(2017年版2020年修订) 附录词汇表",
            "extraction": "官方PDF文字层按行逐字直抽；保留多词短语；已修分区字母粘连",
            "count": len(records),
            "tier_counts": dict(Counter(row["tier"] for row in records)),
            "license": "政府公开文件，词表不受著作权",
            "verbatim": "official-pdf-verbatim",
            "verbatim_official": True,
        },
        "words": records,
    }


def extract_pdf(pdf: Path) -> list[dict]:
    try:
        import pymupdf
    except ImportError as exc:
        raise SeedConvertError("高中 PDF 重抽仅开发期可用，需宿主安装 pymupdf；不是本仓运行时依赖") from exc
    try:
        with pymupdf.open(str(pdf)) as doc:
            lines = [
                line
                for page_number in VOCAB_PAGES_1_BASED
                for line in doc[page_number - 1].get_text().splitlines()
            ]
    except OSError as exc:
        raise SeedConvertError(f"高中 PDF 读取失败：{pdf}") from exc
    return build_records(lines)


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        _write_json(args.output, build_document(extract_pdf(args.pdf)))
    except (OSError, SeedConvertError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
