"""Apply import-map rewrites to the AST.

Reads ``ctx['import_map']`` (loaded from a scaffold JSON) and rewrites:

- ``obj.method(args)`` when ``method`` is listed under ``methods``:
    * ``{"op": "+"}``     -> ``obj + args[0]``
    * ``{"call": "fn"}``  -> ``fn(obj, *args)``
    * ``{"pyexpr": "$receiver == 0"}`` -> raw Python expression via ``RawPy``.
- ``SomeCall(args)`` matching one of the ``calls`` pattern keys (e.g.
  ``"sortBy($a,$k)"``) -> raw Python expression.
- ``new Foo(...)`` likewise via a ``"new Foo($x)"`` pattern.

Any imported symbol that actually appears in the file (``Ident.name``) is
recorded on ``ctx['imports']`` as a ``(python_module, symbol, alias)``
tuple so the emitter can emit ``from <module> import <symbol> [as <alias>]``
lines later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .. import ast_nodes as A


@dataclass
class RawPy(A.Node):
    """A raw Python expression snippet that the emitter prints verbatim."""
    text: str = ""


# Hard-coded fallback imports for identifiers that may appear in pyexpr
# templates without a dedicated call rule (e.g. ``timedelta``, ``deepcopy``).
# Values are ``(python_module, symbol)`` pairs. These do NOT reference any
# project names — only Python stdlib / generic helpers.
_FALLBACK_IMPORTS: Dict[str, Tuple[str, str]] = {
    "deepcopy": ("copy", "deepcopy"),
    "timedelta": ("datetime", "timedelta"),
    "datetime": ("datetime", "datetime"),
    "date": ("datetime", "date"),
}


def apply(node: Any, ctx: Dict[str, Any]) -> Any:
    """Rewrite ``node`` per the import-map rules. Returns the new node."""
    import_map = ctx.get("import_map", {}) or {}
    methods = import_map.get("methods", {}) or {}
    calls = import_map.get("calls", {}) or {}
    imports_cfg = import_map.get("imports", {}) or {}

    # Build a symbol registry: alias -> (module, symbol_in_module).
    symbol_registry: Dict[str, Tuple[str, str]] = {}
    alias_set: Set[str] = set()
    for _js_module, spec in imports_cfg.items():
        py_mod = spec.get("python")
        if not py_mod:
            continue
        for _js_name, alias in (spec.get("symbols") or {}).items():
            if alias is None:
                continue
            symbol_registry[alias] = (py_mod, alias)
            alias_set.add(alias)
    ctx["imported_symbols"] = alias_set

    used_imports: Set[Tuple[str, str, Optional[str]]] = set(ctx.get("imports", set()))

    # Compile call patterns.
    call_patterns = [
        (_compile_pattern(k), v.get("py", "")) for k, v in calls.items()
    ]

    def rec(n: Any) -> Any:
        return _rewrite(n, rec, methods, call_patterns)

    new_node = rec(node)

    # Scan for identifier usages after rewrite to populate imports.
    _scan_identifiers(new_node, symbol_registry, used_imports)
    _scan_rawpy(new_node, symbol_registry, used_imports)

    ctx["imports"] = used_imports
    return new_node


# ---------------------------------------------------------------------------
# Rewrite core
# ---------------------------------------------------------------------------


def _rewrite(node, rec, methods, call_patterns):
    if isinstance(node, list):
        return [rec(x) for x in node]
    if not isinstance(node, A.Node):
        return node
    if isinstance(node, RawPy):
        return node

    # Recurse into children first so inner calls get rewritten.
    for field_name in _field_names(node):
        val = getattr(node, field_name, None)
        if isinstance(val, A.Node):
            setattr(node, field_name, rec(val))
        elif isinstance(val, list):
            setattr(node, field_name, [rec(x) for x in val])

    # Method-call rewrites: obj.method(args)
    if isinstance(node, A.Call) and isinstance(node.callee, A.Member):
        method_name = node.callee.prop
        if method_name in methods:
            rule = methods[method_name]
            receiver = node.callee.obj
            return _apply_method_rule(rule, receiver, node.args)

    # NewExpr -> check ``new Foo($x)`` style patterns.
    if isinstance(node, A.NewExpr):
        replaced = _try_call_pattern(node, call_patterns, is_new=True)
        if replaced is not None:
            return replaced

    # Call -> ``sortBy($a,$k)`` etc.
    if isinstance(node, A.Call):
        replaced = _try_call_pattern(node, call_patterns, is_new=False)
        if replaced is not None:
            return replaced

    return node


def _apply_method_rule(rule: Dict[str, Any], receiver: Any, args: List[Any]) -> Any:
    if "op" in rule:
        right = args[0] if args else A.Literal(value=0, kind="number")
        return A.BinaryOp(op=rule["op"], left=receiver, right=right)
    if "call" in rule:
        return A.Call(callee=A.Ident(name=rule["call"]), args=[receiver] + list(args))
    if "pyexpr" in rule:
        text = rule["pyexpr"]
        text = text.replace("$receiver", "({" + "RECEIVER" + "})")
        # Build via substitution using _render_subnode from emitter-side.
        # Simpler: emit a RawPy with placeholders filled by rendering
        # ourselves right now — but we don't have the emitter yet. Use a
        # small local renderer for the specific sub-expressions we receive.
        rendered = _expand_pyexpr(rule["pyexpr"], receiver, args)
        return RawPy(text=rendered)
    return A.Call(callee=A.Ident(name=str(rule)), args=[receiver] + list(args))


# ---------------------------------------------------------------------------
# Pattern matching for ``calls`` rules
# ---------------------------------------------------------------------------


@dataclass
class _CompiledPattern:
    head: str             # function name or constructor name
    is_new: bool          # True if pattern starts with ``new``
    holes: List[str]      # ordered argument hole names (without $)


def _compile_pattern(pat: str) -> _CompiledPattern:
    """Parse patterns like ``"sortBy($a,$k)"`` or ``"new Big($x)"``.

    We tokenize loosely and capture identifier/placeholder argument list.
    """
    pat = pat.strip()
    is_new = False
    if pat.startswith("new "):
        is_new = True
        pat = pat[4:].lstrip()
    # head (function or class name) then '(' args ')'
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", pat)
    if not m:
        return _CompiledPattern(head="", is_new=is_new, holes=[])
    head = m.group(1)
    inside = m.group(2).strip()
    holes: List[str] = []
    if inside:
        for piece in inside.split(","):
            piece = piece.strip()
            if piece.startswith("$"):
                holes.append(piece[1:])
            else:
                holes.append("_lit_" + piece)
    return _CompiledPattern(head=head, is_new=is_new, holes=holes)


def _try_call_pattern(node, call_patterns, is_new: bool):
    callee = node.callee
    name = None
    if isinstance(callee, A.Ident):
        name = callee.name
    if name is None:
        return None
    for pattern, py_template in call_patterns:
        if pattern.head != name or pattern.is_new != is_new:
            continue
        if len(pattern.holes) != len(node.args):
            continue
        bindings = dict(zip(pattern.holes, node.args))
        text = _substitute_template(py_template, bindings)
        return RawPy(text=text)
    return None


def _substitute_template(template: str, bindings: Dict[str, Any]) -> str:
    def repl(match):
        hole = match.group(1)
        val = bindings.get(hole)
        if val is None:
            return "None"
        return _render_subnode(val)
    return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", repl, template)


# ---------------------------------------------------------------------------
# pyexpr expansion ($receiver, $arg0, $arg1, ...)
# ---------------------------------------------------------------------------


def _expand_pyexpr(template: str, receiver: Any, args: List[Any]) -> str:
    bindings: Dict[str, Any] = {"receiver": receiver}
    for i, a in enumerate(args):
        bindings[f"arg{i}"] = a
    return _substitute_template(template, bindings)


# ---------------------------------------------------------------------------
# Lightweight node renderer (used to inline sub-expressions into RawPy text)
# ---------------------------------------------------------------------------


def _render_subnode(node: Any) -> str:
    """Minimal node-to-Python renderer for the subset that appears inside
    ``pyexpr``/``calls`` templates. Falls back to ``<?>`` for unknown
    shapes — emitter will still print the outer structure and tests will
    catch regressions.
    """
    if isinstance(node, RawPy):
        return node.text
    if isinstance(node, A.Ident):
        return _ident_name(node.name)
    if isinstance(node, A.Literal):
        return _render_literal(node)
    if isinstance(node, A.Member):
        return f"{_render_subnode(node.obj)}.{node.prop}"
    if isinstance(node, A.Index):
        return f"{_render_subnode(node.obj)}[{_render_subnode(node.key)}]"
    if isinstance(node, A.Call):
        args = ", ".join(_render_subnode(a) for a in node.args)
        return f"{_render_subnode(node.callee)}({args})"
    if isinstance(node, A.NewExpr):
        args = ", ".join(_render_subnode(a) for a in node.args)
        return f"{_render_subnode(node.callee)}({args})"
    if isinstance(node, A.BinaryOp):
        op = {"===": "==", "!==": "!="}.get(node.op, node.op)
        return f"({_render_subnode(node.left)} {op} {_render_subnode(node.right)})"
    if isinstance(node, A.UnaryOp):
        op = {"!": "not "}.get(node.op, node.op)
        return f"({op}{_render_subnode(node.operand)})"
    if isinstance(node, A.Arrow):
        return _render_arrow(node)
    if isinstance(node, A.Array):
        return "[" + ", ".join(_render_subnode(i) for i in node.items) + "]"
    return "None"


def _ident_name(n: str) -> str:
    if n == "this":
        return "self"
    if n == "super":
        return "super()"
    return n


def _render_literal(lit: A.Literal) -> str:
    k = lit.kind
    if k == "string":
        return repr(lit.value)
    if k == "number":
        return str(lit.value)
    if k == "bool":
        return "True" if lit.value else "False"
    if k in ("null", "undefined", "none"):
        return "None"
    return repr(lit.value)


def _render_arrow(arrow: A.Arrow) -> str:
    params = ", ".join(
        _ident_name(p.name) if isinstance(p.name, str) else "_arg"
        for p in arrow.params
    )
    if arrow.expr_body or not isinstance(arrow.body, A.Block):
        body = arrow.body if not isinstance(arrow.body, A.Block) else arrow.body
        return f"(lambda {params}: {_render_subnode(body)})"
    return f"(lambda {params}: None)"


# ---------------------------------------------------------------------------
# Import collection
# ---------------------------------------------------------------------------


_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def _scan_identifiers(node, registry, used):
    for ident in _walk_idents(node):
        if ident in registry:
            mod, sym = registry[ident]
            used.add((mod, sym, None))


def _scan_rawpy(node, registry, used):
    for text in _walk_rawpy(node):
        for m in _IDENT_RE.finditer(text):
            name = m.group(1)
            if name in registry:
                mod, sym = registry[name]
                used.add((mod, sym, None))
            elif name in _FALLBACK_IMPORTS:
                mod, sym = _FALLBACK_IMPORTS[name]
                used.add((mod, sym, None))


def _walk_idents(node):
    if isinstance(node, A.Ident):
        yield node.name
        return
    if isinstance(node, list):
        for x in node:
            yield from _walk_idents(x)
        return
    if not isinstance(node, A.Node):
        return
    for f in _field_names(node):
        yield from _walk_idents(getattr(node, f, None))


def _walk_rawpy(node):
    if isinstance(node, RawPy):
        yield node.text
        return
    if isinstance(node, list):
        for x in node:
            yield from _walk_rawpy(x)
        return
    if not isinstance(node, A.Node):
        return
    for f in _field_names(node):
        yield from _walk_rawpy(getattr(node, f, None))


def _field_names(node: A.Node) -> List[str]:
    return [f for f in getattr(node, "__dataclass_fields__", {}).keys()
            if f != "src_range"]
