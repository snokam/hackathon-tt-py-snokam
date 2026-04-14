"""Minimal date-fns shim. Stdlib only."""
from __future__ import annotations

from datetime import date, datetime, timedelta

_TOKENS = [
    ("yyyy", "%Y"),
    ("MM", "%m"),
    ("dd", "%d"),
    ("HH", "%H"),
    ("mm", "%M"),
    ("ss", "%S"),
]


def _to_dt(d):
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day)
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            return datetime.strptime(d, "%Y-%m-%d")
    raise TypeError(f"cannot convert {type(d)!r} to datetime")


def _date_format(d, fmt):
    """Translate date-fns tokens to strftime, preserving non-token text."""
    dt = _to_dt(d)
    out = []
    i = 0
    while i < len(fmt):
        matched = False
        for tok, repl in _TOKENS:
            if fmt.startswith(tok, i):
                out.append(dt.strftime(repl))
                i += len(tok)
                matched = True
                break
        if not matched:
            out.append(fmt[i])
            i += 1
    return "".join(out)


def _each_year_of_interval(interval):
    start = _to_dt(interval["start"])
    end = _to_dt(interval["end"])
    years = []
    for y in range(start.year, end.year + 1):
        years.append(datetime(y, 1, 1))
    return years


def _is_this_year(d):
    return _to_dt(d).year == date.today().year


def _is_before(a, b):
    return _to_dt(a) < _to_dt(b)


def _difference_in_days(a, b):
    return (_to_dt(a).date() - _to_dt(b).date()).days


def _add_milliseconds(d, ms):
    return _to_dt(d) + timedelta(milliseconds=int(ms))


# re-exports for emitted code
__all__ = [
    "_date_format",
    "_each_year_of_interval",
    "_is_this_year",
    "_is_before",
    "_difference_in_days",
    "_add_milliseconds",
    "timedelta",
    "datetime",
]
