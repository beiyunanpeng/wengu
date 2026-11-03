"""P3-3c 候选抽词纯函数：token 归一、题内去重、停用词、已有条目排除、排序截断。"""

from __future__ import annotations

import pytest
from app.services.recitation import (
    MAX_CANDIDATES,
    RecitationInvalid,
    english_word_tokens,
    extract_word_candidates,
)


def _words(candidates) -> list[str]:
    return [entry.word for entry in candidates]


def test_tokens_are_lowercase_and_strip_trailing_possessive() -> None:
    assert english_word_tokens("The Student's BOOK is here.") == (
        "the",
        "student",
        "book",
        "is",
        "here",
    )


def test_tokens_keep_hyphen_and_inner_apostrophe_but_drop_single_letters() -> None:
    assert english_word_tokens("A well-known don't x y") == (
        "well-known",
        "don't",
    )


def test_chinese_is_skipped_and_ascii_letters_only() -> None:
    assert english_word_tokens("苹果 Apple 香蕉 banana 123") == (
        "apple",
        "banana",
    )


def test_repeated_word_in_one_problem_counts_once() -> None:
    candidates = extract_word_candidates(
        ["diligent diligent diligent student"]
    )

    assert [(entry.word, entry.mistake_count) for entry in candidates] == [
        ("diligent", 1),
        ("student", 1),
    ]


def test_sorted_by_mistake_count_desc_then_alphabetical() -> None:
    candidates = extract_word_candidates(
        [
            "zebra apple",
            "zebra mango",
            "apple mango",
            "zebra",
        ]
    )

    assert [(entry.word, entry.mistake_count) for entry in candidates] == [
        ("zebra", 3),
        ("apple", 2),
        ("mango", 2),
    ]


def test_stopwords_are_excluded() -> None:
    candidates = extract_word_candidates(
        ["The student is in the library and the teacher is here"]
    )

    assert _words(candidates) == sorted(["student", "library", "teacher"])


def test_existing_prompts_are_excluded_case_insensitively() -> None:
    candidates = extract_word_candidates(
        ["Apple banana cherry"],
        existing_prompts=["APPLE", " banana "],
    )

    assert _words(candidates) == ["cherry"]


def test_limit_truncates_ranked_candidates() -> None:
    candidates = extract_word_candidates(
        ["alpha", "alpha beta", "alpha beta gamma"], limit=2
    )

    assert [(entry.word, entry.mistake_count) for entry in candidates] == [
        ("alpha", 3),
        ("beta", 2),
    ]


@pytest.mark.parametrize("limit", [0, -1, MAX_CANDIDATES + 1])
def test_limit_outside_range_is_rejected(limit: int) -> None:
    with pytest.raises(RecitationInvalid):
        extract_word_candidates(["alpha"], limit=limit)
