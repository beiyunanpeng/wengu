"""词表内存索引：查询时 band、fail-fast、跨源聚合与真仓互证。"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from app.seed import vocab as vocab_module
from app.seed.vocab import VocabFormatError, load_vocab

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCAB_DIR = REPO_ROOT / "seeds" / "vocab"
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


def _write_json(path: Path, value: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(value, ensure_ascii=False, indent=1) + "\n")


def _level(word: str, stages: list[str], **extra: object) -> dict:
    return {
        "word": word,
        "forms": [word],
        "stages": stages,
        "senior_tier": None,
        "block": None,
        "unaudited": False,
        **extra,
    }


def _detail(word: str, translation: str | None = "词义") -> dict:
    return {
        "word": word,
        "matched": word,
        "match_kind": "whole",
        "phonetic": None,
        "definition": None,
        "translation": translation,
        "pos": None,
        "exchange": None,
        "collins": None,
        "oxford": None,
        "tag": None,
        "bnc": None,
        "frq": None,
        "exam_badges": {"collins": None, "oxford": None, "tags": []},
    }


def _family(root: str, word: str, mnemonic: str) -> dict:
    return {
        "root": root,
        "root_meaning": None,
        "tags": [],
        "source_file": f"dict/roots/{root}.yml",
        "source_sha256": "0" * 64,
        "words": [
            {
                "word": word,
                "root": root,
                "path": [root, word],
                "phonetic": None,
                "mnemonic": mnemonic,
                "meaning": None,
            }
        ],
    }


def _make_seeds(root: Path) -> None:
    vocab = root / "vocab"
    vocab.mkdir(parents=True)
    levels = [
        _level("a/an", ["primary", "junior"], forms=["a", "a/an", "an"]),
        _level("junior-only", ["junior"]),
        _level("senior-only", ["senior"], senior_tier="必修"),
        _level("rooted", ["junior"]),
        _level("lonely", ["junior"]),
        _level("rootless", ["primary"], block="专有名词", unaudited=True),
    ]
    details = [
        _detail("a/an", "一个\r\nart. 一"),
        _detail("junior-only"),
        _detail("senior-only"),
        _detail("rooted"),
        _detail("lonely"),
        _detail("rootless", None),
    ]
    roots = {
        "meta": {},
        "families": [
            _family("root-one", "rooted", "mnemonic-one"),
            _family("root-two", "rooted", "mnemonic-two"),
            _family("root-missing", "lonely", "keep-me"),
        ],
    }
    wordroot = {
        "meta": {},
        "entries": [
            {
                "key": "root-one",
                "class": "root",
                "example": [],
                "meaning": "root one meaning",
                "root": "root-one",
                "function": "root function",
            }
        ],
    }
    source = {
        "counts": {
            "union": len(levels),
            "primary": sum("primary" in row["stages"] for row in levels),
            "junior": sum("junior" in row["stages"] for row in levels),
            "senior": sum("senior" in row["stages"] for row in levels),
            "supplement": sum(row["block"] is not None for row in levels),
        },
        "no_detail": ["rootless"],
    }
    _write_json(vocab / "levels.json", {"meta": {}, "words": levels})
    _write_json(vocab / "words.json", {"meta": {}, "words": details})
    _write_json(vocab / "roots.json", roots)
    _write_json(vocab / "wordroot_meaning.json", wordroot)
    _write_json(vocab / "_source_vocab.json", source)



def test_missing_files_yield_empty_index_with_missing_stats(tmp_path: Path) -> None:
    index = load_vocab(tmp_path)

    assert index.words == ()
    assert dict(index.by_word) == {}
    assert index.stats.total == 0
    assert set(index.stats.missing) == {
        "levels.json",
        "words.json",
        "roots.json",
        "wordroot_meaning.json",
        "_source_vocab.json",
    }
    assert index.stats.missing_count == 5


def test_bad_top_level_fails_fast(tmp_path: Path) -> None:
    vocab = tmp_path / "vocab"
    vocab.mkdir()
    _write_json(vocab / "levels.json", [])

    with pytest.raises(VocabFormatError, match="levels.json"):
        load_vocab(tmp_path)


def test_unknown_stage_fails_fast(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    path = tmp_path / "vocab" / "levels.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["words"][1]["stages"] = ["gaokao"]
    _write_json(path, data)

    with pytest.raises(VocabFormatError, match="stages"):
        load_vocab(tmp_path)


def test_band_six_hides_junior_only_word(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)

    assert "junior-only" not in {word.word for word in index.visible(6)}
    assert "senior-only" not in {word.word for word in index.visible(6)}


def test_band_six_keeps_official_primary_form(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)

    assert "a/an" in {word.word for word in index.visible(6)}


def test_band_nine_hides_senior_only_word(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)

    visible = {word.word for word in index.visible(9)}
    assert "junior-only" in visible
    assert "senior-only" not in visible


def test_band_sixteen_returns_all_words(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)

    assert index.visible(16) == index.words


def test_invalid_ceiling_fails_instead_of_falling_back(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)

    with pytest.raises(ValueError, match="ceiling"):
        index.visible(7)


def test_multiple_root_families_are_aggregated(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)
    word = index.by_word["rooted"]

    assert word.root_family == (
        ("root-one", ("root-one", "rooted"), "mnemonic-one"),
        ("root-two", ("root-two", "rooted"), "mnemonic-two"),
    )
    assert word.root_meaning == "root one meaning"


def test_missing_wordroot_key_keeps_engra_mnemonic(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)
    word = index.by_word["lonely"]

    assert word.root_meaning is None
    assert word.root_family == (
        ("root-missing", ("root-missing", "lonely"), "keep-me"),
    )
    assert index.by_word["rootless"].root_family == ()
    assert index.stats.rootless == 4


def test_official_forms_and_detail_newlines_pass_through_unchanged(tmp_path: Path) -> None:
    _make_seeds(tmp_path)
    index = load_vocab(tmp_path)
    word = index.by_word["a/an"]

    assert word.word == "a/an"
    assert word.forms == ("a", "a/an", "an")
    assert word.translation == "一个\r\nart. 一"


def test_loader_source_has_no_database_terms() -> None:
    source = inspect.getsource(vocab_module)

    assert "sqlalchemy" not in source
    assert "sqlite3" not in source
    assert "Session" not in source


def test_band_filtering_is_a_query_not_a_load_option(tmp_path: Path) -> None:
    parameters = inspect.signature(load_vocab).parameters

    assert tuple(parameters) == ("seeds_dir",)
    assert hasattr(vocab_module.VocabIndex, "visible")


def test_real_repository_index_matches_curated_counts_and_word_sets() -> None:
    source = json.loads((VOCAB_DIR / "_source_vocab.json").read_text(encoding="utf-8"))
    levels = json.loads((VOCAB_DIR / "levels.json").read_text(encoding="utf-8"))
    details = json.loads((VOCAB_DIR / "words.json").read_text(encoding="utf-8"))
    index = load_vocab(REPO_ROOT / "seeds")
    counts = source["counts"]

    assert {row["word"] for row in levels["words"]} == {row["word"] for row in details["words"]}
    assert set(index.by_word) == {row["word"] for row in levels["words"]}
    no_detail = {
        row["word"] for row in details["words"] if all(row.get(field) is None for field in DETAIL_FIELDS)
    }
    assert no_detail == set(source["no_detail"])
    assert all(index.by_word[word].block is not None for word in no_detail)
    assert index.stats.total == counts["union"]
    assert index.stats.total == counts["words"]
    assert index.stats.primary == counts["primary"]
    assert index.stats.junior == counts["junior"]
    assert index.stats.senior == counts["senior"]
    assert index.stats.supplement == counts["supplement"]
    assert index.stats.matched == counts["matched"]
    assert index.stats.no_detail == counts["no_detail"]
    assert index.stats.root_families == counts["root_families"]
    assert index.stats.root_word_nodes == counts["root_word_nodes"]
    assert index.stats.wordroot_entries == counts["wordroot_entries"]
    assert index.stats.missing == ()
