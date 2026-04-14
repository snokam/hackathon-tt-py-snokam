"""Splice translated method bodies into a stub Python file.

The merger preserves every byte of the stub that we do not explicitly
replace. For each successfully translated method, we locate the method in
the stub using Python's ``ast`` module, then substitute the source text in
place of the original method's character range. Extra imports (collected
by the emitter) are inserted near the top of the file, deduplicated and
placed after any existing ``from __future__`` import.
"""
from __future__ import annotations

import ast
import re
from typing import Dict, Iterable, List, Tuple


def merge_into_stub(
    stub_src: str,
    translated_methods: Dict[str, str],
    extra_imports: Iterable[str],
) -> str:
    """Return the stub with each translated method substituted in.

    Parameters
    ----------
    stub_src:
        Full Python source of the stub file (as read from disk).
    translated_methods:
        Mapping of method name -> already-indented Python source for the
        method. The emitter is responsible for producing correct class-body
        indentation.
    extra_imports:
        Import lines (e.g. ``"from x import y"``) to add at the top of the
        file, after any ``from __future__`` block. Duplicates are removed.
    """
    new_src = stub_src
    if translated_methods:
        new_src = _replace_methods(new_src, translated_methods)
    new_src = _inject_imports(new_src, list(extra_imports))
    return new_src


# ---------------------------------------------------------------------------
# Method replacement
# ---------------------------------------------------------------------------


def _replace_methods(src: str, translations: Dict[str, str]) -> str:
    """Replace each named method in ``src`` with the translation."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    # Collect (name, start_line, end_line) for every method in every class.
    ranges: List[Tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name in translations:
                        start = _method_start_line(item)
                        end = item.end_lineno or start
                        ranges.append((item.name, start, end))

    if not ranges:
        return src

    # Apply replacements from the bottom up so line indices stay valid.
    lines = src.splitlines(keepends=True)
    ranges.sort(key=lambda r: r[1], reverse=True)
    for name, start, end in ranges:
        new_body = translations[name].rstrip("\n") + "\n"
        # Preserve a blank line after the replacement if the original had one.
        before_slice = lines[: start - 1]
        after_slice = lines[end:]
        lines = before_slice + [new_body] + after_slice
    return "".join(lines)


def _method_start_line(func: ast.AST) -> int:
    """Return the first line of a function, accounting for decorators."""
    decorators = getattr(func, "decorator_list", [])
    if decorators:
        first = min(d.lineno for d in decorators)
        return first
    return func.lineno  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Import injection
# ---------------------------------------------------------------------------


_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+\S+")


def _skip_docstring(lines: List[str], i: int) -> int:
    """Advance past a leading triple-quoted docstring if present."""
    if i >= len(lines) or not lines[i].lstrip().startswith(('"""', "'''")):
        return i
    quote = '"""' if '"""' in lines[i] else "'''"
    if lines[i].count(quote) >= 2:
        return i + 1
    i += 1
    while i < len(lines) and quote not in lines[i]:
        i += 1
    return i + 1 if i < len(lines) else i


def _find_import_insertion(lines: List[str]) -> int:
    """Return the line index where new imports should be inserted."""
    i = 0
    if i < len(lines) and lines[i].startswith("#!"):
        i += 1
    i = _skip_docstring(lines, i)
    insert_at = i
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    while i < len(lines) and lines[i].lstrip().startswith("from __future__"):
        i += 1
        insert_at = i
    while i < len(lines) and lines[i].strip() == "":
        i += 1
        insert_at = i
    return insert_at


def _dedupe_new_imports(lines: List[str], imports: List[str]) -> List[str]:
    existing = {ln.strip() for ln in lines if _IMPORT_RE.match(ln)}
    out: List[str] = []
    seen: set = set()
    for imp in imports:
        stripped = imp.strip()
        if not stripped or stripped in seen or stripped in existing:
            continue
        seen.add(stripped)
        out.append(stripped + "\n")
    return out


def _inject_imports(src: str, imports: List[str]) -> str:
    if not imports:
        return src
    lines = src.splitlines(keepends=True)
    insert_at = _find_import_insertion(lines)
    new_lines = _dedupe_new_imports(lines, imports)
    if not new_lines:
        return src
    block = new_lines[:]
    if insert_at < len(lines) and lines[insert_at].strip() != "":
        block.append("\n")
    return "".join(lines[:insert_at] + block + lines[insert_at:])
