"""初中附录3补充块的纯清洗函数与可选开发期 OCR 入口。"""

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
DEFAULT_OUTPUT = PROJECT_ROOT / "seeds" / "vocab" / "_upstream" / "kebiao-junior-supplement.json"
MONTHS = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}
WEEK = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
NUMBERS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety", "hundred", "thousand", "million", "first", "second", "third",
    "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh",
    "twelfth", "thirteenth", "fourteenth", "fifteenth",
}


def clean(text: str) -> str:
    text = re.sub(r"\s*\d{2,3}$", "", text.strip())
    text = re.sub(r"[^\x00-\x7F]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    match = re.match(r"[A-Za-z][A-Za-z ,\-'&/()\.]*", text)
    return match.group(0).strip(" ,.·-") if match else ""


def categorize(word: str) -> str:
    lower = word.lower()
    if lower in MONTHS:
        return "月份"
    if lower in WEEK:
        return "星期"
    if lower in NUMBERS:
        return "数词"
    if re.fullmatch(r"[A-Z]{2,}(\s*\(.+\))?", word):
        return "组织"
    if word[0].isupper():
        return "专有名词"
    return "其他"


def fix(word: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", word).strip()


def junk(word: str) -> bool:
    if not re.search(r"[aeiouAEIOU]", word):
        return True
    if re.fullmatch(r"[A-Za-z\.\,\s]{0,3}", word):
        return True
    if word in {"adj", "n.", "n., adj", "zation)", "opera)", "()", "n., n.", "N., n."}:
        return True
    return not bool(re.search(r"[A-Za-z]{2,}", word))


def merge_entries(entries: list[str], junior: dict) -> list[str]:
    main_forms = {
        form.lower().strip()
        for row in junior["words"]
        for form in row["forms"]
    }
    filtered = []
    for raw in entries:
        word = fix(raw)
        if not junk(word) and word.lower().split(" (")[0].strip() not in main_forms:
            filtered.append(word)
    merged = []
    skip = set()
    for index, word in enumerate(filtered):
        if word == "The United States of" and index + 1 < len(filtered) and filtered[index + 1].startswith("America"):
            merged.append("the United States of America")
            skip.add(index + 1)
            continue
        if index in skip:
            continue
        word = re.sub(r"Beijing opera \(Peking.*", "Beijing opera", word)
        word = re.sub(r"UNESCO \(.*", "UNESCO", word)
        word = re.sub(r" \)*\(Peking.*", "", word)
        merged.append(word)
    seen = set()
    unique = []
    for word in merged:
        if word.lower() not in seen:
            seen.add(word.lower())
            unique.append(word)
    return unique


def build_document(entries: list[str], junior: dict) -> dict:
    words = merge_entries(entries, junior)
    records = [{"word": word, "category": categorize(word), "unaudited": True} for word in words]
    return {
        "meta": {
            "source": "义务教育英语课程标准(2022) 附录3 额外块(数词/时间/国家/组织/节日/中国文化专有名词)",
            "extraction": "官方扫描PDF OCR 页134-138",
            "count": len(records),
            "categories": dict(Counter(row["category"] for row in records)),
            "license": "政府公开文件",
            "verbatim": "ocr",
            "verbatim_official": False,
            "method": "OCR",
            "unaudited": True,
            "note": "不规则动词表(139-143)未抽，ECDICT exchange 已覆盖；OCR偶发错字需人工过",
        },
        "words": records,
    }


def ocr_entries(pdf: Path) -> list[str]:
    try:
        import numpy as np
        import pymupdf
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise SeedConvertError("补充块重抽仅开发期可用；OCR 依赖不得进入 requirements 或 CI") from exc
    ocr = RapidOCR()
    entries = []
    with pymupdf.open(str(pdf)) as doc:
        for page_index in range(134, 139):
            pixmap = doc[page_index].get_pixmap(dpi=220)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
            if pixmap.n == 4:
                image = image[:, :, :3]
            result, _ = ocr(image)
            boxes = []
            for item in result or []:
                x = int(item[0][0][0])
                y = int(item[0][0][1])
                text = item[1]
                if y < 150 or re.search(r"课程标准|义务教育", text):
                    continue
                boxes.append((x, y, text))
            for _, _, text in sorted(boxes, key=lambda box: (box[1], box[0])):
                word = clean(text)
                if len(word) >= 2 and re.search(r"[A-Za-z]", word):
                    entries.append(word)
    return entries


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--junior", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        junior = json.loads(args.junit.read_text(encoding="utf-8"))
        document = build_document(ocr_entries(args.pdf), junior)
        _write_json(args.output, document)
    except (OSError, json.JSONDecodeError, KeyError, SeedConvertError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(document["meta"]["counts"] if "counts" in document["meta"] else {"count": document["meta"]["count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
