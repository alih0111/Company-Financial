"""Golden regression tests for the SERVED engine: score_version = canonical-v1-dev.

Purpose (Step-0 protection before any V2 work): freeze the exact scoring behavior
of `Engine.rank_and_score` (compute_metrics.py) so the V1→V2 transition cannot
silently change what is served today.

How it works, deliberately:
  * `Engine.rank_and_score` is a pure cross-sectional pass over `self.metrics` —
    it never touches the database (`Engine.load()` does, and it is NOT called
    here). We construct an Engine, inject a fixed 4-company fixture, and call
    the production `rank_and_score` directly.
  * GOLDEN below holds LITERAL expected values captured once from the current
    engine build. Tests compare engine output against these literals and never
    re-derive expected values by calling the engine itself.
  * Known V1 defects are pinned as-is (NOT fixed in this phase):
      - BASELINE_WEIGHTS_V37 sums to 89 while the UI shows "از ۱۰۰"
      - a missing factor input earns the neutral 0.30 percentile (points for
        missing data), except valuation/liquidity which use neutral 0.00
      - penalties are baked into category scores and the DQ multiplier shrinks
        the whole sum
  * No database connection happens in this file; nothing is written anywhere.

Run:
    .venv/Scripts/python.exe -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_canonical_v1_golden.py -q
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
PKG = BASE / "analytics_canonical_v1"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(BASE / "migration_tools"))

import compute_metrics as CM  # noqa: E402
from data_quality import DQ  # noqa: E402

AS_OF = dt.date(2026, 10, 4)
CUTOFF = dt.datetime(2026, 10, 4, 23, 0, 0, tzinfo=dt.timezone.utc)

# The 21 factor ranks rank_and_score writes (one per BASELINE_WEIGHTS_V37 key).
RANK_FIELDS = [
    "SalesGrowthRank", "SalesGrowth3MRank", "RevenueGrowthRank",
    "OperatingProfitGrowthRank", "NetProfitGrowthRank",
    "OperatingMarginRank", "NetMarginRank", "MarginTrendRank", "ROERank",
    "InterestCoverageRank", "CashConversionRank", "EarningsQualityRank",
    "PERank", "PSRank", "PBRank",
    "LiquidityRank", "LeverageRank", "CurrentRatioRank", "StabilityRank",
    "LowVolatilityRank", "MomentumRank",
]
SCORE_FIELDS = [
    "quant_score", "data_quality_score",
    "growth_score", "profitability_score", "valuation_score", "market_score",
]

_COMPANIES = {
    # Healthy grower, complete data (financial + monthly + price -> DQ = 1.0).
    # No penalty branch triggers. Ranks top of the cross-section.
    "GOOD": {
        "sales_growth_12m": 40.0, "sales_growth_3m": 15.0, "revenue_growth": 35.0,
        "operating_profit_growth": 30.0, "net_profit_growth": 45.0, "eps_growth": 45.0,
        "operating_margin": 25.0, "net_margin": 18.0, "margin_trend": 3.0,
        "roe": 22.0, "interest_coverage": 12.0, "cash_conversion": 1.2,
        "earnings_quality": 5.0,
        "pe": 8.0, "ps": 2.0, "pb": 3.0,
        "avg_trade_value_30d": 5_000_000_000_000.0, "debt_ratio": 0.35,
        "current_ratio": 2.0, "sales_stability": 0.9, "volatility_30d": 1.5,
        "price_momentum_30d": 10.0,
        "net_profit_ttm": 500_000_000_000.0,
        "has_financial": True, "has_monthly": True, "has_price": True,
        "_dq_flags": [],
    },
    # Loss-maker: net_profit_ttm < 0 (pp +10), interest_coverage < 1.5 (pp +4),
    # margin_trend < -2 (pp +3), earnings_quality >= 100 (pp +8),
    # sales_growth_12m < -20 (gp +6), operating_profit_growth < -25 (gp +5),
    # negative PE and missing equity -> PERank/PBRank invalid -> 0.0 + vp +8.
    "LOSS": {
        "sales_growth_12m": -30.0, "sales_growth_3m": -12.0, "revenue_growth": -25.0,
        "operating_profit_growth": -40.0, "net_profit_growth": -60.0, "eps_growth": None,
        "operating_margin": -15.0, "net_margin": -20.0, "margin_trend": -6.0,
        "roe": -25.0, "interest_coverage": 0.8, "cash_conversion": -0.5,
        "earnings_quality": 120.0,
        "pe": -3.5, "ps": 1.5, "pb": None,
        "avg_trade_value_30d": 800_000_000_000.0, "debt_ratio": 0.85,
        "current_ratio": 0.6, "sales_stability": 0.2, "volatility_30d": 4.5,
        "price_momentum_30d": -25.0,
        "net_profit_ttm": -200_000_000_000.0,
        "has_financial": True, "has_monthly": True, "has_price": True,
        "_dq_flags": [],
    },
    # Incomplete data: no monthly activity, no price/market data (DQ = 0.45).
    # Missing non-valuation factors fall to the 0.30 neutral percentile and
    # STILL earn weight*0.30 points (documented V1 behavior, kept as-is).
    # Missing PE additionally takes the vp -8 penalty; LiquidityRank missing
    # uses neutral 0.00 (not 0.30).
    "PARTIAL": {
        "sales_growth_12m": None, "sales_growth_3m": None, "revenue_growth": 10.0,
        "operating_profit_growth": None, "net_profit_growth": 8.0, "eps_growth": 7.0,
        "operating_margin": 12.0, "net_margin": 9.0, "margin_trend": None,
        "roe": 14.0, "interest_coverage": 5.0, "cash_conversion": None,
        "earnings_quality": None,
        "pe": None, "ps": None, "pb": None,
        "avg_trade_value_30d": None, "debt_ratio": 0.5,
        "current_ratio": 1.1, "sales_stability": None, "volatility_30d": None,
        "price_momentum_30d": None,
        "net_profit_ttm": 90_000_000_000.0,
        "has_financial": True, "has_monthly": False, "has_price": False,
        "_dq_flags": ["missing_monthly_activity", "missing_price"],
    },
    # Valid fundamentals but P/E above the 60 cap: PERank invalidated to 0.0
    # AND the vp -8 valuation penalty. PS/PB of the same company stay ranked
    # normally (valuation legs are isolated from each other).
    "BADPE": {
        "sales_growth_12m": 5.0, "sales_growth_3m": 2.0, "revenue_growth": 4.0,
        "operating_profit_growth": 3.0, "net_profit_growth": 6.0, "eps_growth": 6.5,
        "operating_margin": 10.0, "net_margin": 7.0, "margin_trend": 0.5,
        "roe": 11.0, "interest_coverage": 4.0, "cash_conversion": 0.7,
        "earnings_quality": 15.0,
        "pe": 85.0, "ps": 6.0, "pb": 4.0,
        "avg_trade_value_30d": 900_000_000_000.0, "debt_ratio": 0.55,
        "current_ratio": 1.3, "sales_stability": 0.7, "volatility_30d": 2.5,
        "price_momentum_30d": -2.0,
        "net_profit_ttm": 120_000_000_000.0,
        "has_financial": True, "has_monthly": True, "has_price": True,
        "_dq_flags": [],
    },
}


def _golden_engine() -> CM.Engine:
    """Engine with the fixed 4-company fixture injected; DB never touched."""
    eng = CM.Engine(AS_OF, CUTOFF)
    eng.metrics = {}
    for sym, spec in _COMPANIES.items():
        v = {k: spec[k] for k in spec if k != "_dq_flags"}
        v["symbol"] = sym
        v["security_id"] = "SEC-" + sym
        v["_dq"] = DQ(list(spec["_dq_flags"]))
        eng.metrics["CID-" + sym] = v
    return eng


def _dq_pair_engine() -> CM.Engine:
    """Two IDENTICAL companies; only the DQ booleans differ (B has no price).

    Because every ranked value ties, both get identical category scores; the
    only score difference is the DQ multiplier (1.0 vs 0.85). Isolates the
    quant_score = dq * (growth + prof + val + mkt) contract.
    """
    eng = CM.Engine(AS_OF, CUTOFF)
    eng.metrics = {}
    for sym, has_price in (("DQFULL", True), ("DQNOPX", False)):
        spec = dict(_COMPANIES["GOOD"])
        v = {k: spec[k] for k in spec if k != "_dq_flags"}
        v["symbol"] = sym
        v["security_id"] = "SEC-" + sym
        v["has_price"] = has_price
        v["_dq"] = DQ([] if has_price else ["missing_price"])
        eng.metrics["CID-" + sym] = v
    return eng


def _run(engine: CM.Engine) -> dict:
    engine.rank_and_score()
    out = {}
    for cid, v in engine.metrics.items():
        out[v["symbol"]] = {
            **{f: v[f] for f in SCORE_FIELDS},
            "ranks": {f: v[f] for f in RANK_FIELDS},
        }
    return out


# ----------------------------------------------------------------------------
# GOLDEN — literal expected outputs captured from the current engine build
# (score_version = canonical-v1-dev, direct valuation). Values below were
# produced by running _run(_golden_engine()) once against that build and are
# now frozen; the tests never recompute them.
# ----------------------------------------------------------------------------
GOLDEN: dict = {
    "GOOD": {
        "quant_score": 88.0, "data_quality_score": 1.0,
        "growth_score": 36.0, "profitability_score": 26.0,
        "valuation_score": 15.0, "market_score": 11.0,
        "ranks": {
            "SalesGrowthRank": 1.0, "SalesGrowth3MRank": 1.0,
            "RevenueGrowthRank": 1.0, "OperatingProfitGrowthRank": 1.0,
            "NetProfitGrowthRank": 1.0, "OperatingMarginRank": 1.0,
            "NetMarginRank": 1.0, "MarginTrendRank": 1.0, "ROERank": 1.0,
            "InterestCoverageRank": 1.0, "CashConversionRank": 1.0,
            "EarningsQualityRank": 1.0, "PERank": 1.0,
            "PSRank": 0.6666666666666667, "PBRank": 1.0,
            "LiquidityRank": 1.0, "LeverageRank": 1.0,
            "CurrentRatioRank": 1.0, "StabilityRank": 1.0,
            "LowVolatilityRank": 1.0, "MomentumRank": 1.0,
        },
    },
    "LOSS": {
        "quant_score": 0.0, "data_quality_score": 1.0,
        "growth_score": 0.0, "profitability_score": 0.0,
        "valuation_score": 0.0, "market_score": 0.0,
        "ranks": {
            "SalesGrowthRank": 0.0, "SalesGrowth3MRank": 0.0,
            "RevenueGrowthRank": 0.0, "OperatingProfitGrowthRank": 0.0,
            "NetProfitGrowthRank": 0.0, "OperatingMarginRank": 0.0,
            "NetMarginRank": 0.0, "MarginTrendRank": 0.0, "ROERank": 0.0,
            "InterestCoverageRank": 0.0, "CashConversionRank": 0.0,
            "EarningsQualityRank": 0.0, "PERank": 0.0, "PSRank": 1.0,
            "PBRank": 0.0, "LiquidityRank": 0.0, "LeverageRank": 0.0,
            "CurrentRatioRank": 0.0, "StabilityRank": 0.0,
            "LowVolatilityRank": 0.0, "MomentumRank": 0.0,
        },
    },
    "PARTIAL": {
        "quant_score": 15.45, "data_quality_score": 0.45,
        "growth_score": 16.3, "profitability_score": 14.8,
        "valuation_score": 0.0, "market_score": 3.2,
        "ranks": {
            "SalesGrowthRank": 0.3, "SalesGrowth3MRank": 0.3,
            "RevenueGrowthRank": 0.6666666666666666,
            "OperatingProfitGrowthRank": 0.3,
            "NetProfitGrowthRank": 0.6666666666666666,
            "OperatingMarginRank": 0.6666666666666666,
            "NetMarginRank": 0.6666666666666666, "MarginTrendRank": 0.3,
            "ROERank": 0.6666666666666666,
            "InterestCoverageRank": 0.6666666666666666,
            "CashConversionRank": 0.3, "EarningsQualityRank": 0.5,
            "PERank": 0.0, "PSRank": 0.0, "PBRank": 0.0,
            "LiquidityRank": 0.0, "LeverageRank": 0.6666666666666667,
            "CurrentRatioRank": 0.3333333333333333, "StabilityRank": 0.3,
            "LowVolatilityRank": 0.3, "MomentumRank": 0.3,
        },
    },
    "BADPE": {
        "quant_score": 31.17, "data_quality_score": 1.0,
        "growth_score": 15.5, "profitability_score": 10.2,
        "valuation_score": 0.0, "market_score": 5.5,
        "ranks": {
            "SalesGrowthRank": 0.5, "SalesGrowth3MRank": 0.5,
            "RevenueGrowthRank": 0.3333333333333333,
            "OperatingProfitGrowthRank": 0.5,
            "NetProfitGrowthRank": 0.3333333333333333,
            "OperatingMarginRank": 0.3333333333333333,
            "NetMarginRank": 0.3333333333333333, "MarginTrendRank": 0.5,
            "ROERank": 0.3333333333333333,
            "InterestCoverageRank": 0.3333333333333333,
            "CashConversionRank": 0.5, "EarningsQualityRank": 0.5,
            "PERank": 0.0, "PSRank": 0.33333333333333337,
            "PBRank": 0.6666666666666667, "LiquidityRank": 0.5,
            "LeverageRank": 0.33333333333333337,
            "CurrentRatioRank": 0.6666666666666666, "StabilityRank": 0.5,
            "LowVolatilityRank": 0.5, "MomentumRank": 0.5,
        },
    },
}


# ----------------------------------------------------------------------------
# Tests — engine output vs frozen GOLDEN literals
# ----------------------------------------------------------------------------

import math  # noqa: E402
import pytest  # noqa: E402

_TOL = 1e-9


def _approx(got, want, msg=""):
    assert got == pytest.approx(want, abs=_TOL), f"{msg}: got {got!r}, golden {want!r}"


def test_score_version_and_total_weight_are_frozen():
    """Pin the served version string and the 89-total weight prototype.

    The 89 total (UI shows /100) is a KNOWN V1 defect; it is documented here,
    NOT fixed in this phase. Any change to any weight trips this test.
    """
    assert CM.SCORE_VERSION == "canonical-v1-dev"
    assert len(CM.BASELINE_WEIGHTS_V37) == 21
    assert sum(CM.BASELINE_WEIGHTS_V37.values()) == 89, (
        "BASELINE_WEIGHTS_V37 total changed from 89 — V1 behavior must stay "
        "frozen while V2 is developed in parallel")


def test_golden_scores_match_current_engine():
    out = _run(_golden_engine())
    assert set(out) == set(GOLDEN)
    for sym, golden in GOLDEN.items():
        for f in SCORE_FIELDS:
            _approx(out[sym][f], golden[f], f"{sym}.{f}")


def test_golden_rank_percentiles_match_current_engine():
    out = _run(_golden_engine())
    for sym, golden in GOLDEN.items():
        assert set(out[sym]["ranks"]) == set(golden["ranks"])
        for f, want in golden["ranks"].items():
            _approx(out[sym]["ranks"][f], want, f"{sym}.{f}")


def test_missing_data_earns_neutral_points_v1_behavior():
    """Known V1 defect, pinned as-is: a missing factor still earns
    weight x 0.30 (the neutral percentile), so data-poor companies keep
    scoring. Valuation/liquidity are the exceptions (neutral 0.00)."""
    p = GOLDEN["PARTIAL"]["ranks"]
    assert p["SalesGrowthRank"] == 0.30        # missing monthly sales -> 0.30
    assert p["MarginTrendRank"] == 0.30        # missing -> 0.30
    assert p["EarningsQualityRank"] == 0.50    # InterestCoverage/EarnQ neutral is 0.50
    assert p["LiquidityRank"] == 0.00          # liquidity neutral is 0.00
    assert p["PERank"] == 0.00                 # missing PE -> invalid sentinel -> 0.0
    # missing inputs still produced positive growth/profitability points:
    assert GOLDEN["PARTIAL"]["growth_score"] == 16.3
    assert GOLDEN["PARTIAL"]["profitability_score"] == 14.8
    # ...but valuation was wiped out (all legs missing + vp -8 penalty):
    assert GOLDEN["PARTIAL"]["valuation_score"] == 0.0


def test_loss_maker_penalties_bake_categories_to_zero():
    """Known V1 behavior, pinned: penalties are subtracted INSIDE category
    scores (never reported separately), and this loss-maker's gp/pp/vp
    penalties zero every category — quant_score 0.0 despite DQ = 1.0 and
    despite holding the best P/S of the cross-section (PSRank 1.0)."""
    loss = GOLDEN["LOSS"]
    assert loss["data_quality_score"] == 1.0
    assert loss["ranks"]["PSRank"] == 1.0
    for f in ("growth_score", "profitability_score", "valuation_score", "market_score"):
        assert loss[f] == 0.0, f
    assert loss["quant_score"] == 0.0


def test_invalid_pe_isolated_from_ps_pb():
    """P/E above the 60 cap invalidates ONLY the PE leg: PERank 0.0 plus the
    vp -8 penalty zero the valuation category, while the same company's
    P/S and P/B stay normally ranked."""
    b = GOLDEN["BADPE"]
    assert b["ranks"]["PERank"] == 0.0
    assert b["ranks"]["PSRank"] == pytest.approx(0.33333333333333337, abs=_TOL)
    assert b["ranks"]["PBRank"] == pytest.approx(0.6666666666666667, abs=_TOL)
    assert b["valuation_score"] == 0.0
    assert b["growth_score"] == 15.5 and b["profitability_score"] == 10.2


def test_quant_is_dq_times_category_sum():
    """The V1 contract: quant_score = DQ x (growth + prof + val + mkt), with
    DQ MULTIPLIED INTO the score (V4+ design drops this — this test pins V1).
    Tolerance covers the engine rounding each category to 1 decimal."""
    for sym, g in GOLDEN.items():
        s = g["growth_score"] + g["profitability_score"] + g["valuation_score"] + g["market_score"]
        want = g["data_quality_score"] * s
        assert g["quant_score"] == pytest.approx(want, abs=0.25), sym


def test_dq_multiplier_scales_quant_isolated():
    """Two IDENTICAL companies, only price coverage differs: identical
    category scores (all ranks tie), DQ 1.0 vs 0.85, quant scales by DQ."""
    pair = _run(_dq_pair_engine())
    a, b = pair["DQFULL"], pair["DQNOPX"]
    assert a["data_quality_score"] == 1.0
    assert b["data_quality_score"] == 0.65   # 0.30 fin + 0.20 monthly + 0.15 fresh-fin
    for f in ("growth_score", "profitability_score", "valuation_score", "market_score"):
        assert a[f] == b[f], f
    assert b["quant_score"] == pytest.approx(0.65 * a["quant_score"], abs=0.009)


def test_golden_engine_deterministic():
    """Same fixture -> byte-identical scores across runs (no hidden state)."""
    assert _run(_golden_engine()) == _run(_golden_engine())

