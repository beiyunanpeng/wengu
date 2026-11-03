"""P3-3b 词表导入解析纯函数：分隔符、表头、引号、行号与限额。"""

from __future__ import annotations

import pytest
from app.services.recitation_import import (
    MAX_ANSWER_CHARS,
    MAX_IMPORT_ROWS,
    MAX_PROMPT_CHARS,
    MAX_UNIT_CHARS,
    ImportRejected,
    parse_text,
)

pytestmark = pytest.mark.unit


def test_tsv_detected_from_first_content_line_after_comment() -> None:
    parsed = parse_text("# Unit 1\n\nabandon\t放弃\tUnit 1\nability\t能力\n")

    assert [(row.line, row.prompt, row.answer, row.unit) for row in parsed.rows] == [
        (3, "abandon", "放弃", "Unit 1"),
        (4, "ability", "能力", None),
    ]
    assert parsed.issues == ()


def test_csv_header_skipped_but_lone_unit_word_is_data() -> None:
    parsed = parse_text("prompt,answer,unit\nunit,单位,\nabandon,放弃,Unit 1\n")

    assert [row.prompt for row in parsed.rows] == ["unit", "abandon"]
    assert parsed.rows[0].line == 2


def test_quoted_csv_keeps_comma_and_embedded_newline_with_line_numbers() -> None:
    parsed = parse_text('prompt,answer\n"take, off",脱掉\n"a\nb",多行\n')

    assert [row.prompt for row in parsed.rows] == ["take, off", "a\nb"]
    assert [row.line for row in parsed.rows] == [2, 3]


def test_bad_rows_reported_without_blocking_good_rows() -> None:
    parsed = parse_text(",缺少条目\nabandon,放弃\nfour,columns,here,x\n")

    assert [row.prompt for row in parsed.rows] == ["abandon"]
    assert [(issue.line, issue.field) for issue in parsed.issues] == [
        (1, "prompt"),
        (3, "columns"),
    ]


@pytest.mark.parametrize(
    ("row", "field", "limit"),
    [
        ("x" * (MAX_PROMPT_CHARS + 1), "prompt", MAX_PROMPT_CHARS),
        (
            f"abandon,{'x' * (MAX_ANSWER_CHARS + 1)}",
            "answer",
            MAX_ANSWER_CHARS,
        ),
        (f"abandon,放弃,{'x' * (MAX_UNIT_CHARS + 1)}", "unit", MAX_UNIT_CHARS),
    ],
)
def test_overlong_field_rejects_whole_batch_with_line(
    row: str, field: str, limit: int
) -> None:
    with pytest.raises(ImportRejected) as rejected:
        parse_text(f"ok_row\n{row}\n")

    assert rejected.value.line == 2
    assert rejected.value.field == field
    assert str(limit) in str(rejected.value)


def test_bom_and_crlf_are_accepted() -> None:
    parsed = parse_text("\ufeffprompt,answer\r\nabandon,放弃\r\n")

    assert [(row.prompt, row.answer) for row in parsed.rows] == [("abandon", "放弃")]


def test_replacement_character_rejects_batch_as_non_utf8() -> None:
    with pytest.raises(ImportRejected) as rejected:
        parse_text("abandon,放\ufffd\n")

    assert rejected.value.field == "text"


def test_row_limit_boundary_500_ok_501_rejected() -> None:
    ok = "\n".join(f"word{i}" for i in range(MAX_IMPORT_ROWS))
    parsed = parse_text(ok)
    assert len(parsed.rows) == MAX_IMPORT_ROWS

    with pytest.raises(ImportRejected) as rejected:
        parse_text(f"{ok}\nword{MAX_IMPORT_ROWS}")

    assert rejected.value.line == MAX_IMPORT_ROWS + 1


def test_unclosed_quote_is_a_parse_error_not_a_silent_row() -> None:
    with pytest.raises(ImportRejected) as rejected:
        parse_text('prompt,answer\n"abandon,放弃\n')

    assert rejected.value.field == "text"
