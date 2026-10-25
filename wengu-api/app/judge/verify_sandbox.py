"""入库时 verify 表达式沙箱（AGENTS §5；TICKETS P1-5 三档核验第 2 档）。

自写 AST 解释器：不使用 Python 内置 eval/exec 执行表达式，只允许
四则/乘方/比较/推导式/下标与少量纯函数。节点数、深度、集合长度、指数、
结果位数与 2 秒时间预算共同兜底，防止表达式变成资源炸弹。
"""

from __future__ import annotations

import ast
import math
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from app.judge.normalize import judge_answer

MAX_EXPRESSION_CHARS = 2000
MAX_NODES = 500
MAX_DEPTH = 40
MAX_COLLECTION = 1000
MAX_ITERATIONS = 50_000
MAX_EXPONENT = 100
MAX_NUMBER_BITS = 4096
MAX_STRING_CHARS = 1000
DEFAULT_TIMEOUT_S = 2.0

_ALLOWED_CALLS = frozenset({"abs", "min", "max", "sum", "len", "round"})

_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UnaryOp,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.IfExp,
    ast.Call,
)


class SandboxError(Exception):
    """verify 表达式非法；`reason` 是稳定错误码，可进审计但不含表达式正文。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class SandboxTimeout(SandboxError):
    def __init__(self) -> None:
        super().__init__("timeout")


@dataclass(frozen=True)
class VerifyOutcome:
    verdict: Literal["verified", "mismatch", "uncertain"]
    computed: str
    reason: str


class _Budget:
    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise SandboxError("invalid_timeout")
        self._deadline = time.monotonic() + seconds
        self._ticks = 0

    def tick(self) -> None:
        self._ticks += 1
        if (self._ticks == 1 or self._ticks % 64 == 0) and time.monotonic() > self._deadline:
            raise SandboxTimeout()


def _tree_depth(node: ast.AST, depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        return depth
    children = list(ast.iter_child_nodes(node))
    if not children:
        return depth
    return max(_tree_depth(child, depth + 1) for child in children)


def _validate_tree(tree: ast.Expression) -> None:
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise SandboxError("too_many_nodes")
    if _tree_depth(tree) > MAX_DEPTH:
        raise SandboxError("too_deep")
    for node in nodes:
        if not isinstance(node, _ALLOWED_NODES):
            raise SandboxError(f"forbidden_node:{type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise SandboxError("forbidden_name")
        if isinstance(node, ast.comprehension) and node.is_async:
            raise SandboxError("async_comprehension")


def _coerce_value(value: object, depth: int = 0) -> object:
    if depth > 5:
        raise SandboxError("variables_too_deep")
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SandboxError("variables_not_finite")
        return Fraction(str(value))
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise SandboxError("variables_too_long")
        return value
    if isinstance(value, list | tuple):
        if len(value) > MAX_COLLECTION:
            raise SandboxError("variables_too_large")
        return tuple(_coerce_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION:
            raise SandboxError("variables_too_large")
        coerced: dict[object, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or key.startswith("_"):
                raise SandboxError("variables_bad_key")
            coerced[key] = _coerce_value(item, depth + 1)
        return coerced
    raise SandboxError("variables_bad_type")


def _coerce_variables(variables: Mapping[str, object] | None) -> dict[str, object]:
    if not variables:
        return {}
    env: dict[str, object] = {}
    for name, value in variables.items():
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise SandboxError("variables_bad_name")
        if name in _ALLOWED_CALLS:
            raise SandboxError("variables_reserved_name")
        env[name] = _coerce_value(value)
    return env


def _as_number(value: object) -> Fraction:
    if isinstance(value, bool):
        return Fraction(int(value))
    if isinstance(value, Fraction):
        return value
    raise SandboxError("type_error")


def _check_number(value: Fraction) -> Fraction:
    if value.numerator.bit_length() > MAX_NUMBER_BITS or value.denominator.bit_length() > MAX_NUMBER_BITS:
        raise SandboxError("number_too_large")
    return value


def _ensure_size(value: object) -> object:
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise SandboxError("string_too_long")
        return value
    if isinstance(value, list | tuple | set | frozenset | dict) and len(value) > MAX_COLLECTION:
        raise SandboxError("collection_too_large")
    return value


def _iterable_values(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple | set | frozenset):
        return tuple(value)
    if isinstance(value, str):
        return tuple(value)
    if isinstance(value, dict):
        return tuple(value.keys())
    raise SandboxError("not_iterable")


def _truthy(value: object) -> bool:
    return bool(value)


class _Evaluator:
    def __init__(self, budget: _Budget) -> None:
        self._budget = budget
        self._iterations = 0

    def evaluate(self, tree: ast.Expression, env: Mapping[str, object]) -> object:
        return self._eval(tree.body, env)

    def _eval(self, node: ast.AST, env: Mapping[str, object]) -> object:
        self._budget.tick()
        if isinstance(node, ast.Constant):
            return self._constant(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise SandboxError("unknown_name")
            return env[node.id]
        if isinstance(node, ast.BinOp):
            return self._binop(node, env)
        if isinstance(node, ast.UnaryOp):
            return self._unary(node, env)
        if isinstance(node, ast.BoolOp):
            return self._boolop(node, env)
        if isinstance(node, ast.Compare):
            return self._compare(node, env)
        if isinstance(node, ast.IfExp):
            return self._eval(node.body if _truthy(self._eval(node.test, env)) else node.orelse, env)
        if isinstance(node, ast.List):
            return _ensure_size(tuple(self._eval(item, env) for item in node.elts))
        if isinstance(node, ast.Tuple):
            return _ensure_size(tuple(self._eval(item, env) for item in node.elts))
        if isinstance(node, ast.Set):
            return frozenset(_ensure_size(tuple(self._eval(item, env) for item in node.elts)))
        if isinstance(node, ast.Dict):
            result: dict[object, object] = {}
            for key_node, value_node in zip(node.keys, node.values, strict=True):
                if key_node is None:
                    raise SandboxError("forbidden_node:DictUnpack")
                key = self._eval(key_node, env)
                result[key] = self._eval(value_node, env)
            return _ensure_size(result)
        if isinstance(node, ast.Subscript):
            return self._subscript(node, env)
        if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            items = self._comprehension(node.generators, node.elt, env)
            if isinstance(node, ast.SetComp):
                return frozenset(items)
            return _ensure_size(items)
        if isinstance(node, ast.DictComp):
            result: dict[object, object] = {}
            for child_env in self._iterate(node.generators, 0, env):
                key = self._eval(node.key, child_env)
                result[key] = self._eval(node.value, child_env)
                if len(result) > MAX_COLLECTION:
                    raise SandboxError("collection_too_large")
            return result
        if isinstance(node, ast.Call):
            return self._call(node, env)
        raise SandboxError(f"forbidden_node:{type(node).__name__}")

    @staticmethod
    def _constant(value: object) -> object:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return _check_number(Fraction(value))
        if isinstance(value, float):
            if not math.isfinite(value):
                raise SandboxError("constant_not_finite")
            return _check_number(Fraction(str(value)))
        if isinstance(value, str):
            if len(value) > MAX_STRING_CHARS:
                raise SandboxError("string_too_long")
            return value
        raise SandboxError("constant_type")

    def _binop(self, node: ast.BinOp, env: Mapping[str, object]) -> Fraction:
        left = _as_number(self._eval(node.left, env))
        right = _as_number(self._eval(node.right, env))
        try:
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            elif isinstance(node.op, ast.Div):
                result = left / right
            elif isinstance(node.op, ast.FloorDiv):
                result = Fraction(left // right)
            elif isinstance(node.op, ast.Mod):
                result = left % right
            elif isinstance(node.op, ast.Pow):
                if right.denominator != 1:
                    raise SandboxError("non_integer_exponent")
                exponent = int(right)
                if abs(exponent) > MAX_EXPONENT:
                    raise SandboxError("exponent_too_large")
                if left == 0 and exponent < 0:
                    raise SandboxError("division_by_zero")
                magnitude = abs(exponent)
                if (
                    left.numerator.bit_length() * magnitude > MAX_NUMBER_BITS
                    or left.denominator.bit_length() * magnitude > MAX_NUMBER_BITS
                ):
                    raise SandboxError("number_too_large")
                result = left**exponent
            else:
                raise SandboxError("unsupported_operator")
        except ZeroDivisionError:
            raise SandboxError("division_by_zero") from None
        except (OverflowError, ValueError):
            raise SandboxError("arithmetic_error") from None
        return _check_number(Fraction(result))

    def _unary(self, node: ast.UnaryOp, env: Mapping[str, object]) -> object:
        value = self._eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not _truthy(value)
        number = _as_number(value)
        if isinstance(node.op, ast.UAdd):
            return number
        if isinstance(node.op, ast.USub):
            return -number
        raise SandboxError("unsupported_operator")

    def _boolop(self, node: ast.BoolOp, env: Mapping[str, object]) -> object:
        is_and = isinstance(node.op, ast.And)
        result: object = is_and
        for item in node.values:
            result = self._eval(item, env)
            if is_and and not _truthy(result):
                return result
            if not is_and and _truthy(result):
                return result
        return result

    def _compare(self, node: ast.Compare, env: Mapping[str, object]) -> bool:
        left = self._eval(node.left, env)
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            right = self._eval(comparator, env)
            try:
                if isinstance(operator, ast.Eq):
                    matched = left == right
                elif isinstance(operator, ast.NotEq):
                    matched = left != right
                elif isinstance(operator, ast.Lt):
                    matched = left < right
                elif isinstance(operator, ast.LtE):
                    matched = left <= right
                elif isinstance(operator, ast.Gt):
                    matched = left > right
                elif isinstance(operator, ast.GtE):
                    matched = left >= right
                else:
                    raise SandboxError("unsupported_operator")
            except TypeError:
                raise SandboxError("type_error") from None
            if not matched:
                return False
            left = right
        return True

    def _subscript(self, node: ast.Subscript, env: Mapping[str, object]) -> object:
        container = self._eval(node.value, env)
        if isinstance(node.slice, ast.Slice):
            if not isinstance(container, list | tuple | str):
                raise SandboxError("type_error")
            start = self._optional_index(node.slice.lower, env)
            stop = self._optional_index(node.slice.upper, env)
            step = self._optional_index(node.slice.step, env)
            result = container[slice(start, stop, step)]
            return _ensure_size(result)

        index = self._eval(node.slice, env)
        try:
            if isinstance(container, dict):
                if not isinstance(index, str):
                    raise SandboxError("type_error")
                if index not in container:
                    raise SandboxError("index_error")
                return container[index]
            if isinstance(container, str):
                if not isinstance(index, Fraction) or index.denominator != 1:
                    raise SandboxError("type_error")
                return container[int(index)]
            if isinstance(container, list | tuple):
                if not isinstance(index, Fraction) or index.denominator != 1:
                    raise SandboxError("type_error")
                return container[int(index)]
        except (IndexError, KeyError, TypeError):
            raise SandboxError("index_error") from None
        raise SandboxError("type_error")

    def _optional_index(self, node: ast.AST | None, env: Mapping[str, object]) -> int | None:
        if node is None:
            return None
        value = self._eval(node, env)
        if not isinstance(value, Fraction) or value.denominator != 1:
            raise SandboxError("type_error")
        return int(value)

    def _comprehension(
        self, generators: Sequence[ast.comprehension], element: ast.AST, env: Mapping[str, object]
    ) -> tuple[object, ...]:
        results: list[object] = []
        for child_env in self._iterate(generators, 0, env):
            results.append(self._eval(element, child_env))
            if len(results) > MAX_COLLECTION:
                raise SandboxError("collection_too_large")
        return tuple(results)

    def _iterate(
        self,
        generators: Sequence[ast.comprehension],
        index: int,
        env: Mapping[str, object],
    ) -> Iterable[Mapping[str, object]]:
        if index >= len(generators):
            yield env
            return
        generator = generators[index]
        if generator.is_async:
            raise SandboxError("async_comprehension")
        if not isinstance(generator.target, ast.Name):
            raise SandboxError("bad_comprehension_target")
        iterable = self._eval(generator.iter, env)
        for item in _iterable_values(iterable):
            self._iterations += 1
            if self._iterations > MAX_ITERATIONS:
                raise SandboxError("too_many_iterations")
            self._budget.tick()
            child_env = {**env, generator.target.id: item}
            if all(_truthy(self._eval(condition, child_env)) for condition in generator.ifs):
                yield from self._iterate(generators, index + 1, child_env)

    def _call(self, node: ast.Call, env: Mapping[str, object]) -> object:
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
            raise SandboxError("forbidden_call")
        if node.keywords:
            raise SandboxError("keyword_arguments")
        name = node.func.id
        args = [self._eval(arg, env) for arg in node.args]

        if name == "abs":
            self._require_arity(name, args, 1)
            return abs(_as_number(args[0]))
        if name == "len":
            self._require_arity(name, args, 1)
            if not isinstance(args[0], str | list | tuple | set | frozenset | dict):
                raise SandboxError("type_error")
            return Fraction(len(args[0]))
        if name == "round":
            if len(args) not in (1, 2):
                raise SandboxError("bad_arity")
            number = _as_number(args[0])
            if len(args) == 1:
                return Fraction(round(number))
            digits = _as_number(args[1])
            if digits.denominator != 1 or abs(int(digits)) > 20:
                raise SandboxError("bad_round_digits")
            return Fraction(round(number, int(digits)))
        if name == "sum":
            self._require_arity(name, args, 1)
            values = _iterable_values(args[0])
            total = Fraction(0)
            for value in values:
                self._budget.tick()
                total += _as_number(value)
                _check_number(total)
            return total
        if name in ("min", "max"):
            values = _iterable_values(args[0]) if len(args) == 1 else tuple(args)
            if not values:
                raise SandboxError("empty_sequence")
            try:
                return (min if name == "min" else max)(values)
            except TypeError:
                raise SandboxError("type_error") from None
        raise SandboxError("forbidden_call")

    @staticmethod
    def _require_arity(name: str, args: Sequence[object], expected: int) -> None:
        if len(args) != expected:
            raise SandboxError(f"bad_arity:{name}")


def evaluate_expression(
    expression: str,
    *,
    variables: Mapping[str, object] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> object:
    """在 AST 白名单内求值；任何非法输入抛 SandboxError（reason 稳定）。"""

    if not isinstance(expression, str) or not expression.strip():
        raise SandboxError("empty_expression")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise SandboxError("expression_too_long")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError, MemoryError):
        raise SandboxError("syntax_error") from None
    _validate_tree(tree)
    env = _coerce_variables(variables)
    return _Evaluator(_Budget(timeout_s)).evaluate(tree, env)


def serialize_value(value: object) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return str(value.numerator)
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return ",".join(serialize_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return ",".join(sorted(serialize_value(item) for item in value))
    raise SandboxError("result_type")


def verify_answer(
    expression: str,
    *,
    expected: str | None,
    acceptable: Sequence[str] = (),
    unordered: bool = False,
    variables: Mapping[str, object] | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> VerifyOutcome:
    """求值并和标准答案比较；只有 verdict=verified 才允许题库入库。"""

    computed = serialize_value(
        evaluate_expression(expression, variables=variables, timeout_s=timeout_s)
    )
    judged = judge_answer(computed, expected, acceptable=acceptable, unordered=unordered)
    if judged.verdict == "correct":
        return VerifyOutcome("verified", computed, "verify_ok")
    if judged.verdict == "wrong":
        return VerifyOutcome("mismatch", computed, "verify_mismatch")
    return VerifyOutcome("uncertain", computed, judged.reason)
