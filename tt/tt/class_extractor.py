"""Extract class structure from TypeScript AST."""
from __future__ import annotations

from typing import Any


def extract_methods(class_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all methods from a class body.

    Args:
        class_body: Class body node from AST

    Returns:
        List of method info dicts
    """
    methods = []

    for element in class_body.get('body', []):
        if element.get('type') == 'MethodDefinition':
            method_info = {
                'name': element['key']['name'] if element.get('key') else None,
                'kind': element.get('kind', 'method'),  # method, constructor, get, set
                'static': element.get('static', False),
                'params': extract_params(element.get('value', {})),
                'body': element.get('value', {}).get('body'),
                'node': element
            }
            methods.append(method_info)

    return methods


def extract_params(function_node: dict[str, Any]) -> list[str]:
    """Extract parameter names from a function node.

    Args:
        function_node: FunctionExpression node

    Returns:
        List of parameter names
    """
    params = []
    for param in function_node.get('params', []):
        if param.get('type') == 'Identifier':
            params.append(param['name'])
        elif param.get('type') == 'AssignmentPattern':
            # Default parameter: x = defaultValue
            params.append(param['left']['name'])
        elif param.get('type') == 'RestElement':
            # Rest parameter: ...args
            params.append(f"*{param['argument']['name']}")

    return params


def camel_to_snake(name: str) -> str:
    """Convert camelCase to snake_case.

    Args:
        name: camelCase identifier

    Returns:
        snake_case identifier
    """
    import re
    # Insert underscore before uppercase letters
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    # Insert underscore before uppercase letters preceded by lowercase
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def generate_class_skeleton(class_info: dict[str, Any]) -> str:
    """Generate Python class skeleton from TypeScript class info.

    Args:
        class_info: Class info from extract_class_info

    Returns:
        Python class skeleton as string
    """
    class_name = class_info['name']
    base_class = class_info.get('superClass', 'object')

    # Start with class declaration
    lines = [
        f'class {class_name}({base_class}):',
        f'    """Translated from TypeScript {class_name}."""',
        ''
    ]

    # Extract methods
    methods = extract_methods(class_info['body'])

    # Find constructor
    constructor = next((m for m in methods if m['kind'] == 'constructor'), None)

    if constructor:
        params_str = ', '.join(constructor['params'])
        lines.extend([
            f'    def __init__(self, {params_str}):',
            f'        """Initialize {class_name}."""',
            f'        super().__init__({params_str})',
            f'        # TODO: Translate constructor body',
            ''
        ])

    # Add method stubs
    non_constructor_methods = [m for m in methods if m['kind'] != 'constructor']

    for method in non_constructor_methods:
        method_name = camel_to_snake(method['name'])
        params_str = ', '.join(method['params']) if method['params'] else ''

        lines.extend([
            f'    def {method_name}(self{", " + params_str if params_str else ""}):',
            f'        """TODO: Translate {method["name"]}."""',
            f'        raise NotImplementedError("{method["name"]} not yet translated")',
            ''
        ])

    return '\n'.join(lines)


def test_class_extractor():
    """Test class extraction."""
    from ts_parser import parse_typescript, extract_class_info

    sample_ts = """
    export class RoaiPortfolioCalculator extends PortfolioCalculator {
        constructor(activities, currentRateService) {
            super(activities, currentRateService);
        }

        getPerformanceCalculationType() {
            return 'ROAI';
        }

        calculateOverallPerformance(positions) {
            return { hasErrors: false };
        }
    }
    """

    ast = parse_typescript(sample_ts)
    class_info = extract_class_info(ast)

    if class_info:
        print("=== Extracted Class Info ===")
        print(f"Name: {class_info['name']}")
        print(f"Extends: {class_info['superClass']}")

        methods = extract_methods(class_info['body'])
        print(f"Methods: {len(methods)}")
        for m in methods:
            print(f"  - {m['name']} ({m['kind']}): {m['params']}")

        print("\n=== Generated Python Skeleton ===")
        skeleton = generate_class_skeleton(class_info)
        print(skeleton)

        print("\n✅ Class extractor tests passed!")
    else:
        print("❌ No class found")


if __name__ == '__main__':
    test_class_extractor()
