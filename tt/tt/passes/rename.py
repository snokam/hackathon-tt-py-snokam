"""Identifier renaming pass.

Responsibilities:
- ``this`` -> ``self`` (always).
- ``super`` -> ``super()`` is handled by the emitter via keyword lookup.
- Configured identifier mappings from ``ctx['import_map']['identifiers']``.
- Default ``camelCase`` -> ``snake_case`` for all other identifiers unless
  the name appears in ``ctx['keep_names']`` (e.g. the public interface
  method names from the stub class).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Set

from .. import ast_nodes as A


_CAMEL_RE1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE2 = re.compile(r"([a-z0-9])([A-Z])")


def camel_to_snake(name: str) -> str:
    """Convert ``camelCase`` / ``PascalCase`` to ``snake_case``.

    Fully upper-case identifiers (e.g. ``DATE_FORMAT``) are returned
    unchanged. Single-word identifiers are also unchanged.
    """
    if not name or "_" in name and name.isupper():
        return name
    if name.isupper():
        return name
    # Keep leading underscores/dollar signs.
    prefix_len = 0
    while prefix_len < len(name) and name[prefix_len] in ("_", "$"):
        prefix_len += 1
    core = name[prefix_len:]
    step1 = _CAMEL_RE1.sub(r"\1_\2", core)
    step2 = _CAMEL_RE2.sub(r"\1_\2", step1)
    return name[:prefix_len] + step2.lower()


def apply(node: Any, ctx: Dict[str, Any]) -> Any:
    """Recursively rewrite identifiers in ``node``. Returns ``node``."""
    id_map: Dict[str, str] = dict(ctx.get("import_map", {}).get("identifiers", {}))
    keep: Set[str] = set(ctx.get("keep_names", set()))
    # Imported symbols keep their mapped python_alias (set by libmap scan).
    keep |= set(ctx.get("imported_symbols", set()))

    def rename_name(name: str) -> str:
        if name == "this":
            return "self"
        if name == "super":
            return "super"
        if name in id_map:
            return id_map[name]
        if name in keep:
            return name
        if name.startswith("_"):
            return name
        return camel_to_snake(name)

    _walk(node, rename_name)
    return node


_SPECIAL_HANDLERS = {}


def _walk(node: Any, rename_name) -> None:
    handler = _SPECIAL_HANDLERS.get(type(node))
    if handler is not None:
        handler(node, rename_name)
        return
    if isinstance(node, A.Ident):
        node.name = rename_name(node.name)
        return
    if isinstance(node, A.Node):
        for field_name in _field_names(node):
            _walk(getattr(node, field_name, None), rename_name)
        return
    if isinstance(node, list):
        for it in node:
            _walk(it, rename_name)


def _walk_member(node: A.Member, rename_name) -> None:
    _walk(node.obj, rename_name)
    node.prop = rename_name(node.prop)


def _walk_func(node, rename_name) -> None:
    node.name = rename_name(node.name)
    for p in node.params:
        _rename_param(p, rename_name)
    _walk(node.body, rename_name)


def _walk_arrow(node: A.Arrow, rename_name) -> None:
    for p in node.params:
        _rename_param(p, rename_name)
    _walk(node.body, rename_name)


def _walk_var(node: A.VarDecl, rename_name) -> None:
    if isinstance(node.name, A.Ident):
        node.name.name = rename_name(node.name.name)
    elif isinstance(node.name, A.Destructure):
        node.name.targets = [rename_name(t) for t in node.name.targets]
    if node.init is not None:
        _walk(node.init, rename_name)


def _walk_destructure(node: A.Destructure, rename_name) -> None:
    node.targets = [rename_name(t) for t in node.targets]
    if node.init is not None:
        _walk(node.init, rename_name)


def _walk_forof(node: A.ForOf, rename_name) -> None:
    var = node.var_name
    if isinstance(var, A.Ident):
        var.name = rename_name(var.name)
    elif isinstance(var, A.Destructure):
        var.targets = [rename_name(t) for t in var.targets]
    else:
        _walk(var, rename_name)
    _walk(node.iter, rename_name)
    _walk(node.body, rename_name)


def _walk_object(node: A.Object, rename_name) -> None:
    new_pairs = []
    for k, v in node.pairs:
        if not isinstance(k, str):
            _walk(k, rename_name)
        _walk(v, rename_name)
        new_pairs.append((k, v))
    node.pairs = new_pairs


_SPECIAL_HANDLERS.update({
    A.Member: _walk_member,
    A.MethodDecl: _walk_func,
    A.FuncDecl: _walk_func,
    A.Arrow: _walk_arrow,
    A.VarDecl: _walk_var,
    A.Destructure: _walk_destructure,
    A.ForOf: _walk_forof,
    A.Object: _walk_object,
})


def _rename_param(p: A.Param, rename_name) -> None:
    if isinstance(p.name, str):
        if p.name.startswith("*"):
            p.name = "*" + rename_name(p.name.lstrip("*"))
        else:
            p.name = rename_name(p.name)
    elif isinstance(p.name, A.Destructure):
        p.name.targets = [rename_name(t) for t in p.name.targets]
    if p.default is not None:
        _walk(p.default, rename_name)


def _field_names(node: A.Node):
    # dataclass fields minus src_range
    return [f for f in getattr(node, "__dataclass_fields__", {}).keys()
            if f != "src_range"]
