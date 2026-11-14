"""公式题判分（P4-6）：formula_equivalent 等值 + judge_answer 公式分支 + 白名单防注入。

纪律：超出子集/不可判 → None → 降级自评（formula_fallback），绝不猜对错、绝不伪装判对。
注入串必须被 AST 白名单挡在 sympify 之前（eval/exec 不被调用）。同输入重放一致。
"""

from __future__ import annotations

import builtins

import pytest
from app.judge.normalize import (
    JudgeOutcome,
    _FormulaUnsupported,
    _looks_like_formula,
    _parse_formula_side,
    formula_equivalent,
    judge_answer,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("a", "b"),
    [
        (r"\frac{1}{2}", "0.5"),
        (r"\frac{1}{2}", r"\frac{2}{4}"),
        (r"\sqrt{16}", "4"),
        (r"\sqrt{9}", "3"),
        ("2(x-3)+4=3x-5", "x=3"),
        ("2x+2=8", "x=3"),
        (r"x^{2}", "x*x"),
        (r"50\%", "0.5"),
        (r"2\cdot 3", "6"),
        (r"\frac{3}{4}", "0.75"),
        (r"\left(x+1\right)", "x+1"),
        (r"\pi", "pi"),
        (r"\frac{1}{3}", "1/3"),
        ("3x", "x*3"),
        (r"\frac{2}{3}", r"\frac{4}{6}"),
        (r"e^{x}", "E**x"),
        ("0.5", r"\frac{1}{2}"),
        (r"\frac{1}{2}", "50%"),
    ],
)
def test_formula_equivalent_positives(a: str, b: str) -> None:
    assert formula_equivalent(a, b) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("a", "b"),
    [
        (r"\frac{1}{2}", "0.6"),
        (r"\sqrt{16}", "5"),
        (r"x^{2}", "x"),
        (r"\frac{1}{3}", "0.333"),
        (r"\sqrt{2}", "1.4142135623730951"),
        ("x=3", "x=5"),
    ],
)
def test_formula_equivalent_negatives_never_true(a: str, b: str) -> None:
    assert formula_equivalent(a, b) is not True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("a", "b"),
    [
        (r"\frac{1}{2}", "0.6"),
        (r"\sqrt{16}", "5"),
        (r"x^{2}", "x"),
        (r"\frac{1}{3}", "0.333"),
    ],
)
def test_formula_equivalent_clear_negatives_are_false(a: str, b: str) -> None:
    assert formula_equivalent(a, b) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "latex",
    [r"\int x dx", r"\sum x", r"\begin{matrix}1\end{matrix}", r"\alpha", r"\sqrt[3]{8}"],
)
def test_unsupported_latex_returns_none_not_raise(latex: str) -> None:
    assert formula_equivalent(latex, "1") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "latex",
    [r"\int x dx", r"\sum x", r"\begin{matrix}1\end{matrix}", r"\alpha", r"\sqrt[3]{8}"],
)
def test_unsupported_latex_judge_falls_back_to_self_eval(latex: str) -> None:
    outcome = judge_answer(latex, "1")
    assert outcome.verdict == "uncertain"
    assert outcome.reason == "formula_fallback"


@pytest.mark.unit
@pytest.mark.parametrize(
    "payload",
    [
        "__import__('os')",
        "open('/etc/passwd')",
        "x.__class__",
        "a[0]",
        "(lambda: 1)()",
        "x if True else y",
        "[1,2,3]",
        "{'a':1}",
        "__import__('os').system('rm -rf /')",
    ],
)
def test_injection_rejected_by_whitelist(payload: str) -> None:
    assert formula_equivalent(payload, "1") is None
    assert judge_answer(payload, "1").verdict != "correct"


@pytest.mark.unit
def test_injection_never_calls_eval_or_exec(monkeypatch) -> None:
    """白名单必须在 sympify 之前挡下注入：eval/exec 一旦被调用即失败。"""

    def _boom(*args, **kwargs):
        raise AssertionError("公式判分不得调用 eval/exec")

    monkeypatch.setattr(builtins, "eval", _boom)
    monkeypatch.setattr(builtins, "exec", _boom)
    for payload in (
        "__import__('os')",
        "open('/etc/passwd')",
        "x.__class__",
        "a[0]",
        "(lambda: 1)()",
    ):
        assert formula_equivalent(payload, "1") is None
    # 带幂标记的注入会进公式分支，但仍只能降级自评，绝不触发 eval。
    assert judge_answer("__import__('os')^{2}", "1").verdict == "uncertain"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        # 语法合法但结构被白名单禁止：直接测内部入口 _parse_formula_side，断言精确拒绝码。
        ("x.y", "forbidden_node"),  # 属性访问 → ast.Attribute 不在白名单
        ("sqrt[2]", "forbidden_node"),  # 下标 → ast.Subscript 不在白名单
        ("sqrt(1,2)", "bad_call"),  # 多参调用 → sqrt 只许单参
        ("sqrt(x=1)", "bad_call"),  # 关键字参数 → 一律拒绝
        ("foo+1", "forbidden_name"),  # 白名单外名字
        ("_x+1", "forbidden_name"),  # 下划线名（x 在符号集，但 _x 仍禁）
        ('"a"+1', "forbidden_constant"),  # 字符串常量 → 只许 int|float
        # ast.walk 是 BFS：外层 Call 先于 Lambda 被访问，故 (lambda:1)(x) 命中调用规则
        # （func 不是 Name "sqrt"）→ forbidden_call；裸 lambda 才落 forbidden_node。
        ("(lambda: 1)(x)", "forbidden_call"),
        ("lambda: 1", "forbidden_node"),
        ("1e300", "const_too_large"),  # 超大常数 > 1e15
    ],
)
def test_parse_formula_side_whitelist_rejects_with_precise_reason(
    text: str, reason: str
) -> None:
    """白名单是承重墙：语法合法但结构被禁的输入必须在 sympify 之前抛精确拒绝码。

    可证伪：把 _validate_formula_ast 的 nodes 置空（绕过白名单）→ 这批用例全部变红；
    还原 → 全绿。仅断言"抛异常"不够，必须钉死 reason，才能证明是白名单而非 sympy 兜底。
    """

    with pytest.raises(_FormulaUnsupported) as excinfo:
        _parse_formula_side(text)
    assert excinfo.value.reason == reason


@pytest.mark.unit
def test_huge_exponent_is_rejected_not_computed() -> None:
    assert formula_equivalent("2^{999999999}", "1") is None
    assert formula_equivalent("2^{-999999999}", "1") is None


@pytest.mark.unit
def test_formula_judging_is_deterministic() -> None:
    pairs = [
        (r"\frac{1}{2}", "0.5"),
        ("2(x-3)+4=3x-5", "x=3"),
        (r"\sqrt{16}", "4"),
        (r"\int x", "1"),
        ("__import__('os')", "1"),
    ]
    for a, b in pairs:
        results = [formula_equivalent(a, b) for _ in range(3)]
        assert all(r == results[0] for r in results)
        outcomes = [judge_answer(a, b) for _ in range(3)]
        assert all(o == outcomes[0] for o in outcomes)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("student", "standard"),
    [
        (r"\frac{1}{2}", "0.5"),
        ("0.5", r"\frac{1}{2}"),
        (r"\sqrt{16}", "4"),
        (r"x^{2}", "x*x"),
        (r"50\%", "0.5"),
        (r"\frac{3}{4}", "0.75"),
        (r"\pi", "pi"),
        (r"e^{x}", "E**x"),
    ],
)
def test_judge_answer_formula_correct(student: str, standard: str) -> None:
    outcome = judge_answer(student, standard)
    assert outcome.verdict == "correct", outcome
    assert outcome.reason == "formula_equal"
    assert outcome.rule == "formula"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("student", "standard"),
    [(r"\frac{1}{2}", "0.6"), (r"\sqrt{16}", "5"), (r"x^{2}", "x")],
)
def test_judge_answer_formula_wrong(student: str, standard: str) -> None:
    outcome = judge_answer(student, standard)
    assert outcome.verdict == "wrong"
    assert outcome.reason == "mismatch"


@pytest.mark.unit
def test_formula_match_via_acceptable_alias() -> None:
    outcome = judge_answer("0.5", "二分之一", acceptable=[r"\frac{1}{2}"])
    assert outcome.verdict == "correct"
    assert outcome.reason == "accepted_alias"
    assert outcome.rule == "formula"


@pytest.mark.unit
def test_definitive_match_wins_over_undecidable_alias() -> None:
    outcome = judge_answer("0.5", r"\int x", acceptable=[r"\frac{1}{2}"])
    assert outcome.verdict == "correct"
    assert outcome.rule == "formula"


@pytest.mark.unit
def test_fallback_is_never_correct_or_wrong() -> None:
    outcome = judge_answer(r"\frac{1}{2}", r"\int x")
    assert outcome.verdict == "uncertain"
    assert outcome.reason == "formula_fallback"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"\frac{1}{2}", True),
        ("x^2", True),
        (r"50\%", True),
        ("0.5", False),
        ("1+1", False),
        ("x=3", False),
        ("2(x-3)+4=3x-5", False),
        ("【依赖图形】x^2", False),
        (r"【依赖图形】\frac{1}{2}", False),
    ],
)
def test_formula_detection_is_narrow_and_excludes_figures(text: str, expected: bool) -> None:
    # 口径（P4-6 返工③）：公式判分触发面是「仅标记触发」——含 \宏 或 ^ 才进公式分支；
    # 卡里提到的 answer_kind == formula 未实现。纯文本等式（如 2(x-3)+4=3x-5 与 x=3）
    # 不含标记 → 不进公式分支，由既有文本/有理数规范化比对处理（下方 False 行钉住该行为）。
    assert _looks_like_formula(text) is expected


@pytest.mark.unit
def test_figure_dependent_answer_skips_formula_judging() -> None:
    # 依赖图形 + 幂标记：不得进公式分支（reason 必须是普通 mismatch，而非 formula_*）。
    outcome = judge_answer("【依赖图形】x^{2}", "4")
    assert outcome.reason == "mismatch"


@pytest.mark.unit
def test_non_formula_path_is_unchanged() -> None:
    assert judge_answer("2", "1+1").verdict == "wrong"
    assert judge_answer("1+1", "1+1").reason == "text_equal"
    assert judge_answer("0.5", "1/2") == JudgeOutcome("correct", "numeric_equal", "numeric")
    assert judge_answer("5cm", "5厘米") == JudgeOutcome("correct", "numeric_unit_equal", "numeric_unit")
    assert judge_answer("4", "3") == JudgeOutcome("wrong", "mismatch")


@pytest.mark.unit
def test_empty_and_placeholder_formula_inputs_are_manual() -> None:
    assert formula_equivalent("", r"\frac{1}{2}") is None
    assert formula_equivalent(None, r"\frac{1}{2}") is None
    assert formula_equivalent("〔?〕", r"\frac{1}{2}") is None
    assert judge_answer(r"\frac{1}{2}", "〔?〕").verdict == "uncertain"
