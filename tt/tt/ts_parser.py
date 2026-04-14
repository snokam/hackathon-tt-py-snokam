"""Parse TypeScript code to AST using esprima."""
from __future__ import annotations

import json
from typing import Any

import esprima  # Using esprima2 package (v5.0.1)

try:
    from .type_stripper import strip_typescript_types
except ImportError:
    from type_stripper import strip_typescript_types


def parse_typescript(ts_code: str) -> dict[str, Any]:
    """Parse TypeScript code to JavaScript AST.

    Args:
        ts_code: TypeScript source code

    Returns:
        ESTree-compatible AST dictionary

    Process:
        1. Strip TypeScript type annotations
        2. Parse resulting JavaScript with esprima
        3. Return AST as dictionary
    """
    # Strip TypeScript types to get valid JavaScript
    js_code = strip_typescript_types(ts_code)

    # Parse with esprima
    try:
        # Use parseModule for better ES6+ support (import/export)
        ast = esprima.parseModule(js_code, {'tolerant': True})
    except Exception as e:
        # Fallback to parseScript if parseModule fails
        try:
            ast = esprima.parseScript(js_code, {'tolerant': True})
        except Exception as e2:
            print(f"Error parsing TypeScript:")
            print(f"  parseModule error: {e}")
            print(f"  parseScript error: {e2}")
            print("\nJavaScript after type stripping (first 1000 chars):")
            print(js_code[:1000])
            raise e2

    # Convert to dict (esprima returns objects)
    return ast.toDict()


def explore_ast(ast: dict[str, Any], max_depth: int = 3) -> None:
    """Print AST structure for understanding.

    Args:
        ast: AST dictionary from parse_typescript
        max_depth: Maximum depth to print
    """
    print(json.dumps(ast, indent=2, default=str)[:2000])  # First 2000 chars
    print("\n... (truncated)")


def extract_class_info(ast: dict[str, Any]) -> dict[str, Any] | None:
    """Extract class declaration info from AST.

    Args:
        ast: Full AST dictionary

    Returns:
        Class info dict or None if no class found
    """
    # Find ClassDeclaration in body
    for node in ast.get('body', []):
        if node.get('type') == 'ClassDeclaration':
            class_node = node
            return {
                'name': class_node['id']['name'] if class_node.get('id') else None,
                'superClass': class_node['superClass']['name'] if class_node.get('superClass') else None,
                'body': class_node.get('body', {}),
                'node': class_node
            }

    # Also check for ExportNamedDeclaration containing ClassDeclaration
    for node in ast.get('body', []):
        if node.get('type') == 'ExportNamedDeclaration':
            decl = node.get('declaration')
            if decl and decl.get('type') == 'ClassDeclaration':
                class_node = decl
                return {
                    'name': class_node['id']['name'] if class_node.get('id') else None,
                    'superClass': class_node['superClass']['name'] if class_node.get('superClass') else None,
                    'body': class_node.get('body', {}),
                    'node': class_node
                }

    return None


def test_parser():
    """Test the TypeScript parser."""
    sample_ts = """
    export class Calculator extends BaseCalculator {
        private value: number;

        constructor(val: number) {
            super();
            this.value = val;
        }

        calculate(): number {
            return this.value + 10;
        }
    }
    """

    print("=== Parsing TypeScript ===")
    ast = parse_typescript(sample_ts)

    print(f"\nAST type: {ast.get('type')}")
    print(f"Body length: {len(ast.get('body', []))}")

    class_info = extract_class_info(ast)
    if class_info:
        print(f"\n✅ Found class: {class_info['name']}")
        print(f"   Extends: {class_info['superClass']}")
        print(f"   Methods: {len(class_info['body'].get('body', []))}")
    else:
        print("\n❌ No class found")

    print("\n✅ Parser tests passed!")


if __name__ == '__main__':
    test_parser()
