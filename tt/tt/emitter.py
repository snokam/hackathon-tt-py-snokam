"""AST -> Python source emitter.

Per-method entry point is :func:`emit_method`. The runner calls this once
per class member; failures raise :class:`EmitError` with a short reason
so the merger can fall back to the stub method.

The emitter wires the four AST passes together before printing:

    1. rename        — ``this`` -> ``self``, camelCase -> snake_case, etc.
    2. control_flow  — lower C-style for / forEach to Python-friendly forms.
    3. libmap        — apply import-map rewrites, collect required imports.
    4. py_ready      — final JS-isms -> Python (``===`` -> ``==`` etc.).

Imports collected across the translation run are surfaced through
:func:`collect_imports`, which the runner calls once at the end.
"""

from __future__ import annotations

import ast as _pyast
import copy
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import ast_nodes as A
from .passes import rename as rename_pass
from .passes import control_flow as cf_pass
from .passes import libmap as libmap_pass
from .passes import py_ready as pyready_pass
from .passes.libmap import RawPy


class EmitError(Exception):
    """Raised when a method cannot be emitted. The runner catches it
    per-method so the stub remains in the output file.
    """

    def __init__(self, method_name: str, reason: str):
        self.method_name = method_name
        self.reason = reason
        super().__init__(f"{method_name}: {reason}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_method(method: A.MethodDecl, ctx: Dict[str, Any]) -> str:
    """Emit a single method as Python source (indented for a class body).

    Returns a block of text whose lines start with 4 spaces (``def``) and
    whose body lines start with 8 spaces. Raises :class:`EmitError` on
    any failure.
    """
    name = getattr(method, "name", "<anon>")
    try:
        # 1. Work on a deep copy so subsequent methods still see pristine AST.
        node = copy.deepcopy(method)

        # 2. Populate ctx defaults lazily.
        ctx.setdefault("imports", set())
        if "keep_names" not in ctx:
            ctx["keep_names"] = _load_keep_names(ctx)
        # Pre-populate the set of imported symbols so rename doesn't mangle
        # them (e.g. ``Big`` -> ``big``).
        _prime_imported_symbols(ctx)

        # 3. Run passes.
        rename_pass.apply(node, ctx)
        cf_pass.apply(node, ctx)
        node = libmap_pass.apply(node, ctx)
        node = pyready_pass.apply(node, ctx)

        # 4. Print.
        emitter = _Emitter()
        text = emitter.method(node)
        return text
    except EmitError:
        raise
    except Exception as exc:  # pragma: no cover
        raise EmitError(name, str(exc))


def collect_imports(ctx: Dict[str, Any]) -> List[str]:
    """Turn ``ctx['imports']`` into a sorted list of ``from X import Y`` lines.

    Stdlib modules appear first, then anything else.
    """
    items: Set[Tuple[str, str, Optional[str]]] = set(ctx.get("imports", set()))
    if not items:
        return []

    def is_stdlib(mod: str) -> bool:
        root = mod.split(".")[0]
        return root in {"copy", "datetime", "decimal", "math", "re", "typing",
                        "collections", "itertools", "functools"}

    lines: List[str] = []
    for mod, sym, alias in sorted(items):
        if alias and alias != sym:
            lines.append(f"from {mod} import {sym} as {alias}")
        else:
            lines.append(f"from {mod} import {sym}")

    # Dedup while preserving stdlib-first ordering.
    seen: Set[str] = set()
    deduped: List[str] = []
    for group in (True, False):
        for line in lines:
            mod = line.split()[1]
            if is_stdlib(mod) != group:
                continue
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
    return deduped


# ---------------------------------------------------------------------------
# keep-names loader (reads the stub class's public method names so we don't
# rename them away from the interface)
# ---------------------------------------------------------------------------


def _prime_imported_symbols(ctx: Dict[str, Any]) -> None:
    """Seed ``ctx['imported_symbols']`` from the import-map configuration."""
    aliases: Set[str] = set(ctx.get("imported_symbols", set()))
    for _mod_js, spec in (ctx.get("import_map", {}).get("imports", {}) or {}).items():
        if not spec.get("python"):
            continue
        for _js_name, alias in (spec.get("symbols") or {}).items():
            if alias:
                aliases.add(alias)
    ctx["imported_symbols"] = aliases


def _load_keep_names(ctx: Dict[str, Any]) -> Set[str]:
    """Best-effort load of method names from the stub class file."""
    names: Set[str] = set(ctx.get("keep_names", set()))
    stub_src = ctx.get("stub_src")
    if not stub_src:
        return names
    try:
        tree = _pyast.parse(stub_src)
    except SyntaxError:
        return names
    for node in _pyast.walk(tree):
        if isinstance(node, _pyast.ClassDef):
            for item in node.body:
                if isinstance(item, (_pyast.FunctionDef, _pyast.AsyncFunctionDef)):
                    names.add(item.name)
    return names


# ---------------------------------------------------------------------------
# Visitor — pure "render to text" walker
# ---------------------------------------------------------------------------


class _Emitter:
    def __init__(self) -> None:
        self.indent_unit = "    "

    # ---- public ----
    def method(self, m: A.MethodDecl) -> str:
        sig = self._render_method_signature(m)
        body_lines = self._render_body(m.body, m.params, depth=2)
        if not body_lines:
            body_lines = [self.indent_unit * 2 + "pass"]
        header = self.indent_unit + sig
        return header + "\n" + "\n".join(body_lines) + "\n"

    # ---- signatures ----
    def _render_method_signature(self, m: A.MethodDecl) -> str:
        parts = ["self"]
        body_prelude: List[str] = []
        for p in m.params:
            name = p.name
            if isinstance(name, A.Destructure):
                # Keep a placeholder; body prelude will unpack.
                parts.append(f"_arg{len(parts) - 1}")
            elif isinstance(name, str):
                if name.startswith("*"):
                    parts.append(name)
                else:
                    txt = name
                    if p.default is not None:
                        txt += "=" + self.expr(p.default)
                    parts.append(txt)
            else:
                parts.append("_unknown")
        joined = ", ".join(parts)
        prefix = "async def " if m.is_async else "def "
        method_name = m.name
        if m.is_constructor:
            method_name = "__init__"
        return f"{prefix}{method_name}({joined}):"

    def _render_body(self, block: A.Block, params, depth: int) -> List[str]:
        lines: List[str] = []

        # Synthesise destructuring prelude for any destructured params.
        for idx, p in enumerate(params):
            if isinstance(p.name, A.Destructure):
                alias = f"_arg{idx}"
                for t in p.name.targets:
                    lines.append(self.indent_unit * depth +
                                 f"{t} = {alias}[{t!r}]")

        body_lines = self.stmt(block, depth)
        lines.extend(body_lines)
        return lines

    # ---- statements ----
    def stmt(self, node: Any, depth: int) -> List[str]:
        handler = _STMT_HANDLERS.get(type(node))
        if handler is None:
            raise EmitError(
                "<stmt>", f"unsupported statement: {type(node).__name__}"
            )
        return handler(self, node, depth)

    def _stmt_block(self, node: A.Block, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        out: List[str] = []
        for s in node.stmts:
            out.extend(self.stmt(s, depth))
        if not out:
            out.append(ind + "pass")
        return out

    def _stmt_var(self, node: A.VarDecl, depth: int) -> List[str]:
        return [self.indent_unit * depth + self._render_var_decl(node)]

    def _stmt_expr(self, node: A.ExprStmt, depth: int) -> List[str]:
        return [self.indent_unit * depth + self.expr(node.expr)]

    def _stmt_return(self, node: A.Return, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        if node.expr is None:
            return [ind + "return"]
        return [ind + "return " + self.expr(node.expr)]

    def _stmt_while(self, node: A.While, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        body = self.stmt(node.body, depth + 1)
        if not body:
            body = [self.indent_unit * (depth + 1) + "pass"]
        return [ind + "while " + self.expr(node.cond) + ":"] + body

    def _stmt_throw(self, node: A.Throw, depth: int) -> List[str]:
        return [self.indent_unit * depth + "raise " + self.expr(node.expr)]

    def _stmt_break(self, node: A.Break, depth: int) -> List[str]:
        return [self.indent_unit * depth + "break"]

    def _stmt_continue(self, node: A.Continue, depth: int) -> List[str]:
        return [self.indent_unit * depth + "continue"]

    def _render_var_decl(self, node: A.VarDecl) -> str:
        if isinstance(node.name, A.Ident):
            name = node.name.name
        elif isinstance(node.name, A.Destructure):
            if node.init is None:
                return ", ".join(node.name.targets) + " = " + ", ".join(
                    ["None"] * len(node.name.targets)
                )
            rhs = self.expr(node.init)
            if node.name.kind == "array":
                return ", ".join(node.name.targets) + " = " + rhs
            # object destructure
            tmp = "_destr"
            lines = [f"{tmp} = {rhs}"]
            for t in node.name.targets:
                lines.append(f"{t} = {tmp}[{t!r}]")
            return "\n".join(lines)
        else:
            raise EmitError("<var>", f"unknown var name: {node.name}")
        if node.init is None:
            return f"{name} = None"
        return f"{name} = {self.expr(node.init)}"

    def _render_if(self, node: A.If, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        lines = [ind + "if " + self.expr(node.cond) + ":"]
        lines.extend(self._block_stmts(node.then, depth + 1))
        cur_else = node.else_
        while isinstance(cur_else, A.If):
            lines.append(ind + "elif " + self.expr(cur_else.cond) + ":")
            lines.extend(self._block_stmts(cur_else.then, depth + 1))
            cur_else = cur_else.else_
        if cur_else is not None:
            lines.append(ind + "else:")
            lines.extend(self._block_stmts(cur_else, depth + 1))
        return lines

    def _block_stmts(self, node: Any, depth: int) -> List[str]:
        if isinstance(node, A.Block):
            out = self.stmt(node, depth)
        else:
            out = self.stmt(node, depth)
        if not out:
            out = [self.indent_unit * depth + "pass"]
        return out

    def _render_for(self, node: A.ForOf, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        var = node.var_name
        if isinstance(var, A.Ident):
            var_text = var.name
        elif isinstance(var, A.Destructure):
            var_text = ", ".join(var.targets)
        else:
            var_text = self.expr(var)
        header = ind + f"for {var_text} in {self.expr(node.iter)}:"
        body = self._block_stmts(node.body, depth + 1)
        return [header] + body

    def _render_try(self, node: A.TryCatch, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        colon = ":"
        lines = [ind + "try" + colon]
        lines.extend(self._block_stmts(node.try_block, depth + 1))
        if node.catch_block is not None:
            cp = node.catch_param or "_exc"
            lines.append(ind + f"except Exception as {cp}" + colon)
            lines.extend(self._block_stmts(node.catch_block, depth + 1))
        if node.finally_block is not None:
            lines.append(ind + "finally" + colon)
            lines.extend(self._block_stmts(node.finally_block, depth + 1))
        return lines

    def _render_funcdecl(self, node: A.FuncDecl, depth: int) -> List[str]:
        ind = self.indent_unit * depth
        params = []
        for p in node.params:
            if isinstance(p.name, str):
                if p.default is not None:
                    params.append(f"{p.name}={self.expr(p.default)}")
                else:
                    params.append(p.name)
            else:
                params.append("_arg")
        head = ind + f"def {node.name}({', '.join(params)}):"
        body = self._block_stmts(node.body, depth + 1)
        return [head] + body

    # ---- expressions ----
    def expr(self, node: Any) -> str:
        if isinstance(node, RawPy):
            return node.text
        handler = _EXPR_HANDLERS.get(type(node))
        if handler is None:
            raise EmitError(
                "<expr>", f"unsupported expression: {type(node).__name__}"
            )
        return handler(self, node)

    def _expr_ident(self, node: A.Ident) -> str:
        if node.name == "self":
            return "self"
        if node.name == "super":
            return "super()"
        return node.name

    def _expr_array(self, node: A.Array) -> str:
        return "[" + ", ".join(self._render_item(x) for x in node.items) + "]"

    def _expr_member(self, node: A.Member) -> str:
        return f"{self.expr(node.obj)}.{node.prop}"

    def _expr_index(self, node: A.Index) -> str:
        return f"{self.expr(node.obj)}[{self.expr(node.key)}]"

    def _expr_call(self, node: A.Call) -> str:
        args = ", ".join(self._render_item(a) for a in node.args)
        return f"{self.expr(node.callee)}({args})"

    def _expr_new(self, node: A.NewExpr) -> str:
        args = ", ".join(self._render_item(a) for a in node.args)
        return f"{self.expr(node.callee)}({args})"

    def _expr_cond(self, node: A.Conditional) -> str:
        return (f"({self.expr(node.a)} if {self.expr(node.cond)} "
                f"else {self.expr(node.b)})")

    def _expr_spread(self, node: A.Spread) -> str:
        return "*" + self.expr(node.expr)

    def _render_item(self, node: Any) -> str:
        return self.expr(node)

    def _render_literal(self, lit: A.Literal) -> str:
        k = lit.kind
        if k == "string":
            return repr(lit.value)
        if k == "number":
            return str(lit.value)
        if k == "bool":
            return "True" if lit.value else "False"
        if k in ("null", "undefined", "none"):
            return "None"
        if k == "regex":
            return repr(lit.value)
        return repr(lit.value)

    def _render_template(self, tpl: A.Template) -> str:
        parts = []
        for i, s in enumerate(tpl.parts):
            parts.append(s.replace("{", "{{").replace("}", "}}"))
            if i < len(tpl.exprs):
                parts.append("{" + self.expr(tpl.exprs[i]) + "}")
        return "f" + repr("".join(parts))

    def _render_object(self, obj: A.Object) -> str:
        if not obj.pairs:
            return "{}"
        pieces: List[str] = []
        for key, val in obj.pairs:
            if key == "__spread__":
                pieces.append("**" + self.expr(val))
                continue
            if isinstance(key, str):
                key_text = repr(key)
            else:
                key_text = self.expr(key)
            pieces.append(f"{key_text}: {self.expr(val)}")
        return "{" + ", ".join(pieces) + "}"

    _PY_BINOPS = {
        "&&": "and", "||": "or", "??": "or",
        "===": "==", "!==": "!=",
    }

    def _render_binop(self, node: A.BinaryOp) -> str:
        op = self._PY_BINOPS.get(node.op, node.op)
        return f"({self.expr(node.left)} {op} {self.expr(node.right)})"

    def _render_unaryop(self, node: A.UnaryOp) -> str:
        op = node.op
        py_op = {"!": "not ", "typeof": "type "}.get(op, op)
        if op in ("++", "--") and not node.prefix:
            # Post-increment as a statement-level tweak; we mimic by
            # returning the operand followed by '+=1' — only valid as
            # an ExprStmt. The caller should have lowered C-for loops.
            delta = "+= 1" if op == "++" else "-= 1"
            return f"{self.expr(node.operand)} {delta}"
        if op in ("++", "--"):
            delta = "+= 1" if op == "++" else "-= 1"
            return f"{self.expr(node.operand)} {delta}"
        return f"({py_op}{self.expr(node.operand)})"

    def _render_assign(self, node: A.AssignOp) -> str:
        op = node.op
        if op == "=":
            return f"{self.expr(node.target)} = {self.expr(node.value)}"
        if op in ("+=", "-=", "*=", "/=", "%=", "**=", "|=", "&=", "^=",
                  "<<=", ">>="):
            return f"{self.expr(node.target)} {op} {self.expr(node.value)}"
        if op == "||=" or op == "??=":
            tgt = self.expr(node.target)
            return f"{tgt} = {tgt} or {self.expr(node.value)}"
        if op == "&&=":
            tgt = self.expr(node.target)
            return f"{tgt} = {tgt} and {self.expr(node.value)}"
        return f"{self.expr(node.target)} = {self.expr(node.value)}"

    def _render_arrow(self, arrow: A.Arrow) -> str:
        params = []
        for p in arrow.params:
            if isinstance(p.name, str):
                params.append(p.name)
            else:
                params.append("_arg")
        param_text = ", ".join(params)
        body = arrow.body
        if arrow.expr_body or not isinstance(body, A.Block):
            if isinstance(body, A.Block):
                raise EmitError("<arrow>", "block arrow outside statement context")
            return f"(lambda {param_text}: {self.expr(body)})"
        # A block body with just a single return is expressible as a lambda.
        if (isinstance(body, A.Block) and len(body.stmts) == 1
                and isinstance(body.stmts[0], A.Return)
                and body.stmts[0].expr is not None):
            return f"(lambda {param_text}: {self.expr(body.stmts[0].expr)})"
        # General block-bodied arrow cannot be emitted as a Python lambda.
        raise EmitError("<arrow>", "block-bodied arrow cannot be emitted as lambda")


_STMT_HANDLERS = {
    A.Block:    _Emitter._stmt_block,
    A.VarDecl:  _Emitter._stmt_var,
    A.ExprStmt: _Emitter._stmt_expr,
    A.Return:   _Emitter._stmt_return,
    A.If:       _Emitter._render_if,
    A.ForOf:    _Emitter._render_for,
    A.While:    _Emitter._stmt_while,
    A.Throw:    _Emitter._stmt_throw,
    A.TryCatch: _Emitter._render_try,
    A.Break:    _Emitter._stmt_break,
    A.Continue: _Emitter._stmt_continue,
    A.FuncDecl: _Emitter._render_funcdecl,
}


_EXPR_HANDLERS = {
    A.Ident:       _Emitter._expr_ident,
    A.Literal:     _Emitter._render_literal,
    A.Template:    _Emitter._render_template,
    A.Array:       _Emitter._expr_array,
    A.Object:      _Emitter._render_object,
    A.Member:      _Emitter._expr_member,
    A.Index:       _Emitter._expr_index,
    A.Call:        _Emitter._expr_call,
    A.NewExpr:     _Emitter._expr_new,
    A.BinaryOp:    _Emitter._render_binop,
    A.UnaryOp:     _Emitter._render_unaryop,
    A.AssignOp:    _Emitter._render_assign,
    A.Conditional: _Emitter._expr_cond,
    A.Arrow:       _Emitter._render_arrow,
    A.Spread:      _Emitter._expr_spread,
}
