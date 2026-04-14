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
        # Walk forward past the next top-level `{...}` block, or to a ';'.
        depth = 0
        while not self.eof():
            t = self.peek()
            if t.kind == "PUNCT":
                if t.value == "{":
                    depth += 1
                    self.advance()
                    continue
                if t.value == "}":
                    if depth == 0:
                        return  # class end; outer loop handles it
                    depth -= 1
                    self.advance()
                    if depth == 0:
                        return
                    continue
                if t.value == ";" and depth == 0:
                    self.advance()
                    return
            self.advance()

    def _parse_class_member(self) -> Optional[Node]:
        # Re-strip residual modifiers (preprocessor may miss some combos).
        access = "public"
        is_static = False
        is_async = False
        while True:
            tok = self.peek()
            if tok.kind == "KEYWORD" and tok.value in ("static", "async"):
                if tok.value == "static":
                    is_static = True
                elif tok.value == "async":
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

        # Method or field?
        name_tok = self.peek()
        if name_tok.kind not in ("IDENT", "KEYWORD"):
            raise ParseError("class_member", name_tok.pos,
                             detail=f"unexpected {name_tok}")
        name = name_tok.value
        self.advance()
        is_constructor = name == "constructor"

        if self.check("PUNCT", "("):
            params = self._parse_params()
            # Residual return-type annotation survived: skip `: ...` until `{`.
            if self.check("PUNCT", ":"):
                while not self.eof() and not self.check("PUNCT", "{"):
                    self.advance()
            body = self._parse_block()
            return MethodDecl(
                name=name, params=params, body=body,
                is_static=is_static, access=access,
                is_constructor=is_constructor, is_async=is_async,
            )

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

    def _parse_destructure_pattern(self, kind: str) -> Destructure:
        if kind == "object":
            self.expect("PUNCT", "{")
            targets: List[str] = []
            while not self.check("PUNCT", "}") and not self.eof():
                self.match("PUNCT", "...")
                # Accept `name` or `name: alias` (alias becomes target)
                if self.peek().kind in ("IDENT", "KEYWORD"):
                    key = self.advance().value
                    if self.match("PUNCT", ":"):
                        # alias or nested
                        if self.peek().kind in ("IDENT", "KEYWORD"):
                            targets.append(self.advance().value)
                        else:
                            # nested — skip
                            self._skip_balanced_in_destructure()
                    else:
                        targets.append(key)
                    # default
                    if self.match("PUNCT", "="):
                        self._parse_assignment()
                else:
                    # skip unknown
                    self.advance()
                if not self.match("PUNCT", ","):
                    break
            self.expect("PUNCT", "}")
            return Destructure(kind="object", targets=targets)
        else:
            self.expect("PUNCT", "[")
            targets: List[str] = []
            while not self.check("PUNCT", "]") and not self.eof():
                self.match("PUNCT", "...")
                if self.peek().kind in ("IDENT", "KEYWORD"):
                    targets.append(self.advance().value)
                    if self.match("PUNCT", "="):
                        self._parse_assignment()
                elif self.check("PUNCT", ","):
                    targets.append("_")
                else:
                    self.advance()
                if not self.match("PUNCT", ","):
                    break
            self.expect("PUNCT", "]")
            return Destructure(kind="array", targets=targets)

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

    def _parse_statement(self) -> Node:
        t = self.peek()
        if t.kind == "PUNCT" and t.value == "{":
            return self._parse_block()
        if t.kind == "PUNCT" and t.value == ";":
            self.advance()
            return ExprStmt(expr=Literal(value=None, kind="null"))
        if t.kind == "KEYWORD":
            v = t.value
            if v in ("const", "let", "var"):
                return self._parse_var_decl()
            if v == "if":
                return self._parse_if()
            if v == "for":
                return self._parse_for()
            if v == "while":
                return self._parse_while()
            if v == "return":
                return self._parse_return()
            if v == "throw":
                return self._parse_throw()
            if v == "try":
                return self._parse_try()
            if v == "break":
                self.advance()
                self.match("PUNCT", ";")
                return Break()
            if v == "continue":
                self.advance()
                self.match("PUNCT", ";")
                return Continue()
            if v == "function":
                return self._parse_function_decl()
            if v == "switch":
                return self._parse_switch()
        # Expression statement.
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

    def _parse_for(self) -> Node:
        self.expect("KEYWORD", "for")
        self.expect("PUNCT", "(")
        # Peek: for-of / for-in / for-C
        save = self.i
        init_node: Optional[Node] = None
        is_decl = False
        decl_kind = None
        if self.peek().kind == "KEYWORD" and self.peek().value in (
            "const", "let", "var",
        ):
            decl_kind = self.advance().value
            is_decl = True
            # read one binding
            if self.check("PUNCT", "{"):
                binding: object = self._parse_destructure_pattern("object")
            elif self.check("PUNCT", "["):
                binding = self._parse_destructure_pattern("array")
            else:
                tk = self.expect("IDENT")
                binding = Ident(name=tk.value)
            # for-of / for-in
            if self.peek().kind == "KEYWORD" and self.peek().value in ("of", "in"):
                is_in = self.advance().value == "in"
                iter_expr = self._parse_expression()
                self.expect("PUNCT", ")")
                body = self._parse_statement()
                return ForOf(var_name=binding, iter=iter_expr, body=body,
                             is_in=is_in)
            # Otherwise it's a C-style for; assemble init
            if self.match("PUNCT", "="):
                initial = self._parse_assignment()
                init_node = VarDecl(kind=decl_kind, name=binding, init=initial)
            else:
                init_node = VarDecl(kind=decl_kind, name=binding, init=None)
        else:
            # Either empty init or expression
            if not self.check("PUNCT", ";"):
                init_expr = self._parse_expression()
                # for (x of y)
                if self.peek().kind == "KEYWORD" and self.peek().value in ("of", "in"):
                    is_in = self.advance().value == "in"
                    iter_expr = self._parse_expression()
                    self.expect("PUNCT", ")")
                    body = self._parse_statement()
                    return ForOf(var_name=init_expr, iter=iter_expr, body=body,
                                 is_in=is_in)
                init_node = ExprStmt(expr=init_expr)
        self.expect("PUNCT", ";")
        cond = None
        if not self.check("PUNCT", ";"):
            cond = self._parse_expression()
        self.expect("PUNCT", ";")
        update = None
        if not self.check("PUNCT", ")"):
            update = self._parse_expression()
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

    def _parse_call(self) -> Node:
        expr = self._parse_new_or_primary()
        while True:
            if self.match("PUNCT", "."):
                prop_tok = self.peek()
                if prop_tok.kind in ("IDENT", "KEYWORD"):
                    self.advance()
                    expr = Member(obj=expr, prop=prop_tok.value, computed=False)
                else:
                    raise ParseError("member", prop_tok.pos)
            elif self.match("PUNCT", "?."):
                prop_tok = self.peek()
                if prop_tok.kind in ("IDENT", "KEYWORD"):
                    self.advance()
                    expr = Member(obj=expr, prop=prop_tok.value, computed=False)
                elif self.check("PUNCT", "("):
                    args = self._parse_call_args()
                    expr = Call(callee=expr, args=args)
                elif self.check("PUNCT", "["):
                    self.advance()
                    key = self._parse_expression()
                    self.expect("PUNCT", "]")
                    expr = Index(obj=expr, key=key)
                else:
                    raise ParseError("optional_chain", prop_tok.pos)
            elif self.check("PUNCT", "("):
                args = self._parse_call_args()
                expr = Call(callee=expr, args=args)
            elif self.match("PUNCT", "["):
                key = self._parse_expression()
                self.expect("PUNCT", "]")
                expr = Index(obj=expr, key=key)
            elif self.check("TEMPLATE"):
                # Tagged template — treat as call(templatestring).
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

    def _parse_primary(self) -> Node:
        t = self.peek()
        # Parenthesized expression or arrow function
        if t.kind == "PUNCT" and t.value == "(":
            return self._parse_paren_or_arrow()
        if t.kind == "PUNCT" and t.value == "[":
            return self._parse_array()
        if t.kind == "PUNCT" and t.value == "{":
            return self._parse_object()
        if t.kind == "KEYWORD":
            if t.value == "this":
                self.advance()
                return Ident(name="this")
            if t.value == "super":
                self.advance()
                return Ident(name="super")
            if t.value == "true":
                self.advance()
                return Literal(value=True, kind="bool")
            if t.value == "false":
                self.advance()
                return Literal(value=False, kind="bool")
            if t.value == "null":
                self.advance()
                return Literal(value=None, kind="null")
            if t.value == "undefined":
                self.advance()
                return Literal(value=None, kind="undefined")
            if t.value == "function":
                # Function expression: function [name]?(params){ body }
                self.advance()
                if self.peek().kind == "IDENT":
                    self.advance()
                params = self._parse_params()
                body = self._parse_block()
                return Arrow(params=params, body=body, expr_body=False)
            if t.value == "async":
                # async arrow
                self.advance()
                if self.check("PUNCT", "("):
                    return self._parse_paren_or_arrow()
                # async ident =>
                if self.peek().kind == "IDENT":
                    name = self.advance().value
                    if self.match("PUNCT", "=>"):
                        body = self._parse_arrow_body()
                        return Arrow(params=[Param(name=name)], body=body,
                                     expr_body=not isinstance(body, Block))
                raise ParseError("async_expr", t.pos)
            if t.value == "new":
                return self._parse_new_or_primary()
        if t.kind == "IDENT":
            self.advance()
            # arrow with single ident param: x => ...
            if self.check("PUNCT", "=>"):
                self.advance()
                body = self._parse_arrow_body()
                return Arrow(params=[Param(name=t.value)], body=body,
                             expr_body=not isinstance(body, Block))
            return Ident(name=t.value)
        if t.kind == "NUMBER":
            self.advance()
            return Literal(value=t.value, kind="number")
        if t.kind == "STRING":
            self.advance()
            # t.value is (quote, content)
            return Literal(value=t.value[1], kind="string")
        if t.kind == "TEMPLATE":
            self.advance()
            parts_raw = t.value
            str_parts: List[str] = []
            expr_parts: List[Node] = []
            for idx, chunk in enumerate(parts_raw):
                if idx % 2 == 0:
                    str_parts.append(chunk)
                else:
                    # chunk is a list of tokens for the embedded expression
                    sub = _Parser(list(chunk) + [Token("EOF", None, (0, 0))])
                    try:
                        expr_parts.append(sub._parse_expression())
                    except ParseError:
                        expr_parts.append(Literal(value="", kind="string"))
            return Template(parts=str_parts, exprs=expr_parts)
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

    def _parse_object(self) -> Object:
        self.expect("PUNCT", "{")
        pairs: List[Tuple[object, Node]] = []
        while not self.check("PUNCT", "}") and not self.eof():
            if self.match("PUNCT", "..."):
                pairs.append(("__spread__", self._parse_assignment()))
                if not self.match("PUNCT", ","):
                    break
                continue
            key_tok = self.peek()
            key: object
            if key_tok.kind == "STRING":
                self.advance()
                key = key_tok.value[1]
            elif key_tok.kind == "NUMBER":
                self.advance()
                key = key_tok.value
            elif key_tok.kind == "PUNCT" and key_tok.value == "[":
                self.advance()
                key = self._parse_assignment()
                self.expect("PUNCT", "]")
            elif key_tok.kind in ("IDENT", "KEYWORD"):
                self.advance()
                key = key_tok.value
            else:
                raise ParseError("object_key", key_tok.pos,
                                 detail=f"unexpected {key_tok}")
            # Shorthand method: key(params) { body }
            if self.check("PUNCT", "("):
                params = self._parse_params()
                body = self._parse_block()
                value: Node = Arrow(params=params, body=body, expr_body=False)
            elif self.match("PUNCT", ":"):
                value = self._parse_assignment()
            else:
                # Shorthand property
                if isinstance(key, str):
                    value = Ident(name=key)
                else:
                    raise ParseError("object_shorthand", key_tok.pos)
            pairs.append((key, value))
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", "}")
        return Object(pairs=pairs)


# ------------- per-method isolation wrapper -------------


def parse(tokens: List[Token]) -> Program:
    """Parse a token stream into a ``Program``. Class members that fail to
    parse are skipped and recorded on ``Program.failed_methods``.
    """
    p = _Parser(tokens)
    return p.parse_program()
