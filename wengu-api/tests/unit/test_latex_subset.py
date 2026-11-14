"""受限 LaTeX 子集转换器（P4-6）：子集内确定性归一，子集外抛 UnsupportedLatex。

只验证文本规则，不调 sympy、不判分；判分等值在 test_judge_formula.py。
"""

from __future__ import annotations

import pytest
from app.judge.latex_subset import MAX_FORMULA_CHARS, UnsupportedLatex, to_sympy


@pytest.mark.unit
@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        (r"\frac{1}{2}", "(1)/(2)"),
        (r"\frac{3}{4}", "(3)/(4)"),
        (r"\frac{\frac{1}{2}}{3}", "((1)/(2))/(3)"),
        (r"\sqrt{16}", "sqrt(16)"),
        (r"\sqrt{2}", "sqrt(2)"),
        (r"x^{2}", "x**(2)"),
        ("x^2", "x**2"),
        (r"e^{x}", "e**(x)"),
        (r"50\%", "50/100"),
        (r"2\cdot 3", "2*3"),
        (r"2\times 3", "2*3"),
        (r"2\div 3", "2/3"),
        (r"\left(x+1\right)", "(x+1)"),
        (r"\pi", "pi"),
        ("2(x-3)+4=3x-5", "2*(x-3)+4=3*x-5"),
        ("3x", "3*x"),
        ("2x+2=8", "2*x+2=8"),
        (r"\frac{1}{2}+\frac{1}{3}", "(1)/(2)+(1)/(3)"),
    ],
)
def test_subset_converts_deterministically(latex: str, expected: str) -> None:
    assert to_sympy(latex) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("latex", "reason"),
    [
        (r"\int x dx", "unsupported_macro"),
        (r"\sum x", "unsupported_macro"),
        (r"\begin{matrix}1\end{matrix}", "unsupported_macro"),
        (r"\alpha", "unsupported_macro"),
        (r"\lim_{x}", "unsupported_macro"),
        (r"\sqrt[3]{8}", "nth_root"),
        (r"\frac{1}", "missing_argument"),
        (r"\frac{1}{2", "unbalanced_brace"),
        ("\\", "bad_escape"),
        ("", "empty"),
        ("   ", "empty"),
    ],
)
def test_out_of_subset_raises_unsupported(latex: str, reason: str) -> None:
    with pytest.raises(UnsupportedLatex) as excinfo:
        to_sympy(latex)
    assert excinfo.value.reason == reason


@pytest.mark.unit
def test_not_string_raises_unsupported() -> None:
    with pytest.raises(UnsupportedLatex) as excinfo:
        to_sympy(None)  # type: ignore[arg-type]
    assert excinfo.value.reason == "not_string"


@pytest.mark.unit
def test_too_long_raises_unsupported() -> None:
    with pytest.raises(UnsupportedLatex) as excinfo:
        to_sympy("x" * (MAX_FORMULA_CHARS + 1))
    assert excinfo.value.reason == "too_long"


@pytest.mark.unit
def test_conversion_is_replayable() -> None:
    for latex in (r"\frac{1}{2}", r"\sqrt{16}", "2(x-3)+4=3x-5", r"e^{x}"):
        assert to_sympy(latex) == to_sympy(latex) == to_sympy(latex)


@pytest.mark.unit
def test_whitespace_is_stripped_before_parsing() -> None:
    assert to_sympy(r"  \frac { 1 } { 2 }  ") == to_sympy(r"\frac{1}{2}")
