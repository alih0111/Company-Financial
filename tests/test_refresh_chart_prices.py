"""Offline contract tests for the chart price back-adjustment repair.

Regression: after a capital increase the exchange resets its reference price,
but rows stored before the event kept the old scale forever (append-only
table + watermark break), so the served chart showed a fake crash.
refresh_chart_prices must recompute the full adjusted chain and re-emit only
the days whose stored close disagrees with it.
"""
import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "refresh_chart_prices", ROOT / "scripts" / "refresh_chart_prices.py")
refresh_chart_prices = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh_chart_prices)


def bar(day, close, yesterday, first=None, high=None, low=None):
    first = close if first is None else first
    high = max(close, yesterday, first) if high is None else high
    low = min(close, yesterday, first) if low is None else low
    return {"dEven": day, "pClosing": close, "priceYesterday": yesterday,
            "priceFirst": first, "priceMax": high, "priceMin": low,
            "pDrCotVal": close, "qTotTran5J": 10, "qTotCap": 1000, "zTotTran": 5}


# d1/d2 trade in the pre-event scale; d3 is the capital-increase day whose
# reference price the exchange already reset (110 -> 55, a 2x increase).
BARS = [bar("20260901", 100, 95), bar("20260902", 110, 100), bar("20260903", 56, 55)]
CUTOFF = dt.date(2026, 9, 3)
D1, D2, D3 = (dt.date(2026, 9, d) for d in (1, 2, 3))


def emitted(watermark, stored):
    rows = list(refresh_chart_prices.chart_rows("sid", BARS, "u", CUTOFF, watermark, stored))
    return {row[1]: row for row in rows}


def test_event_day_keeps_new_scale_and_reference_change():
    rows = emitted(D2, {})
    assert rows[D3][11] == 56  # closing stays raw on the event day
    assert rows[D3][13] == 55  # yesterday price is the reset reference
    assert rows[D3][17] == round(100 * (56 / 55 - 1), 4)  # change vs reference


def test_pre_event_history_is_back_adjusted():
    rows = emitted(D2, {})
    assert rows[D2][11] == 55  # 110 * (55 / 110)
    assert rows[D1][11] == 50  # 100 * (55 / 110)
    assert rows[D1][13] == 47.5  # 95 * (55 / 110)


def test_stale_stored_rows_are_re_emitted():
    # Stored legacy closes keep the old scale: repair must rewrite them.
    rows = emitted(D2, {D1: 100.0, D2: 110.0})
    assert set(rows) == {D1, D2, D3}


def test_consistent_stored_rows_are_not_rewritten():
    # Matching adjusted history must stay untouched to avoid daily row bloat.
    rows = emitted(D2, {D1: 50.0, D2: 55.0})
    assert set(rows) == {D2, D3}


def test_empty_watermark_emits_full_history():
    assert set(emitted(None, {})) == {D1, D2, D3}


def test_stale_row_tolerance():
    stale = refresh_chart_prices.stale_row
    assert not stale({D1: 50.0}, D1, 50.0)
    assert not stale({D1: 50.0}, D1, 50.04)  # rounding noise stays put
    assert stale({D1: 50.0}, D1, 50.1)  # a real scale break repairs
    assert stale({}, D1, 50.0)  # missing day is always emitted
