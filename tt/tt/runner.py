"""Orchestrates the full translation pipeline.

The runner is generic: it knows nothing about the concrete project being
translated. All project-specific configuration (which TS files to read, which
stub files to merge into, which import mappings to apply, which support shims
to drop in) lives under ``tt/tt/scaffold/<scaffold_name>/``.

Pipeline overview
-----------------
1. Scaffold stage — overlay the example's ``app/implementation/`` tree onto
   the output directory (never touching ``app/main.py`` or ``app/wrapper/``).
2. Shim stage — copy ``scaffold/<name>/shims/*.py`` into
   ``<output>/<support_dir>/`` so the translated code has Python stand-ins
   for JS libraries.
3. Translate stage — for every entry in ``sources.json`` run
   ``preprocess -> tokenize -> parse -> emit`` per method and merge the
   successful translations back into the stub via :mod:`tt.merger`.

All translation-time errors are caught per file so we never regress below
the baseline stub.
"""
from __future__ import annotations

import json
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


SCAFFOLD_ROOT = Path(__file__).parent / "scaffold"


@dataclass
class FileReport:
    out_path: Path
    translated: List[str] = field(default_factory=list)
    failed: Dict[str, str] = field(default_factory=dict)
    imports_added: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class RunReport:
    scaffold_name: str
    output_root: Path
    files: List[FileReport] = field(default_factory=list)
    support_files_copied: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total_translated(self) -> int:
        return sum(len(f.translated) for f in self.files)

    @property
    def total_failed(self) -> int:
        return sum(len(f.failed) for f in self.files)

    def pretty_print(self) -> None:
        print()
        print("=" * 60)
        print(f"Translation run: {self.scaffold_name}")
        print(f"Output: {self.output_root}")
        print("-" * 60)
        for fr in self.files:
            rel = fr.out_path
            print(f"  {rel}")
            if fr.error:
                print(f"    ERROR: {fr.error}")
                continue
            print(f"    translated: {len(fr.translated)}  failed: {len(fr.failed)}")
            for name in fr.translated:
                print(f"      [ok] {name}")
            for name, reason in fr.failed.items():
                print(f"      [skip] {name}: {reason}")
        print("-" * 60)
        print(f"Support files copied: {len(self.support_files_copied)}")
        print(f"Total methods translated: {self.total_translated}")
        print(f"Total methods skipped:    {self.total_failed}")
        if self.errors:
            print("Top-level errors:")
            for e in self.errors:
                print(f"  - {e}")
        print("=" * 60)


# ---------------------------------------------------------------------------
# Scaffold discovery
# ---------------------------------------------------------------------------


def available_scaffolds() -> List[str]:
    if not SCAFFOLD_ROOT.exists():
        return []
    return sorted(
        p.name
        for p in SCAFFOLD_ROOT.iterdir()
        if p.is_dir() and (p / "sources.json").exists()
    )


def autodetect_scaffold() -> Optional[str]:
    """Return the single scaffold name if exactly one exists, else None."""
    names = available_scaffolds()
    return names[0] if len(names) == 1 else None


# ---------------------------------------------------------------------------
# Support / utilities
# ---------------------------------------------------------------------------


def _ensure_init_files(root: Path, up_to: Path) -> None:
    """Create ``__init__.py`` stubs for every directory between ``up_to`` and
    ``root`` (inclusive of ``up_to``)."""
    root = root.resolve()
    up_to = up_to.resolve()
    if not str(up_to).startswith(str(root)):
        return
    cur = up_to
    while cur != root and cur != cur.parent:
        if cur.is_dir():
            init = cur / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
        cur = cur.parent


def _copy_tree(src: Path, dst: Path) -> None:
    """Replace ``dst`` with ``src`` (directory copy)."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def _stage_scaffold(example_root: Path, output_root: Path) -> None:
    """Refresh ``output_root/app/implementation`` from the example.

    We only touch ``app/implementation/`` — ``app/main.py`` and
    ``app/wrapper/`` are immutable per competition rules.
    """
    src_impl = example_root / "app" / "implementation"
    dst_impl = output_root / "app" / "implementation"

    if not src_impl.exists():
        raise FileNotFoundError(
            f"Example implementation not found: {src_impl}"
        )

    # Ensure output_root exists with main.py + wrapper from the example on
    # first run. On subsequent runs only reset implementation/.
    if not (output_root / "app" / "main.py").exists():
        output_root.mkdir(parents=True, exist_ok=True)
        # Copy the full example only for items that don't yet exist.
        for item in example_root.iterdir():
            target = output_root / item.name
            if target.exists():
                continue
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

    _copy_tree(src_impl, dst_impl)


def _stage_shims(
    scaffold_dir: Path, output_root: Path, support_dir_rel: str
) -> List[Path]:
    """Copy ``scaffold/<name>/shims/*.py`` into the support dir.

    Returns the list of copied destination paths.
    """
    copied: List[Path] = []
    shims_dir = scaffold_dir / "shims"
    support_dst = output_root / support_dir_rel
    support_dst.mkdir(parents=True, exist_ok=True)
    _ensure_init_files(output_root, support_dst)

    if not shims_dir.exists():
        # Nothing to copy — still make sure support dir is a package.
        (support_dst / "__init__.py").touch(exist_ok=True)
        return copied

    for py in sorted(shims_dir.glob("*.py")):
        dst = support_dst / py.name
        shutil.copy2(py, dst)
        copied.append(dst)

    (support_dst / "__init__.py").touch(exist_ok=True)
    return copied


def _load_pipeline():
    """Import the translation modules lazily so the CLI can load even if
    any individual module is broken. Returns a dict of modules, or None on
    failure along with the error message."""
    try:
        from tt import preprocess, lexer, parser, emitter  # type: ignore
        from tt.merger import merge_into_stub  # type: ignore
        return {
            "preprocess": preprocess,
            "lexer": lexer,
            "parser": parser,
            "emitter": emitter,
            "merge": merge_into_stub,
        }, None
    except Exception as exc:  # pragma: no cover — pipeline not ready
        return None, f"pipeline modules unavailable: {exc}"


def _emit_methods(program: Any, emitter_mod: Any, import_map: Dict[str, Any]):
    """Walk the program AST and emit Python source per method."""
    translated: Dict[str, str] = {}
    failed: Dict[str, str] = {}
    ctx: Dict[str, Any] = {
        "import_map": import_map,
        "translated": set(),
        "imports": [],
    }
    classes = [c for c in getattr(program, "body", []) if _is_class(c)]
    for cls in classes:
        for member in getattr(cls, "members", []):
            name = getattr(member, "name", None)
            if not name or not hasattr(member, "body"):
                continue
            try:
                py_src = emitter_mod.emit_method(member, ctx)
                if py_src:
                    translated[name] = py_src
                    ctx["translated"].add(name)
            except Exception as exc:
                failed[name] = _short_reason(exc)
    for fname, reason in getattr(program, "failed_methods", []) or []:
        failed.setdefault(fname, reason)
    try:
        extra_imports = list(emitter_mod.collect_imports(ctx))
    except Exception:
        extra_imports = []
    return translated, failed, extra_imports


def _translate_one_file(
    ts_path: Path,
    stub_path: Path,
    out_path: Path,
    import_map: Dict[str, Any],
) -> FileReport:
    """Translate a single TS file. Never raises — errors land in report."""
    report = FileReport(out_path=out_path)

    pipeline, err = _load_pipeline()
    if pipeline is None:
        report.error = err
        _copy_stub_to_output(stub_path, out_path)
        return report

    try:
        ts_src = ts_path.read_text(encoding="utf-8")
        stub_src = stub_path.read_text(encoding="utf-8")
    except Exception as exc:
        report.error = f"failed to read input: {exc}"
        _copy_stub_to_output(stub_path, out_path)
        return report

    try:
        pre = pipeline["preprocess"].preprocess(ts_src)
        tokens = pipeline["lexer"].tokenize(pre)
        program = pipeline["parser"].parse(tokens)
    except Exception as exc:
        report.error = f"parse failed: {exc}"
        _safe_write(out_path, stub_src)
        return report

    translated, failed, extra_imports = _emit_methods(
        program, pipeline["emitter"], import_map
    )

    try:
        final_src = pipeline["merge"](stub_src, translated, extra_imports)
    except Exception as exc:
        report.error = f"merge failed: {exc}"
        _safe_write(out_path, stub_src)
        return report

    _safe_write(out_path, final_src)
    report.translated = sorted(translated)
    report.failed = failed
    report.imports_added = extra_imports
    return report


def _is_class(node: Any) -> bool:
    return type(node).__name__ == "ClassDecl"


def _short_reason(exc: Exception) -> str:
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    if len(msg) > 120:
        msg = msg[:117] + "..."
    return f"{type(exc).__name__}: {msg}"


def _safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_stub_to_output(stub_path: Path, out_path: Path) -> None:
    """Best-effort: ensure the output file at least contains the stub."""
    try:
        if stub_path.exists():
            _safe_write(out_path, stub_path.read_text(encoding="utf-8"))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _load_scaffold_config(scaffold_dir: Path):
    """Read sources.json and tt_import_map.json; returns (sources, import_map)."""
    sources = json.loads((scaffold_dir / "sources.json").read_text("utf-8"))
    import_map_path = scaffold_dir / "tt_import_map.json"
    import_map: Dict[str, Any] = {}
    if import_map_path.exists():
        import_map = json.loads(import_map_path.read_text("utf-8"))
    return sources, import_map


def _translate_entry(
    entry: Dict[str, Any],
    repo_root: Path,
    example_root: Path,
    output_root: Path,
    import_map: Dict[str, Any],
) -> FileReport:
    """Resolve an entry from sources.json and translate the referenced file."""
    ts_path = (repo_root / entry["ts"]).resolve()
    stub_rel = entry.get("stub") or entry.get("stub_path")
    stub_path = (example_root / stub_rel).resolve() if stub_rel else None
    out_rel = entry.get("py") or entry.get("out")
    out_path = (output_root / out_rel).resolve() if out_rel else None
    if out_path is None or stub_path is None:
        return FileReport(out_path=out_path or Path("<unknown>"), error="missing path keys")
    if not ts_path.exists():
        return FileReport(out_path=out_path, error=f"TS source missing: {ts_path}")
    if not stub_path.exists():
        return FileReport(out_path=out_path, error=f"stub missing: {stub_path}")
    try:
        return _translate_one_file(ts_path, stub_path, out_path, import_map)
    except Exception as exc:  # final safety net
        traceback.print_exc()
        return FileReport(out_path=out_path, error=f"unexpected: {exc}")


def run(scaffold_name: str, repo_root: Path) -> RunReport:
    """Run the full translation pipeline for the given scaffold."""
    repo_root = repo_root.resolve()
    scaffold_dir = SCAFFOLD_ROOT / scaffold_name
    report = RunReport(scaffold_name=scaffold_name, output_root=repo_root)

    if not scaffold_dir.exists():
        report.errors.append(f"scaffold not found: {scaffold_dir}")
        report.pretty_print()
        return report

    try:
        sources, import_map = _load_scaffold_config(scaffold_dir)
    except Exception as exc:
        report.errors.append(f"failed to load scaffold config: {exc}")
        report.pretty_print()
        return report

    example_root = (repo_root / sources["example_root"]).resolve()
    output_root = (repo_root / sources["output_root"]).resolve()
    support_dir_rel = sources.get("support_dir", "app/implementation/_support")
    report.output_root = output_root

    if not _run_overlay(report, scaffold_dir, example_root, output_root, support_dir_rel):
        return report
    for entry in sources.get("translations", []):
        fr = _translate_entry(entry, repo_root, example_root, output_root, import_map)
        report.files.append(fr)
    report.pretty_print()
    return report


def _run_overlay(
    report: RunReport,
    scaffold_dir: Path,
    example_root: Path,
    output_root: Path,
    support_dir_rel: str,
) -> bool:
    """Run scaffold + shim stages. Returns False if scaffold stage failed."""
    try:
        _stage_scaffold(example_root, output_root)
    except Exception as exc:
        report.errors.append(f"scaffold stage failed: {exc}")
        traceback.print_exc()
        report.pretty_print()
        return False
    try:
        report.support_files_copied = _stage_shims(
            scaffold_dir, output_root, support_dir_rel
        )
    except Exception as exc:
        report.errors.append(f"shim stage failed: {exc}")
        traceback.print_exc()
    return True
