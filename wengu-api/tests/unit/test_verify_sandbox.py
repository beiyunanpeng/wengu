"""verify AST 沙箱：合法表达式精确求值，非法/资源炸弹一律拒绝。"""

from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest
from app.judge.verify_sandbox import (
    SandboxError,
    SandboxTimeout,
    evaluate_expression,
    serialize_value,
    verify_answer,
)


def _eval(expression: str, variables: dict | None = None) -> str:
    return serialize_value(evaluate_expression(expression, variables=variables))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", "7"),
        ("1/3 + 1/6", "1/2"),
        ("2 ** 10", "1024"),
        ("7 // 2", "3"),
        ("7 % 4", "3"),
        ("-3 + +5", "2"),
        ("1 if 2 > 1 else 0", "1"),
        ("1 < 2 < 3", "True"),
        ("max(1, 5, 3)", "5"),
        ("min([4, 2, 8])", "2"),
        ("abs(-3)", "3"),
        ("len('abc')", "3"),
        ("round(1/3, 2)", "33/100"),
        ("[x * 2 for x in xs]", "2,4,6"),
        ("[x for x in xs if x > 1]", "2,3"),
        ("sum(x * x for x in xs)", "14"),
        ("{x for x in xs}", "1,2,3"),
    ],
)
def test_allowed_expressions(expression: str, expected: str) -> None:
    assert _eval(expression, {"xs": [1, 2, 3]}) == expected


@pytest.mark.unit
def test_variables_and_subscripts() -> None:
    variables = {"xs": [1, 2, 3], "d": {"a": 2}, "name": "abc"}
    assert _eval("sum(xs)", variables) == "6"
    assert _eval("xs[0] + xs[-1]", variables) == "4"
    assert _eval("xs[1:]", variables) == "2,3"
    assert _eval("d['a'] + 1", variables) == "3"
    assert _eval("name[1]", variables) == "b"


@pytest.mark.unit
def test_verify_uses_exact_judge_answer() -> None:
    assert verify_answer("2 + 3", expected="5").verdict == "verified"
    assert verify_answer("1/2", expected="50%").verdict == "verified"
    assert verify_answer("1/3", expected="0.333").verdict == "mismatch"
    assert verify_answer("2 + 3", expected="6").verdict == "mismatch"
    assert verify_answer("2 + 3", expected="5", acceptable=["5.0"]).verdict == "verified"
    assert verify_answer("1/2", expected="0.5", unordered=True).verdict == "verified"


@pytest.mark.unit
def test_verify_uncertain_on_unusable_reference() -> None:
    assert verify_answer("2 + 3", expected=None).verdict == "uncertain"
    assert verify_answer("2 + 3", expected="〔?〕").verdict == "uncertain"
    assert verify_answer("2 + 3", expected="").verdict == "uncertain"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("expression", "reason"),
    [
        ("__import__('os')", "forbidden_name"),
        ("xs.__class__", "forbidden_node:Attribute"),
        ("(lambda x: x)(1)", "forbidden_node:Lambda"),
        ("(x := 1)", "forbidden_node:NamedExpr"),
        ("x = 1", "syntax_error"),
        ("sqrt(4)", "forbidden_call"),
        ("open('x')", "forbidden_call"),
        ("len(1)", "type_error"),
        ("xs['a']", "type_error"),
        ("d['missing']", "index_error"),
        ("1/0", "division_by_zero"),
        ("2 ** 101", "exponent_too_large"),
        ("9 ** 100 ** 2", "exponent_too_large"),
        ("[0] * 5", "type_error"),
        ("1 +", "syntax_error"),
        ("", "empty_expression"),
    ],
)
def test_forbidden_expressions(expression: str, reason: str) -> None:
    with pytest.raises(SandboxError) as excinfo:
        evaluate_expression(expression, variables={"xs": [1], "d": {}})
    assert excinfo.value.reason == reason


@pytest.mark.unit
def test_resource_limits() -> None:
    with pytest.raises(SandboxError, match="too_many_nodes|too_deep"):
        evaluate_expression("+".join(["1"] * 400))
    with pytest.raises(SandboxError) as excinfo:
        evaluate_expression("+" * 40 + "1")
    assert excinfo.value.reason == "too_deep"
    with pytest.raises(SandboxError) as excinfo:
        evaluate_expression("1" * 2001)
    assert excinfo.value.reason == "expression_too_long"
    with pytest.raises(SandboxError) as excinfo:
        evaluate_expression("(9 ** 100) ** 100")
    assert excinfo.value.reason == "number_too_large"


@pytest.mark.unit
def test_timeout_budget(monkeypatch) -> None:
    clock = iter([0.0, 10.0])
    monkeypatch.setattr(
        "app.judge.verify_sandbox.time",
        SimpleNamespace(monotonic=lambda: next(clock)),
    )
    with pytest.raises(SandboxTimeout) as excinfo:
        evaluate_expression("1 + 1")
    assert excinfo.value.reason == "timeout"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("variables", "reason"),
    [
        ({"__x": 1}, "variables_bad_name"),
        ({"abs": 1}, "variables_reserved_name"),
        ({"x": object()}, "variables_bad_type"),
        ({"x": float("nan")}, "variables_not_finite"),
        ({"x": [1] * 1001}, "variables_too_large"),
    ],
)
def test_bad_variables(variables: dict, reason: str) -> None:
    with pytest.raises(SandboxError) as excinfo:
        evaluate_expression("1", variables=variables)
    assert excinfo.value.reason == reason


@pytest.mark.unit
def test_no_builtin_eval_or_exec(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("builtin eval/exec must not be used")

    monkeypatch.setattr(builtins, "eval", boom)
    monkeypatch.setattr(builtins, "exec", boom)
    assert _eval("1 + 2") == "3"
