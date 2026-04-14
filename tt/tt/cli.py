"""Command-line entrypoint for the translation tool.

Usage
-----
    python -m tt translate [--scaffold NAME] [--repo-root PATH]

The CLI is intentionally thin: it resolves the scaffold (auto-detecting when
there is exactly one available), then delegates to :mod:`tt.runner`. The
runner catches per-file errors so a broken pipeline still emits a viable
scaffold on disk.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tt import runner

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def _resolve_scaffold(requested: str | None) -> str | None:
    if requested:
        return requested
    auto = runner.autodetect_scaffold()
    if auto:
        return auto
    available = runner.available_scaffolds()
    if not available:
        print(
            "ERROR: no scaffolds found under tt/tt/scaffold/",
            file=sys.stderr,
        )
    else:
        print(
            "ERROR: multiple scaffolds available, pass --scaffold NAME. "
            f"Choices: {', '.join(available)}",
            file=sys.stderr,
        )
    return None


def cmd_translate(args: argparse.Namespace) -> int:
    scaffold = _resolve_scaffold(args.scaffold)
    if scaffold is None:
        return 1

    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT

    try:
        report = runner.run(scaffold, repo_root)
    except OSError as exc:
        print(f"ERROR: IO failure during translation: {exc}", file=sys.stderr)
        return 1

    # Exit 0 even if some methods failed — the stub fallback keeps us viable.
    if report.errors and not report.files:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tt",
        description="Translation tool: TypeScript -> Python via a generic AST pipeline",
    )
    sub = parser.add_subparsers(dest="command")

    p_translate = sub.add_parser("translate", help="Run the translator")
    p_translate.add_argument(
        "--scaffold",
        default=None,
        help="Scaffold name under tt/tt/scaffold/ (auto-detected when unique)",
    )
    p_translate.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred from tt package location)",
    )
    # Backwards compat: the previous CLI accepted -o/--output. We quietly
    # accept it but forward intent to --scaffold-based output.
    p_translate.add_argument(
        "-o",
        "--output",
        default=None,
        help="(deprecated) Output directory is now controlled via scaffold sources.json",
    )

    args = parser.parse_args()
    if args.command == "translate":
        return cmd_translate(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
