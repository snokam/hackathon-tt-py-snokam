"""Generic helpers that replace @ghostfolio/... helper imports."""
from __future__ import annotations

from datetime import datetime

_DATE_FORMAT = "yyyy-MM-dd"

# Activity types whose cash-flow sign is negative from the investor's view.
_NEGATIVE_FACTOR_TYPES = {"SELL", "LIABILITY"}


def _get_factor(activity_type):
    """Return +1 for inflows (BUY, DIVIDEND, ...) and -1 for outflows (SELL,
    LIABILITY). Accepts raw strings or objects with a ``type`` attr/key."""
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
