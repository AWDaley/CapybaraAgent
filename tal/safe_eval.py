"""A deliberately small expression evaluator for materialized outputs."""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
from typing import Any


class SafeExpressionError(ValueError):
    pass


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_CMPOPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


def evaluate_expression(expression: str, variables: Mapping[str, Any]) -> Any:
    """Evaluate data-only expressions; calls, attributes, and imports are forbidden."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeExpressionError(f"Invalid expression: {exc.msg}") from exc

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id == "dict":
                return dict
            if node.id not in variables or node.id.startswith("_"):
                raise SafeExpressionError(f"Unknown or private name: {node.id}")
            return variables[node.id]
        if isinstance(node, ast.Attribute):
            value = visit(node.value)
            if node.attr.startswith("_"):
                raise SafeExpressionError("Private attributes are forbidden")
            try:
                return getattr(value, node.attr)
            except AttributeError as exc:
                raise SafeExpressionError(f"Unknown attribute: {node.attr}") from exc
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            args = [visit(arg) for arg in node.args]
            if name == "len" and len(args) == 1:
                return len(args[0])
            if name == "hasattr" and len(args) == 2 and isinstance(args[1], str) and not args[1].startswith("_"):
                return hasattr(args[0], args[1])
            if name == "isinstance" and len(args) == 2 and args[1] is dict:
                return isinstance(args[0], dict)
            if name == "list" and len(args) == 1:
                return list(args[0])
            raise SafeExpressionError(f"Call to {name} is forbidden")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and not node.keywords:
            value = visit(node.func.value)
            args = [visit(arg) for arg in node.args]
            if isinstance(value, dict) and 1 <= len(args) <= 2:
                return value.get(*args)
            raise SafeExpressionError("Only dict.get() is permitted")
        if isinstance(node, ast.List):
            return [visit(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(visit(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {visit(key): visit(value) for key, value in zip(node.keys, node.values)}
        if isinstance(node, ast.IfExp):
            return visit(node.body) if visit(node.test) else visit(node.orelse)
        if isinstance(node, ast.Subscript):
            value = visit(node.value)
            index = visit(node.slice)
            try:
                return value[index]
            except (IndexError, KeyError, TypeError) as exc:
                raise SafeExpressionError(f"Invalid subscript: {exc}") from exc
        if isinstance(node, ast.Slice):
            return slice(
                visit(node.lower) if node.lower else None,
                visit(node.upper) if node.upper else None,
                visit(node.step) if node.step else None,
            )
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
            return _UNARYOPS[type(node.op)](visit(node.operand))
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [visit(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare):
            left = visit(node.left)
            for op_node, comparator in zip(node.ops, node.comparators):
                if type(op_node) not in _CMPOPS or not _CMPOPS[type(op_node)](left, visit(comparator)):
                    return False
                left = visit(comparator)
            return True
        raise SafeExpressionError(f"Unsupported expression construct: {type(node).__name__}")

    return visit(tree)
