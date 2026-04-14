"""Analyze TypeScript source to understand what needs to be translated."""
from __future__ import annotations

from pathlib import Path

def read_typescript_source(file_path: str | Path) -> str:
    """Read TypeScript source file."""
    path = Path(file_path) if isinstance(file_path, str) else file_path
    return path.read_text(encoding='utf-8')


def get_roai_source() -> str:
    """Get the ROAI portfolio calculator TypeScript source."""
    root = Path(__file__).parent.parent.parent  # Get to repo root
    ts_file = root / "projects" / "ghostfolio" / "apps" / "api" / "src" / "app" / "portfolio" / "calculator" / "roai" / "portfolio-calculator.ts"
    return read_typescript_source(ts_file)


def get_base_calculator_source() -> str:
    """Get the base PortfolioCalculator TypeScript source."""
    root = Path(__file__).parent.parent.parent
    ts_file = root / "projects" / "ghostfolio" / "apps" / "api" / "src" / "app" / "portfolio" / "calculator" / "portfolio-calculator.ts"
    return read_typescript_source(ts_file)
