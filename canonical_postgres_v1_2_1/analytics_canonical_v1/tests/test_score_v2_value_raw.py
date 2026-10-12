"""Value raw extraction/validation tests (step 2-J-1) — pure, no database.

Covers score_v2_value_raw.build_v_raw() on synthetic engine-metric + market
channel worlds:

  * construction: each ratio from its OWN economic quantity, market cap =
    PIT price x PIT shares, computed only when both are real and positive
  * financial gates: a loss maker or zero-profit company can NEVER produce a
    negative / cheap-reading P/E (not_applicable, never valid); negative or
    zero book value refuses P/B with an explicit warning; negative revenue is
    invalid (Q doctrine), zero revenue not_applicable; P/S is family-scoped
    to general (config doctrine)
  * above-band values stay VALID with an explicit warning (V1's own bands,
    reused; real-but-unusual economics are never deleted at the raw layer)
  * market gates: missing price / zero or negative price / future price /
    missing or nonpositive shares — each named, none guessed around
  * freshness + consistency: stale price, share snapshot older than the
    price (no corporate-action evidence in the store), stale balance sheet —
    all stay computable but warned
  * legacy-sentinel net_profit legs surface a visible warning on P/E
  * look-ahead doctrine: a financial input published after the cutoff
    invalidates a otherwise-valid ratio (same contract as the Q raw layer)
  * config agreement: pe/pb/ps are READY valuation factors, direction
    lower, and the general family map is exactly pe 13 + pb 12 + ps 10

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2_value_raw.py -q
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import score_v2_config as CFG  # noqa: E402
import score_v2_raw as SR  # noqa: E402
import score_v2_value_raw as VRW  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc)


def channel(price=10.0, ptd=dt.date(2026, 10, 5), price_age=3,
            shares=1000.0, gap=0, source="TSETMC_ZTITAD_CURRENT",
            ssd=dt.date(2026, 10, 5)):
    return {"price": price, "price_trade_date": ptd,
            "price_collected_at": dt.datetime(2026, 10, 5, 18, 0,
                                              tzinfo=dt.timezone.utc),
            "price_age_days": price_age, "shares": shares,
            "share_source": source, "share_source_date": ssd,
            "share_price_gap_days": gap,
            "share_cross_check": "AGREE"}


def metrics(np=500.0, rev=1000.0):
    return {"net_profit_ttm": np, "revenue_ttm": rev}


META_G = {"model_family": "general", "industry": "م Misc"}
EQUITY_OK = {"equity": 2500.0, "period_end_date": dt.date(2026, 7, 31)}


def build(m=None, meta=None, ch=None, eq=None, prov=None, sent=None,
          as_of=AS_OF, cutoff=CUTOFF):
    equity = {"C1": eq} if eq is not None else {"C1": EQUITY_OK}
    return VRW.build_v_raw(
        {"C1": dict(metrics() if m is None else m)},
        meta if meta is not None else {"C1": META_G},
        market={"C1": dict(channel() if ch is None else ch)},
        equity_by_company=equity,
        provenance={"C1": prov} if prov else None,
        net_profit_sentinel=sent, as_of=as_of,
        cutoff=cutoff)["C1"]


# ---------------------------------------------------------------------------
# config agreement
# ---------------------------------------------------------------------------
def test_v_factors_are_ready_lower_valuation_in_config():
    for fid, w in (("pe", 13), ("pb", 12), ("ps", 10)):
        spec = CFG.V2_QVT_FACTORS[fid]
        assert spec["axis"] == "valuation"
        assert spec["direction"] == "lower"
        assert spec["availability"] == CFG.READY
        assert spec["target_weight"] == w
    for fam in ("bank", "insurance", "investment"):
        assert "ps" not in CFG.FAMILY_WEIGHTS[fam]


def test_needs_development_v_factors_never_computed():
    for fid in ("ev_ebit", "fcf_yield"):
        assert CFG.V2_QVT_FACTORS[fid]["availability"] == CFG.NEEDS_DEVELOPMENT
        assert fid not in VRW.IN_SCOPE_V_FACTORS


# ---------------------------------------------------------------------------
# construction + financial gates
# ---------------------------------------------------------------------------
def test_pe_pb_ps_valid_construction():
    recs = build(metrics())
    # market cap = 10 * 1000 = 10,000
    assert recs["pe"]["status"] == "valid"
    assert recs["pe"]["raw_value"] == pytest.approx(10000 / 500)
    assert recs["pb"]["raw_value"] == pytest.approx(10000 / 2500)
    assert recs["ps"]["raw_value"] == pytest.approx(10000 / 1000)
    for fid in ("pe", "pb", "ps"):
        assert recs[fid]["warnings"] == []
        assert recs[fid]["market"]["price"] == 10.0
        assert recs[fid]["market"]["shares"] == 1000.0
        assert recs[fid]["market"]["price_trade_date"] == "2026-10-05"


def test_negative_profit_never_produces_a_cheap_pe():
    recs = build(metrics(np=-300.0))
    pe = recs["pe"]
    assert pe["status"] == "not_applicable"
    assert pe["raw_value"] is None
    assert "negative_net_profit_ttm" in pe["validation_reason"]
    assert any(w.startswith("loss_maker") for w in pe["warnings"])


def test_zero_profit_pe_not_applicable():
    recs = build(metrics(np=0.0))
    assert recs["pe"]["status"] == "not_applicable"
    assert "zero_net_profit_ttm" in recs["pe"]["validation_reason"]


def test_missing_profit_pe_missing():
    recs = build(metrics(np=None))
    assert recs["pe"]["status"] == "missing"
    assert "net_profit_ttm_missing" in recs["pe"]["validation_reason"]


def test_pe_above_v1_band_stays_valid_with_warning():
    recs = build(metrics(np=100.0))  # pe = 100 > 60
    pe = recs["pe"]
    assert pe["status"] == "valid"
    assert any(w.startswith("pe_above_v1_valid_band") for w in pe["warnings"])


def test_non_finite_pe_result_is_invalid():
    recs = build(metrics(np=1e-308))
    pe = recs["pe"]
    assert pe["status"] == "invalid"
    assert pe["raw_value"] is None
    assert pe["raw_value"] is not math.inf
    assert "non_finite_result" in pe["validation_reason"]


def test_negative_equity_never_reads_as_cheap_pb():
    recs = build(eq={"equity": -400.0, "period_end_date": dt.date(2026, 7, 31)})
    pb = recs["pb"]
    assert pb["status"] == "not_applicable"
    assert "negative_total_equity" in pb["validation_reason"]
    assert any(w.startswith("negative_equity") for w in pb["warnings"])


def test_zero_equity_pb_not_applicable_missing_equity_pb_missing():
    recs = build(eq={"equity": 0.0, "period_end_date": dt.date(2026, 7, 31)})
    assert recs["pb"]["status"] == "not_applicable"
    assert "zero_total_equity" in recs["pb"]["validation_reason"]
    recs = build(eq={})
    assert recs["pb"]["status"] == "missing"
    assert "total_equity_missing" in recs["pb"]["validation_reason"]


def test_stale_balance_sheet_warns_but_stays_computable():
    recs = build(eq={"equity": 2500.0,
                     "period_end_date": dt.date(2025, 1, 1)})  # > 366 days
    pb = recs["pb"]
    assert pb["status"] == "valid"
    assert any(w.startswith("stale_balance_sheet") for w in pb["warnings"])


def test_ps_negative_revenue_invalid_zero_not_applicable():
    recs = build(metrics(rev=-5.0))
    assert recs["ps"]["status"] == "invalid"
    assert "negative_revenue_ttm" in recs["ps"]["validation_reason"]
    recs = build(metrics(rev=0.0))
    assert recs["ps"]["status"] == "not_applicable"
    assert "zero_revenue_ttm" in recs["ps"]["validation_reason"]
    recs = build(metrics(rev=None))
    assert recs["ps"]["status"] == "missing"


def test_ps_family_gate_general_only():
    recs = build(meta={"C1": {"model_family": "bank", "industry": "بانک"}})
    ps = recs["ps"]
    assert ps["status"] == "not_applicable"
    assert "ps_not_meaningful_for_specialized_family" \
        in ps["validation_reason"]
    # pe/pb stay computable for the specialized family
    assert recs["pe"]["status"] == "valid"
    assert recs["pb"]["status"] == "valid"


# ---------------------------------------------------------------------------
# market gates
# ---------------------------------------------------------------------------
def test_no_channel_missing_no_price_missing_zero_price_invalid():
    recs = VRW.build_v_raw({"C1": metrics()}, META_G, market={},
                           equity_by_company=EQUITY_OK, as_of=AS_OF,
                           cutoff=CUTOFF)["C1"]
    assert recs["pe"]["status"] == "missing"
    assert "no_pit_market_data" in recs["pe"]["validation_reason"]
    recs = build(ch=channel(price=None))
    assert recs["pe"]["status"] == "missing"
    assert "no_price_data" in recs["pe"]["validation_reason"]
    recs = build(ch=channel(price=0.0))
    assert recs["pe"]["status"] == "invalid"
    assert "nonpositive_price" in recs["pe"]["validation_reason"]
    recs = build(ch=channel(price=-2.0))
    assert "nonpositive_price" in recs["pe"]["validation_reason"]


def test_future_price_is_lookahead_invalid():
    recs = build(ch=channel(ptd=dt.date(2026, 10, 9), price_age=-1),
                 as_of=AS_OF)
    assert recs["pe"]["status"] == "invalid"
    assert "price_after_as_of" in recs["pe"]["validation_reason"]


def test_missing_and_nonpositive_shares_refuse():
    recs = build(ch=channel(shares=None))
    assert recs["pe"]["status"] == "missing"
    assert "no_pit_share_snapshot" in recs["pe"]["validation_reason"]
    recs = build(ch=channel(shares=0.0))
    assert recs["pe"]["status"] == "invalid"
    assert "nonpositive_shares" in recs["pe"]["validation_reason"]


def test_stale_price_warns_but_stays_computable():
    recs = build(ch=channel(price_age=12))  # > PRICE_STALE_DAYS (7)
    assert recs["pe"]["status"] == "valid"
    assert any(w.startswith("stale_price") for w in recs["pe"]["warnings"])


def test_share_snapshot_older_than_price_warns_unprovable_capital_change():
    recs = build(ch=channel(gap=3, ssd=dt.date(2026, 10, 2)))
    assert recs["pe"]["status"] == "valid"
    w = [x for x in recs["pe"]["warnings"]
         if x.startswith("share_snapshot_older_than_price")]
    assert w and "no corporate-action evidence" in w[0]


# ---------------------------------------------------------------------------
# sentinel + look-ahead doctrine
# ---------------------------------------------------------------------------
def test_sentinel_net_profit_legs_warn_on_pe_only():
    recs = build(sent={"C1": ["net_profit@1405/06(order 2)"]})
    assert recs["pe"]["status"] == "valid"
    assert any(w.startswith("net_profit_ttm_consumes_legacy_sentinel_cell")
               for w in recs["pe"]["warnings"])
    for fid in ("pb", "ps"):
        assert not any("sentinel" in w for w in recs[fid]["warnings"])


def test_publication_after_cutoff_invalidates_valid_ratio():
    prov = {"available_at": dt.datetime(2026, 10, 9, 8, 0,
                                        tzinfo=dt.timezone.utc),
            "source_ref": "codal:1"}
    recs = build(prov=prov)
    assert recs["pe"]["pit_status"] == SR.PIT_AFTER_AS_OF
    assert recs["pe"]["status"] == "invalid"
    assert recs["pe"]["raw_value"] is None
    assert "after as_of" in recs["pe"]["validation_reason"]


def test_unverified_provenance_keeps_exploratory_valid():
    recs = build(prov={"available_at": dt.datetime(2026, 10, 1, 8, 0,
                                                   tzinfo=dt.timezone.utc)})
    assert recs["pe"]["pit_status"] == SR.PIT_UNVERIFIED
    assert recs["pe"]["status"] == "valid"


# ---------------------------------------------------------------------------
# every company gets a record for all three factors
# ---------------------------------------------------------------------------
def test_all_three_factors_present_even_on_total_market_failure():
    recs = VRW.build_v_raw({"C1": metrics()}, META_G, market={},
                           equity_by_company={}, as_of=AS_OF,
                           cutoff=CUTOFF)["C1"]
    assert set(recs) == {"pe", "pb", "ps"}
    assert recs["pb"]["status"] == "missing"  # both market and equity fail


def test_every_record_carries_market_traceability():
    recs = build(ch=channel(gap=1, ssd=dt.date(2026, 10, 4)))
    for fid in ("pe", "pb", "ps"):
        mkt = recs[fid]["market"]
        assert mkt["price_trade_date"] == "2026-10-05"
        assert mkt["share_source_date"] == "2026-10-04"
        assert mkt["share_price_gap_days"] == 1
        assert mkt["price_age_days"] == 3
