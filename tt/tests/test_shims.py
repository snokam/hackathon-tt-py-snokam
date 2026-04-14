"""Sanity tests for the ghostfolio_pytx scaffold shims."""
from __future__ import annotations

import copy
import sys
from datetime import date, datetime
from pathlib import Path

SHIMS = Path(__file__).resolve().parents[1] / "tt" / "scaffold" / "ghostfolio_pytx" / "shims"
sys.path.insert(0, str(SHIMS))

import bigjs  # noqa: E402
import datefns  # noqa: E402
import lodashish  # noqa: E402
import ghostfolio_helper  # noqa: E402
import nest_logger  # noqa: E402


# --- Big -----------------------------------------------------------------

def test_big_plus_minus_times_div():
    assert bigjs.Big("0.1").plus("0.2").eq("0.3")
    assert bigjs.Big(10).minus(3).eq(7)
    assert bigjs.Big("2.5").times(4).eq(10)
    assert bigjs.Big(10).div(4).eq("2.5")


def test_big_predicates_and_conversions():
    assert bigjs.Big(0).isZero()
    assert bigjs.Big(-3).isNeg()
    assert bigjs.Big(5).isPos()
    assert bigjs.Big("1.23456").toNumber() == 1.23456
    assert bigjs.Big("1.2345").toFixed(2) == "1.23"
    assert bigjs.Big("0.1").plus("0.2").toFixed(1) == "0.3"


def test_big_dunders():
    a, b = bigjs.Big(7), bigjs.Big(3)
    assert (a + b).eq(10)
    assert (a - b).eq(4)
    assert (a * b).eq(21)
    assert bool(bigjs.Big(1)) and not bool(bigjs.Big(0))
    assert a > b and b < a and a >= a and a <= a


# --- date-fns -----------------------------------------------------------

def test_date_format_tokens():
    d = datetime(2024, 3, 7, 15, 4, 9)
    assert datefns._date_format(d, "yyyy-MM-dd") == "2024-03-07"
    assert datefns._date_format(d, "yyyy/MM/dd HH:mm:ss") == "2024/03/07 15:04:09"


def test_each_year_of_interval():
    years = datefns._each_year_of_interval({"start": datetime(2020, 6, 1), "end": datetime(2022, 2, 1)})
    assert [y.year for y in years] == [2020, 2021, 2022]
    assert all(y.month == 1 and y.day == 1 for y in years)


def test_diff_and_before():
    assert datefns._difference_in_days(datetime(2024, 1, 11), datetime(2024, 1, 1)) == 10
    assert datefns._is_before(datetime(2020, 1, 1), datetime(2021, 1, 1))
    assert datefns._is_this_year(datetime(date.today().year, 6, 1))


# --- lodashish ----------------------------------------------------------

def test_sortby_callable_and_fieldname():
    data = [{"n": 3}, {"n": 1}, {"n": 2}]
    assert [d["n"] for d in lodashish.sortBy(data, "n")] == [1, 2, 3]
    assert [d["n"] for d in lodashish.sortBy(data, lambda d: d["n"])] == [1, 2, 3]


def test_clonedeep_independence():
    original = {"a": [1, 2, [3, 4]]}
    clone = lodashish.cloneDeep(original)
    clone["a"][2].append(99)
    assert original["a"][2] == [3, 4]


# --- ghostfolio_helper / logger ---------------------------------------

def test_get_factor_and_logger():
    assert ghostfolio_helper._get_factor("BUY") == 1
    assert ghostfolio_helper._get_factor("SELL") == -1
    assert ghostfolio_helper._get_factor({"type": "LIABILITY"}) == -1
    # logger must be a no-op without raising
    nest_logger.Logger.warn("hi")
    nest_logger.Logger.error("oops", ctx="ctx")
