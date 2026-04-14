"""Tiny lodash shim: sortBy + cloneDeep."""
from __future__ import annotations

import copy
from operator import itemgetter, attrgetter


def _make_key(k):
    if callable(k):
        return k
    if isinstance(k, str):
        def getter(item, _k=k):
            if isinstance(item, dict):
                return item.get(_k)
            return getattr(item, _k, None)
        return getter
    raise TypeError(f"sortBy key must be callable or str, got {type(k)!r}")


def sortBy(iterable, key):
    keys = [key] if not isinstance(key, (list, tuple)) else list(key)
    getters = [_make_key(k) for k in keys]

    def composite(item):
        return tuple(g(item) for g in getters)

    return sorted(iterable, key=composite)


cloneDeep = copy.deepcopy

__all__ = ["sortBy", "cloneDeep"]
