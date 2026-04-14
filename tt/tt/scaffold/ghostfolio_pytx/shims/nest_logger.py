"""No-op stand-in for @nestjs/common Logger."""
from __future__ import annotations


class Logger:
    def __init__(self, *_, **__):
        pass

    @staticmethod
    def warn(msg, ctx=None):  # noqa: D401
        return None

    @staticmethod
    def error(msg, ctx=None, trace=None):
        return None

    @staticmethod
    def info(msg, ctx=None):
        return None

    @staticmethod
    def log(msg, ctx=None):
        return None

    @staticmethod
    def debug(msg, ctx=None):
        return None


__all__ = ["Logger"]
