"""Smoke test: preprocess -> tokenize -> parse the real ROAI TS source."""

from __future__ import annotations

from pathlib import Path

from tt.ast_nodes import ClassDecl, MethodDecl, Program
from tt.lexer import tokenize
from tt.parser import parse
from tt.preprocess import preprocess


ROAI_TS = (
    Path(__file__).resolve().parent.parent.parent
    / "projects"
    / "ghostfolio"
    / "apps"
    / "api"
    / "src"
    / "app"
    / "portfolio"
    / "calculator"
    / "roai"
    / "portfolio-calculator.ts"
)


def test_parse_roai_smoke(capsys):
    src = ROAI_TS.read_text()
    pp = preprocess(src)
    toks = tokenize(pp)
    prog = parse(toks)

    # (a) Program was produced
    assert isinstance(prog, Program)
    classes = [n for n in prog.body if isinstance(n, ClassDecl)]
    assert classes, "expected at least one class"

    cls = classes[0]
    assert cls.name == "RoaiPortfolioCalculator"

    # (b) At least the two cornerstone methods are present.
    methods = {
        m.name for m in cls.members if isinstance(m, MethodDecl)
    }
    assert "getPerformanceCalculationType" in methods, methods
    assert "calculateOverallPerformance" in methods, methods

    # (c) Print failed methods for visibility.
    total_members = sum(1 for m in cls.members if isinstance(m, MethodDecl))
    print(f"\n[smoke] parsed {total_members} methods; failed={len(cls.failed_methods)}")
    for name, reason in cls.failed_methods:
        print(f"  FAILED {name}: {reason}")
    captured = capsys.readouterr()
    assert "parsed" in captured.out
