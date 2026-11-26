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


def stored_row(close, **overrides):
    row = {"trade_date": None, "jalali_date_text": "1405/06/11", "open_price_rial": close,
           "first_price_rial": close, "high_price_rial": close, "low_price_rial": close,
           "closing_price_rial": close, "last_price_rial": close, "yesterday_price_rial": None,
           "volume": 10, "trade_value_rial": None, "trade_count": None,
           "closing_change_percent": None}
    row.update(overrides)
    return row


def emitted(watermark, stored, raw=BARS):
    rows = list(refresh_chart_prices.chart_rows("sid", raw, "u", CUTOFF, watermark, stored))
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
    rows = emitted(D2, {D1: stored_row(100.0), D2: stored_row(110.0)})
    assert set(rows) == {D1, D2, D3}


def test_consistent_stored_rows_are_not_rewritten():
    # Matching adjusted history must stay untouched to avoid daily row bloat.
    rows = emitted(D2, {D1: stored_row(50.0), D2: stored_row(55.0)})
    assert set(rows) == {D2, D3}


def test_empty_watermark_emits_full_history():
    assert set(emitted(None, {})) == {D1, D2, D3}


def test_stale_row_tolerance():
    stale = refresh_chart_prices.stale_row
    assert not stale({D1: stored_row(50.0)}, D1, 50.0)
    assert not stale({D1: stored_row(50.0)}, D1, 50.04)  # rounding noise stays put
    assert stale({D1: stored_row(50.0)}, D1, 50.1)  # a real scale break repairs
    assert stale({}, D1, 50.0)  # missing day is always emitted


def test_gap_day_between_chain_bars_is_rescaled():
    # A halt day stored only by the broker keeps the pre-event scale; it must be
    # rescaled into the chain's scale so it stops splitting the chart in two.
    raw = [BARS[0], BARS[2]]  # chain skips the halt day between d1 and d3
    halt = dt.date(2026, 9, 2)
    rows = emitted(D1, {halt: stored_row(108.0, yesterday_price_rial=105.0)}, raw=raw)
    gap = rows[halt]
    assert gap[5] == "local_heuristic"
    assert gap[11] == 59.4  # 108 * (55 / 100), continuous with the 55..56 chain
    assert gap[14] == 10  # volumes are not rescaled


def test_gap_day_with_no_matching_scale_is_left_alone():
    raw = [BARS[0], BARS[2]]
    halt = dt.date(2026, 9, 2)
    # A well-formed candle (has a reference price) that fits no chain scale.
    rows = emitted(D1, {halt: stored_row(300.0, yesterday_price_rial=295.0)}, raw=raw)
    assert halt not in rows  # continuity guard refuses both candidate scales


def test_gap_day_outside_chain_range_is_untouched():
    raw = [BARS[0], BARS[2]]
    older = dt.date(2026, 8, 31)
    rows = emitted(D1, {older: stored_row(99.0)}, raw=raw)
    assert older not in rows  # no chain neighbor to prove the scale


def test_degenerate_gap_day_is_filled_with_previous_close():
    # A broken candle (no reference price, no volume) carries no usable scale;
    # a no-trade day's price equals the previous close, so fill from the chain.
    raw = [BARS[0], BARS[2]]
    halt = dt.date(2026, 9, 2)
    broken = stored_row(1000.0, yesterday_price_rial=None, volume=None)
    rows = emitted(D1, {halt: broken}, raw=raw)
    gap = rows[halt]
    assert gap[11] == 55.0  # chain close of d1, the previous trading day
    assert gap[17] == 0.0  # no trades happened, change is zero


def test_degenerate_fill_requires_neighbour_agreement():
    raw = [bar("20260901", 100, 95), bar("20260903", 50, 25)]  # a real 2x event inside
    halt = dt.date(2026, 9, 2)
    broken = stored_row(1000.0, yesterday_price_rial=None, volume=None)
    rows = emitted(dt.date(2026, 9, 1), {halt: broken}, raw=raw)
    assert halt not in rows  # neighbours disagree (real event between them)


def test_canceled_session_far_off_own_reference_is_filled():
    # A broker candle whose close sits far off its own reference price marks a
    # canceled session; fill it with the previous close like any halt day.
    raw = [BARS[0], BARS[2]]
    halt = dt.date(2026, 9, 2)
    canceled = stored_row(108.0, yesterday_price_rial=55.0, volume=1)
    rows = emitted(D1, {halt: canceled}, raw=raw)
    gap = rows[halt]
    assert gap[11] == 55.0
    assert gap[17] == 0.0


def test_normal_candle_off_own_reference_but_matching_scale_is_rescaled():
    raw = [BARS[0], BARS[2]]
    halt = dt.date(2026, 9, 2)
    stale = stored_row(110.0, yesterday_price_rial=108.0, volume=5)  # old scale, sane
    rows = emitted(D1, {halt: stale}, raw=raw)
    assert rows[halt][11] == 60.5  # 110 * (55 / 100), kept its real prices
