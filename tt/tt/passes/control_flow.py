"""Control-flow normalization pass.

Rewrites JS control structures into shapes the Python emitter can print
directly. Operates recursively over any node.

Transforms:
- ``arr.forEach((x) => body)`` -> ``for x in arr: body``
- C-style ``for (let i=A; i<B; i++)`` -> ``for i in range(A, B): body``
  (falls back to a ``While`` form when the pattern doesn't match).
- ``for (let x of y)`` / ``for (let x in y)`` -> kept as ``ForOf`` (the
  emitter renders both as ``for x in y:`` in Python).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import ast_nodes as A


def apply(node: Any, ctx: Dict[str, Any]) -> Any:
    return _rewrite(node, ctx)


def _rewrite(node: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_rewrite(x, ctx) for x in node]
    if not isinstance(node, A.Node):
        return node

    # ExprStmt wrapping a .forEach() call -> ForOf
    if isinstance(node, A.ExprStmt):
        rewritten = _try_foreach(node.expr, ctx)
        if rewritten is not None:
            return rewritten
        node.expr = _rewrite(node.expr, ctx)
        return node

    if isinstance(node, A.ForC):
        lowered = _lower_forc(node, ctx)
        return lowered

    # Generic recursion over child fields.
    for field_name in _field_names(node):
        val = getattr(node, field_name, None)
        if isinstance(val, A.Node):
            setattr(node, field_name, _rewrite(val, ctx))
        elif isinstance(val, list):
            setattr(node, field_name, [_rewrite(x, ctx) for x in val])
    return node


def _field_names(node: A.Node) -> List[str]:
    return [f for f in getattr(node, "__dataclass_fields__", {}).keys()
            if f != "src_range"]


def _try_foreach(expr: Any, ctx: Dict[str, Any]) -> Optional[A.Node]:
    """If ``expr`` is ``arr.forEach((x) => body)``, return a ForOf."""
    if not isinstance(expr, A.Call):
        return None
    callee = expr.callee
    if not isinstance(callee, A.Member):
        return None
    if callee.prop != "forEach":
        return None
    if len(expr.args) != 1:
        return None
    arrow = expr.args[0]
    if not isinstance(arrow, A.Arrow) or not arrow.params:
        return None
    first = arrow.params[0]
    if isinstance(first.name, str):
        var = A.Ident(name=first.name)
    else:
        var = first.name  # Destructure
    body = arrow.body
    if not isinstance(body, A.Block):
        body = A.Block(stmts=[A.ExprStmt(expr=body)])
    body = _rewrite(body, ctx)
    iter_expr = _rewrite(callee.obj, ctx)
    return A.ForOf(var_name=var, iter=iter_expr, body=body, is_in=False)


def _lower_forc(node: A.ForC, ctx: Dict[str, Any]) -> A.Node:
    """Try to detect ``for (let i=A; i<B; i++)`` and emit a range-loop.

    Falls back to a ``While`` form (with update appended to body) when the
    pattern doesn't match.
    """
    range_form = _match_range_loop(node)
    if range_form is not None:
        var, start, stop = range_form
        body = _rewrite(node.body, ctx)
        if not isinstance(body, A.Block):
            body = A.Block(stmts=[body])
        range_call = A.Call(
            callee=A.Ident(name="range"),
            args=[start, stop],
        )
        return A.ForOf(var_name=A.Ident(name=var), iter=range_call,
                       body=body, is_in=False)

    # Fallback: init; while(cond): body; update
    body = node.body
    if not isinstance(body, A.Block):
        body = A.Block(stmts=[body])
    if node.update is not None:
        body = A.Block(stmts=list(body.stmts) + [A.ExprStmt(expr=node.update)])
    body = _rewrite(body, ctx)
    cond = node.cond if node.cond is not None else A.Literal(value=True, kind="bool")
    cond = _rewrite(cond, ctx)
    loop = A.While(cond=cond, body=body)
    if node.init is not None:
        init = _rewrite(node.init, ctx)
        return A.Block(stmts=[init, loop])
    return loop


def _match_range_loop(node: A.ForC):
    """Return (var_name, start, stop) if node matches ``for (let i=A; i<B; i++)``."""
    init = node.init
    if not isinstance(init, A.VarDecl) or not isinstance(init.name, A.Ident):
        return None
    if init.init is None:
        return None
    var = init.name.name
    start = init.init

    cond = node.cond
    if not isinstance(cond, A.BinaryOp) or cond.op not in ("<", "<="):
        return None
    if not isinstance(cond.left, A.Ident) or cond.left.name != var:
        return None
    stop = cond.right
    if cond.op == "<=":
        # Python range is exclusive; add 1 to stop.
        stop = A.BinaryOp(op="+", left=stop, right=A.Literal(value=1, kind="number"))

    update = node.update
    # Accept i++, ++i, i += 1
    if isinstance(update, A.UnaryOp) and update.op == "++" and \
            isinstance(update.operand, A.Ident) and update.operand.name == var:
        return var, start, stop
    if isinstance(update, A.AssignOp) and update.op == "+=" and \
            isinstance(update.target, A.Ident) and update.target.name == var:
        if isinstance(update.value, A.Literal) and update.value.value == 1:
            return var, start, stop
    return None
