"""Final cleanup pass: turn JS-flavoured AST into Python-ready AST.

Transforms:
- ``===`` -> ``==``, ``!==`` -> ``!=``
- ``null`` / ``undefined`` literals -> ``None``
- ``typeof x === 'string'`` -> ``isinstance(x, str)`` (and the other
  primitive types).
- Logical ``&&`` / ``||`` / ``!`` -> ``and`` / ``or`` / ``not`` (the
  emitter prints these directly, this pass just normalizes the op string).
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import ast_nodes as A


_TYPEOF_MAP = {
    "string": "str",
    "number": "float",
    "boolean": "bool",
    "object": "dict",
    "function": "callable",
    "undefined": "type(None)",
}


def apply(node: Any, ctx: Dict[str, Any]) -> Any:
    return _rewrite(node)


def _rewrite(node: Any) -> Any:
    if isinstance(node, list):
        return [_rewrite(x) for x in node]
    if not isinstance(node, A.Node):
        return node

    # Recurse first.
    for field_name in _field_names(node):
        val = getattr(node, field_name, None)
        if isinstance(val, A.Node):
            setattr(node, field_name, _rewrite(val))
        elif isinstance(val, list):
            setattr(node, field_name, [_rewrite(x) for x in val])

    if isinstance(node, A.BinaryOp):
        return _rewrite_binop(node)
    if isinstance(node, A.Literal):
        if node.kind in ("null", "undefined"):
            return A.Literal(value=None, kind="none")
    return node


def _rewrite_binop(node: A.BinaryOp) -> A.Node:
    # typeof x === 'string'  -> isinstance(x, str)
    if node.op in ("===", "==", "!==", "!="):
        typeof_match = _match_typeof_eq(node)
        if typeof_match is not None:
            operand, py_type, negate = typeof_match
            call = A.Call(
                callee=A.Ident(name="isinstance"),
                args=[operand, A.Ident(name=py_type)],
            )
            if negate:
                return A.UnaryOp(op="!", operand=call, prefix=True)
            return call
        node.op = "==" if node.op in ("===", "==") else "!="
    return node


def _match_typeof_eq(node: A.BinaryOp):
    """If ``node`` is ``typeof x === 'literal'`` return ``(x, py_type, negate)``."""
    if not isinstance(node.left, A.UnaryOp) or node.left.op != "typeof":
        return None
    if not isinstance(node.right, A.Literal) or node.right.kind != "string":
        return None
    py_type = _TYPEOF_MAP.get(node.right.value)
    if py_type is None:
        return None
    negate = node.op in ("!==", "!=")
    return node.left.operand, py_type, negate


def _field_names(node: A.Node) -> List[str]:
    return [f for f in getattr(node, "__dataclass_fields__", {}).keys()
            if f != "src_range"]
