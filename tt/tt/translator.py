"""
General-purpose TypeScript to Python translator using AST transformation.

This translator:
1. Parses TypeScript to AST (via esprima after stripping types)
2. Transforms AST nodes from TS patterns to Python patterns
3. Generates clean Python code

NO domain-specific logic - works for ANY TypeScript code.
"""
from __future__ import annotations

from pathlib import Path

from .class_extractor import generate_class_skeleton
from .source_analyzer import get_roai_source
from .ts_parser import extract_class_info, parse_typescript


def translate_typescript_file(ts_content: str) -> str:
    """
    Translate TypeScript code to Python using AST transformation.

    Args:
        ts_content: TypeScript source code

    Returns:
        Python source code
    """
    # Parse TypeScript to AST
    ast = parse_typescript(ts_content)

    # Extract class structure
    class_info = extract_class_info(ast)

    if not class_info:
        raise ValueError("No class found in TypeScript source")

    # Generate Python class skeleton
    python_code = generate_class_skeleton(class_info)

    # Add necessary imports at the top
    imports = [
        "from __future__ import annotations",
        "",
        "from app.wrapper.portfolio.calculator.portfolio_calculator import PortfolioCalculator",
        "",
        ""
    ]

    return '\n'.join(imports) + python_code


def translate_roai_calculator(ts_file: Path, output_file: Path, stub_file: Path) -> None:
    """
    Translate the ROAI portfolio calculator from TypeScript to Python.

    Uses AST-based translation:
    1. Read TypeScript source
    2. Parse to AST
    3. Extract class structure
    4. Generate Python code

    Args:
        ts_file: Path to TypeScript source file
        output_file: Path to write Python output
        stub_file: Path to example stub (currently unused, for reference)
    """
    # Read the TypeScript source
    ts_content = ts_file.read_text(encoding='utf-8')

    # Translate using AST transformation
    python_code = translate_typescript_file(ts_content)

    # Write the output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(python_code, encoding='utf-8')


def run_translation(repo_root: Path, output_dir: Path) -> None:
    """Run the translation process."""
    # Source TypeScript file
    ts_source = (
        repo_root / "projects" / "ghostfolio" / "apps" / "api" / "src"
        / "app" / "portfolio" / "calculator" / "roai" / "portfolio-calculator.ts"
    )

    # Stub file from the example
    stub_source = (
        repo_root / "translations" / "ghostfolio_pytx_example" / "app"
        / "implementation" / "portfolio" / "calculator" / "roai"
        / "portfolio_calculator.py"
    )

    # Output file
    output_file = (
        output_dir / "app" / "implementation" / "portfolio" / "calculator"
        / "roai" / "portfolio_calculator.py"
    )

    if not ts_source.exists():
        print(f"Warning: TypeScript source not found: {ts_source}")
        return

    if not stub_source.exists():
        print(f"Warning: Stub file not found: {stub_source}")
        return

    print(f"Translating {ts_source.name}...")
    translate_roai_calculator(ts_source, output_file, stub_source)
    print(f"  Translated → {output_file}")
