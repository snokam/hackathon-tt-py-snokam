"""Hand-rolled JS tokenizer.

Consumes a preprocessed (TS-stripped) source string and yields a list of
``Token`` records. Template literals are emitted as a single ``TEMPLATE``
token whose ``.value`` is a list alternating raw-string parts and inner
token-lists (recursive tokenization of each ``${...}`` region).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple


KEYWORDS = {
    "class", "extends", "export", "import", "from", "const", "let", "var",
    "if", "else", "for", "of", "in", "while", "do", "return", "throw", "try",
    "catch", "finally", "new", "this", "true", "false", "null", "undefined",
    "break", "continue", "switch", "case", "default", "function", "async",
    "await", "typeof", "instanceof", "void", "delete", "yield", "super",
}

# Multi-char punctuation, longest first.
PUNCT_MULTI = sorted(
    [
        "...", "===", "!==", "**=", "<<=", ">>=", ">>>", "??=", "||=", "&&=",
        "==", "!=", "<=", ">=", "=>", "&&", "||", "??", "**", "+=", "-=",
        "*=", "/=", "%=", "|=", "&=", "^=", "++", "--", "<<", ">>", "?.",
    ],
    key=len,
    reverse=True,
)
PUNCT_SINGLE = set("+-*/%=<>!&|^~?:;,.(){}[]")

# Token kinds that, when they are the PREVIOUS token, mean a following `/`
# begins a regex literal (not a division). Covers punctuators and most
# keywords.
_REGEX_AFTER_PUNCT = set("({[,;=<>!&|?:+-*%/^~") | {"=>"}
_REGEX_AFTER_KEYWORDS = {
    "return", "typeof", "instanceof", "in", "of", "delete", "void", "throw",
    "new", "else", "do", "case", "yield", "await",
}


@dataclass
class Token:
    kind: str  # IDENT | NUMBER | STRING | TEMPLATE | REGEX | PUNCT | KEYWORD | NEWLINE | EOF
    value: Any
    pos: Tuple[int, int]  # (line, column) 1-based

    def __repr__(self) -> str:  # pragma: no cover
        v = self.value if self.kind != "TEMPLATE" else "<tmpl>"
        return f"Tok({self.kind} {v!r} @ {self.pos})"


class LexError(Exception):
    pass


class _Cursor:
    """Tiny helper tracking (line, column) while walking characters."""

    __slots__ = ("src", "i", "line", "col")

    def __init__(self, src: str, start: int = 0, line: int = 1, col: int = 1):
        self.src = src
        self.i = start
        self.line = line
        self.col = col

    def peek(self, k: int = 0) -> str:
        j = self.i + k
        return self.src[j] if j < len(self.src) else ""

    def eof(self) -> bool:
        return self.i >= len(self.src)

    def advance(self) -> str:
        c = self.src[self.i]
        self.i += 1
        if c == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return c

    def pos(self) -> Tuple[int, int]:
        return (self.line, self.col)


def _regex_allowed(prev: Optional[Token]) -> bool:
    if prev is None:
        return True
    if prev.kind == "KEYWORD" and prev.value in _REGEX_AFTER_KEYWORDS:
        return True
    if prev.kind == "PUNCT" and prev.value in _REGEX_AFTER_PUNCT:
        return True
    return False


def _read_string(cur: _Cursor, quote: str) -> Tuple[str, Tuple[int, int]]:
    start = cur.pos()
    cur.advance()  # opening quote
    buf: List[str] = []
    while not cur.eof():
        c = cur.peek()
        if c == "\\":
            cur.advance()
            esc = cur.advance() if not cur.eof() else ""
            buf.append("\\" + esc)
            continue
        if c == quote:
            cur.advance()
            return "".join(buf), start
        buf.append(cur.advance())
    raise LexError(f"Unterminated string at {start}")


def _read_number(cur: _Cursor) -> Tuple[str, Tuple[int, int]]:
    start = cur.pos()
    buf: List[str] = []
    saw_dot = False
    saw_e = False
    # Hex/oct/bin
    if cur.peek() == "0" and cur.peek(1) in ("x", "X", "o", "O", "b", "B"):
        buf.append(cur.advance())
        buf.append(cur.advance())
        while not cur.eof() and (cur.peek().isalnum() or cur.peek() == "_"):
            buf.append(cur.advance())
        return "".join(buf), start
    while not cur.eof():
        c = cur.peek()
        if c.isdigit() or c == "_":
            buf.append(cur.advance())
        elif c == "." and not saw_dot and not saw_e:
            saw_dot = True
            buf.append(cur.advance())
        elif c in ("e", "E") and not saw_e:
            saw_e = True
            buf.append(cur.advance())
            if cur.peek() in ("+", "-"):
                buf.append(cur.advance())
        elif c == "n":  # bigint marker
            buf.append(cur.advance())
            break
        else:
            break
    return "".join(buf), start


def _read_ident(cur: _Cursor) -> Tuple[str, Tuple[int, int]]:
    start = cur.pos()
    buf: List[str] = []
    while not cur.eof():
        c = cur.peek()
        if c.isalnum() or c == "_" or c == "$":
            buf.append(cur.advance())
        else:
            break
    return "".join(buf), start


def _read_regex(cur: _Cursor) -> Tuple[str, Tuple[int, int]]:
    start = cur.pos()
    buf = [cur.advance()]  # leading /
    in_class = False
    while not cur.eof():
        c = cur.peek()
        if c == "\\":
            buf.append(cur.advance())
            if not cur.eof():
                buf.append(cur.advance())
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            buf.append(cur.advance())
            # flags
            while not cur.eof() and cur.peek().isalpha():
                buf.append(cur.advance())
            return "".join(buf), start
        elif c == "\n":
            raise LexError(f"Unterminated regex at {start}")
        buf.append(cur.advance())
    raise LexError(f"Unterminated regex at {start}")


def _read_template_expr(cur: _Cursor) -> List[Token]:
    """Read a balanced ``${...}`` region and return its inner tokens."""
    depth = 1
    inner_start = cur.i
    inner_line = cur.line
    inner_col = cur.col
    while not cur.eof() and depth:
        ch = cur.peek()
        if ch == "{":
            depth += 1
            cur.advance()
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
            cur.advance()
        elif ch in ("'", '"'):
            _read_string(cur, ch)
        elif ch == "`":
            _read_template(cur)
        else:
            cur.advance()
    inner_src = cur.src[inner_start : cur.i]
    inner_tokens = tokenize(inner_src, line=inner_line, col=inner_col)
    if inner_tokens and inner_tokens[-1].kind == "EOF":
        inner_tokens = inner_tokens[:-1]
    if not cur.eof() and cur.peek() == "}":
        cur.advance()
    return inner_tokens


def _read_template(cur: _Cursor) -> Tuple[List[Any], Tuple[int, int]]:
    """Read a template literal. Returns alternating list: [part0, exprToks0,
    part1, exprToks1, ..., partN]."""
    start = cur.pos()
    cur.advance()  # opening `
    parts: List[Any] = []
    cur_part: List[str] = []
    while not cur.eof():
        c = cur.peek()
        if c == "\\":
            cur.advance()
            if not cur.eof():
                cur_part.append("\\" + cur.advance())
            continue
        if c == "`":
            cur.advance()
            parts.append("".join(cur_part))
            return parts, start
        if c == "$" and cur.peek(1) == "{":
            parts.append("".join(cur_part))
            cur_part = []
            cur.advance()  # $
            cur.advance()  # {
            parts.append(_read_template_expr(cur))
            continue
        cur_part.append(cur.advance())
    raise LexError(f"Unterminated template literal at {start}")


def _skip_whitespace_or_comment(cur: _Cursor) -> bool:
    """If the cursor is at whitespace/comment, skip it and return True."""
    c = cur.peek()
    if c in (" ", "\t", "\r", "\n"):
        cur.advance()
        return True
    if c == "/" and cur.peek(1) == "/":
        while not cur.eof() and cur.peek() != "\n":
            cur.advance()
        return True
    if c == "/" and cur.peek(1) == "*":
        cur.advance()
        cur.advance()
        while not cur.eof() and not (cur.peek() == "*" and cur.peek(1) == "/"):
            cur.advance()
        if not cur.eof():
            cur.advance(); cur.advance()
        return True
    return False


def _try_read_regex(cur: _Cursor, prev: Optional[Token]) -> Optional[Token]:
    if cur.peek() != "/" or not _regex_allowed(prev):
        return None
    try:
        s, p = _read_regex(cur)
        return Token("REGEX", s, p)
    except LexError:
        # Match original behavior: cursor may have advanced; fall through.
        return None


def _read_punct(cur: _Cursor) -> Optional[Token]:
    for sym in PUNCT_MULTI:
        if cur.src.startswith(sym, cur.i):
            p = cur.pos()
            for _ in range(len(sym)):
                cur.advance()
            return Token("PUNCT", sym, p)
    c = cur.peek()
    if c in PUNCT_SINGLE:
        p = cur.pos()
        cur.advance()
        return Token("PUNCT", c, p)
    return None


def _next_token(cur: _Cursor, prev: Optional[Token]) -> Optional[Token]:
    c = cur.peek()
    if c in ("'", '"'):
        s, p = _read_string(cur, c)
        return Token("STRING", (c, s), p)
    if c == "`":
        parts, p = _read_template(cur)
        return Token("TEMPLATE", parts, p)
    rx = _try_read_regex(cur, prev)
    if rx is not None:
        return rx
    if c.isdigit() or (c == "." and cur.peek(1).isdigit()):
        s, p = _read_number(cur)
        return Token("NUMBER", s, p)
    if c.isalpha() or c == "_" or c == "$":
        s, p = _read_ident(cur)
        return Token("KEYWORD" if s in KEYWORDS else "IDENT", s, p)
    return _read_punct(cur)


def tokenize(src: str, line: int = 1, col: int = 1) -> List[Token]:
    cur = _Cursor(src, 0, line, col)
    tokens: List[Token] = []
    prev: Optional[Token] = None
    while not cur.eof():
        if _skip_whitespace_or_comment(cur):
            continue
        tok = _next_token(cur, prev)
        if tok is None:
            # Unknown char — skip with no token; keeps lexer robust.
            cur.advance()
            continue
        tokens.append(tok)
        prev = tok
    tokens.append(Token("EOF", None, cur.pos()))
    return tokens
