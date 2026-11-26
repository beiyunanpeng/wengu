"""P6-1 词表产物与抽取器回归：计数、集合、官方形态、哈希与授权等级。"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from scripts.import_vocab import verify_vendored
from scripts.vocab_extract import SeedConvertError
from scripts.vocab_extract.extract_gsenior import build_records, entry
from scripts.vocab_extract.extract_junior import load_vendored, record
from scripts.vocab_extract.vocab_join import DETAIL_FIELDS, join_levels

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCAB_DIR = REPO_ROOT / "seeds" / "vocab"
UPSTREAM_DIR = VOCAB_DIR / "_upstream"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_counts_are_derived_and_equal_to_curated_source() -> None:
    source = _load(VOCAB_DIR / "_source_vocab.json")
    levels = _load(VOCAB_DIR / "levels.json")
    words = _load(VOCAB_DIR / "words.json")
    roots = _load(VOCAB_DIR / "roots.json")
    wordroot = _load(VOCAB_DIR / "wordroot_meaning.json")
    junior = _load(UPSTREAM_DIR / "kebiao-level3-1600.json")
    expected = source["counts"]

    assert len(levels["words"]) == expected["union"]
    assert sum(row["block"] is not None for row in levels["words"]) == expected["supplement"]
    assert levels["meta"]["counts"] == {key: expected[key] for key in levels["meta"]["counts"]}
    assert words["meta"]["counts"] == {key: expected[key] for key in words["meta"]["counts"]}
    assert roots["meta"]["counts"] == {
        "families": expected["root_families"],
        "word_nodes": expected["root_word_nodes"],
    }
    assert wordroot["meta"]["counts"] == {"entries": expected["wordroot_entries"]}
    assert len(wordroot["entries"]) == expected["wordroot_entries"]
    assert sum(len(family["words"]) for family in roots["families"]) == expected["root_word_nodes"]
    assert len(roots["families"]) == source["inputs"]["engra"]["roots_files"]
    assert any(family["root"] == "con" for family in roots["families"])
    assert {
        "rows": len(junior["words"]),
        "official_word_count": junior["meta"]["official_word_count"],
        "level2_marked": junior["meta"]["level2_count"],
    } == {
        "rows": expected["junior_rows"],
        "official_word_count": expected["junior_official_word_count"],
        "level2_marked": expected["junior_level2_marked"],
    }


def test_primary_received_count_is_only_equality_baseline() -> None:
    source = _load(VOCAB_DIR / "_source_vocab.json")
    primary = _load(UPSTREAM_DIR / "vocab-level2.json")
    received = source["sources"]["primary"]["counts"]["words"]
    assert primary["count"] == len(primary["words"]) == received


def test_join_uses_collection_equality_not_threshold() -> None:
    source = _load(VOCAB_DIR / "_source_vocab.json")
    levels = {row["word"]: row for row in _load(VOCAB_DIR / "levels.json")["words"]}
    words = _load(VOCAB_DIR / "words.json")["words"]
    unmatched = {row["word"] for row in words if row["matched"] is None and not levels[row["word"]]["block"]}
    no_detail = {row["word"] for row in words if all(row.get(field) is None for field in DETAIL_FIELDS)}

    assert unmatched == set()
    assert no_detail == set(source["no_detail"])
    assert all(levels[word]["block"] is not None for word in no_detail)


def test_verbatim_levels_and_supplement_audit_flags() -> None:
    source = _load(VOCAB_DIR / "_source_vocab.json")
    expected = {
        "ecdict": "official-repo",
        "engra": "official-repo",
        "primary": "official-repo",
        "junior": "derived-from-transcription",
        "supplement": "ocr",
        "senior": "official-pdf-verbatim",
    }
    assert {name: value["verbatim"] for name, value in source["sources"].items()} == expected
    assert source["sources"]["supplement"]["unaudited"] is True
    levels = _load(VOCAB_DIR / "levels.json")["words"]
    block_rows = [row for row in levels if row["block"] is not None]
    assert block_rows
    assert all(row["unaudited"] is True for row in block_rows)
    assert "errata" not in source


def test_junior_official_forms_survive_rebuild() -> None:
    path = UPSTREAM_DIR / "kebiao-level3-1600.json"
    vendored = _load(path)
    rebuilt, _meta = load_vendored(path)
    assert rebuilt == vendored["words"]

    words = {row["word"] for row in vendored["words"]}
    assert "o'clock" in words
    assert "o clock" not in words
    assert "a/an" in words
    assert sum("'" in row["word"] for row in vendored["words"]) >= 1
    for marker in ("(", "/"):
        assert sum(marker in row["word"] for row in vendored["words"]) == sum(
            marker in row["official"] for row in vendored["words"]
        )
    assert "o'clock" in record("o'clock", 1)["forms"]
    assert record("actor / actress", 2)["word"] == "actor / actress"
    assert record("a/an", 3)["word"] == "a/an"
    by_word = {row["word"]: row for row in vendored["words"]}
    assert {"miss", "Miss"} <= words
    assert by_word["miss"]["is_level2"] is False
    assert by_word["Miss"]["is_level2"] is True


def test_vendored_hashes_match_and_one_byte_drift_fails_fast(tmp_path: Path) -> None:
    source = _load(VOCAB_DIR / "_source_vocab.json")
    verify_vendored(VOCAB_DIR, source)
    for name, evidence in source["vendored"].items():
        path = VOCAB_DIR / evidence["path"]
        assert path.stat().st_size == evidence["bytes"]
        assert _sha256(path) == evidence["sha256"], name

    copied = tmp_path / "vocab"
    shutil.copytree(VOCAB_DIR, copied)
    victim = copied / next(iter(source["vendored"].values()))["path"]
    with victim.open("ab") as fh:
        fh.write(b"x")
    with pytest.raises(SeedConvertError, match="sha256/bytes"):
        verify_vendored(copied, source)


def test_two_level_exact_join_uses_equivalent_subforms(tmp_path: Path) -> None:
    csv_path = tmp_path / "ecdict.csv"
    fields = [
        "word", "phonetic", "definition", "translation", "pos", "collins", "oxford",
        "tag", "bnc", "frq", "exchange",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"word": "actress", "translation": "女演员"})
        writer.writerow({"word": "am", "translation": "是"})
    levels = {
        "words": [
            {"word": "actor / actress", "forms": ["actor / actress", "actor", "actress"]},
            {"word": "be (am, is, are)", "forms": ["be (am, is, are)", "be", "am", "is", "are"]},
        ]
    }
    document, unmatched, no_detail = join_levels(levels, csv_path)
    assert unmatched == set()
    assert no_detail == []
    assert [row["match_kind"] for row in document["words"]] == ["equivalent", "equivalent"]
    assert [row["translation"] for row in document["words"]] == ["女演员", "是"]


def test_senior_parser_preserves_multiword_phrases() -> None:
    phrases = (
        "according to",
        "bean curd",
        "due to",
        "mobile phone",
        "ought to",
        "new zealand",
        "new zealander",
        "south africa",
        "south african",
        "viet nam",
    )
    for phrase in phrases:
        assert entry(phrase) == (phrase, 0)
    assert {row["word"] for row in build_records(phrases)} == set(phrases)
