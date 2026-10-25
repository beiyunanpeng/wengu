"""运行时判卷：确定性 judgeAnswer，规范化字符串/集合比对（AGENTS §5）。

只做答案比较，不执行 verify 表达式，不调用模型。数值一律用 Fraction 精确比较，
避免 `1/3 == 0.333` 这类浮点假阳性。无法判断的输入返回 uncertain（路由人工），
绝不猜。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

Verdict = Literal["correct", "wrong", "uncertain"]
PLACEHOLDER = "〔?〕"

_VULGAR_FRACTIONS: dict[str, tuple[int, int]] = {
    "½": (1, 2),
    "⅓": (1, 3),
    "⅔": (2, 3),
    "¼": (1, 4),
    "¾": (3, 4),
    "⅕": (1, 5),
    "⅖": (2, 5),
    "⅗": (3, 5),
    "⅘": (4, 5),
    "⅙": (1, 6),
    "⅚": (5, 6),
    "⅛": (1, 8),
    "⅜": (3, 8),
    "⅝": (5, 8),
    "⅞": (7, 8),
}

# 单位别名只做等价映射，不做跨单位换算（1kg ≠ 1000g），避免制造虚假精确。
_UNIT_ALIASES: dict[str, str] = {
    "mm": "mm",
    "毫米": "mm",
    "cm": "cm",
    "厘米": "cm",
    "cm2": "cm2",
    "平方厘米": "cm2",
    "cm3": "cm3",
    "立方厘米": "cm3",
    "dm": "dm",
    "分米": "dm",
    "m": "m",
    "米": "m",
    "m2": "m2",
    "平方米": "m2",
    "m3": "m3",
    "立方米": "m3",
    "km": "km",
    "千米": "km",
    "公里": "km",
    "g": "g",
    "克": "g",
    "kg": "kg",
    "千克": "kg",
    "公斤": "kg",
    "t": "t",
    "吨": "t",
    "ml": "ml",
    "毫升": "ml",
    "l": "l",
    "升": "l",
    "s": "s",
    "秒": "s",
    "min": "min",
    "分钟": "min",
    "h": "h",
    "小时": "h",
    "时": "h",
    "°": "deg",
    "度": "deg",
    "元": "yuan",
    "块": "yuan",
    "角": "jiao",
}

_WRAPPER_PAIRS = {"(": ")", "[": "]", "{": "}", "【": "】", "<": ">"}
_CLOSERS = frozenset(_WRAPPER_PAIRS.values())

_VULGAR_SYMBOLS = frozenset(_VULGAR_FRACTIONS)

_MIXED_RE = re.compile(
    r"^([+-]?)(\d+(?:\.\d+)?)\s*(?:又\s*|\s+)(\d+)\s*/\s*(\d+)$"
)
_FRACTION_RE = re.compile(r"^([+-]?)\s*(\d+)\s*/\s*(\d+)$")
_SIMPLE_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")

_HARD_SPLIT = re.compile(r"[,，、;；\n]+")
_SOFT_SPLIT = re.compile(r"(?:或者|和|或)")

_TRAILING_PUNCT = "。．.；;，,、:：!！?？"


@dataclass(frozen=True)
class JudgeOutcome:
    """判分结论。`verdict=uncertain` 表示必须路由人工，不是答错。"""

    verdict: Verdict
    reason: str
    rule: str | None = None


def _expand_vulgar_fractions(text: str) -> str:
    out: list[str] = []
    for char in text:
        fraction = _VULGAR_FRACTIONS.get(char)
        if fraction is None:
            out.append(char)
            continue
        numerator, denominator = fraction
        if out and out[-1][-1:].isdigit():
            out.append(f"又{numerator}/{denominator}")
        else:
            out.append(f"{numerator}/{denominator}")
    return "".join(out)


def _clean(value: str) -> str:
    text = _expand_vulgar_fractions(value)
    text = unicodedata.normalize("NFKC", text)
    text = (
        text.replace("\u00a0", " ")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(_TRAILING_PUNCT).strip()


def _is_balanced(text: str) -> bool:
    stack: list[str] = []
    for char in text:
        expected = _WRAPPER_PAIRS.get(char)
        if expected is not None:
            stack.append(expected)
        elif char in _CLOSERS and (not stack or stack.pop() != char):
            return False
    return not stack


def _strip_outer(text: str) -> str:
    value = text.strip()
    while len(value) >= 2:
        expected = _WRAPPER_PAIRS.get(value[0])
        if expected != value[-1]:
            break
        inner = value[1:-1].strip()
        if not _is_balanced(inner):
            break
        value = inner
    return value


def _parse_number_core(text: str) -> Fraction | None:
    value = _strip_outer(text.strip())
    if not value:
        return None

    mixed = _MIXED_RE.fullmatch(value)
    if mixed is not None:
        sign, whole, numerator, denominator = mixed.groups()
        if int(denominator) == 0:
            return None
        result = Fraction(whole) + Fraction(int(numerator), int(denominator))
        return -result if sign == "-" else result

    fraction = _FRACTION_RE.fullmatch(value)
    if fraction is not None:
        sign, numerator, denominator = fraction.groups()
        if int(denominator) == 0:
            return None
        result = Fraction(int(numerator), int(denominator))
        return -result if sign == "-" else result

    if _THOUSANDS_RE.fullmatch(value):
        value = value.replace(",", "")
    if not _SIMPLE_RE.fullmatch(value):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return Fraction(number)


def _parse_number_with_unit(text: str) -> tuple[Fraction, str | None] | None:
    value = _strip_outer(text.strip())
    if not value:
        return None
    if value.endswith("%"):
        number = _parse_number_core(value[:-1])
        if number is None:
            return None
        return number / 100, None

    number = _parse_number_core(value)
    if number is not None:
        return number, None

    lowered = value.casefold()
    for alias in sorted(_UNIT_ALIASES, key=len, reverse=True):
        if not lowered.endswith(alias):
            continue
        prefix = value[: -len(alias)].strip()
        if not prefix:
            continue
        number = _parse_number_core(prefix)
        if number is not None:
            return number, _UNIT_ALIASES[alias]
    return None


def _parse_coordinate(text: str) -> tuple[tuple[Fraction, ...], ...] | None:
    parts = [part.strip() for part in re.split(r"[;；]", text.strip()) if part.strip()]
    if not parts:
        return None
    points: list[tuple[Fraction, ...]] = []
    for part in parts:
        if not (part.startswith("(") and part.endswith(")")):
            return None
        components = [item.strip() for item in part[1:-1].split(",")]
        if not 2 <= len(components) <= 3:
            return None
        values: list[Fraction] = []
        for component in components:
            parsed = _parse_number_with_unit(component)
            if parsed is None or parsed[1] is not None:
                return None
            values.append(parsed[0])
        points.append(tuple(values))
    return tuple(points)


def _parse_bare_coordinate(
    text: str, arity: int
) -> tuple[tuple[Fraction, ...], ...] | None:
    components = [item.strip() for item in text.split(",")]
    if len(components) != arity:
        return None
    values: list[Fraction] = []
    for component in components:
        parsed = _parse_number_with_unit(component)
        if parsed is None or parsed[1] is not None:
            return None
        values.append(parsed[0])
    return (tuple(values),)


def _parse_choice(text: str) -> tuple[str, ...] | None:
    value = re.sub(r"[\s、,，;；/|.。]+", "", _strip_outer(text))
    if not value:
        return None
    if re.fullmatch(r"[A-Za-z]", value):
        return (value.upper(),)
    if re.fullmatch(r"[A-Ha-h]{2,8}", value):
        return tuple(value.upper())
    return None


def _normalize_text(text: str) -> str:
    value = text.casefold()
    if re.search(r"[\u3400-\u9fff]", value):
        return re.sub(r"\s+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _split_multi(text: str) -> list[str] | None:
    parts = [part.strip() for part in _HARD_SPLIT.split(text) if part.strip()]
    if len(parts) >= 2:
        return parts

    # 和/或 仅在两侧含数字/选项时拆，避免把“饱和”“共和国”等词拆开。
    soft_parts = [part.strip() for part in _SOFT_SPLIT.split(text) if part.strip()]
    if len(soft_parts) < 2:
        return None
    if not any(
        _parse_number_with_unit(part) is not None or _parse_choice(part) is not None
        for part in soft_parts
    ):
        return None
    return soft_parts


def _compare_token(student: str, standard: str) -> tuple[bool, str]:
    student_number = _parse_number_with_unit(student)
    standard_number = _parse_number_with_unit(standard)
    if student_number is not None and standard_number is not None:
        return student_number == standard_number, "numeric"

    student_choice = _parse_choice(student)
    standard_choice = _parse_choice(standard)
    if student_choice is not None and standard_choice is not None:
        return student_choice == standard_choice, "choice"

    return _normalize_text(student) == _normalize_text(standard), "text"


def _token_key(token: str) -> tuple[object, ...]:
    number = _parse_number_with_unit(token)
    if number is not None:
        return ("number", *number)
    coordinate = _parse_coordinate(token)
    if coordinate is not None:
        return ("coordinate", coordinate)
    choice = _parse_choice(token)
    if choice is not None:
        return ("choice", choice)
    return ("text", _normalize_text(token))


def _compare(student: str, standard: str, unordered: bool) -> tuple[bool, str]:
    standard_coordinate = _parse_coordinate(standard)
    student_coordinate = _parse_coordinate(student)
    if standard_coordinate is None and student_coordinate is not None and len(student_coordinate) == 1:
        standard_coordinate = _parse_bare_coordinate(standard, len(student_coordinate[0]))
    if student_coordinate is None and standard_coordinate is not None and len(standard_coordinate) == 1:
        student_coordinate = _parse_bare_coordinate(student, len(standard_coordinate[0]))
    if standard_coordinate is not None and student_coordinate is not None:
        if unordered:
            return Counter(standard_coordinate) == Counter(student_coordinate), "coordinate"
        return standard_coordinate == student_coordinate, "coordinate"

    standard_number = _parse_number_with_unit(standard)
    student_number = _parse_number_with_unit(student)
    if standard_number is not None and student_number is not None:
        rule = "numeric_unit" if standard_number[1] is not None else "numeric"
        return standard_number == student_number, rule

    standard_choice = _parse_choice(standard)
    student_choice = _parse_choice(student)
    if standard_choice is not None and student_choice is not None:
        if unordered:
            return Counter(standard_choice) == Counter(student_choice), "choice"
        return standard_choice == student_choice, "choice"

    standard_tokens = _split_multi(standard)
    student_tokens = _split_multi(student)
    if standard_tokens is not None or student_tokens is not None:
        if standard_tokens is None or student_tokens is None:
            return False, "multiset"
        if unordered:
            return (
                Counter(_token_key(token) for token in standard_tokens)
                == Counter(_token_key(token) for token in student_tokens),
                "multiset",
            )
        if len(standard_tokens) != len(student_tokens):
            return False, "multiset"
        for student_token, standard_token in zip(student_tokens, standard_tokens, strict=True):
            matched, _ = _compare_token(student_token, standard_token)
            if not matched:
                return False, "multiset"
        return True, "multiset"

    return _normalize_text(student) == _normalize_text(standard), "text"


def judge_answer(
    student: str | None,
    standard: str | None,
    *,
    acceptable: Sequence[str] = (),
    unordered: bool = False,
) -> JudgeOutcome:
    """比较学生作答与标准答案；任何不确定输入都返回 uncertain，由上层转人工。"""

    if not isinstance(student, str) or not _clean(student):
        return JudgeOutcome("uncertain", "empty_answer")
    if not isinstance(standard, str) or not _clean(standard):
        return JudgeOutcome("uncertain", "empty_reference")

    student_clean = _clean(student)
    if PLACEHOLDER in student_clean or PLACEHOLDER in _clean(standard):
        return JudgeOutcome("uncertain", "placeholder")

    references: list[str] = [standard]
    references.extend(item for item in acceptable if isinstance(item, str))
    for index, reference in enumerate(references):
        reference_clean = _clean(reference)
        if not reference_clean or PLACEHOLDER in reference_clean:
            continue
        matched, rule = _compare(student_clean, reference_clean, unordered)
        if matched:
            if index == 0:
                return JudgeOutcome("correct", f"{rule}_equal", rule)
            return JudgeOutcome("correct", "accepted_alias", rule)
    return JudgeOutcome("wrong", "mismatch")
