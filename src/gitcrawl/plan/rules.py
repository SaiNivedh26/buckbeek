"""A tiny, safe expression language for hard rules.

    tests.file_count == 0
    not ci.has_ci or ci.run_success_rate < 0.2
    contributors.count <= 1 and repo.stars < 10

A name is a check id from the plan and the attribute is a field of that
check's collector output. Allowed: comparisons, and/or/not, numbers,
booleans (true/false as well as True/False), strings, null/None. Nothing
else — no calls, subscripts, arithmetic or imports. Expressions are parsed
with `ast` and walked against a whitelist; they are never `eval`'d.

A rule whose facts are missing or errored is *undetermined*: it neither
fires nor silently passes, and the report says so.
"""

from __future__ import annotations

import ast
import operator
from typing import Any

from gitcrawl.collectors.base import Fact


class RuleError(Exception):
    pass


_LITERAL_NAMES = {"true": True, "false": False, "null": None, "none": None}
_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class Undetermined(Exception):
    """A referenced fact is missing/errored or a comparison can't be made."""


def parse(expr: str) -> ast.Expression:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise RuleError(f"not a valid rule expression: {expr!r} ({e.msg})") from e
    for node in ast.walk(tree):
        _check_node(node, expr)
    return tree


def _check_node(node: ast.AST, expr: str) -> None:
    allowed = (
        ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub,
        ast.Compare, ast.Constant, ast.Name, ast.Attribute, ast.Load,
        *_COMPARE_OPS,
    )  # fmt: skip
    if not isinstance(node, allowed):
        raise RuleError(f"{type(node).__name__} is not allowed in rule {expr!r}")
    is_neg = isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
    if is_neg and not isinstance(node.operand, ast.Constant):  # type: ignore[attr-defined]
        raise RuleError(f"unary minus is only allowed on numbers in rule {expr!r}")
    if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool, type(None))):
        raise RuleError(f"unsupported literal {node.value!r} in rule {expr!r}")
    if isinstance(node, ast.Attribute) and not isinstance(node.value, ast.Name):
        raise RuleError(f"only check_id.field references are allowed in rule {expr!r}")


def references(expr: str) -> list[tuple[str, str]]:
    """(check_id, field) pairs an expression reads, in order."""
    tree = parse(expr)
    attrs = [
        node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    ]
    attrs.sort(key=lambda n: (n.lineno, n.col_offset))  # ast.walk is breadth-first; keep source order
    return list(dict.fromkeys((n.value.id, n.attr) for n in attrs))  # type: ignore[attr-defined]


def validate(expr: str, check_fields: dict[str, set[str]]) -> list[str]:
    """Plan-time: expression parses, every reference is a known check and a real output field."""
    try:
        tree = parse(expr)
    except RuleError as e:
        return [str(e)]
    errors: list[str] = []
    attr_names = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in attr_names and node.id.lower() not in _LITERAL_NAMES:
            errors.append(f"bare name {node.id!r} in rule {expr!r}: use check_id.field")
    for check_id, field in references(expr):
        if check_id not in check_fields:
            errors.append(f"rule {expr!r} references unknown check {check_id!r}")
        elif field not in check_fields[check_id]:
            errors.append(
                f"rule {expr!r}: check {check_id!r} has no field {field!r} "
                f"(available: {', '.join(sorted(check_fields[check_id]))})"
            )
    return errors


def evaluate(expr: str, facts: dict[str, Fact]) -> bool | None:
    """True/False, or None when undetermined (missing/errored fact, bad comparison)."""
    tree = parse(expr)
    try:
        return bool(_eval(tree.body, facts))
    except Undetermined:
        return None


def _eval(node: ast.AST, facts: dict[str, Fact]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key in _LITERAL_NAMES:
            return _LITERAL_NAMES[key]
        raise Undetermined(f"bare name {node.id!r}")
    if isinstance(node, ast.Attribute):
        fact = facts.get(node.value.id)  # type: ignore[attr-defined]
        if fact is None or not fact.ok or node.attr not in fact.data:
            raise Undetermined(f"no usable fact for {node.value.id}.{node.attr}")  # type: ignore[attr-defined]
        return fact.data[node.attr]
    if isinstance(node, ast.UnaryOp):
        value = _eval(node.operand, facts)
        return (not value) if isinstance(node.op, ast.Not) else -value
    if isinstance(node, ast.BoolOp):
        # Short-circuit like Python, but an undetermined operand only matters
        # if the result actually depends on it.
        is_and = isinstance(node.op, ast.And)
        undetermined = False
        for value_node in node.values:
            try:
                value = bool(_eval(value_node, facts))
            except Undetermined:
                undetermined = True
                continue
            if is_and and not value:
                return False
            if not is_and and value:
                return True
        if undetermined:
            raise Undetermined("depends on an undetermined operand")
        return is_and
    if isinstance(node, ast.Compare):
        left = _eval(node.left, facts)
        for op, right_node in zip(node.ops, node.comparators, strict=True):
            right = _eval(right_node, facts)
            try:
                if not _COMPARE_OPS[type(op)](left, right):
                    return False
            except TypeError as e:
                raise Undetermined(f"cannot compare {left!r} and {right!r}") from e
            left = right
        return True
    raise Undetermined(f"unsupported node {type(node).__name__}")
