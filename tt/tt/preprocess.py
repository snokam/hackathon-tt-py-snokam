"""Regex/scan-based preprocessor that strips TS-only syntax.

The preprocessor works directly on the source string but is *string- and
comment-aware*: a single forward walk skips strings/comments verbatim while
performing targeted deletions on real code regions. We keep the operations
small and local — when in doubt we keep the source intact, since leftover
tokens can usually still be parsed but mangled output cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Tuple


# ------------------------- low-level char walking -------------------------


def _skip_string(src: str, i: int) -> int:
    """Advance past a string literal that starts at ``src[i]``."""
    quote = src[i]
    n = len(src)
    j = i + 1
    while j < n:
        c = src[j]
        if c == "\\":
            j += 2
            continue
        if c == quote:
            return j + 1
        if quote == "`" and c == "$" and j + 1 < n and src[j + 1] == "{":
            depth = 1
            j += 2
            while j < n and depth:
                # Inside ${...} we must respect nested strings/templates.
                cc = src[j]
                if cc in ("'", '"', "`"):
                    j = _skip_string(src, j)
                    continue
                if cc == "{":
                    depth += 1
                elif cc == "}":
                    depth -= 1
                j += 1
            continue
        j += 1
    return n


def _skip_comment(src: str, i: int) -> int:
    """If ``src[i:]`` begins a comment, skip it; otherwise return i."""
    n = len(src)
    if i + 1 < n and src[i] == "/" and src[i + 1] == "/":
        j = src.find("\n", i)
        return n if j == -1 else j
    if i + 1 < n and src[i] == "/" and src[i + 1] == "*":
        j = src.find("*/", i + 2)
        return n if j == -1 else j + 2
    return i


def _skip_opaque(src: str, i: int) -> int:
    """Skip a string or comment starting at ``src[i]`` if present."""
    if src[i] in ("'", '"', "`"):
        return _skip_string(src, i)
    return _skip_comment(src, i)


# ------------------------- scan-based stripping passes -------------------------


def _walk_emit(src: str, edits: List[Tuple[int, int]]) -> str:
    """Apply a list of (start, end) deletions to ``src``."""
    if not edits:
        return src
    edits = sorted(edits)
    out: List[str] = []
    pos = 0
    for s, e in edits:
        if s < pos:
            continue  # overlapping; skip
        out.append(src[pos:s])
        pos = e
    out.append(src[pos:])
    return "".join(out)


def _strip_imports_of_type(src: str) -> str:
    """Remove `import type ...;` lines."""
    return re.sub(r"^[ \t]*import\s+type\s+[^;\n]*;?\s*\n?",
                  "", src, flags=re.MULTILINE)


def _find_next_brace(src: str, i: int) -> int:
    """Return the next real ``{`` at or after ``i``."""
    n = len(src)
    while i < n:
        ni = _skip_opaque(src, i)
        if ni != i:
            i = ni
            continue
        if src[i] == "{":
            return i
        i += 1
    return n


def _scan_balanced_braces(src: str, i: int) -> int:
    """Return the position just past the balanced block starting at ``i``."""
    n = len(src)
    depth = 1
    j = i + 1
    while j < n and depth:
        nj = _skip_opaque(src, j)
        if nj != j:
            j = nj
            continue
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
        j += 1
    return j


def _strip_balanced_block(src: str, header_re: re.Pattern) -> str:
    """Remove constructs whose header is matched by ``header_re`` and whose
    body is the next ``{...}`` block (string-aware)."""
    while True:
        m = header_re.search(src)
        if not m:
            return src
        i = _find_next_brace(src, m.end())
        if i >= len(src):
            return src
        j = _scan_balanced_braces(src, i)
        src = src[: m.start()] + src[j:]


def _scan_type_alias_end(src: str, j: int) -> int:
    """Return the end position of a ``type Foo = ...`` alias."""
    n = len(src)
    depth = 0
    while j < n:
        nj = _skip_opaque(src, j)
        if nj != j:
            j = nj
            continue
        c = src[j]
        if c in "({[<":
            depth += 1
        elif c in ")}]>":
            if depth == 0:
                return j
            depth -= 1
        elif depth == 0 and c in ";\n":
            return j + 1
        j += 1
    return j


def _strip_type_aliases(src: str) -> str:
    """Delete `type Name = ...;` (or until newline at depth 0)."""
    pattern = re.compile(
        r"^\s*(?:export\s+)?type\s+[A-Za-z_$][\w$]*\s*(?:<[^>]*>)?\s*=",
        re.MULTILINE,
    )
    while True:
        m = pattern.search(src)
        if not m:
            return src
        j = _scan_type_alias_end(src, m.end())
        src = src[: m.start()] + src[j:]


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c == "_" or c == "$"


def _annot_needs_brace(src: str, i: int) -> bool:
    """True if the type annotation starting at ``i`` begins with ``{``.

    Used to decide whether ``_scan_type_ref`` should descend into an
    inline object type (e.g. ``: { a: number } & Other``) without
    mistakenly eating a following function body.
    """
    n = len(src)
    while i < n and src[i] in " \t\r\n":
        i += 1
    return i < n and src[i] == "{"


def _type_ref_stop_at_top(
    src: str,
    i: int,
    depths: Tuple[int, int, int, int],
    allow_brace: bool,
) -> int | None:
    """Return a stop position before consuming ``src[i]`` if needed."""
    depth_angle, depth_paren, depth_brace, depth_brack = depths
    c = src[i]
    if c == ">" and depth_angle == 0:
        return i
    if c == ")" and depth_paren == 0:
        return i
    if c == "]" and depth_brack == 0:
        return i
    if c == "{" and depth_brace == 0 and not allow_brace:
        return i
    if c == "}" and depth_brace == 0:
        return i
    if depth_angle == depth_paren == depth_brace == depth_brack == 0 and c in ",;=\n":
        return i
    return None


def _type_ref_update_depths(
    c: str,
    depths: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    """Advance bracket depths for one consumed type-expression character."""
    depth_angle, depth_paren, depth_brace, depth_brack = depths
    if c == "<":
        depth_angle += 1
    elif c == ">":
        depth_angle -= 1
    elif c == "(":
        depth_paren += 1
    elif c == ")":
        depth_paren -= 1
    elif c == "[":
        depth_brack += 1
    elif c == "]":
        depth_brack -= 1
    elif c == "{":
        depth_brace += 1
    elif c == "}":
        depth_brace -= 1
    return (depth_angle, depth_paren, depth_brace, depth_brack)


def _type_ref_following_suffix(src: str, i: int) -> int:
    """Return the position after any whitespace following a completed suffix."""
    n = len(src)
    while i < n and src[i] in " \t\r\n":
        i += 1
    return i


def _type_ref_suffix_stop(
    src: str,
    i: int,
    c: str,
    depths: Tuple[int, int, int, int],
) -> int | None:
    """Stop after a top-level ``]`` or ``}`` unless the type clearly continues."""
    depth_angle, depth_paren, depth_brace, depth_brack = depths
    if c not in ("]", "}"):
        return None
    if depth_angle or depth_paren or depth_brace or depth_brack:
        return None
    j = _type_ref_following_suffix(src, i)
    if j >= len(src) or src[j] not in "&|[":
        return j
    return None


def _scan_type_ref(src: str, i: int, allow_brace: bool = False) -> int:
    """Return position just past a TS type reference starting at ``i``.

    A type reference is a sequence of identifiers / qualified names /
    generic param lists ``<...>`` / array suffix ``[]`` / unions ``|`` /
    intersections ``&``. We stop at the first character that cannot belong
    to a type expression at depth 0.

    If ``allow_brace`` is True we also descend into ``{ ... }`` for inline
    object types; otherwise we stop at ``{``.
    """
    n = len(src)
    depths = (0, 0, 0, 0)
    while i < n:
        ni = _skip_opaque(src, i)
        if ni != i:
            i = ni
            continue
        stop = _type_ref_stop_at_top(src, i, depths, allow_brace)
        if stop is not None:
            return stop
        c = src[i]
        depths = _type_ref_update_depths(c, depths)
        i += 1
        stop = _type_ref_suffix_stop(src, i, c, depths)
        if stop is not None:
            return stop
    return i


@dataclass
class _AnnotationState:
    out: List[str]
    stack: List[Tuple[str, str]]
    tern_stack: List[int]
    i: int = 0


def _annotation_peek_non_ws(src: str, k: int) -> str:
    while k < len(src) and src[k] in " \t\r\n":
        k += 1
    return src[k] if k < len(src) else ""


def _annotation_prev_sig(out: List[str]) -> str:
    k = len(out) - 1
    while k >= 0 and out[k].isspace():
        k -= 1
    return out[k] if k >= 0 else ""


def _annotation_prev_word(out: List[str]) -> str:
    text = "".join(out)
    m = re.search(r"([A-Za-z_$][\w$]*)\s*$", text)
    return m.group(1) if m else ""


def _annotation_copy_opaque(src: str, state: _AnnotationState) -> bool:
    i = state.i
    if src[i] in ("'", '"', "`"):
        j = _skip_string(src, i)
        state.out.append(src[i:j])
        state.i = j
        return True
    nj = _skip_comment(src, i)
    if nj == i:
        return False
    state.out.append(src[i:nj])
    state.i = nj
    return True


def _annotation_brace_context(out: List[str]) -> str:
    tail = "".join(out).rstrip()
    if tail.endswith(("=>", "else", "do", "try", "finally")):
        return "block"
    return "block" if _annotation_prev_sig(out) in ("", ")", "}", ";", "{") else "object"


def _annotation_open_context(src: str, state: _AnnotationState) -> bool:
    c = src[state.i]
    if c == "(":
        ctx = ("paren", "")
    elif c == "[":
        ctx = ("brack", "")
    elif c == "{":
        ctx = ("brace", _annotation_brace_context(state.out))
    else:
        return False
    state.stack.append(ctx)
    state.tern_stack.append(0)
    state.out.append(c)
    state.i += 1
    return True


def _annotation_maybe_consume_return_type(src: str, state: _AnnotationState) -> None:
    if state.tern_stack[-1] != 0:
        return
    k = state.i
    while k < len(src) and src[k] in " \t":
        k += 1
    if k >= len(src) or src[k] != ":":
        return
    end = _scan_type_ref(src, k + 1, allow_brace=_annot_needs_brace(src, k + 1))
    j = _type_ref_following_suffix(src, end)
    if j < len(src) and (src[j] == "{" or src[j] == ";" or src[j:j + 2] == "=>"):
        state.i = end


def _annotation_close_context(src: str, state: _AnnotationState) -> bool:
    c = src[state.i]
    if c not in ")]}":
        return False
    if state.stack:
        state.stack.pop()
    if len(state.tern_stack) > 1:
        state.tern_stack.pop()
    state.out.append(c)
    state.i += 1
    if c == ")":
        _annotation_maybe_consume_return_type(src, state)
    return True


def _annotation_handle_question(src: str, state: _AnnotationState) -> bool:
    if src[state.i] != "?":
        return False
    nxt = src[state.i + 1] if state.i + 1 < len(src) else ""
    if nxt == "?":
        state.out.append(src[state.i : state.i + 2])
        state.i += 2
        return True
    if nxt == "." or _annotation_peek_non_ws(src, state.i + 1) == ":":
        state.out.append("?")
        state.i += 1
        return True
    state.tern_stack[-1] += 1
    state.out.append("?")
    state.i += 1
    return True


def _annotation_block_binding_tail(out: List[str]) -> bool:
    tail = "".join(out)
    if re.search(r"\?\s*[\w$\(\[]+\s*$", tail):
        return False
    return bool(
        re.search(
            r"(?:^|[^\w$])(let|const|var)\b[^;]{0,200}[\w$\)\]\}]\s*$",
            tail,
        )
    )


def _annotation_is_type_colon(state: _AnnotationState) -> bool:
    ctx_kind, ctx_info = state.stack[-1] if state.stack else ("top", "")
    if ctx_kind == "paren":
        return True
    if ctx_kind == "top":
        prev_word = _annotation_prev_word(state.out)
        return bool(prev_word and prev_word not in ("case", "default", "return"))
    if ctx_kind == "brace" and ctx_info == "block":
        if _annotation_block_binding_tail(state.out):
            return True
        return False
    return False


def _annotation_handle_colon(src: str, state: _AnnotationState) -> bool:
    if src[state.i] != ":":
        return False
    if state.tern_stack[-1] > 0:
        state.tern_stack[-1] -= 1
        state.out.append(":")
        state.i += 1
        return True
    if not _annotation_is_type_colon(state):
        return False
    state.i = _scan_type_ref(src, state.i + 1, allow_brace=True)
    return True


def _strip_type_annotations(src: str) -> str:
    """Strip `: <Type>` annotations.

    Strategy: walk the source while tracking bracket nesting and identifying
    "annotation positions". An annotation appears when:
      * In a paren-list (parameters), after an identifier (and optional `?`).
      * After `)` (return-type position).
      * In a ``let``/``const``/``var`` declaration after the binding.
      * In a class field declaration after the field name.
    Object-literal `{k: v}` colons are preserved by skipping whole object
    literals — we recognize them when `{` follows `=`, `(`, `,`, `:`, `?`, or
    `return`.
    """
    state = _AnnotationState(out=[], stack=[], tern_stack=[0])
    while state.i < len(src):
        if _annotation_copy_opaque(src, state):
            continue
        if _annotation_open_context(src, state):
            continue
        if _annotation_close_context(src, state):
            continue
        if _annotation_handle_question(src, state):
            continue
        if _annotation_handle_colon(src, state):
            continue
        state.out.append(src[state.i])
        state.i += 1
    return "".join(state.out)


def _strip_optional_param_marks(src: str) -> str:
    return re.sub(r"([A-Za-z_$][\w$]*)\s*\?\s*(?=[,\)=])", r"\1", src)


def _strip_as_casts(src: str) -> str:
    """String-aware removal of ``as <Type>`` casts."""
    n = len(src)
    out: List[str] = []
    i = 0
    while i < n:
        c = src[i]
        if c in ("'", '"', "`"):
            j = _skip_string(src, i)
            out.append(src[i:j])
            i = j
            continue
        nj = _skip_comment(src, i)
        if nj != i:
            out.append(src[i:nj])
            i = nj
            continue
        # Look for ` as `
        if c.isspace() and src.startswith("as", i + 1) \
           and i + 3 < n and src[i + 3].isspace():
            # 'as' must be a standalone word: chars around the match slot are
            # already whitespace, so no further check needed.
            out.append(c)  # keep the leading space
            # `as` casts can contain inline object types (`as { k: v }`).
            end = _scan_type_ref(src, i + 4, allow_brace=_annot_needs_brace(src, i + 4))
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_non_null(src: str) -> str:
    return re.sub(r"!\s*(?=[\.\[\(])", "", src)


def _strip_access_modifiers(src: str) -> str:
    pattern = re.compile(
        r"^(\s*)(?:(?:public|protected|private|readonly|override|abstract)\s+)+",
        re.MULTILINE,
    )
    return pattern.sub(r"\1", src)


def _strip_export_keywords(src: str) -> str:
    src = re.sub(r"^\s*export\s+default\s+", "", src, flags=re.MULTILINE)
    src = re.sub(r"^(\s*)export\s+(?=(?:class|function|const|let|var|abstract|async))",
                 r"\1", src, flags=re.MULTILINE)
    return src


def _scan_generic_param_block(src: str, i: int) -> int | None:
    """Return the end of a generic ``<...>`` block, or None if it looks unsafe."""
    n = len(src)
    depth = 1
    j = i + 1
    while j < n and depth:
        nj = _skip_opaque(src, j)
        if nj != j:
            j = nj
            continue
        c = src[j]
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif c in ";{}\n" or (c == "=" and j + 1 < n and src[j + 1] == ">"):
            return None
        j += 1
    if depth != 0:
        return None
    inner = src[i + 1 : j - 1]
    if any(tok in inner for tok in ("&&", "||", "==", "!=")):
        return None
    follow = src[j : j + 1]
    if follow and follow not in "(){}[],;.:?=\n\t " and not follow.isspace():
        return None
    if not re.fullmatch(r"[\w\s,\.\[\]\|\&\?<>\-:'\"]*", inner or ""):
        return None
    return j


def _strip_generic_params(src: str) -> str:
    """Remove generic angle-bracket parameter lists in declaration positions.

    We restrict ourselves to the common cases that show up in our target
    code: ``Foo<...>`` where Foo is an identifier directly preceding ``<``,
    AND the contents look type-ish (no `&&`/`||`/`==`/etc.). To avoid
    eating ternary or comparison operators in expressions we additionally
    require the matching ``>`` to be immediately followed by certain
    non-expression characters.
    """
    n = len(src)
    out: List[str] = []
    i = 0
    while i < n:
        nj = _skip_opaque(src, i)
        if nj != i:
            out.append(src[i:nj])
            i = nj
            continue
        c = src[i]
        if c == "<" and out and (_is_ident_char(out[-1]) or out[-1] == ">"):
            end = _scan_generic_param_block(src, i)
            if end is not None:
                i = end
                continue
        out.append(c)
        i += 1
    return "".join(out)


# ------------------------- public API -------------------------


_INTERFACE_RE = re.compile(
    r"\binterface\s+[A-Za-z_$][\w$]*(?:\s*<[^>]*>)?(?:\s+extends\s+[^\{]+)?\s*(?=\{)",
)
_NAMESPACE_RE = re.compile(r"\b(?:declare\s+)?namespace\s+[A-Za-z_$][\w$]*\s*(?=\{)")


def preprocess(ts_src: str) -> str:
    """Strip TS-only syntax from ``ts_src`` and return JS-ish source."""
    src = ts_src
    src = _strip_imports_of_type(src)
    src = _strip_balanced_block(src, _INTERFACE_RE)
    src = _strip_balanced_block(src, _NAMESPACE_RE)
    src = _strip_type_aliases(src)
    src = _strip_generic_params(src)
    src = _strip_type_annotations(src)
    src = _strip_optional_param_marks(src)
    src = _strip_as_casts(src)
    src = _strip_non_null(src)
    src = _strip_access_modifiers(src)
    src = _strip_export_keywords(src)
    return src
