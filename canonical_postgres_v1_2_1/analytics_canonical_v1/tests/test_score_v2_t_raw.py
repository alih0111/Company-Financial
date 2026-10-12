"""Tests for score_v2_t_raw — the raw T (timing) extraction layer.

World construction: every synthetic security gets a three-segment daily
close path with EXACT endpoints (piecewise geometric interpolation, final
exponent 1.0), so window returns are exact anchor ratios:
    seg1  flat 100.0                      (Mar 2 .. Apr 8)   <- 6m base
    seg2  100.0 -> 125.0                  (Apr 9 .. Jul 8)   <- 3m base
    seg3  125.0 -> final                  (Jul 9 .. Oct 5)
mom6 = final/100 - 1, mom3 = final/125 - 1, daily steps far below the
gap band. A "gap" injection replaces one close to create a move no TSE
session can produce and the refusal must name it.
"""
import copy
import datetime as dt
import math
import statistics

import pytest

import score_v2_config as CFG2
import score_v2_raw as RAW
import score_v2_t_raw as TRW

AS_OF = dt.date(2026, 10, 8)
SID = "S1"
META = {"C1": {"model_family": "general", "industry": "فولاد"}}


def weekdays(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def seg_closes(d0, d1, c0, c1):
    """Geometric interpolation c0 -> c1 over the weekdays in [d0, d1] with
    an exact final endpoint (exponent 1.0)."""
    days = list(weekdays(d0, d1))
    if not days:
        return {}
    if len(days) == 1:
        return {days[0]: c1}
    k = len(days) - 1
    return {d: c0 * math.pow(c1 / c0, i / k) for i, d in enumerate(days)}


def base_path(final=150.0):
    path = {}
    path.update(seg_closes(dt.date(2026, 3, 2), dt.date(2026, 4, 8),
                           100.0, 100.0))
    path.update(seg_closes(dt.date(2026, 4, 9), dt.date(2026, 7, 8),
                           100.0, 125.0))
    path.update(seg_closes(dt.date(2026, 7, 9), dt.date(2026, 10, 5),
                           125.0, final))
    return path


def rows_for(path, tv=1e9, tv_over=None, sid=SID):
    out = []
    for d in sorted(path):
        val = tv if tv_over is None else tv_over(d)
        out.append({"security_id": sid, "trade_date": d,
                    "closing_price_rial": path[d],
                    "trade_value_rial": val,
                    "collected_at": dt.datetime(2026, 10, 6, 10, 0,
                                                tzinfo=dt.timezone.utc)})
    return out


def world(*securities):
    """{sid: day records} — raw rows pushed through the real extractor."""
    return {sid: TRW.extract_daily_history(rows, AS_OF)[sid]
            for sid, rows in securities}


def build(histories, sec_by_cid=None, meta=None, as_of=AS_OF):
    return TRW.build_t_raw(
        histories,
        sec_by_cid if sec_by_cid is not None else {"C1": SID},
        meta if meta is not None else META,
        as_of=as_of)


# ---------------------------------------------------------------------------
# contract agreement
# ---------------------------------------------------------------------------
def test_scope_matches_config_ready_timing_factors():
    ready = {fid for fid, spec in CFG2.V2_QVT_FACTORS.items()
             if spec["axis"] == "timing" and spec["availability"] == CFG2.READY}
    assert set(TRW.IN_SCOPE_T_FACTORS) == ready
    assert "distance_from_52w_high" not in TRW.IN_SCOPE_T_FACTORS


def test_directions_match_config():
    for fid in TRW.IN_SCOPE_T_FACTORS:
        assert CFG2.V2_QVT_FACTORS[fid]["direction"] in ("higher", "lower")
    assert CFG2.V2_QVT_FACTORS["low_volatility"]["direction"] == "lower"
    for fid in ("momentum_6m_rel", "momentum_3m_rel",
                "relative_strength_6m_sector", "liquidity"):
        assert CFG2.V2_QVT_FACTORS[fid]["direction"] == "higher"


def test_record_carry_units_definitions_and_pit():
    recs = build(world((SID, rows_for(base_path()))))
    assert recs["C1"]["liquidity"]["unit"] == "rial"
    assert recs["C1"]["low_volatility"]["unit"] == "daily_return_stdev"
    assert recs["C1"]["momentum_6m_rel"]["unit"] == "return_fraction"
    for fid in TRW.IN_SCOPE_T_FACTORS:
        r = recs["C1"][fid]
        assert r["definition"]
        assert r["pit_status"] == "collected_at_bounded"
        assert r["pit_status"] != RAW.PIT_VERIFIED
        assert r["available_at"] is not None


# ---------------------------------------------------------------------------
# momentum windows
# ---------------------------------------------------------------------------
def test_full_history_all_five_valid_single_company():
    recs = build(world((SID, rows_for(base_path()))))
    for fid in ("momentum_6m_rel", "momentum_3m_rel", "liquidity",
                "low_volatility"):
        assert recs["C1"][fid]["status"] == "valid", (fid, recs["C1"][fid])
    # single company: market benchmark equals its own return -> rel = 0
    assert recs["C1"]["momentum_6m_rel"]["raw_value"] == pytest.approx(0.0,
                                                                       abs=1e-12)


def test_single_company_industry_has_no_sector_benchmark():
    recs = build(world((SID, rows_for(base_path()))))
    r = recs["C1"]["relative_strength_6m_sector"]
    assert r["status"] == "not_applicable"
    assert "insufficient_sector_benchmark" in r["validation_reason"]


def test_momentum_relative_arithmetic_two_companies():
    h = world((SID, rows_for(base_path(final=150.0))),
              ("S2", rows_for(base_path(final=100.0), sid="S2")))
    recs = build(h, sec_by_cid={"C1": SID, "C2": "S2"},
                 meta={"C1": META["C1"],
                       "C2": {"model_family": "general",
                              "industry": "فولاد"}})
    # stock returns +0.5 and 0.0; equal-weight market mean 0.25
    assert recs["C1"]["momentum_6m_rel"]["raw_value"] == pytest.approx(0.25)
    assert recs["C2"]["momentum_6m_rel"]["raw_value"] == pytest.approx(-0.25)
    w6 = recs["C1"]["momentum_6m_rel"]["market"]["window"]
    assert w6["benchmark_kind"] == "equal_weight_market"
    assert w6["benchmark_n"] == 2


def test_momentum_6m_insufficient_history_kept_honest():
    late = {d: c for d, c in base_path(final=150.0).items()
            if d >= dt.date(2026, 5, 1)}
    recs = build(world((SID, rows_for(late))))
    r = recs["C1"]["momentum_6m_rel"]
    assert r["status"] == "missing"
    assert "insufficient_history_6m" in r["validation_reason"]
    # a shorter history is never silently relabeled as a full-window return
    assert r["raw_value"] is None


def test_momentum_3m_window_and_insufficient_history():
    mid = {d: c for d, c in base_path(final=150.0).items()
           if d >= dt.date(2026, 8, 1)}
    recs = build(world((SID, rows_for(mid))))
    r = recs["C1"]["momentum_3m_rel"]
    assert r["status"] == "missing"
    assert "insufficient_history_3m" in r["validation_reason"]


def test_momentum_3m_valid_when_6m_missing():
    late = {d: c for d, c in base_path(final=150.0).items()
            if d >= dt.date(2026, 5, 1)}
    recs = build(world((SID, rows_for(late))))
    assert recs["C1"]["momentum_6m_rel"]["status"] == "missing"
    assert recs["C1"]["momentum_3m_rel"]["status"] == "valid"


# ---------------------------------------------------------------------------
# staleness, gaps, floors
# ---------------------------------------------------------------------------
def test_stale_price_blocks_all_five_with_named_age():
    path = {d: c for d, c in base_path(final=150.0).items()
            if d <= dt.date(2026, 9, 10)}  # 28 days before as_of
    recs = build(world((SID, rows_for(path))))
    for fid in TRW.IN_SCOPE_T_FACTORS:
        r = recs["C1"][fid]
        assert r["status"] == "invalid", (fid, r["validation_reason"])
        assert "price_stale" in r["validation_reason"]
    assert recs["C1"]["momentum_6m_rel"]["market"]["last_trade_date"] \
        == "2026-09-10"


def test_price_age_exactly_at_policy_passes():
    path = {d: c for d, c in base_path(final=150.0).items()
            if d <= dt.date(2026, 9, 24)}  # exactly 14 days
    recs = build(world((SID, rows_for(path))))
    assert recs["C1"]["momentum_6m_rel"]["status"] == "valid"


def test_gap_blocks_momentum_windows_but_not_liquidity():
    path = base_path(final=150.0)
    # a -25% overnight move (both closes above the 100-rial floor): no
    # continuous TSE session can produce it
    path[dt.date(2026, 8, 14)] = path[dt.date(2026, 8, 14)] * 0.75
    recs = build(world((SID, rows_for(path))))
    for fid in ("momentum_6m_rel", "momentum_3m_rel",
                "relative_strength_6m_sector"):
        r = recs["C1"][fid]
        assert r["status"] == "invalid", (fid, r["validation_reason"])
        assert "suspected_unadjusted_gap_in_window" in r["validation_reason"]
        assert any("2026-08-14" in w for w in r["warnings"])
    # money is money: trade value is immune to price adjustments
    assert recs["C1"]["liquidity"]["status"] == "valid"


def test_gap_inside_vol_window_blocks_volatility():
    path = base_path(final=150.0)
    path[dt.date(2026, 9, 15)] = path[dt.date(2026, 9, 15)] * 0.75  # in-window
    recs = build(world((SID, rows_for(path))))
    vol = recs["C1"]["low_volatility"]
    assert vol["status"] == "invalid"
    assert "suspected_unadjusted_gap_in_window" in vol["validation_reason"]
    assert recs["C1"]["liquidity"]["status"] == "valid"


def test_gap_exactly_at_momentum_base_is_caught():
    path = base_path(final=150.0)
    # the first close AFTER the 6m reference is halved: the return chain
    # from the base inclusive must see it
    d0 = dt.date(2026, 4, 9)
    path[d0] = path[d0] * 1.5  # +50% overnight: equally impossible
    recs = build(world((SID, rows_for(path))))
    r = recs["C1"]["momentum_6m_rel"]
    assert r["status"] == "invalid"
    assert "suspected_unadjusted_gap_in_window" in r["validation_reason"]


def test_price_floor_latest_placeholder_not_used_as_latest():
    path = base_path(final=150.0)
    path[dt.date(2026, 10, 5)] = 1.0  # placeholder junk row
    recs = build(world((SID, rows_for(path))))
    # the last VALID close (2026-10-02) drives the factors; the junk row is
    # never a trade price
    assert recs["C1"]["momentum_6m_rel"]["market"]["last_trade_date"] \
        == "2026-10-02"
    assert recs["C1"]["momentum_6m_rel"]["status"] == "valid"


def test_all_junk_closes_missing():
    path = {d: 1.0 for d in base_path(final=150.0)}
    recs = build(world((SID, rows_for(path))))
    for fid in TRW.IN_SCOPE_T_FACTORS:
        assert recs["C1"][fid]["status"] == "missing"
        assert "no_price_history" in recs["C1"][fid]["validation_reason"]


def test_no_history_at_all_missing():
    recs = build(world())
    for fid in TRW.IN_SCOPE_T_FACTORS:
        r = recs["C1"][fid]
        assert r["status"] == "missing"
        assert "no_price_history" in r["validation_reason"]


def test_non_finite_close_never_enters_chains():
    path = base_path(final=150.0)
    path[dt.date(2026, 6, 15)] = float("nan")
    recs = build(world((SID, rows_for(path))))
    # the chain simply continues across the corrupt day: no gap, no crash
    assert recs["C1"]["momentum_6m_rel"]["status"] == "valid"


# ---------------------------------------------------------------------------
# relative strength benchmarks
# ---------------------------------------------------------------------------
def test_rs6_industry_benchmark_arithmetic():
    meta = {"C1": {"model_family": "general", "industry": "فولاد"},
            "C2": {"model_family": "general", "industry": "فولاد"},
            "C3": {"model_family": "general", "industry": "فولاد"}}
    h = world((SID, rows_for(base_path(final=150.0))),
              ("S2", rows_for(base_path(final=110.0), sid="S2")),
              ("S3", rows_for(base_path(final=100.0), sid="S3")))
    recs = build(h, sec_by_cid={"C1": SID, "C2": "S2", "C3": "S3"},
                 meta=meta)
    # stock returns .5 / .1 / 0 -> industry mean .2
    assert recs["C1"]["relative_strength_6m_sector"]["raw_value"] \
        == pytest.approx(0.3)
    assert recs["C3"]["relative_strength_6m_sector"]["raw_value"] \
        == pytest.approx(-0.2)
    w = recs["C1"]["relative_strength_6m_sector"]["market"]["window"]
    assert w["benchmark_kind"] == "equal_weight_industry"
    assert w["benchmark_n"] == 3


def test_rs6_single_member_industry_refused():
    meta = {"C1": {"model_family": "general", "industry": "فولاد"},
            "C2": {"model_family": "general", "industry": "پتروشیمی"},
            "C3": {"model_family": "general", "industry": "پتروشیمی"}}
    h = world((SID, rows_for(base_path(final=150.0))),
              ("S2", rows_for(base_path(final=110.0), sid="S2")),
              ("S3", rows_for(base_path(final=105.0), sid="S3")))
    recs = build(h, sec_by_cid={"C1": SID, "C2": "S2", "C3": "S3"},
                 meta=meta)
    r = recs["C1"]["relative_strength_6m_sector"]
    assert r["status"] == "not_applicable"
    assert "insufficient_sector_benchmark" in r["validation_reason"]
    # the OTHER industry keeps its benchmark (2 members)
    assert recs["C2"]["relative_strength_6m_sector"]["status"] == "valid"


def test_rs6_unclassified_industry_not_applicable():
    recs = build(world((SID, rows_for(base_path(final=150.0)))),
                 meta={"C1": {"model_family": "general", "industry": None}})
    r = recs["C1"]["relative_strength_6m_sector"]
    assert r["status"] == "not_applicable"
    assert "industry_unclassified" in r["validation_reason"]


def test_gap_refused_company_never_seeds_benchmarks():
    gappy = base_path(final=190.0)
    gappy[dt.date(2026, 6, 15)] = gappy[dt.date(2026, 6, 15)] * 1.5
    h = world((SID, rows_for(base_path(final=150.0))),
              ("S2", rows_for(base_path(final=100.0), sid="S2")),
              ("SX", rows_for(gappy, sid="SX")))
    meta = {"C1": {"model_family": "general", "industry": "فولاد"},
            "C2": {"model_family": "general", "industry": "فولاد"},
            "CX": {"model_family": "general", "industry": "فولاد"}}
    recs = build(h, sec_by_cid={"C1": SID, "C2": "S2", "CX": "SX"},
                 meta=meta)
    # X's +0.9 return is refused and must NOT enter the market benchmark:
    # mean of valid returns (.5 + .0) / 2 = .25
    assert recs["C1"]["momentum_6m_rel"]["raw_value"] == pytest.approx(0.25)
    w = recs["C1"]["momentum_6m_rel"]["market"]["window"]
    assert w["benchmark_n"] == 2
    assert recs["CX"]["momentum_6m_rel"]["status"] == "invalid"


# ---------------------------------------------------------------------------
# liquidity
# ---------------------------------------------------------------------------
def test_liquidity_mean_with_no_trade_and_missing_sessions():
    def tv(d):
        if d == dt.date(2026, 9, 21):
            return 0.0          # real no-trade session
        if d == dt.date(2026, 9, 22):
            return None         # missing value, counted not fabricated
        return 2_000_000.0
    recs = build(world((SID, rows_for(base_path(final=150.0),
                                      tv_over=tv))))
    r = recs["C1"]["liquidity"]
    assert r["status"] == "valid"
    w = r["market"]["window"]
    assert w["n_no_trade"] == 1
    assert w["n_missing"] == 1
    win_days = list(weekdays(dt.date(2026, 3, 2), dt.date(2026, 10, 5)))[-30:]
    assert w["n_sessions"] == 30
    expect = sum(2_000_000.0 for d in win_days
                 if d not in (dt.date(2026, 9, 21), dt.date(2026, 9, 22)))
    assert r["raw_value"] == pytest.approx(expect / w["n_valid_tvs"])
    assert any("no-trade sessions" in w_ for w_ in r["warnings"])


def test_liquidity_insufficient_history():
    path = base_path(final=150.0)
    tvs = {d: (1e9 if i % 6 == 0 else None)
           for i, d in enumerate(sorted(path))}
    recs = build(world((SID, rows_for(path, tv_over=tvs.get))))
    r = recs["C1"]["liquidity"]
    assert r["status"] == "missing"
    assert "insufficient_history_liquidity" in r["validation_reason"]


def test_liquidity_window_span_too_long():
    days = [d for d in weekdays(dt.date(2026, 3, 2), dt.date(2026, 10, 5))][::4][-30:]
    path = {d: 100.0 for d in days}
    recs = build(world((SID, rows_for(path))))
    r = recs["C1"]["liquidity"]
    assert r["status"] == "invalid"
    assert "window_span_too_long" in r["validation_reason"]


# ---------------------------------------------------------------------------
# volatility
# ---------------------------------------------------------------------------
def test_volatility_stdev_exact_construction():
    path = base_path(final=150.0)
    recs = build(world((SID, rows_for(path))))
    r = recs["C1"]["low_volatility"]
    assert r["status"] == "valid"
    closes = [c for d, c in sorted(path.items())
              if c >= TRW.PRICE_FLOOR][-TRW.VOL_WINDOW_CLOSES:]
    rets = [(c2 / c1 - 1.0)
            for c1, c2 in zip(closes, closes[1:]) if c1 > 0]
    assert r["raw_value"] == pytest.approx(statistics.stdev(rets))
    assert r["market"]["window"]["n_returns"] == len(rets)


def test_volatility_insufficient_history():
    path = {d: 100.0 + i for i, d in enumerate(
        list(weekdays(dt.date(2026, 9, 28), dt.date(2026, 10, 5))))}
    recs = build(world((SID, rows_for(path))))
    r = recs["C1"]["low_volatility"]
    assert r["status"] == "missing"
    assert "insufficient_history_volatility" in r["validation_reason"]


def test_volatility_window_span_too_long():
    days = list(weekdays(dt.date(2026, 3, 2), dt.date(2026, 10, 5)))[-60:][::3]
    path = {d: 100.0 + (i % 3) for i, d in enumerate(days)}
    recs = build(world((SID, rows_for(path))))
    r = recs["C1"]["low_volatility"]
    assert r["status"] == "invalid"
    assert "window_span_too_long" in r["validation_reason"]


# ---------------------------------------------------------------------------
# extraction + purity
# ---------------------------------------------------------------------------
def test_extract_drops_future_rows_and_dedupes_per_day():
    d1 = dt.date(2026, 10, 5)
    d2 = dt.date(2026, 10, 2)
    rows = [
        {"security_id": SID, "trade_date": d1, "closing_price_rial": 120.0,
         "trade_value_rial": 5.0,
         "collected_at": dt.datetime(2026, 10, 6, 9, 0,
                                     tzinfo=dt.timezone.utc)},
        {"security_id": SID, "trade_date": d1, "closing_price_rial": 100.0,
         "trade_value_rial": 4.0,
         "collected_at": dt.datetime(2026, 10, 6, 8, 0,
                                     tzinfo=dt.timezone.utc)},
        {"security_id": SID, "trade_date": d2, "closing_price_rial": 90.0,
         "trade_value_rial": 3.0,
         "collected_at": dt.datetime(2026, 10, 3, 8, 0,
                                     tzinfo=dt.timezone.utc)},
        {"security_id": SID, "trade_date": dt.date(2026, 10, 9),
         "closing_price_rial": 999.0, "trade_value_rial": 1.0,
         "collected_at": dt.datetime(2026, 10, 9, 8, 0,
                                     tzinfo=dt.timezone.utc)},
    ]
    hist = TRW.extract_daily_history(rows, AS_OF)
    days = hist[SID]
    assert [x["date"] for x in days] == [d2, d1]  # future row dropped
    # engine order is trade_date DESC, collected_at DESC: first seen wins
    assert days[-1]["close"] == 120.0


def test_build_does_not_mutate_inputs():
    rows = rows_for(base_path(final=150.0))
    hist = world((SID, rows))
    frozen = copy.deepcopy(hist)
    build(hist)
    assert hist == frozen


# ---------------------------------------------------------------------------
# T normalize (mirrors the V normalize contract)
# ---------------------------------------------------------------------------
import score_v2_normalize as SN
import score_v2_t_normalize as TN


def norm_world(returns_by_cid, family="general", industry="فولاد"):
    """Real raw+normalize over synthetic peers with controlled 6m returns;
    constant trade value keeps liquidity identical across peers."""
    histories = {}
    sec = {}
    meta = {}
    for i, (cid, ret) in enumerate(sorted(returns_by_cid.items())):
        sid = f"S{i}"
        sec[cid] = sid
        meta[cid] = {"model_family": family, "industry": industry}
        # 1000-rial base keeps every negative-return path above the
        # 100-rial floor so the full window stays valid
        path = {}
        path.update(seg_closes(dt.date(2026, 3, 2), dt.date(2026, 4, 8),
                               1000.0, 1000.0))
        path.update(seg_closes(dt.date(2026, 4, 9), dt.date(2026, 7, 8),
                               1000.0, 1250.0))
        path.update(seg_closes(dt.date(2026, 7, 9), dt.date(2026, 10, 5),
                               1250.0, 1000.0 * (1.0 + ret)))
        histories[sid] = TRW.extract_daily_history(rows_for(path, sid=sid), AS_OF)[sid]
    raw = TRW.build_t_raw(histories, sec, meta, as_of=AS_OF)
    return raw, meta


def test_higher_direction_best_momentum_gets_percentile_one():
    rets = {f"C{i:02d}": -0.3 + i * 0.05 for i in range(12)}
    raw, meta = norm_world(rets)
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    best = max(rets, key=rets.get)
    worst = min(rets, key=rets.get)
    by = {(r["company_id"], r["factor_id"]): r for r in out["records"]}
    assert by[(best, "momentum_6m_rel")]["percentile_combined"] == \
        pytest.approx(1.0)
    assert by[(worst, "momentum_6m_rel")]["percentile_combined"] == \
        pytest.approx(0.0)


def test_low_volatility_lower_direction_best_gets_one():
    rets = {f"C{i:02d}": 0.1 for i in range(12)}
    raw, meta = norm_world(rets)
    # give C00 a calm flat path and C11 a jumpy (in-band) path
    calm = {d: 100.0 for d in base_path(final=100.0)}
    jumpy = {d: (100.0 if i % 2 else 106.0)
             for i, d in enumerate(sorted(base_path(final=100.0)))}
    raw["C00"]["low_volatility"] = build(
        world((SID, rows_for(calm))))["C1"]["low_volatility"]
    raw["C11"]["low_volatility"] = build(
        world((SID, rows_for(jumpy))))["C1"]["low_volatility"]
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    by = {(r["company_id"], r["factor_id"]): r for r in out["records"]}
    assert by[("C00", "low_volatility")]["percentile_combined"] == \
        pytest.approx(1.0)
    assert by[("C11", "low_volatility")]["percentile_combined"] == \
        pytest.approx(0.0)


def test_input_order_independence():
    rets = {f"C{i:02d}": -0.2 + i * 0.04 for i in range(11)}
    raw, meta = norm_world(rets)
    a = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    shuffled = {cid: raw[cid] for cid in sorted(raw, reverse=True)}
    b = TN.normalize_t_cross_section(shuffled, meta, as_of=AS_OF)
    assert a["records"] == b["records"]


def test_families_never_mix():
    rets = {f"G{i:02d}": -0.1 + i * 0.02 for i in range(10)}
    raw, meta = norm_world(rets)
    brets = {"B00": 9.0}
    brets.update({f"B{i:02d}": 0.05 for i in range(1, 10)})
    braw, bmeta = norm_world(brets, family="bank")
    merged_raw = {**raw, **braw}
    merged_meta = {**meta, **bmeta}
    out = TN.normalize_t_cross_section(merged_raw, merged_meta, as_of=AS_OF)
    by = {(r["company_id"], r["factor_id"]): r for r in out["records"]}
    assert by[("B00", "momentum_6m_rel")]["n_valid_market_family"] == 10
    assert by[("G00", "momentum_6m_rel")]["n_valid_market_family"] == 10
    # the bank extreme ranks inside its own family (and its own industry
    # population) only — never against the general companies
    assert by[("B00", "momentum_6m_rel")]["percentile_combined"] == \
        pytest.approx(1.0)
    assert by[("B00", "momentum_6m_rel")]["peer_group"] == \
        "family:bank|industry:فولاد"


def test_insufficient_peers_below_family_min():
    rets = {f"C{i:02d}": 0.05 * i for i in range(9)}
    raw, meta = norm_world(rets)
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    for r in out["records"]:
        assert r["normalization_status"] == SN.NR_INSUFFICIENT_PEERS
        assert r["percentile_combined"] is None
        assert r["null_reasons"]["percentile_combined"] == \
            "insufficient_peers"


def test_winsor_at_n100_clips_outlier_to_p99():
    rets = {f"C{i:03d}": 0.1 for i in range(100)}
    rets["COUT"] = 50.0
    raw, meta = norm_world(rets)
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    pop = out["populations"]["momentum_6m_rel"]["families"]["general"]
    assert pop["winsor"]["applied"] is True
    raw_vals = [r["raw_value"] for r in out["records"]
                if r["factor_id"] == "momentum_6m_rel"]
    bound = pop["winsor"]["high"]
    # raw values are RELATIVE (stock return - equal-weight market mean):
    # market mean = (100 x 0.1 + 50) / 101
    rel_outlier = 50.0 - (100 * 0.1 + 50.0) / 101
    assert max(raw_vals) == pytest.approx(rel_outlier)
    assert bound < max(raw_vals) * 0.02  # the outlier IS clipped
    fin = {(r["company_id"], r["factor_id"]): r
           for r in out["records"]}
    assert fin[("COUT", "momentum_6m_rel")]["normalized_input"] == \
        pytest.approx(bound)


def test_no_winsor_below_min_n():
    rets = {f"C{i:02d}": 0.02 * i for i in range(12)}
    raw, meta = norm_world(rets)
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    pop = out["populations"]["momentum_6m_rel"]["families"]["general"]
    assert pop["winsor"]["applied"] is False


def test_non_finite_valid_value_excluded():
    rets = {f"C{i:02d}": 0.02 * i for i in range(12)}
    raw, meta = norm_world(rets)
    raw["C00"]["momentum_6m_rel"] = {
        **raw["C00"]["momentum_6m_rel"],
        "raw_value": float("nan"), "status": "valid"}
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    pop = out["populations"]["momentum_6m_rel"]
    assert pop["excluded"].get("non_finite") == 1
    assert pop["families"]["general"]["n_valid"] == 11


def test_missing_factor_never_zero_or_neutral():
    rets = {f"C{i:02d}": 0.02 * i for i in range(12)}
    raw, meta = norm_world(rets)
    raw["C00"]["momentum_6m_rel"] = {
        **raw["C00"]["momentum_6m_rel"],
        "raw_value": None, "status": "missing"}
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    entry = out["factors"]["C00"]["momentum_6m_rel"]
    assert entry["normalization_status"] == "not_ranked_raw_missing"
    assert entry["percentile_combined"] is None


def test_historical_strict_refuses_collected_at_bounded_records():
    rets = {f"C{i:02d}": 0.02 * i for i in range(12)}
    raw, meta = norm_world(rets)
    out = TN.normalize_t_cross_section(
        raw, meta, as_of=AS_OF, pit_policy=SN.PIT_HISTORICAL_STRICT)
    assert out["records"], "records are kept, explicitly unranked"
    for r in out["records"]:
        assert r["normalization_status"] == SN.NR_PIT_STRICT
        assert r["percentile_combined"] is None
    pop = out["populations"]["momentum_6m_rel"]
    assert pop["excluded_pit_strict"] == 12


def test_unknown_policy_and_missing_meta_raise():
    rets = {f"C{i:02d}": 0.02 * i for i in range(12)}
    raw, meta = norm_world(rets)
    with pytest.raises(ValueError, match="pit_policy"):
        TN.normalize_t_cross_section(raw, meta, as_of=AS_OF,
                                     pit_policy="yolo")
    with pytest.raises(ValueError, match="company_meta"):
        TN.normalize_t_cross_section(raw, {"CX": meta["C00"]}, as_of=AS_OF)
    with pytest.raises(ValueError, match="historical_strict"):
        TN.normalize_t_cross_section(raw, meta,
                                     pit_policy=SN.PIT_HISTORICAL_STRICT)


def test_foreign_factor_skipped_and_bad_direction_refused():
    rets = {f"C{i:02d}": 0.02 * i for i in range(12)}
    raw, meta = norm_world(rets)
    raw["C00"]["roe_level"] = {"factor_id": "roe_level",
                               "raw_value": 1.0, "status": "valid"}
    out = TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    assert "roe_level" not in out["factors"]["C00"]
    assert "roe_level" not in out["populations"]
    import copy
    saved = copy.deepcopy(CFG2.V2_QVT_FACTORS)
    try:
        CFG2.V2_QVT_FACTORS["momentum_6m_rel"] = {
            **saved["momentum_6m_rel"], "direction": "up"}
        with pytest.raises(ValueError, match="direction"):
            TN.normalize_t_cross_section(raw, meta, as_of=AS_OF)
    finally:
        CFG2.V2_QVT_FACTORS.clear()
        CFG2.V2_QVT_FACTORS.update(saved)
