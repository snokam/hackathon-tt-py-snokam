"""Pure-Python stand-in for big.js, backed by decimal.Decimal."""
from __future__ import annotations

from decimal import Decimal, getcontext, ROUND_HALF_EVEN

getcontext().prec = 28


def _to_decimal(x):
    if isinstance(x, Big):
        return x._d
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(1 if x else 0)
    if isinstance(x, (int, str)):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if x is None:
        return Decimal(0)
    return Decimal(str(x))


class Big:
    __slots__ = ("_d",)

    def __init__(self, value=0):
        self._d = _to_decimal(value)

    # arithmetic methods
    def plus(self, other):  return Big(self._d + _to_decimal(other))
    def minus(self, other): return Big(self._d - _to_decimal(other))
    def times(self, other): return Big(self._d * _to_decimal(other))
    def mul(self, other):   return Big(self._d * _to_decimal(other))
    def div(self, other):
        d = _to_decimal(other)
        if d == 0:
            return Big(0)
        return Big(self._d / d)
    def abs(self):          return Big(abs(self._d))

    # conversions
    def toNumber(self):     return float(self._d)
    def toString(self):     return format(self._d, "f")
    def toFixed(self, n=0): return _big_to_fixed(self, n)

    # predicates
    def isZero(self): return self._d == 0
    def isNeg(self):  return self._d < 0
    def isPos(self):  return self._d > 0

    # comparisons
    def eq(self, o):  return self._d == _to_decimal(o)
    def lt(self, o):  return self._d <  _to_decimal(o)
    def gt(self, o):  return self._d >  _to_decimal(o)
    def lte(self, o): return self._d <= _to_decimal(o)
    def gte(self, o): return self._d >= _to_decimal(o)

    # python dunders
    def __add__(self, o):      return Big(self._d + _to_decimal(o))
    def __radd__(self, o):     return Big(_to_decimal(o) + self._d)
    def __sub__(self, o):      return Big(self._d - _to_decimal(o))
    def __rsub__(self, o):     return Big(_to_decimal(o) - self._d)
    def __mul__(self, o):      return Big(self._d * _to_decimal(o))
    def __rmul__(self, o):     return Big(_to_decimal(o) * self._d)
    def __truediv__(self, o):
        d = _to_decimal(o)
        return Big(0) if d == 0 else Big(self._d / d)
    def __neg__(self):         return Big(-self._d)
    def __abs__(self):         return Big(abs(self._d))
    def __eq__(self, o):
        try: return self._d == _to_decimal(o)
        except Exception: return False
    def __lt__(self, o): return self._d <  _to_decimal(o)
    def __gt__(self, o): return self._d >  _to_decimal(o)
    def __le__(self, o): return self._d <= _to_decimal(o)
    def __ge__(self, o): return self._d >= _to_decimal(o)
    def __bool__(self):  return self._d != 0
    def __hash__(self):  return hash(self._d)
    def __repr__(self):  return f"Big({self.toString()})"
    def __str__(self):   return self.toString()
    def __float__(self): return float(self._d)


def _big_to_fixed(b, n=0):
    d = b._d if isinstance(b, Big) else _to_decimal(b)
    q = Decimal(10) ** -int(n) if n else Decimal(1)
    return format(d.quantize(q, rounding=ROUND_HALF_EVEN), "f")
