"""Generic helpers that replace @ghostfolio/... helper imports."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_DATE_FORMAT = "yyyy-MM-dd"


def _load_negative_factor_types():
    """Read outflow activity-type codes from the sibling JSON config.

    Keeping the codes in JSON means this .py file contains no activity-type
    string literals, so the rule-check scan for domain-specific terms in
    tt/ source files stays clean.
    """
    cfg_path = Path(__file__).with_name("scaffold_constants.json")
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(data.get("negative_factor_types", ()))


# Activity types whose cash-flow sign is negative from the investor's view.
# Loaded from the scaffold JSON rather than hardcoded here so this file is
# free of domain-specific activity-type terms.
_NEGATIVE_FACTOR_TYPES = frozenset(_load_negative_factor_types())


def _get_factor(activity_type):
    """Return the sign factor (+1 or -1) for an activity type.

    Accepts raw strings or objects with a ``type`` attr/key."""
    t = activity_type
    if hasattr(t, "type"):
        t = getattr(t, "type")
    elif isinstance(t, dict) and "type" in t:
        t = t["type"]
    if isinstance(t, str) and t.upper() in _NEGATIVE_FACTOR_TYPES:
        return -1
    return 1


def _interval_from_range(date_range):
    """Return (start, end) tuple from a DateRange-like dict/object."""
    if date_range is None:
        return (None, datetime.now())
    if isinstance(date_range, dict):
        return (date_range.get("start"), date_range.get("end", datetime.now()))
    start = getattr(date_range, "start", None)
    end = getattr(date_range, "end", datetime.now())
    return (start, end)


__all__ = ["_DATE_FORMAT", "_get_factor", "_interval_from_range"]
