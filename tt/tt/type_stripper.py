"""Strip TypeScript type annotations to get valid JavaScript for parsing."""
from __future__ import annotations

import re


def strip_typescript_types(ts_code: str) -> str:
    """Remove TypeScript-specific syntax to get valid JavaScript.

    This is a general-purpose TypeScript-to-JavaScript converter that:
    - Removes type annotations
    - Removes interface/type declarations
    - Removes generic type parameters
    - Removes type casts
    - Preserves all actual code logic

    Args:
        ts_code: TypeScript source code

    Returns:
        JavaScript source code (parseable by esprima)
    """
    js_code = ts_code

    # Remove import type statements
    js_code = re.sub(r'import\s+type\s+.*?;', '', js_code, flags=re.MULTILINE)

    # Remove interface declarations
    js_code = re.sub(
        r'(export\s+)?(interface|type)\s+\w+[^{;]*(\{[^}]*\}|;)',
        '',
        js_code,
        flags=re.MULTILINE | re.DOTALL
    )

    # Remove generic type parameters from class/function declarations
    # e.g., class Foo<T> → class Foo
    js_code = re.sub(r'(\w+)\s*<[^>]+>(?=\s*extends|\s*\{|\s*\()', r'\1', js_code)

    # Remove type annotations from variable declarations
    # e.g., const x: number = 5 → const x = 5
    # e.g., data: Big[] → data
    js_code = re.sub(r'(\w+)\s*:\s*[A-Za-z_][A-Za-z0-9_<>\[\]|&\s]*(?=\s*[=;,\)])', r'\1', js_code)

    # Remove return type annotations
    # e.g., function foo(): number { → function foo() {
    js_code = re.sub(r'\)\s*:\s*[A-Za-z_][A-Za-z0-9_<>\[\]|&\s]*(?=\s*\{)', ')', js_code)

    # Remove optional parameter indicator with type
    # e.g., y?: string → y
    js_code = re.sub(r'(\w+)\?\s*:\s*[A-Za-z_][A-Za-z0-9_<>\[\]|&\s]*', r'\1', js_code)

    # Remove 'as Type' casts
    js_code = re.sub(r'\s+as\s+[A-Za-z_][A-Za-z0-9_<>\[\]|&\s]*', '', js_code)

    # Remove access modifiers (public, private, protected)
    # Keep them as identifiers but remove when used as modifiers
    js_code = re.sub(r'\b(public|private|protected|readonly)\s+', '', js_code)

    # Remove class field declarations without initializers (TypeScript-only feature)
    # e.g., inside a class: "value;" or "private data: number[];" → remove entire line
    # But keep lines with =  (e.g., "value = 5;")
    # This is a class body context, so we need to be careful
    js_code = re.sub(r'^\s+\w+\s*;\s*$', '', js_code, flags=re.MULTILINE)

    # Remove abstract keyword
    js_code = re.sub(r'\babstract\s+', '', js_code)

    # Remove declare keyword
    js_code = re.sub(r'\bdeclare\s+', '', js_code)

    # Remove ! non-null assertions
    js_code = re.sub(r'!(?=\.|\[|\s|;|,|\))', '', js_code)

    # Remove optional ? from properties (but keep ternary operator)
    # This is tricky - only remove ? when it's part of property definition
    js_code = re.sub(r'(\w+)\?(?=:)', r'\1', js_code)

    return js_code


def test_type_stripper():
    """Test the type stripper with sample TypeScript code."""
    sample_ts = """
    import { Big } from 'big.js';
    import type { SomeType } from 'module';

    interface Config {
        name: string;
        value: number;
    }

    export class Calculator extends BaseCalculator {
        private data: Big[];

        constructor(value: number) {
            super();
            this.data = [new Big(value)];
        }

        calculate(x: number, y?: string): Big {
            const result: Big = new Big(x);
            return result.plus(10) as Big;
        }
    }
    """

    js_result = strip_typescript_types(sample_ts)
    print("=== TypeScript Input ===")
    print(sample_ts)
    print("\n=== JavaScript Output ===")
    print(js_result)

    # Verify key transformations
    assert 'import type' not in js_result
    assert 'interface Config' not in js_result
    assert ': Big' not in js_result
    assert ': number' not in js_result
    assert 'as Big' not in js_result
    assert 'private ' not in js_result
    assert 'class Calculator extends BaseCalculator' in js_result

    print("\n✅ Type stripper tests passed!")


if __name__ == '__main__':
    test_type_stripper()
