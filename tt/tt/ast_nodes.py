"""AST node dataclasses for the TS/JS -> Python translator.

All nodes inherit from ``Node`` and optionally carry a ``src_range`` tuple
``(start_pos, end_pos)`` for debugging. Nodes are intentionally minimal and
permissive: the parser produces them, the pass layer rewrites them, and the
emitter turns them into Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple, Union


SrcRange = Optional[Tuple[int, int]]


@dataclass
class Node:
    """Base class for every AST node."""

    src_range: SrcRange = field(default=None, kw_only=True)


# -------------------- Expressions --------------------


@dataclass
class Ident(Node):
    name: str


@dataclass
class Literal(Node):
    value: Any
    kind: str  # 'string' | 'number' | 'bool' | 'null' | 'undefined' | 'regex'


@dataclass
class Template(Node):
    parts: List[str]
    exprs: List["Expr"]


@dataclass
class Array(Node):
    items: List["Expr"]


@dataclass
class Object(Node):
    pairs: List[Tuple[Any, "Expr"]]  # key may be str (ident/string) or Expr (computed)


@dataclass
class Spread(Node):
    expr: "Expr"


@dataclass
class BinaryOp(Node):
    op: str
    left: "Expr"
    right: "Expr"


@dataclass
class UnaryOp(Node):
    op: str
    operand: "Expr"
    prefix: bool = True


@dataclass
class AssignOp(Node):
    op: str  # '=', '+=', '-=', '*=', '/=', '??=', '||=', '&&='
    target: "Expr"
    value: "Expr"


@dataclass
class Call(Node):
    callee: "Expr"
    args: List["Expr"]


@dataclass
class Member(Node):
    obj: "Expr"
    prop: str
    computed: bool = False  # obj.prop vs obj["prop"] (reserved for future)


@dataclass
class Index(Node):
    obj: "Expr"
    key: "Expr"


@dataclass
class NewExpr(Node):
    callee: "Expr"
    args: List["Expr"]


@dataclass
class Arrow(Node):
    params: List["Param"]
    body: Union["Block", "Expr"]
    expr_body: bool = False  # True when body is an expression (no braces)


@dataclass
class Conditional(Node):
    cond: "Expr"
    a: "Expr"
    b: "Expr"


Expr = Node  # alias — any expression node


# -------------------- Statements --------------------


@dataclass
class Block(Node):
    stmts: List["Stmt"] = field(default_factory=list)


@dataclass
class If(Node):
    cond: "Expr"
    then: "Stmt"
    else_: Optional["Stmt"] = None


@dataclass
class ForOf(Node):
    var_name: Any  # Ident or Destructure
    iter: "Expr"
    body: "Stmt"
    is_in: bool = False  # for..in when True, for..of otherwise


@dataclass
class ForC(Node):
    init: Optional["Stmt"]
    cond: Optional["Expr"]
    update: Optional["Expr"]
    body: "Stmt"


@dataclass
class While(Node):
    cond: "Expr"
    body: "Stmt"


@dataclass
class Return(Node):
    expr: Optional["Expr"] = None


@dataclass
class Throw(Node):
    expr: "Expr"


@dataclass
class TryCatch(Node):
    try_block: Block
    catch_param: Optional[str]
    catch_block: Optional[Block]
    finally_block: Optional[Block] = None


@dataclass
class VarDecl(Node):
    kind: str  # 'const' | 'let' | 'var'
    name: Any  # Ident | Destructure
    init: Optional["Expr"] = None


@dataclass
class Destructure(Node):
    kind: str  # 'object' | 'array'
    targets: List[str]  # simple identifier names; shorthand/rest ignored
    init: Optional["Expr"] = None


@dataclass
class ExprStmt(Node):
    expr: "Expr"


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


Stmt = Node  # alias


# -------------------- Declarations --------------------


@dataclass
class Param(Node):
    name: Any  # str (ident) or Destructure
    default: Optional[Expr] = None


@dataclass
class MethodDecl(Node):
    name: str
    params: List[Param]
    body: Block
    is_static: bool = False
    access: str = "public"  # 'public' | 'protected' | 'private'
    is_constructor: bool = False
    is_async: bool = False


@dataclass
class FieldDecl(Node):
    name: str
    type_hint: Optional[str] = None  # informational only
    init: Optional[Expr] = None
    access: str = "public"
    is_static: bool = False


@dataclass
class ClassDecl(Node):
    name: str
    base: Optional[str]
    members: List[Node]  # MethodDecl | FieldDecl
    failed_methods: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class FuncDecl(Node):
    name: str
    params: List[Param]
    body: Block
    is_async: bool = False


@dataclass
class Program(Node):
    body: List[Node] = field(default_factory=list)
    failed_methods: List[Tuple[str, str]] = field(default_factory=list)


class ParseError(Exception):
    """Raised when the parser cannot recognize a construct.

    Attributes: ``node_kind`` (what the parser was trying to build) and
    ``pos`` (source position for diagnostics).
    """

    def __init__(self, node_kind: str, pos: Tuple[int, int] | int | None = None,
                 detail: str = ""):
        self.node_kind = node_kind
        self.pos = pos
        self.detail = detail
        super().__init__(f"ParseError in {node_kind} @ {pos}: {detail}")
