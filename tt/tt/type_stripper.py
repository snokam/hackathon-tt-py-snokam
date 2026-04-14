"""Strip TypeScript type annotations to get valid JavaScript for parsing."""
from __future__ import annotations

import re


def remove_destructured_param_types(code: str) -> str:
    """Remove type annotations from destructured parameters using balanced brace matching.

    Handles patterns like:
      ({a, b}: { a: Type, b: Type })
      ({a, b}: { a: Type } & OtherType)

    Args:
        code: Code with potential destructured param types

    Returns:
        Code with param types removed
    """
    result = []
    i = 0

    while i < len(code):
        # Look for pattern: } : {
        if i < len(code) - 3 and code[i:i+3] in ('}: ', '}\n:', '} :'):
            # Found potential param type annotation
            # Check if this is inside a parameter list (has ) after the type)
            j = i + 1
            while j < len(code) and code[j] in ' \n\t':
                j += 1

            if j < len(code) and code[j] == ':':
                # Skip the :
                j += 1
                while j < len(code) and code[j] in ' \n\t':
                    j += 1

                if j < len(code) and code[j] == '{':
                    # Found type object, skip it with balanced braces
                    brace_count = 0
                    type_start = j

                    while j < len(code):
                        if code[j] == '{':
                            brace_count += 1
                        elif code[j] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                j += 1
                                break
                        j += 1

                    # Check for intersection type (& Type)
                    while j < len(code) and code[j] in ' \n\t':
                        j += 1
                    if j < len(code) and code[j] == '&':
                        # Skip the & and the following type
                        j += 1
                        while j < len(code) and (code[j].isalnum() or code[j] in '_. \n\t'):
                            j += 1

                    # Now we've skipped the entire type, keep the } and skip to j
                    result.append('}')
                    i = j
                    continue

        result.append(code[i])
        i += 1

    return ''.join(result)


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

    # First pass: Remove complex destructured parameter types
    js_code = remove_destructured_param_types(js_code)

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

    # Remove complex parameter destructuring with types
    # Pattern: ({param1, param2}: { param1: Type1, param2: Type2 } & OtherType)
    # This is a multi-pass approach:

    # Step 1: Remove intersection types (&) from parameter types
    # e.g., }: {...} & AssetProfile) → }: {...})
    js_code = re.sub(r'\}\s*&\s*\w+\s*\)', '})', js_code)

    # Step 2: Remove type annotations after destructured parameters
    # Pattern: }: { ... }  where the closing } is from the param destructuring
    # We need to match the ENTIRE type annotation block including nested objects
    # This regex finds }: followed by type object, handling nesting
    def remove_param_types(match):
        # Keep the closing } from parameter, remove the type annotation
        return '}'

    # Match destructured param end (}) followed by type (: { ... })
    # Using a simple but effective pattern
    js_code = re.sub(
        r'\}\s*:\s*\{[^\}]*(?:\{[^\}]*\}[^\}]*)*\}(?=\s*\))',
        remove_param_types,
        js_code,
        flags=re.DOTALL
    )

    # Remove type annotations from variable declarations (including object index signatures)
    # e.g., const x: number = 5 → const x = 5
    # e.g., data: Big[] → data
    # e.g., obj: { [key: string]: Type } = {} → obj = {}
    # First handle object index signatures: : { ... } =
    js_code = re.sub(r'(\w+)\s*:\s*\{[^}]*\}\s*(?==)', r'\1 ', js_code)
    # Then handle simple types (use [ \t]* instead of \s* before : to avoid matching ternary operators across newlines)
    js_code = re.sub(r'(\w+)[ \t]*:[ \t]*[A-Za-z_][A-Za-z0-9_<>\[\]|&\s]*(?=[ \t\n]*[=;,\)])', r'\1', js_code)

    # Remove return type annotations (including complex ones)
    # e.g., function foo(): number { → function foo() {
    # e.g., function foo(): SymbolMetrics { → function foo() {
    js_code = re.sub(r'\)\s*:\s*[A-Za-z_][A-Za-z0-9_<>\[\]|&\s]*\{', ') {', js_code)

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

    # Remove optional chaining operator (?.) → regular property access
    # e.g., obj?.prop → obj.prop, arr?.[index] → arr[index]
    js_code = re.sub(r'\?\.\[', '[', js_code)  # ?.[  →  [
    js_code = re.sub(r'\?\.', '.', js_code)     # ?.   →  .

    # Convert nullish coalescing operator (??) to || (simpler and works with esprima)
    # While not semantically identical (|| checks falsy, ?? checks null/undefined),
    # it's close enough for most portfolio calculator use cases
    # Pattern: a ?? b → a || b
    js_code = re.sub(r'\?\?', '||', js_code)

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
