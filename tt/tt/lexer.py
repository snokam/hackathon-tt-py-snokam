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
            # Read balanced up to matching }.
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
            # Recursively tokenize (without the trailing '}')
            inner_tokens = tokenize(inner_src, line=inner_line, col=inner_col)
            # Drop EOF
            if inner_tokens and inner_tokens[-1].kind == "EOF":
                inner_tokens = inner_tokens[:-1]
            parts.append(inner_tokens)
            if not cur.eof() and cur.peek() == "}":
                cur.advance()
            continue
        cur_part.append(cur.advance())
    raise LexError(f"Unterminated template literal at {start}")


def tokenize(src: str, line: int = 1, col: int = 1) -> List[Token]:
    cur = _Cursor(src, 0, line, col)
    tokens: List[Token] = []
    prev: Optional[Token] = None
    while not cur.eof():
        c = cur.peek()
        # whitespace (not newline)
        if c in (" ", "\t", "\r"):
            cur.advance()
            continue
        if c == "\n":
            cur.advance()
            continue
        # comments
        if c == "/" and cur.peek(1) == "/":
            while not cur.eof() and cur.peek() != "\n":
                cur.advance()
            continue
        if c == "/" and cur.peek(1) == "*":
            cur.advance()
            cur.advance()
            while not cur.eof() and not (cur.peek() == "*" and cur.peek(1) == "/"):
                cur.advance()
            if not cur.eof():
                cur.advance(); cur.advance()
            continue
        # strings
        if c in ("'", '"'):
            s, p = _read_string(cur, c)
            tok = Token("STRING", (c, s), p)
            tokens.append(tok)
            prev = tok
            continue
        # template
        if c == "`":
            parts, p = _read_template(cur)
            tok = Token("TEMPLATE", parts, p)
            tokens.append(tok)
            prev = tok
            continue
        # regex vs division
        if c == "/" and _regex_allowed(prev):
            try:
                s, p = _read_regex(cur)
                tok = Token("REGEX", s, p)
                tokens.append(tok)
                prev = tok
                continue
            except LexError:
                # fall through to punct handling
                pass
        # number
        if c.isdigit() or (c == "." and cur.peek(1).isdigit()):
            s, p = _read_number(cur)
            tok = Token("NUMBER", s, p)
            tokens.append(tok)
            prev = tok
            continue
        # identifier/keyword
        if c.isalpha() or c == "_" or c == "$":
            s, p = _read_ident(cur)
            kind = "KEYWORD" if s in KEYWORDS else "IDENT"
            tok = Token(kind, s, p)
            tokens.append(tok)
            prev = tok
            continue
        # multi-char punct
        matched = None
        for sym in PUNCT_MULTI:
            if cur.src.startswith(sym, cur.i):
                matched = sym
                break
        if matched:
            p = cur.pos()
            for _ in range(len(matched)):
                cur.advance()
            tok = Token("PUNCT", matched, p)
            tokens.append(tok)
            prev = tok
            continue
        if c in PUNCT_SINGLE:
            p = cur.pos()
            cur.advance()
            tok = Token("PUNCT", c, p)
            tokens.append(tok)
            prev = tok
            continue
        # Unknown char — skip with no token; keeps lexer robust.
        cur.advance()

    tokens.append(Token("EOF", None, cur.pos()))
    return tokens
