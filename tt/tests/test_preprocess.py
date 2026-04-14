"""Unit tests for :mod:`tt.preprocess`.

These are representative snippets distilled from the ROAI TS file plus a few
synthetic edge cases that previously tripped the stripper.
"""

from __future__ import annotations

from tt.preprocess import preprocess


def test_interface_removed():
    src = "interface Foo { a: number; b: string; }\nconst x = 1;"
    out = preprocess(src)
    assert "interface" not in out
    assert "const x = 1" in out


def test_type_alias_removed():
    src = "type Id = string;\nlet y = 'hello';"
    out = preprocess(src)
    assert "type Id" not in out
    assert "let y = 'hello'" in out


def test_import_type_removed():
    src = "import type { Foo } from 'bar';\nconst z = 2;"
    out = preprocess(src)
    assert "import type" not in out


def test_access_modifiers_stripped():
    src = "class C {\n  public foo() {}\n  private readonly bar = 1;\n}"
    out = preprocess(src)
    assert "public foo" not in out
    assert "private" not in out
    assert "readonly" not in out
    assert "foo()" in out


def test_as_cast_stripped():
    src = "const x = y as Big;"
    out = preprocess(src)
    assert "as Big" not in out
    assert "const x = y" in out


def test_nonnull_assertion_stripped():
    src = "const v = obj!.field;"
    out = preprocess(src)
    assert "!" not in out.split("=")[1]
    assert "obj.field" in out


def test_object_literal_colons_preserved():
    src = "const r = { a: 1, b: 'x' };"
    out = preprocess(src)
    # Must still have `a: 1` and `b: 'x'`; object-literal colons are NOT
    # annotations.
    assert "a: 1" in out
    assert "b: 'x'" in out


def test_function_param_annotation_stripped():
    src = "function f(x: number, y: string): boolean { return true; }"
    out = preprocess(src)
    assert "number" not in out
    assert "string" not in out
    assert "boolean" not in out
    assert "function f" in out
    assert "return true" in out
