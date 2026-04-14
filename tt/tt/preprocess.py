"""Regex/scan-based preprocessor that strips TS-only syntax.

The preprocessor works directly on the source string but is *string- and
comment-aware*: a single forward walk skips strings/comments verbatim while
performing targeted deletions on real code regions. We keep the operations
small and local — when in doubt we keep the source intact, since leftover
tokens can usually still be parsed but mangled output cannot.
"""

from __future__ import annotations

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


def _strip_balanced_block(src: str, header_re: re.Pattern) -> str:
    """Remove constructs whose header is matched by ``header_re`` and whose
    body is the next ``{...}`` block (string-aware)."""
    while True:
        m = header_re.search(src)
        if not m:
            return src
        # Find first '{' after the match, skipping strings/comments.
        i = m.end()
        n = len(src)
        while i < n:
            c = src[i]
            if c in ("'", '"', "`"):
                i = _skip_string(src, i)
                continue
            ni = _skip_comment(src, i)
            if ni != i:
                i = ni
                continue
            if c == "{":
                break
            i += 1
        if i >= n:
            return src
        # Scan balanced.
        depth = 1
        j = i + 1
        while j < n and depth:
            c = src[j]
            if c in ("'", '"', "`"):
                j = _skip_string(src, j)
                continue
            nj = _skip_comment(src, j)
            if nj != j:
                j = nj
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        src = src[: m.start()] + src[j:]


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
        j = m.end()
        n = len(src)
        depth = 0
        while j < n:
            c = src[j]
            if c in ("'", '"', "`"):
                j = _skip_string(src, j)
                continue
            nj = _skip_comment(src, j)
            if nj != j:
                j = nj
                continue
            if c in "({[<":
                depth += 1
            elif c in ")}]>":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and c == ";":
                j += 1
                break
            elif depth == 0 and c == "\n":
                j += 1
                break
            j += 1
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
    depth_angle = 0
    depth_paren = 0
    depth_brace = 0
    depth_brack = 0
    while i < n:
        # Skip strings/comments — types may include string literals via
        # template-literal types; we treat them opaquely.
        c = src[i]
        if c in ("'", '"', "`"):
            i = _skip_string(src, i)
            continue
        ni = _skip_comment(src, i)
        if ni != i:
            i = ni
            continue
        if c == "<":
            depth_angle += 1
        elif c == ">":
            if depth_angle == 0:
                return i
            depth_angle -= 1
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            if depth_paren == 0:
                return i
            depth_paren -= 1
        elif c == "[":
            depth_brack += 1
        elif c == "]":
            if depth_brack == 0:
                return i
            depth_brack -= 1
        elif c == "{":
            if not allow_brace and depth_brace == 0:
                return i
            depth_brace += 1
        elif c == "}":
            if depth_brace == 0:
                return i
            depth_brace -= 1
        elif depth_angle == depth_paren == depth_brace == depth_brack == 0:
            if c in ",;=\n":
                return i
        i += 1
    return i


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
    n = len(src)
    out: List[str] = []
    i = 0
    # Stack of contexts: 'paren-params', 'paren-call', 'object', 'block', 'class-body'.
    # Lightweight: we mostly just need to know paren vs object.
    # We'll track a simplified stack of opening chars + a flag.
    stack: List[Tuple[str, str]] = []  # (kind, info)
    # Parallel stack of pending (unmatched) ternary `?` counts at each
    # bracket depth. `:` consumes the topmost pending ternary before being
    # considered as a type annotation — prevents mis-stripping expressions
    # like `x ? a : b` inside parens/blocks.
    tern_stack: List[int] = [0]

    def peek_non_ws(k: int) -> str:
        while k < n and src[k] in " \t\r\n":
            k += 1
        return src[k] if k < n else ""

    def prev_sig() -> str:
        k = len(out) - 1
        while k >= 0 and out[k].isspace():
            k -= 1
        return out[k] if k >= 0 else ""

    def prev_word() -> str:
        # Find the previous identifier-like word in `out`.
        text = "".join(out)
        m = re.search(r"([A-Za-z_$][\w$]*)\s*$", text)
        return m.group(1) if m else ""

    while i < n:
        c = src[i]
        # Strings / comments — copy verbatim.
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
        if c == "(":
            stack.append(("paren", ""))
            tern_stack.append(0)
            out.append(c)
            i += 1
            continue
        if c == "[":
            stack.append(("brack", ""))
            tern_stack.append(0)
            out.append(c)
            i += 1
            continue
        if c == "{":
            p = prev_sig()
            ctx = "block" if p in ("", ")", "}", ";", "{") else "object"
            # `else {` / `do {` / `try {` / `=> {` -> block.
            # `=> {` is block too — keyword detection:
            tail = "".join(out).rstrip()
            if tail.endswith("=>") or tail.endswith("else") or tail.endswith("do") \
               or tail.endswith("try") or tail.endswith("finally"):
                ctx = "block"
            stack.append(("brace", ctx))
            tern_stack.append(0)
            out.append(c)
            i += 1
            continue
        if c in ")]}":
            if stack:
                stack.pop()
            if len(tern_stack) > 1:
                tern_stack.pop()
            out.append(c)
            i += 1
            # After ')' check for return-type annotation.
            if c == ")":
                k = i
                while k < n and src[k] in " \t":
                    k += 1
                if k < n and src[k] == ":":
                    end = _scan_type_ref(src, k + 1, allow_brace=_annot_needs_brace(src, k + 1))
                    i = end
            continue
        if c == "?":
            # Distinguish ternary `?` from `?.`, `??`, and optional-param `?:`.
            nxt = src[i + 1] if i + 1 < n else ""
            if nxt in ("?", "."):
                # `??` / `?.` — consume as-is, not a ternary.
                out.append(c)
                i += 1
                continue
            # Optional-param marker `?:` — peek past whitespace.
            if peek_non_ws(i + 1) == ":":
                out.append(c)
                i += 1
                continue
            tern_stack[-1] += 1
            out.append(c)
            i += 1
            continue
        if c == ":":
            # Ternary colon: balances a pending `?` — never an annotation.
            if tern_stack[-1] > 0:
                tern_stack[-1] -= 1
                out.append(c)
                i += 1
                continue
            # Determine if this colon is an annotation.
            ctx_kind = stack[-1][0] if stack else "top"
            ctx_info = stack[-1][1] if stack else ""
            is_annotation = False
            if ctx_kind == "paren":
                is_annotation = True
            elif ctx_kind == "top":
                # After var-decl binding or class-field binding. We assume
                # annotation when previous non-space chunk is an identifier.
                pw = prev_word()
                if pw and pw not in ("case", "default", "return"):
                    is_annotation = True
            elif ctx_kind == "brace" and ctx_info == "block":
                # Inside a function body / class body. Could be an annotation
                # for a local var, OR a label, OR a ternary's `:` (in expr).
                # We're conservative: only strip when previous word is an ident
                # AND the `:` is preceded by something resembling a binding —
                # easier proxy: previous *meaningful* non-ident token is one
                # of `let`/`const`/`var`/`,` (after a binding list) or `}` (
                # destructuring close).  Use a regex on tail.
                tail = "".join(out)
                # Match "(let|const|var)\s+...\s*<ident>\s*$" with optional
                # destructuring brackets in between.
                if re.search(r"(?:^|[^\w$])(let|const|var)\b[^;]{0,200}[\w$\)\]\}]\s*$",
                             tail) and not re.search(r"\?\s*[\w$\(\[]+\s*$", tail):
                    # The negative lookbehind tries to reject ternary tails
                    # that look like `cond ? a`. Crude but practical.
                    is_annotation = True
                elif tail.rstrip().endswith(")"):
                    # method/function signature return annotation that the
                    # `)`-handler already covers; here ignore.
                    is_annotation = False
            elif ctx_kind == "brace" and ctx_info == "object":
                is_annotation = False  # object-literal colon — KEEP.
            elif ctx_kind == "brack":
                is_annotation = False
            if is_annotation:
                end = _scan_type_ref(src, i + 1, allow_brace=_annot_needs_brace(src, i + 1))
                i = end
                continue
        out.append(c)
        i += 1
    return "".join(out)


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
            end = _scan_type_ref(src, i + 4)
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
        if c == "<" and out and (_is_ident_char(out[-1]) or out[-1] == ">"):
            depth = 1
            j = i + 1
            ok = True
            while j < n and depth:
                cj = src[j]
                if cj in ("'", '"', "`"):
                    j = _skip_string(src, j)
                    continue
                if cj == "<":
                    depth += 1
                elif cj == ">":
                    depth -= 1
                elif cj in ";{}\n":
                    ok = False
                    break
                elif cj == "=" and j + 1 < n and src[j + 1] == ">":
                    ok = False
                    break
                j += 1
            if ok and depth == 0:
                inner = src[i + 1 : j - 1]
                if any(tok in inner for tok in ("&&", "||", "==", "!=")):
                    out.append(c)
                    i += 1
                    continue
                # Lookahead requirement to suppress comparisons like `a<b>c`:
                follow = src[j : j + 1]
                if follow and follow not in "(){}[],;.:?=\n\t " and not follow.isspace():
                    out.append(c)
                    i += 1
                    continue
                if re.fullmatch(r"[\w\s,\.\[\]\|\&\?<>\-:'\"]*", inner or ""):
                    i = j
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
