"""从课标三级正文转录源重发射初中词表，或从 vendored 结构化产物复算。"""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_INPUT = PROJECT_ROOT / "seeds" / "vocab" / "_upstream" / "kebiao-level3-1600.json"
TRANSCRIPT_SHA256 = "752a2ee2311c323a4c5ea9beeb7b41dc02fe4926b340cc9be5cadcfb51ee8395"
TRANSCRIPT_URL = "https://zhuanlan.zhihu.com/p/1957531179063415195"
ENTRY_RE = re.compile(r"(\d{1,4})\.\s*(.+?)(?=\d{1,4}\.\s|\Z)", re.S)
GLUE_RE = re.compile(r"\s+[A-Za-z]$|[a-z][A-Z]$")


def strip_glue(base: str) -> str:
    base = re.sub(r"\s+[A-Z]$", "", base)
    base = re.sub(r"(?<=[a-z])[A-Z]$", "", base)
    base = re.sub(r"\)\s*[A-Z]$", ")", base)
    return base.strip()


def forms(headword: str) -> list[str]:
    out = {headword.lower()}
    for eq in re.findall(r"=\s*([^)]+)", headword):
        for part in re.split(r"[/,]", eq):
            out.add(_clean_form(part))
    noparen = re.sub(r"\([^)]*\)", " ", headword)
    for part in noparen.split("/"):
        out.add(_clean_form(part))
    for paren in re.findall(r"\(([^)]*)\)", headword):
        if re.match(r"(?i)AmE\s+", paren):
            for part in re.split(r"[/,]", re.sub(r"(?i)AmE\s+", "", paren)):
                out.add(_clean_form(part))
        elif not re.search(r"(?i)pl\.|=", paren):
            part = _clean_form(paren)
            if part not in {"to", "till", "by"}:
                out.add(part)
    normalised = {"am" if f == "a m" else "pm" if f == "p m" else f for f in out}
    return sorted(f for f in normalised if f)


def _clean_form(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9 '()/,\-.]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def record(headword: str, idx: int) -> dict:
    star = "*" in headword
    base = headword.replace("*", " ").replace("\n", " ")
    base = strip_glue(re.sub(r"\s+", " ", base).strip())
    if not base:
        raise SeedConvertError(f"初中词条 {idx} 抽取后为空")
    return {
        "idx": idx,
        "word": base,
        "official": base,
        "forms": forms(base),
        "is_level2": star,
    }


def parse_transcript(raw: str) -> list[dict]:
    try:
        start = raw.index("A1. a/an")
        end = raw.index("1601. zoo", start) + len("1601. zoo")
    except ValueError as exc:
        raise SeedConvertError("转录源缺 A1. a/an … 1601. zoo 完整区间") from exc
    entries = ENTRY_RE.findall(raw[start:end])
    rows = [record(headword, int(number)) for number, headword in entries]
    numbers = [row["idx"] for row in rows]
    if not numbers or numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise SeedConvertError("初中转录词条编号不连续")
    return rows


def load_vendored(path: Path) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("words") if isinstance(data, dict) else None
    meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not isinstance(meta, dict):
        raise SeedConvertError(f"初中 vendored 文件结构错误：{path}")
    if not meta.get("transcript_sha256"):
        raise SeedConvertError("初中 vendored 文件缺 transcript_sha256")
    rebuilt = []
    for row in rows:
        item = record(row["official"], int(row["idx"]))
        item["is_level2"] = bool(row["is_level2"])
        rebuilt.append(item)
    return rebuilt, meta


def build_document(rows: list[dict], transcript_sha256: str) -> dict:
    return {
        "meta": {
            "source": "义务教育英语课程标准(2022年版) 附录3 词汇表·三级(初中)",
            "level": "三级",
            "count": len(rows),
            "rows": len(rows),
            "official_word_count": len({row["word"].casefold() for row in rows}),
            "level2_count": sum(bool(row["is_level2"]) for row in rows),
            "license": "政府公开文件；词表本身不受著作权保护",
            "verbatim": "derived-from-transcription",
            "provenance": "第三方全文转录的结构化产物；未与官方扫描 PDF 逐字比对",
            "normalization": "先去二级星再剥分区头；word 保留官方标注形态与大小写",
            "draft": True,
            "transcript_sha256": transcript_sha256,
            "transcript_url": TRANSCRIPT_URL,
        },
        "words": rows,
    }


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="vendored 初中结构化产物")
    parser.add_argument("--output", type=Path, default=DEFAULT_INPUT, help="重发射输出路径")
    parser.add_argument("--transcript", type=Path, help="仅开发期：人工提供的转录缓存件，不进 CI")
    args = parser.parse_args(argv)
    try:
        if args.transcript:
            raw_bytes = args.transcript.read_bytes()
            digest = hashlib.sha256(raw_bytes).hexdigest()
            if digest != TRANSCRIPT_SHA256:
                raise SeedConvertError("转录源 sha256 与钉死取证不符")
            rows = parse_transcript(raw_bytes.decode("utf-8", errors="ignore"))
        else:
            rows, meta = load_vendored(args.input)
            digest = meta["transcript_sha256"]
        _write_json(args.output, build_document(rows, digest))
    except (OSError, json.JSONDecodeError, SeedConvertError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    residuals = [row["word"] for row in rows if GLUE_RE.search(row["word"])]
    print(
        json.dumps(
            {
                "entries": len(rows),
                "level2": sum(bool(row["is_level2"]) for row in rows),
                "glue_residuals": len(residuals),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
