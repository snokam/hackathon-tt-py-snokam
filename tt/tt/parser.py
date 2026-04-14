"""Recursive-descent JS parser producing nodes from :mod:`ast_nodes`.

The parser is intentionally permissive: it covers a practical subset of
modern JS and isolates each class member. If one member fails to parse the
failure is recorded in ``Program.failed_methods`` / ``ClassDecl.failed_methods``
and the parser moves on. This keeps the pipeline's blast radius small.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from .ast_nodes import (
    Arrow, Array, AssignOp, BinaryOp, Block, Break, Call, ClassDecl,
    Conditional, Continue, Destructure, ExprStmt, FieldDecl, ForC, ForOf,
    FuncDecl, Ident, If, Index, Literal, Member, MethodDecl, NewExpr, Node,
    Object, Param, ParseError, Program, Return, Spread, Template, Throw,
    TryCatch, UnaryOp, VarDecl, While,
)
from .lexer import Token


# ---- precedence table (binary operators) ----
# Higher number = binds tighter.
_BINOPS = {
    "??": 3, "||": 4, "&&": 5,
    "|": 6, "^": 7, "&": 8,
    "==": 9, "!=": 9, "===": 9, "!==": 9,
    "<": 10, "<=": 10, ">": 10, ">=": 10, "in": 10, "instanceof": 10,
    "<<": 11, ">>": 11, ">>>": 11,
    "+": 12, "-": 12,
    "*": 13, "/": 13, "%": 13,
    "**": 14,
}

_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "**=", "&&=", "||=", "??=",
               "|=", "&=", "^=", "<<=", ">>="}

# Maps primary-position keywords that produce a simple value. "ident" kind
# signals that the value is an identifier name rather than a literal.
_KEYWORD_LITERALS = {
    "this": ("this", "ident"),
    "super": ("super", "ident"),
    "true": (True, "bool"),
    "false": (False, "bool"),
    "null": (None, "null"),
    "undefined": (None, "undefined"),
}


class _Parser:
    def __init__(self, tokens: List[Token]):
        self.toks = tokens
        self.i = 0

    # ---------------- token helpers ----------------
    def peek(self, k: int = 0) -> Token:
        j = self.i + k
        if j >= len(self.toks):
            return self.toks[-1]
        return self.toks[j]

    def eof(self) -> bool:
        return self.peek().kind == "EOF"

    def advance(self) -> Token:
        t = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def check(self, kind: str, value: Optional[str] = None) -> bool:
        t = self.peek()
        if t.kind != kind:
            return False
        if value is not None and t.value != value:
            return False
        return True

    def match(self, kind: str, value: Optional[str] = None) -> Optional[Token]:
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind: str, value: Optional[str] = None) -> Token:
        t = self.peek()
        if not self.check(kind, value):
            raise ParseError(
                "expect", t.pos,
                detail=f"wanted {kind} {value!r}, got {t.kind} {t.value!r}",
            )
        return self.advance()

    # ---------------- top level ----------------
    def parse_program(self) -> Program:
        prog = Program(body=[])
        while not self.eof():
            try:
                node = self._parse_top_level()
                if node is not None:
                    prog.body.append(node)
            except ParseError as e:
                # Skip this top-level construct.
                prog.failed_methods.append((f"<top@{self.peek().pos}>", str(e)))
                self._skip_to_top_level_boundary()
        # Bubble class-level failures into the program summary too.
        for node in prog.body:
            if isinstance(node, ClassDecl):
                for nm, reason in node.failed_methods:
                    prog.failed_methods.append((f"{node.name}.{nm}", reason))
        return prog

    def _skip_to_top_level_boundary(self) -> None:
        depth = 0
        while not self.eof():
            t = self.peek()
            if t.kind == "PUNCT":
                if t.value == "{":
                    depth += 1
                elif t.value == "}":
                    depth -= 1
                    if depth <= 0:
                        self.advance()
                        return
                elif t.value == ";" and depth == 0:
                    self.advance()
                    return
            self.advance()

    def _parse_top_level(self) -> Optional[Node]:
        # Skip export keyword (preprocessor usually removes it, belt+braces).
        self.match("KEYWORD", "export")
        self.match("KEYWORD", "default")

        if self.check("KEYWORD", "class"):
            return self._parse_class()
        if self.check("KEYWORD", "function"):
            return self._parse_function_decl()
        if self.check("KEYWORD", "import"):
            return self._parse_import_as_stmt()
        return self._parse_statement()

    def _parse_import_as_stmt(self) -> Node:
        # Consume up to the next ';' or newline — we don't model imports.
        start = self.advance().pos
        while not self.eof() and not self.check("PUNCT", ";"):
            self.advance()
        self.match("PUNCT", ";")
        return ExprStmt(expr=Literal(value=None, kind="null"), src_range=(0, 0))

    # ---------------- classes ----------------
    def _parse_class(self) -> ClassDecl:
        self.expect("KEYWORD", "class")
        name_tok = self.expect("IDENT")
        base = None
        if self.match("KEYWORD", "extends"):
            base_tok = self.expect("IDENT")
            base = base_tok.value
            # Allow qualified base like `Foo.Bar`.
            while self.match("PUNCT", "."):
                base += "." + self.expect("IDENT").value
        self.expect("PUNCT", "{")
        members: List[Node] = []
        failed: List[Tuple[str, str]] = []

        while not self.eof() and not self.check("PUNCT", "}"):
            # Skip stray semicolons.
            if self.match("PUNCT", ";"):
                continue
            start_idx = self.i
            try:
                m = self._parse_class_member()
                if m is not None:
                    members.append(m)
            except ParseError as e:
                name = self._last_seen_ident_from(start_idx) or "<anon>"
                failed.append((name, str(e)))
                # Restore to before the failed attempt so we can reliably scan
                # to the end of this member (body block or terminating `;`).
                self.i = start_idx
                self._skip_class_member()
        self.expect("PUNCT", "}")
        return ClassDecl(name=name_tok.value, base=base, members=members,
                         failed_methods=failed)

    def _last_seen_ident_from(self, start_idx: int) -> Optional[str]:
        for j in range(start_idx, min(start_idx + 8, len(self.toks))):
            if self.toks[j].kind == "IDENT":
                return self.toks[j].value
        return None

    def _skip_class_member(self) -> None:
        """Advance past one class member.

        We look for the FIRST top-level `{` (method body) or `;` (abstract
        method / field). On `{`, we balance braces until depth returns to
        zero. On `;`, we consume it. A bare `}` at depth 0 signals the end
        of the class body and is left for the outer loop.
        """
        while not self.eof():
            t = self.peek()
            if t.kind == "PUNCT":
                if t.value == "}":
                    return  # class end
                if t.value == ";":
                    self.advance()
                    return
                if t.value == "{":
                    depth = 0
                    while not self.eof():
                        tt = self.peek()
                        if tt.kind == "PUNCT":
                            if tt.value == "{":
                                depth += 1
                            elif tt.value == "}":
                                depth -= 1
                                self.advance()
                                if depth == 0:
                                    return
                                continue
                        self.advance()
                    return
            self.advance()

    def _consume_member_modifiers(self) -> Tuple[str, bool, bool]:
        access = "public"
        is_static = False
        is_async = False
        while True:
            tok = self.peek()
            if tok.kind == "KEYWORD" and tok.value in ("static", "async"):
                if tok.value == "static":
                    is_static = True
                else:
                    is_async = True
                self.advance()
                continue
            if tok.kind == "IDENT" and tok.value in (
                "public", "private", "protected", "readonly", "override",
                "abstract",
            ):
                if tok.value in ("public", "private", "protected"):
                    access = tok.value
                self.advance()
                continue
            break
        return access, is_static, is_async

    def _parse_method_member(self, name: str, access: str, is_static: bool,
                             is_async: bool, is_constructor: bool) -> MethodDecl:
        params = self._parse_params()
        # Residual return-type annotation survived: skip `: ...` until `{` or `;`.
        if self.check("PUNCT", ":"):
            while not self.eof() and not self.check("PUNCT", "{") \
                    and not self.check("PUNCT", ";"):
                self.advance()
        # Abstract/interface method: signature followed by `;` with no body.
        body = Block(stmts=[]) if self.match("PUNCT", ";") else self._parse_block()
        return MethodDecl(
            name=name, params=params, body=body,
            is_static=is_static, access=access,
            is_constructor=is_constructor, is_async=is_async,
        )

    def _parse_field_member(self, name: str, access: str,
                            is_static: bool) -> FieldDecl:
        # Field declaration. Skip residual type annotation `: <Type>`.
        if self.match("PUNCT", ":"):
            while not self.eof() and not (
                self.check("PUNCT", "=") or self.check("PUNCT", ";")
                or self.check("PUNCT", "}")
            ):
                self.advance()
        init: Optional[Node] = None
        if self.match("PUNCT", "="):
            init = self._parse_assignment()
        self.match("PUNCT", ";")
        return FieldDecl(name=name, type_hint=None, init=init,
                         access=access, is_static=is_static)

    def _parse_class_member(self) -> Optional[Node]:
        access, is_static, is_async = self._consume_member_modifiers()
        name_tok = self.peek()
        if name_tok.kind not in ("IDENT", "KEYWORD"):
            raise ParseError("class_member", name_tok.pos,
                             detail=f"unexpected {name_tok}")
        name = name_tok.value
        self.advance()
        is_constructor = name == "constructor"
        if self.check("PUNCT", "("):
            return self._parse_method_member(
                name, access, is_static, is_async, is_constructor,
            )
        return self._parse_field_member(name, access, is_static)

    # ---------------- params ----------------
    def _parse_params(self) -> List[Param]:
        self.expect("PUNCT", "(")
        params: List[Param] = []
        while not self.check("PUNCT", ")") and not self.eof():
            params.append(self._parse_one_param())
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", ")")
        return params

    def _parse_one_param(self) -> Param:
        # Rest, destructure, or simple ident.
        if self.match("PUNCT", "..."):
            name_tok = self.expect("IDENT")
            return Param(name="*" + name_tok.value, default=None)
        if self.check("PUNCT", "{"):
            d = self._parse_destructure_pattern("object")
            default = None
            if self.match("PUNCT", "="):
                default = self._parse_assignment()
            return Param(name=d, default=default)
        if self.check("PUNCT", "["):
            d = self._parse_destructure_pattern("array")
            default = None
            if self.match("PUNCT", "="):
                default = self._parse_assignment()
            return Param(name=d, default=default)
        tok = self.peek()
        if tok.kind not in ("IDENT", "KEYWORD"):
            raise ParseError("param", tok.pos, detail=f"unexpected {tok}")
        self.advance()
        default = None
        if self.match("PUNCT", "="):
            default = self._parse_assignment()
        return Param(name=tok.value, default=default)

    def _parse_object_destructure_entry(self, targets: List[str]) -> None:
        self.match("PUNCT", "...")
        if self.peek().kind in ("IDENT", "KEYWORD"):
            key = self.advance().value
            if self.match("PUNCT", ":"):
                if self.peek().kind in ("IDENT", "KEYWORD"):
                    targets.append(self.advance().value)
                else:
                    self._skip_balanced_in_destructure()
            else:
                targets.append(key)
            if self.match("PUNCT", "="):
                self._parse_assignment()
        else:
            self.advance()

    def _parse_array_destructure_entry(self, targets: List[str]) -> None:
        self.match("PUNCT", "...")
        if self.peek().kind in ("IDENT", "KEYWORD"):
            targets.append(self.advance().value)
            if self.match("PUNCT", "="):
                self._parse_assignment()
        elif self.check("PUNCT", ","):
            targets.append("_")
        else:
            self.advance()

    def _parse_destructure_pattern(self, kind: str) -> Destructure:
        open_p, close_p = ("{", "}") if kind == "object" else ("[", "]")
        entry = (self._parse_object_destructure_entry if kind == "object"
                 else self._parse_array_destructure_entry)
        self.expect("PUNCT", open_p)
        targets: List[str] = []
        while not self.check("PUNCT", close_p) and not self.eof():
            entry(targets)
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", close_p)
        return Destructure(kind=kind, targets=targets)

    def _skip_balanced_in_destructure(self) -> None:
        # Swallow one nested pattern.
        if self.check("PUNCT", "{") or self.check("PUNCT", "["):
            open_c = self.advance().value
            close_c = "}" if open_c == "{" else "]"
            depth = 1
            while not self.eof() and depth:
                t = self.advance()
                if t.kind == "PUNCT" and t.value == open_c:
                    depth += 1
                elif t.kind == "PUNCT" and t.value == close_c:
                    depth -= 1

    # ---------------- statements ----------------
    def _parse_block(self) -> Block:
        start = self.expect("PUNCT", "{").pos
        stmts: List[Node] = []
        while not self.eof() and not self.check("PUNCT", "}"):
            try:
                stmts.append(self._parse_statement())
            except ParseError:
                # Re-raise: caller (method-level) handles isolation.
                raise
        self.expect("PUNCT", "}")
        return Block(stmts=stmts)

    def _parse_break(self) -> Break:
        self.advance()
        self.match("PUNCT", ";")
        return Break()

    def _parse_continue(self) -> Continue:
        self.advance()
        self.match("PUNCT", ";")
        return Continue()

    def _parse_statement(self) -> Node:
        t = self.peek()
        if t.kind == "PUNCT" and t.value == "{":
            return self._parse_block()
        if t.kind == "PUNCT" and t.value == ";":
            self.advance()
            return ExprStmt(expr=Literal(value=None, kind="null"))
        if t.kind == "KEYWORD":
            handler = _STMT_DISPATCH.get(t.value)
            if handler is not None:
                return handler(self)
            if t.value in ("const", "let", "var"):
                return self._parse_var_decl()
        expr = self._parse_expression()
        self.match("PUNCT", ";")
        return ExprStmt(expr=expr)

    def _parse_var_decl(self) -> Node:
        kind = self.advance().value  # const/let/var
        decls: List[VarDecl] = []
        while True:
            # destructure or ident
            name: object
            if self.check("PUNCT", "{"):
                name = self._parse_destructure_pattern("object")
            elif self.check("PUNCT", "["):
                name = self._parse_destructure_pattern("array")
            else:
                tk = self.peek()
                if tk.kind not in ("IDENT", "KEYWORD"):
                    raise ParseError("var_decl", tk.pos,
                                     detail=f"unexpected {tk}")
                self.advance()
                name = Ident(name=tk.value)
            init = None
            if self.match("PUNCT", "="):
                init = self._parse_assignment()
            decls.append(VarDecl(kind=kind, name=name, init=init))
            if not self.match("PUNCT", ","):
                break
        self.match("PUNCT", ";")
        if len(decls) == 1:
            return decls[0]
        return Block(stmts=list(decls))

    def _parse_if(self) -> If:
        self.expect("KEYWORD", "if")
        self.expect("PUNCT", "(")
        cond = self._parse_expression()
        self.expect("PUNCT", ")")
        then = self._parse_statement()
        else_: Optional[Node] = None
        if self.match("KEYWORD", "else"):
            else_ = self._parse_statement()
        return If(cond=cond, then=then, else_=else_)

    def _parse_while(self) -> While:
        self.expect("KEYWORD", "while")
        self.expect("PUNCT", "(")
        cond = self._parse_expression()
        self.expect("PUNCT", ")")
        body = self._parse_statement()
        return While(cond=cond, body=body)

    def _parse_for_binding(self) -> object:
        if self.check("PUNCT", "{"):
            return self._parse_destructure_pattern("object")
        if self.check("PUNCT", "["):
            return self._parse_destructure_pattern("array")
        tk = self.expect("IDENT")
        return Ident(name=tk.value)

    def _try_parse_for_of(self, var_name: object) -> Optional[ForOf]:
        if not (self.peek().kind == "KEYWORD"
                and self.peek().value in ("of", "in")):
            return None
        is_in = self.advance().value == "in"
        iter_expr = self._parse_expression()
        self.expect("PUNCT", ")")
        body = self._parse_statement()
        return ForOf(var_name=var_name, iter=iter_expr, body=body, is_in=is_in)

    def _parse_for_init_decl(self) -> Tuple[Optional[Node], Optional[ForOf]]:
        decl_kind = self.advance().value
        binding = self._parse_for_binding()
        for_of = self._try_parse_for_of(binding)
        if for_of is not None:
            return None, for_of
        initial = self._parse_assignment() if self.match("PUNCT", "=") else None
        return VarDecl(kind=decl_kind, name=binding, init=initial), None

    def _parse_for_init_expr(self) -> Tuple[Optional[Node], Optional[ForOf]]:
        if self.check("PUNCT", ";"):
            return None, None
        init_expr = self._parse_expression()
        for_of = self._try_parse_for_of(init_expr)
        if for_of is not None:
            return None, for_of
        return ExprStmt(expr=init_expr), None

    def _parse_for(self) -> Node:
        self.expect("KEYWORD", "for")
        self.expect("PUNCT", "(")
        if self.peek().kind == "KEYWORD" and self.peek().value in (
            "const", "let", "var",
        ):
            init_node, for_of = self._parse_for_init_decl()
        else:
            init_node, for_of = self._parse_for_init_expr()
        if for_of is not None:
            return for_of
        self.expect("PUNCT", ";")
        cond = None if self.check("PUNCT", ";") else self._parse_expression()
        self.expect("PUNCT", ";")
        update = None if self.check("PUNCT", ")") else self._parse_expression()
        self.expect("PUNCT", ")")
        body = self._parse_statement()
        return ForC(init=init_node, cond=cond, update=update, body=body)

    def _parse_return(self) -> Return:
        self.expect("KEYWORD", "return")
        if self.check("PUNCT", ";") or self.check("PUNCT", "}"):
            self.match("PUNCT", ";")
            return Return(expr=None)
        expr = self._parse_expression()
        self.match("PUNCT", ";")
        return Return(expr=expr)

    def _parse_throw(self) -> Throw:
        self.expect("KEYWORD", "throw")
        expr = self._parse_expression()
        self.match("PUNCT", ";")
        return Throw(expr=expr)

    def _parse_try(self) -> TryCatch:
        self.expect("KEYWORD", "try")
        try_block = self._parse_block()
        catch_param = None
        catch_block: Optional[Block] = None
        finally_block: Optional[Block] = None
        if self.match("KEYWORD", "catch"):
            if self.match("PUNCT", "("):
                if self.peek().kind in ("IDENT", "KEYWORD"):
                    catch_param = self.advance().value
                self.expect("PUNCT", ")")
            catch_block = self._parse_block()
        if self.match("KEYWORD", "finally"):
            finally_block = self._parse_block()
        return TryCatch(try_block=try_block, catch_param=catch_param,
                        catch_block=catch_block, finally_block=finally_block)

    def _parse_switch(self) -> Node:
        # Parse as a generic block-ish structure; emitter will handle later.
        # For now we collapse to If/elif via ExprStmt markers.
        self.expect("KEYWORD", "switch")
        self.expect("PUNCT", "(")
        discriminant = self._parse_expression()
        self.expect("PUNCT", ")")
        self.expect("PUNCT", "{")
        cases: List[Tuple[Optional[Node], List[Node]]] = []
        while not self.eof() and not self.check("PUNCT", "}"):
            if self.match("KEYWORD", "case"):
                val = self._parse_expression()
                self.expect("PUNCT", ":")
                body: List[Node] = []
                while not self.eof() and not (
                    self.check("KEYWORD", "case")
                    or self.check("KEYWORD", "default")
                    or self.check("PUNCT", "}")
                ):
                    body.append(self._parse_statement())
                cases.append((val, body))
            elif self.match("KEYWORD", "default"):
                self.expect("PUNCT", ":")
                body = []
                while not self.eof() and not (
                    self.check("KEYWORD", "case")
                    or self.check("PUNCT", "}")
                ):
                    body.append(self._parse_statement())
                cases.append((None, body))
            else:
                self.advance()
        self.expect("PUNCT", "}")
        # Lower to nested If chain.
        else_node: Optional[Node] = None
        for val, body in reversed(cases):
            blk = Block(stmts=body)
            if val is None:
                else_node = blk
            else:
                cond = BinaryOp(op="===", left=discriminant, right=val)
                else_node = If(cond=cond, then=blk, else_=else_node)
        return else_node or Block(stmts=[])

    def _parse_function_decl(self) -> FuncDecl:
        is_async = bool(self.match("KEYWORD", "async"))
        self.expect("KEYWORD", "function")
        name = self.expect("IDENT").value
        params = self._parse_params()
        body = self._parse_block()
        return FuncDecl(name=name, params=params, body=body, is_async=is_async)

    # ---------------- expressions ----------------
    def _parse_expression(self) -> Node:
        expr = self._parse_assignment()
        while self.match("PUNCT", ","):
            _ = self._parse_assignment()  # ignore sequence result
        return expr

    def _parse_assignment(self) -> Node:
        left = self._parse_conditional()
        if self.peek().kind == "PUNCT" and self.peek().value in _ASSIGN_OPS:
            op = self.advance().value
            right = self._parse_assignment()
            return AssignOp(op=op, target=left, value=right)
        return left

    def _parse_conditional(self) -> Node:
        cond = self._parse_binary(0)
        if self.match("PUNCT", "?"):
            a = self._parse_assignment()
            self.expect("PUNCT", ":")
            b = self._parse_assignment()
            return Conditional(cond=cond, a=a, b=b)
        return cond

    def _parse_binary(self, min_prec: int) -> Node:
        left = self._parse_unary()
        while True:
            t = self.peek()
            op = None
            if t.kind == "PUNCT" and t.value in _BINOPS:
                op = t.value
            elif t.kind == "KEYWORD" and t.value in ("in", "instanceof"):
                op = t.value
            if op is None:
                return left
            prec = _BINOPS[op]
            if prec < min_prec:
                return left
            self.advance()
            right = self._parse_binary(prec + (0 if op == "**" else 1))
            left = BinaryOp(op=op, left=left, right=right)

    def _parse_unary(self) -> Node:
        t = self.peek()
        if t.kind == "PUNCT" and t.value in ("!", "-", "+", "~", "++", "--"):
            self.advance()
            operand = self._parse_unary()
            return UnaryOp(op=t.value, operand=operand, prefix=True)
        if t.kind == "KEYWORD" and t.value in ("typeof", "void", "delete", "await"):
            self.advance()
            operand = self._parse_unary()
            return UnaryOp(op=t.value, operand=operand, prefix=True)
        return self._parse_postfix()

    def _parse_postfix(self) -> Node:
        expr = self._parse_call()
        t = self.peek()
        if t.kind == "PUNCT" and t.value in ("++", "--"):
            self.advance()
            return UnaryOp(op=t.value, operand=expr, prefix=False)
        return expr

    def _parse_member_access(self, expr: Node) -> Node:
        prop_tok = self.peek()
        if prop_tok.kind not in ("IDENT", "KEYWORD"):
            raise ParseError("member", prop_tok.pos)
        self.advance()
        return Member(obj=expr, prop=prop_tok.value, computed=False)

    def _parse_optional_chain(self, expr: Node) -> Node:
        prop_tok = self.peek()
        if prop_tok.kind in ("IDENT", "KEYWORD"):
            self.advance()
            return Member(obj=expr, prop=prop_tok.value, computed=False)
        if self.check("PUNCT", "("):
            return Call(callee=expr, args=self._parse_call_args())
        if self.check("PUNCT", "["):
            self.advance()
            key = self._parse_expression()
            self.expect("PUNCT", "]")
            return Index(obj=expr, key=key)
        raise ParseError("optional_chain", prop_tok.pos)

    def _parse_index(self, expr: Node) -> Node:
        key = self._parse_expression()
        self.expect("PUNCT", "]")
        return Index(obj=expr, key=key)

    def _parse_call(self) -> Node:
        expr = self._parse_new_or_primary()
        while True:
            if self.match("PUNCT", "."):
                expr = self._parse_member_access(expr)
            elif self.match("PUNCT", "?."):
                expr = self._parse_optional_chain(expr)
            elif self.check("PUNCT", "("):
                expr = Call(callee=expr, args=self._parse_call_args())
            elif self.match("PUNCT", "["):
                expr = self._parse_index(expr)
            elif self.check("TEMPLATE"):
                tmpl = self._parse_primary()
                expr = Call(callee=expr, args=[tmpl])
            else:
                return expr

    def _parse_call_args(self) -> List[Node]:
        self.expect("PUNCT", "(")
        args: List[Node] = []
        while not self.check("PUNCT", ")") and not self.eof():
            if self.match("PUNCT", "..."):
                args.append(Spread(expr=self._parse_assignment()))
            else:
                args.append(self._parse_assignment())
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", ")")
        return args

    def _parse_new_or_primary(self) -> Node:
        if self.match("KEYWORD", "new"):
            callee = self._parse_new_or_primary()
            # Strip inner call if any — new Foo(args) parses as new with call
            args: List[Node] = []
            if isinstance(callee, Call):
                args = callee.args
                callee = callee.callee
            elif self.check("PUNCT", "("):
                args = self._parse_call_args()
            return NewExpr(callee=callee, args=args)
        return self._parse_primary()

    def _parse_function_expression(self) -> Arrow:
        self.advance()
        if self.peek().kind == "IDENT":
            self.advance()
        params = self._parse_params()
        body = self._parse_block()
        return Arrow(params=params, body=body, expr_body=False)

    def _parse_async_expression(self, t: Token) -> Node:
        self.advance()
        if self.check("PUNCT", "("):
            return self._parse_paren_or_arrow()
        if self.peek().kind == "IDENT":
            name = self.advance().value
            if self.match("PUNCT", "=>"):
                body = self._parse_arrow_body()
                return Arrow(params=[Param(name=name)], body=body,
                             expr_body=not isinstance(body, Block))
        raise ParseError("async_expr", t.pos)

    def _parse_primary_keyword(self, t: Token) -> Node:
        literal = _KEYWORD_LITERALS.get(t.value)
        if literal is not None:
            self.advance()
            value, kind = literal
            if kind in ("ident",):
                return Ident(name=value)
            return Literal(value=value, kind=kind)
        if t.value == "function":
            return self._parse_function_expression()
        if t.value == "async":
            return self._parse_async_expression(t)
        if t.value == "new":
            return self._parse_new_or_primary()
        raise ParseError("primary", t.pos, detail=f"unexpected {t}")

    def _parse_ident_primary(self, t: Token) -> Node:
        self.advance()
        if self.check("PUNCT", "=>"):
            self.advance()
            body = self._parse_arrow_body()
            return Arrow(params=[Param(name=t.value)], body=body,
                         expr_body=not isinstance(body, Block))
        return Ident(name=t.value)

    def _parse_template_primary(self, t: Token) -> Template:
        self.advance()
        str_parts: List[str] = []
        expr_parts: List[Node] = []
        for idx, chunk in enumerate(t.value):
            if idx % 2 == 0:
                str_parts.append(chunk)
            else:
                sub = _Parser(list(chunk) + [Token("EOF", None, (0, 0))])
                try:
                    expr_parts.append(sub._parse_expression())
                except ParseError:
                    expr_parts.append(Literal(value="", kind="string"))
        return Template(parts=str_parts, exprs=expr_parts)

    def _parse_primary(self) -> Node:
        t = self.peek()
        if t.kind == "PUNCT":
            if t.value == "(":
                return self._parse_paren_or_arrow()
            if t.value == "[":
                return self._parse_array()
            if t.value == "{":
                return self._parse_object()
        if t.kind == "KEYWORD":
            return self._parse_primary_keyword(t)
        if t.kind == "IDENT":
            return self._parse_ident_primary(t)
        if t.kind == "NUMBER":
            self.advance()
            return Literal(value=t.value, kind="number")
        if t.kind == "STRING":
            self.advance()
            return Literal(value=t.value[1], kind="string")
        if t.kind == "TEMPLATE":
            return self._parse_template_primary(t)
        if t.kind == "REGEX":
            self.advance()
            return Literal(value=t.value, kind="regex")
        raise ParseError("primary", t.pos, detail=f"unexpected {t}")

    def _parse_paren_or_arrow(self) -> Node:
        # Save position so we can backtrack.
        start = self.i
        self.expect("PUNCT", "(")
        # Quick sweep to the matching ')'; look ahead for '=>'.
        depth = 1
        j = self.i
        while j < len(self.toks) and depth:
            tk = self.toks[j]
            if tk.kind == "PUNCT":
                if tk.value == "(":
                    depth += 1
                elif tk.value == ")":
                    depth -= 1
            j += 1
        # j is one past matching ')'
        is_arrow = (
            j < len(self.toks)
            and self.toks[j].kind == "PUNCT"
            and self.toks[j].value == "=>"
        )
        if is_arrow:
            # Rewind & parse formal params.
            self.i = start
            params = self._parse_params()
            self.expect("PUNCT", "=>")
            body = self._parse_arrow_body()
            return Arrow(params=params, body=body,
                         expr_body=not isinstance(body, Block))
        # Otherwise: grouped expression (or empty).
        if self.match("PUNCT", ")"):
            return Literal(value=None, kind="null")
        expr = self._parse_expression()
        self.expect("PUNCT", ")")
        return expr

    def _parse_arrow_body(self) -> Node:
        if self.check("PUNCT", "{"):
            return self._parse_block()
        return self._parse_assignment()

    def _parse_array(self) -> Array:
        self.expect("PUNCT", "[")
        items: List[Node] = []
        while not self.check("PUNCT", "]") and not self.eof():
            if self.match("PUNCT", "..."):
                items.append(Spread(expr=self._parse_assignment()))
            elif self.check("PUNCT", ","):
                items.append(Literal(value=None, kind="null"))  # hole
            else:
                items.append(self._parse_assignment())
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", "]")
        return Array(items=items)

    def _parse_object_key(self) -> object:
        key_tok = self.peek()
        if key_tok.kind == "STRING":
            self.advance()
            return key_tok.value[1]
        if key_tok.kind == "NUMBER":
            self.advance()
            return key_tok.value
        if key_tok.kind == "PUNCT" and key_tok.value == "[":
            self.advance()
            key = self._parse_assignment()
            self.expect("PUNCT", "]")
            return key
        if key_tok.kind in ("IDENT", "KEYWORD"):
            self.advance()
            return key_tok.value
        raise ParseError("object_key", key_tok.pos, detail=f"unexpected {key_tok}")

    def _parse_object_value(self, key: object, key_pos: Tuple[int, int]) -> Node:
        if self.check("PUNCT", "("):
            params = self._parse_params()
            body = self._parse_block()
            return Arrow(params=params, body=body, expr_body=False)
        if self.match("PUNCT", ":"):
            return self._parse_assignment()
        if isinstance(key, str):
            return Ident(name=key)
        raise ParseError("object_shorthand", key_pos)

    def _parse_object(self) -> Object:
        self.expect("PUNCT", "{")
        pairs: List[Tuple[object, Node]] = []
        while not self.check("PUNCT", "}") and not self.eof():
            if self.match("PUNCT", "..."):
                pairs.append(("__spread__", self._parse_assignment()))
                if not self.match("PUNCT", ","):
                    break
                continue
            key_pos = self.peek().pos
            key = self._parse_object_key()
            value = self._parse_object_value(key, key_pos)
            pairs.append((key, value))
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", "}")
        return Object(pairs=pairs)


# ------------- statement keyword dispatch -------------
_STMT_DISPATCH: dict = {
    "if": _Parser._parse_if,
    "for": _Parser._parse_for,
    "while": _Parser._parse_while,
    "return": _Parser._parse_return,
    "throw": _Parser._parse_throw,
    "try": _Parser._parse_try,
    "break": _Parser._parse_break,
    "continue": _Parser._parse_continue,
    "function": _Parser._parse_function_decl,
    "switch": _Parser._parse_switch,
    "const": _Parser._parse_var_decl,
    "let": _Parser._parse_var_decl,
    "var": _Parser._parse_var_decl,
}


# ------------- per-method isolation wrapper -------------


def parse(tokens: List[Token]) -> Program:
    """Parse a token stream into a ``Program``. Class members that fail to
    parse are skipped and recorded on ``Program.failed_methods``.
    """
    p = _Parser(tokens)
    return p.parse_program()
