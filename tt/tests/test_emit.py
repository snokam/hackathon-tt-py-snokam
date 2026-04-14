"""Smoke tests for the AST emitter pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tt import emitter, lexer, parser, preprocess
from tt.ast_nodes import ClassDecl


SCAFFOLD = (
    Path(__file__).parent.parent
    / "tt"
    / "scaffold"
    / "ghostfolio_pytx"
    / "tt_import_map.json"
)


def _import_map():
    return json.loads(SCAFFOLD.read_text("utf-8"))


def _parse_method_from_source(ts_src: str, method_name: str):
    pre = preprocess.preprocess(ts_src)
    toks = lexer.tokenize(pre)
    prog = parser.parse(toks)
    for cls in prog.body:
        if isinstance(cls, ClassDecl):
            for m in cls.members:
                if getattr(m, "name", None) == method_name:
                    return m
    raise AssertionError(f"method {method_name!r} not parsed from source")


def _ctx():
    return {"import_map": _import_map(), "imports": set(), "keep_names": set()}


def test_emit_performance_calculation_type():
    ts = """
    export class Roai {
      public getPerformanceCalculationType() {
        return 'ROAI';
      }
    }
    """
    method = _parse_method_from_source(ts, "getPerformanceCalculationType")
    py = emitter.emit_method(method, _ctx())
    assert "def get_performance_calculation_type(self)" in py
    assert "return 'ROAI'" in py or 'return "ROAI"' in py


def test_emit_simple_aggregation():
    ts = """
    export class Roai {
      calculateOverallPerformance(positions) {
        let totalInvestment = new Big(0);
        for (const p of positions) {
          totalInvestment = totalInvestment.plus(p.investment);
        }
        return totalInvestment;
      }
    }
    """
    method = _parse_method_from_source(ts, "calculateOverallPerformance")
    ctx = _ctx()
    py = emitter.emit_method(method, ctx)
    assert "total_investment" in py
    assert "for p in positions" in py
    assert "Big(" in py
    # Big should appear in imports.
    imports = emitter.collect_imports(ctx)
    assert any("Big" in line for line in imports)


def test_emit_for_range():
    ts = """
    export class Roai {
      sum(n) {
        let s = 0;
        for (let i = 0; i < n; i++) {
          s = s + i;
        }
        return s;
      }
    }
    """
    method = _parse_method_from_source(ts, "sum")
    py = emitter.emit_method(method, _ctx())
    assert "for i in range(0, n)" in py
