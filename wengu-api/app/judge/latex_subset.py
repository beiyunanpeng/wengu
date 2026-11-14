"""受限 LaTeX 子集 → sympy 表达式的确定性字符串规则转换器（AGENTS §5；P4-6）。

不解析任意 LaTeX：只认设计文档 §19-E 钉死的子集（\\frac \\sqrt ^ \\cdot \\times
\\div \\left \\right \\% \\pi e^x 四则括号与等号两侧）。超出子集（积分 \\int、
求和 \\sum、矩阵 \\begin{...}、未识别宏、n 次根）一律抛 UnsupportedLatex，
由上层降级自评，绝不猜。纯字符串规则、同输入必同输出，可整体重放。

风格参照 judge/verify_sandbox.py：稳定错误码、长度/复杂度兜底、不执行任意代码。
本模块只做文本归一，不调用 sympy、不 eval。
"""

from __future__ import annotations

import re

MAX_FORMULA_CHARS = 1000

# 子集内允许的字母宏；其余宏（含 \int \sum \begin \alpha 等）一律拒绝。
_ALLOWED_MACROS = frozenset({"frac", "sqrt", "cdot", "times", "div", "left", "right", "pi"})
# 隐式乘法不得拆开的函数名（sqrt( 不能变成 sqrt*( ）。
_FUNCTIONS = frozenset({"sqrt"})

_MACRO_RE = re.compile(r"[a-zA-Z]+")
_PERCENT_RE = re.compile(r"(?<=[\d)])%")
_DIGIT_ATOM_RE = re.compile(r"(\d)([a-zA-Z(])")
_CLOSE_ATOM_RE = re.compile(r"\)([a-zA-Z0-9(])")
_IDENT_CALL_RE = re.compile(r"([a-zA-Z]+)\(")


class UnsupportedLatex(Exception):
    """超出受限子集或无法确定性归一；reason 是稳定错误码，不含题目正文。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _read_group(text: str, index: int) -> tuple[str, int]:
    """读取 \\frac/\\sqrt 的一个参数：{...} 平衡组，或单个 token（\\frac12 / \\sqrt2）。"""

    n = len(text)
    while index < n and text[index].isspace():
        index += 1
    if index >= n:
        raise UnsupportedLatex("missing_argument")
    if text[index] != "{":
        # 无花括号时只取单个字符（数字/字母），多字符参数必须用 {}。
        return text[index], index + 1
    depth = 0
    start = index + 1
    cursor = index
    while cursor < n:
        char = text[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:cursor], cursor + 1
        cursor += 1
    raise UnsupportedLatex("unbalanced_brace")


def _expand(text: str) -> str:
    """扫描宏与花括号，产出含 ^ / % / 隐式乘法的中间串（递归处理 frac/sqrt 参数）。"""

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "\\":
            j = i + 1
            if j < n and text[j] == "%":
                out.append("%")
                i = j + 1
                continue
            match = _MACRO_RE.match(text, j)
            if match is None:
                raise UnsupportedLatex("bad_escape")
            name = match.group(0)
            j = match.end()
            if name not in _ALLOWED_MACROS:
                raise UnsupportedLatex("unsupported_macro")
            if name in ("left", "right"):
                i = j
                continue
            if name in ("cdot", "times"):
                out.append("*")
                i = j
                continue
            if name == "div":
                out.append("/")
                i = j
                continue
            if name == "pi":
                out.append("pi")
                i = j
                continue
            if name == "frac":
                numerator, j = _read_group(text, j)
                denominator, j = _read_group(text, j)
                out.append(f"({_expand(numerator)})/({_expand(denominator)})")
                i = j
                continue
            # sqrt
            if j < n and text[j] == "[":
                raise UnsupportedLatex("nth_root")
            radicand, j = _read_group(text, j)
            out.append(f"sqrt({_expand(radicand)})")
            i = j
            continue
        if char == "{":
            out.append("(")
            i += 1
            continue
        if char == "}":
            out.append(")")
            i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _implicit_multiplication(text: str) -> str:
    """插入显式 *：2x / 2( / )( / )x / x(（sqrt( 除外）。不拆字母串（保 pi/sqrt）。"""

    text = _DIGIT_ATOM_RE.sub(r"\1*\2", text)
    text = _CLOSE_ATOM_RE.sub(r")*\1", text)
    text = _IDENT_CALL_RE.sub(
        lambda m: m.group(0) if m.group(1) in _FUNCTIONS else f"{m.group(1)}*(",
        text,
    )
    return text


def to_sympy(text: str) -> str:
    """把受限 LaTeX 子集归一为 sympy 可解析的表达式串；超出子集抛 UnsupportedLatex。

    产出只含数字、单字母变量、pi/E、sqrt()、四则、**、括号与等号；
    百分号转 /100，隐式乘法补 *。等号原样保留，由调用方拆成两侧。
    """

    if not isinstance(text, str):
        raise UnsupportedLatex("not_string")
    stripped = re.sub(r"\s+", "", text)
    if not stripped:
        raise UnsupportedLatex("empty")
    if len(stripped) > MAX_FORMULA_CHARS:
        raise UnsupportedLatex("too_long")
    expanded = _expand(stripped)
    expanded = expanded.replace("^", "**")
    expanded = _PERCENT_RE.sub("/100", expanded)
    expanded = _implicit_multiplication(expanded)
    if "\\" in expanded:
        raise UnsupportedLatex("stray_backslash")
    return expanded
