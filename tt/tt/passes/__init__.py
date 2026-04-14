"""AST-to-AST transformation passes.

Each pass exposes an ``apply(node, ctx)`` function that mutates (or returns
a new) node in-place. Passes are pure Python, stdlib-only, and know nothing
about any specific project — all project-specific rules come from the
``ctx.import_map`` dictionary loaded from a scaffold JSON.
"""

from . import rename, control_flow, libmap, py_ready

__all__ = ["rename", "control_flow", "libmap", "py_ready"]
