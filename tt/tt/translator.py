"""Backwards-compatible shim delegating to :mod:`tt.runner`.

The original regex-based translator lived here. It has been replaced by a
proper pipeline (preprocess -> lex -> parse -> emit -> merge). To keep any
callers that still import from ``tt.translator`` working, we expose two
thin wrappers that dispatch to :mod:`tt.runner`.

New code should call :func:`tt.runner.run` directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tt import runner


def _default_scaffold() -> str:
    name = runner.autodetect_scaffold()
    if name is None:
        available = runner.available_scaffolds()
        raise RuntimeError(
            "translator.py shim cannot auto-detect a scaffold; "
            f"available: {available}"
        )
    return name


def run_translation(repo_root: Path, output_dir: Optional[Path] = None) -> None:
    """Deprecated: delegates to :func:`tt.runner.run`.

    ``output_dir`` is ignored — the output path is driven by
    ``scaffold/<name>/sources.json``. It is kept in the signature so existing
    call sites continue to work.
    """
    print(
        "[tt.translator] run_translation is deprecated; use tt.runner.run",
    )
    runner.run(_default_scaffold(), Path(repo_root))


def translate_typescript_file(ts_content: str) -> str:
    """Deprecated compatibility shim.

    The old function took raw TypeScript source and returned a best-effort
    Python string. The new pipeline is file-based (it needs a stub to merge
    into), so this shim triggers a full run against the default scaffold
    and returns an empty string. Callers should migrate to :mod:`tt.runner`.
    """
    print(
        "[tt.translator] translate_typescript_file is deprecated; "
        "invoking the full runner against the default scaffold",
    )
    try:
        runner.run(_default_scaffold(), Path.cwd())
    except Exception as exc:  # pragma: no cover — legacy path
        print(f"[tt.translator] runner failed: {exc}")
    return ""
