"""课标词表内存索引：五份 JSON 合成不可变词条，band 在查询时过滤。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.core.config import get_settings

STAGES = frozenset({"primary", "junior", "senior"})
CEILING_STAGES = {
    6: frozenset({"primary"}),
    9: frozenset({"primary", "junior"}),
    16: STAGES,
}
VOCAB_FILES = (
    "levels.json",
    "words.json",
    "roots.json",
    "wordroot_meaning.json",
    "_source_vocab.json",
)
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

RootFamily = tuple[str, tuple[str, ...], str | None]


class VocabFormatError(ValueError):
    """词表 JSON 存在非法结构或关键字段。"""


@dataclass(frozen=True)
class VocabExamBadges:
    collins: str | None
    oxford: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class VocabWord:
    word: str
    forms: tuple[str, ...]
    stages: tuple[str, ...]
    senior_tier: str | None
    block: str | None
    unaudited: bool
    matched: str | None
    match_kind: str | None
    phonetic: str | None
    definition: str | None
    translation: str | None
    pos: str | None
    exchange: str | None
    collins: str | None
    oxford: str | None
    exam_badges: VocabExamBadges
    bnc: str | None
    frq: str | None
    root_family: tuple[RootFamily, ...]
    root_meaning: str | None


@dataclass(frozen=True)
class VocabStats:
    total: int
    primary: int
    junior: int
    senior: int
    supplement: int
    matched: int
    no_detail: int
    rootless: int
    root_families: int
    root_word_nodes: int
    wordroot_entries: int
    missing: tuple[str, ...] = ()
    by_stage: Mapping[str, int] = field(default_factory=dict)

    @property
    def missing_count(self) -> int:
        return len(self.missing)


@dataclass(frozen=True)
class VocabIndex:
    words: tuple[VocabWord, ...]
    by_word: Mapping[str, VocabWord]
    stats: VocabStats

    def visible(self, ceiling: int) -> tuple[VocabWord, ...]:
        if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling not in CEILING_STAGES:
            raise ValueError("ceiling 只能是 6、9 或 16")
        allowed = CEILING_STAGES[ceiling]
        return tuple(word for word in self.words if allowed.intersection(word.stages))


def load_vocab(seeds_dir: Path | None = None) -> VocabIndex:
    """从 seeds/vocab 读取五份产物并建全量索引；缺文件容忍，坏结构 fail-fast。"""

    root = Path(seeds_dir) if seeds_dir is not None else get_settings().seeds_dir
    vocab_dir = root / "vocab"
    documents: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name in VOCAB_FILES:
        document = _read_json(vocab_dir / name)
        if document is None:
            missing.append(name)
        else:
            documents[name] = _require_object(document, name)

    level_rows = _rows(documents.get("levels.json"), "words", "levels.json")
    detail_rows = _rows(documents.get("words.json"), "words", "words.json")
    family_rows = _rows(documents.get("roots.json"), "families", "roots.json")
    wordroot_rows = _rows(
        documents.get("wordroot_meaning.json"), "entries", "wordroot_meaning.json"
    )

    details = _build_details(detail_rows)
    roots, root_families, root_word_nodes = _build_roots(family_rows)
    wordroot_meanings = _build_wordroot_meanings(wordroot_rows)
    words_list: list[VocabWord] = []
    seen_words: set[str] = set()
    for row in level_rows:
        word = _build_word(row, details, roots, wordroot_meanings)
        if word.word in seen_words:
            raise VocabFormatError(f"levels.json 重复 word：{word.word}")
        seen_words.add(word.word)
        words_list.append(word)
    words = tuple(words_list)
    by_word = MappingProxyType({word.word: word for word in words})
    by_stage = {
        stage: sum(stage in word.stages for word in words)
        for stage in ("primary", "junior", "senior")
    }
    stats = VocabStats(
        total=len(words),
        primary=by_stage["primary"],
        junior=by_stage["junior"],
        senior=by_stage["senior"],
        supplement=sum(word.block is not None for word in words),
        matched=sum(word.matched is not None for word in words),
        no_detail=sum(
            all((details.get(word.word) or {}).get(name) is None for name in DETAIL_FIELDS)
            for word in words
        ),
        rootless=sum(not word.root_family for word in words),
        root_families=root_families,
        root_word_nodes=root_word_nodes,
        wordroot_entries=len(wordroot_rows),
        missing=tuple(missing),
        by_stage=MappingProxyType(by_stage),
    )
    return VocabIndex(words=words, by_word=by_word, stats=stats)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VocabFormatError(f"{path.name} 读取失败") from exc


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VocabFormatError(f"{label} 必须是对象")
    return value


def _rows(document: dict[str, Any] | None, key: str, label: str) -> list[Any]:
    if document is None:
        return []
    value = document.get(key)
    if not isinstance(value, list):
        raise VocabFormatError(f"{label}.{key} 必须是数组")
    return value


def _build_details(rows: list[Any]) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(rows):
        row = _require_object(value, f"words.json[{index}]")
        word = _required_str(row, "word", f"words.json[{index}]")
        if word in details:
            raise VocabFormatError(f"words.json 重复 word：{word}")
        detail = {name: _optional_str(row.get(name), name, f"words.json[{index}]") for name in DETAIL_FIELDS}
        detail["matched"] = _optional_str(row.get("matched"), "matched", f"words.json[{index}]")
        detail["match_kind"] = _optional_str(
            row.get("match_kind"), "match_kind", f"words.json[{index}]"
        )
        badges = _require_object(
            row.get("exam_badges"), f"words.json[{index}].exam_badges"
        )
        detail["exam_badges"] = VocabExamBadges(
            collins=_optional_str(
                badges.get("collins"), "exam_badges.collins", f"words.json[{index}]"
            ),
            oxford=_optional_str(
                badges.get("oxford"), "exam_badges.oxford", f"words.json[{index}]"
            ),
            tags=tuple(_str_list(badges.get("tags"), "exam_badges.tags", f"words.json[{index}]")),
        )
        details[word] = detail
    return details


def _build_roots(
    rows: list[Any],
) -> tuple[dict[str, list[RootFamily]], int, int]:
    roots: dict[str, list[RootFamily]] = {}
    word_nodes = 0
    for family_index, value in enumerate(rows):
        label = f"roots.json[{family_index}]"
        family = _require_object(value, label)
        root = _required_str(family, "root", label)
        _optional_str(family.get("root_meaning"), "root_meaning", label)
        _str_list(family.get("tags"), "tags", label)
        _required_str(family, "source_file", label)
        _required_str(family, "source_sha256", label)
        nodes = family.get("words")
        if not isinstance(nodes, list):
            raise VocabFormatError(f"{label}.words 必须是数组")
        word_nodes += len(nodes)
        for node_index, node_value in enumerate(nodes):
            node_label = f"{label}.words[{node_index}]"
            node = _require_object(node_value, node_label)
            word = _required_str(node, "word", node_label)
            _required_str(node, "root", node_label)
            path = _str_list(node.get("path"), "path", node_label)
            _optional_str(node.get("phonetic"), "phonetic", node_label)
            _optional_str(node.get("meaning"), "meaning", node_label)
            mnemonic = _optional_str(node.get("mnemonic"), "mnemonic", node_label)
            roots.setdefault(word, []).append((root, tuple(path), mnemonic))
    return roots, len(rows), word_nodes


def _build_wordroot_meanings(rows: list[Any]) -> dict[str, str | None]:
    meanings: dict[str, str | None] = {}
    for index, value in enumerate(rows):
        label = f"wordroot_meaning.json[{index}]"
        row = _require_object(value, label)
        key = _required_str(row, "key", label)
        _optional_str(row.get("class"), "class", label)
        _str_list(row.get("example"), "example", label)
        _optional_str(row.get("origin"), "origin", label)
        _optional_str(row.get("root"), "root", label)
        _optional_str(row.get("function"), "function", label)
        _optional_str(row.get("synonyms"), "synonyms", label)
        _optional_str(row.get("antonyms"), "antonyms", label)
        meanings[key] = _optional_str(row.get("meaning"), "meaning", label)
    return meanings


def _build_word(
    value: object,
    details: dict[str, dict[str, Any]],
    roots: dict[str, list[RootFamily]],
    wordroot_meanings: dict[str, str | None],
) -> VocabWord:
    row = _require_object(value, "levels.json word")
    word = _required_str(row, "word", "levels.json word")
    forms = _str_list(row.get("forms"), "forms", f"levels.json:{word}")
    stages = _str_list(row.get("stages"), "stages", f"levels.json:{word}")
    unknown = set(stages) - STAGES
    if unknown:
        raise VocabFormatError(f"levels.json:{word} stages 含未知值：{sorted(unknown)}")
    senior_tier = _optional_str(row.get("senior_tier"), "senior_tier", f"levels.json:{word}")
    block = _optional_str(row.get("block"), "block", f"levels.json:{word}")
    unaudited = row.get("unaudited")
    if not isinstance(unaudited, bool):
        raise VocabFormatError(f"levels.json:{word} unaudited 必须是布尔值")
    detail = details.get(word, {})
    root_family = tuple(roots.get(word, ()))
    root_meaning = next(
        (wordroot_meanings[family[0]] for family in root_family if family[0] in wordroot_meanings),
        None,
    )
    return VocabWord(
        word=word,
        forms=tuple(forms),
        stages=tuple(stages),
        senior_tier=senior_tier,
        block=block,
        unaudited=unaudited,
        matched=detail.get("matched"),
        match_kind=detail.get("match_kind"),
        phonetic=detail.get("phonetic"),
        definition=detail.get("definition"),
        translation=detail.get("translation"),
        pos=detail.get("pos"),
        exchange=detail.get("exchange"),
        collins=detail.get("collins"),
        oxford=detail.get("oxford"),
        exam_badges=detail.get("exam_badges", VocabExamBadges(None, None, ())),
        bnc=detail.get("bnc"),
        frq=detail.get("frq"),
        root_family=root_family,
        root_meaning=root_meaning,
    )


def _required_str(row: dict[str, Any], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise VocabFormatError(f"{label}.{key} 必须是非空字符串")
    return value


def _optional_str(value: object, key: str, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise VocabFormatError(f"{label}.{key} 必须是字符串或 null")
    return value


def _str_list(value: object, key: str, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise VocabFormatError(f"{label}.{key} 必须是字符串数组")
    return value
