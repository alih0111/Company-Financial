"""Score v2 cross-sectional normalization tests (step 2-B-2) — pure, no DB.

Covers normalize_q_cross_section() for the four in-scope Q factors: the
correct comparison population (valid values only, families never mixed),
V4-reused midrank percentiles, direction handling, winsorization (P1/P99
with the min-sample guard, post-clip tie determinism), the three-zone
small-sector policy, insufficient_peers, the composite blend contract
(step 2-B-3-B: factor_blend_score for general-family composites,
pending_blend preserved for specialized families), both PIT policies
(exploratory vs historical_strict) and determinism. All inputs are fixed
synthetic dicts; no database, no engine.

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2_normalize.py -q
"""

from __future__ import annotations

import ast
import copy
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
import score_v2_normalize as SN  # noqa: E402
import score_v2_raw as SR  # noqa: E402

# small-population policy for tests that exercise the ranking math itself
SMALL = SN.RankPolicy(family_min_n=3, winsor_min_n=4)


# ---------------------------------------------------------------------------
# Synthetic Engine.compute()-shaped metrics (fixed, deterministic)
# ---------------------------------------------------------------------------
def company_metrics(**over) -> dict:
    m = {
        "revenue_ttm": 1000.0,
        "net_profit_ttm": 100.0,
        "operating_profit_ttm": 150.0,
        "ocf_ttm": 90.0,
        "debt_ratio": 0.4,
    }
    m.update(over)
    return m


def build_raw(mets: dict, **kw) -> dict:
    return SR.build_q_raw(mets, **kw)


def general_meta(cids, industry="Metals") -> dict:
    return {cid: {"model_family": "general", "industry": industry}
            for cid in cids}


def cash_recs(out, company_ids=None) -> dict:
    recs = {r["company_id"]: r for r in out["records"]
            if r["factor_id"] == "cash_conversion"
            and r["component_id"] is None}
    if company_ids is not None:
        assert set(recs) == set(company_ids)
    return recs


# ---------------------------------------------------------------------------
# 1. Basic ranking (spec scenario 1)
# ---------------------------------------------------------------------------
def test_five_companies_ranked_with_custom_policy():
    # Five companies, distinct cash conversion, ranked under a small-sample
    # policy override: exact V4 midrank values, higher is better.
    vals = {"A": 0.1, "B": 0.3, "C": 0.5, "D": 0.7, "E": 0.9}
    mets = {cid: company_metrics(ocf_ttm=v * 100.0) for cid, v in vals.items()}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets),
                                       policy=SMALL)
    recs = cash_recs(out, vals)
    expected = {"A": 0.0, "B": 0.25, "C": 0.5, "D": 0.75, "E": 1.0}
    for cid, pct in expected.items():
        r = recs[cid]
        assert r["percentile_market_family"] == pytest.approx(pct)
        assert r["direction"] == "higher"
        assert r["normalization_status"] == "ranked"
        assert r["n_valid_market_family"] == 5
        # one sector of exactly 5 -> percentile computed, weight 0
        assert r["percentile_sector"] == pytest.approx(pct)
        assert r["effective_sector_weight"] == 0.0
        assert r["percentile_combined"] == pytest.approx(pct)
        assert 0.0 <= r["percentile_combined"] <= 1.0


# ---------------------------------------------------------------------------
# 2. Direction (spec scenario 2 + §6 directions read from config)
# ---------------------------------------------------------------------------
def test_leverage_lower_is_better_direction():
    drs = [0.05 + 0.08 * i for i in range(12)]
    mets = {f"C{i:02d}": company_metrics(debt_ratio=dr)
            for i, dr in enumerate(drs)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = {r["company_id"]: r for r in out["records"]
            if r["factor_id"] == "leverage"}
    assert len(recs) == 12
    best = min(recs.values(), key=lambda r: r["raw_value"])
    worst = max(recs.values(), key=lambda r: r["raw_value"])
    assert best["raw_value"] == pytest.approx(0.05)
    assert best["percentile_market_family"] == pytest.approx(1.0)
    assert worst["raw_value"] == pytest.approx(0.93)
    assert worst["percentile_market_family"] == pytest.approx(0.0)
    # monotonic: higher leverage -> strictly lower percentile
    ordered = sorted(recs.values(), key=lambda r: r["raw_value"])
    pcts = [r["percentile_market_family"] for r in ordered]
    assert pcts == sorted(pcts, reverse=True)
    assert all(r["direction"] == "lower" for r in recs.values())


def test_directions_read_from_config_registry():
    mets = {f"C{i:02d}": company_metrics(net_profit_ttm=80.0 + 10.0 * i,
                                         operating_profit_ttm=120.0 + 10.0 * i,
                                         ocf_ttm=40.0 + 5.0 * i,
                                         debt_ratio=0.2 + 0.05 * i)
            for i in range(11)}
    bases = {cid: {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}
             for cid in mets}
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    assert out["records"]
    for r in out["records"]:
        assert r["direction"] == CFG.V2_QVT_FACTORS[r["factor_id"]]["direction"]
    lows = {r["factor_id"] for r in out["records"] if r["direction"] == "lower"}
    assert lows == {"leverage"}


# ---------------------------------------------------------------------------
# 3. Ties / midrank (spec scenario 3)
# ---------------------------------------------------------------------------
def test_ties_share_identical_midrank_percentile():
    vals = [0.1, 0.2, 0.3, 0.4, 0.5, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=v * 100.0)
            for i, v in enumerate(vals)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = cash_recs(out)
    tied = [r for r in recs.values() if r["raw_value"] == pytest.approx(0.5)]
    assert len(tied) == 2
    # ascending positions 4,5 among 12: (2*4 + 1) / (2*11)
    assert tied[0]["percentile_market_family"] == \
        tied[1]["percentile_market_family"]
    assert tied[0]["percentile_market_family"] == pytest.approx(9.0 / 22.0)


# ---------------------------------------------------------------------------
# 4. Real zero vs missing (spec scenario 4)
# ---------------------------------------------------------------------------
def test_real_zero_ranks_and_missing_stays_out():
    mets = {f"C{i:02d}": company_metrics(debt_ratio=0.3 + 0.05 * i)
            for i in range(10)}
    mets["ZERO"] = company_metrics(debt_ratio=0.0)       # real zero
    no_dr = company_metrics()
    del no_dr["debt_ratio"]
    mets["GAP"] = no_dr                                   # missing input
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = {r["company_id"]: r for r in out["records"]
            if r["factor_id"] == "leverage"}
    assert "ZERO" in recs and "GAP" not in recs
    z = recs["ZERO"]
    assert z["raw_value"] == 0.0
    assert z["normalized_input"] == 0.0
    assert z["percentile_market_family"] == pytest.approx(1.0)  # best leverage
    assert z["normalization_status"] == "ranked"
    pop = out["populations"]["leverage"]
    assert pop["excluded"] == {"missing": 1}
    assert pop["families"]["general"]["n_valid"] == 11


# ---------------------------------------------------------------------------
# 5. Population hygiene: invalid / not_applicable / not_implemented
#    (spec scenario 5)
# ---------------------------------------------------------------------------
def test_invalid_not_applicable_not_implemented_excluded():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=50.0 + 4.0 * i)
            for i in range(10)}
    mets["BAD"] = company_metrics(ocf_ttm=float("nan"))    # invalid
    mets["LOSS"] = company_metrics(net_profit_ttm=-50.0)   # not_applicable
    raw = build_raw(mets)
    raw["BAD"]["roic"] = SR.not_implemented_record("roic")
    out = SN.normalize_q_cross_section(raw, general_meta(mets))
    recs = cash_recs(out)
    assert "BAD" not in recs and "LOSS" not in recs
    assert len(recs) == 10
    pop = out["populations"]["cash_conversion"]
    assert pop["excluded"] == {"invalid": 1, "not_applicable": 1}
    assert pop["families"]["general"]["n_valid"] == 10
    assert "roic" not in out["populations"]
    assert not [r for r in out["records"] if r["factor_id"] == "roic"]


# ---------------------------------------------------------------------------
# 6. Winsorization (spec scenario 6 + §7)
# ---------------------------------------------------------------------------
def test_winsor_applied_clips_only_above_the_p99_bound():
    # 23 ordinary values + two far outliers; n=25 >= winsor_min_n -> P1/P99
    # bounds estimated. V4's interpolated P99 lands BETWEEN the two largest
    # order statistics (100*0.24 + 200*0.76 = 176), so only the maximum is
    # clipped; raw values are preserved either way.
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=100.0) for i in range(23)}
    mets["HI100"] = company_metrics(ocf_ttm=100.0 * 100.0)   # ratio 100
    mets["HI200"] = company_metrics(ocf_ttm=100.0 * 200.0)   # ratio 200
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = cash_recs(out)
    pop = out["populations"]["cash_conversion"]["families"]["general"]
    assert pop["winsor"]["applied"] is True
    assert pop["winsor"]["n"] == 25
    assert pop["winsor"]["low"] == pytest.approx(1.0)
    assert pop["winsor"]["high"] == pytest.approx(176.0)
    assert recs["HI200"]["raw_value"] == pytest.approx(200.0)       # preserved
    assert recs["HI200"]["normalized_input"] == pytest.approx(176.0)  # clipped
    assert recs["HI100"]["raw_value"] == pytest.approx(100.0)
    assert recs["HI100"]["normalized_input"] == pytest.approx(100.0)  # < P99
    assert recs["HI200"]["percentile_market_family"] == pytest.approx(1.0)
    ordinary = recs["C00"]
    assert ordinary["normalized_input"] == pytest.approx(1.0)
    assert ordinary["percentile_market_family"] == pytest.approx(22.0 / 48.0)


def test_winsor_post_clip_ties_are_deterministic():
    # With configurable quantiles (P5/P95 over n=25) the P95 bound falls
    # INSIDE the data: sorted ratios [1x22, 50, 60, 100] give
    # P95 = 50*0.2 + 60*0.8 = 58, so BOTH 60 and 100 clip to 58 -> a tie
    # CREATED by clipping, ranked deterministically as one midrank value.
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=100.0) for i in range(22)}
    mets["V50"] = company_metrics(ocf_ttm=100.0 * 50.0)
    mets["V60"] = company_metrics(ocf_ttm=100.0 * 60.0)
    mets["V100"] = company_metrics(ocf_ttm=100.0 * 100.0)
    pol = SN.RankPolicy(family_min_n=3, winsor_min_n=20,
                        winsor_low_q=0.05, winsor_high_q=0.95)
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets),
                                       policy=pol)
    recs = cash_recs(out)
    pop = out["populations"]["cash_conversion"]["families"]["general"]
    assert pop["winsor"]["applied"] is True
    assert pop["winsor"]["low"] == pytest.approx(1.0)
    assert pop["winsor"]["high"] == pytest.approx(58.0)
    for cid, raw_v in (("V60", 60.0), ("V100", 100.0)):
        assert recs[cid]["raw_value"] == pytest.approx(raw_v)     # preserved
        assert recs[cid]["normalized_input"] == pytest.approx(58.0)  # clipped
    assert recs["V60"]["percentile_market_family"] == \
        recs["V100"]["percentile_market_family"]
    assert recs["V60"]["percentile_market_family"] == pytest.approx(47.0 / 48.0)
    assert recs["V50"]["normalized_input"] == pytest.approx(50.0)  # < P95
    assert recs["C00"]["percentile_market_family"] == pytest.approx(21.0 / 48.0)


def test_winsor_skipped_below_min_sample():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=100.0) for i in range(14)}
    mets["OUT"] = company_metrics(ocf_ttm=100.0 * 100.0)
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = cash_recs(out)
    assert out["populations"]["cash_conversion"]["families"]["general"][
        "winsor"]["applied"] is False
    assert recs["OUT"]["normalized_input"] == pytest.approx(100.0)
    assert recs["OUT"]["winsor_applied"] is False
    assert recs["OUT"]["percentile_market_family"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 7-9. Small-sector policy (spec scenarios 7, 8, 9)
# ---------------------------------------------------------------------------
def _two_industry_cash_fixture(n_metal: int, n_chem: int):
    mets = {}
    for i in range(n_metal):
        mets[f"M{i:02d}"] = company_metrics(ocf_ttm=30.0 + 5.0 * i)
    for i in range(n_chem):
        mets[f"K{i:02d}"] = company_metrics(ocf_ttm=200.0 + 5.0 * i)
    meta = general_meta(mets, industry="Metals")
    for cid in list(mets)[n_metal:]:
        meta[cid]["industry"] = "Chem"
    return mets, meta


def test_sector_below_five_falls_back_to_family():
    mets, meta = _two_industry_cash_fixture(4, 11)
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    recs = cash_recs(out)
    m = recs["M00"]
    assert m["percentile_sector"] is None
    assert m["null_reasons"]["percentile_sector"] == "sector_too_small"
    assert m["effective_sector_weight"] == 0.0
    assert m["percentile_combined"] == m["percentile_market_family"]
    assert m["peer_group"] == "family:general"
    k = recs["K00"]
    assert k["percentile_sector"] is not None
    assert k["effective_sector_weight"] == pytest.approx(0.26)  # 0.65*6/15
    assert k["percentile_combined"] == pytest.approx(
        0.26 * k["percentile_sector"] + 0.74 * k["percentile_market_family"])
    sectors = out["populations"]["cash_conversion"]["families"]["general"][
        "sectors"]
    assert sectors["family:general|industry:Metals"]["n_valid"] == 4
    assert sectors["family:general|industry:Chem"]["n_valid"] == 11


def test_sector_mid_band_weight_ramps_linearly():
    mets, meta = _two_industry_cash_fixture(12, 3)
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    recs = cash_recs(out)
    assert recs["M00"]["effective_sector_weight"] == \
        pytest.approx(0.65 * 7.0 / 15.0)
    assert recs["K00"]["percentile_sector"] is None          # n=3 < 5
    assert recs["K00"]["effective_sector_weight"] == 0.0


def test_sector_full_weight_at_twenty_and_range_invariant():
    mets, meta = _two_industry_cash_fixture(20, 5)
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    recs = cash_recs(out)
    m = recs["M10"]  # mid-range company, untouched by the P1/P99 clip
    assert m["effective_sector_weight"] == pytest.approx(0.65)
    assert m["peer_group"] == "family:general|industry:Metals"
    assert m["percentile_combined"] == pytest.approx(
        0.65 * m["percentile_sector"] + 0.35 * m["percentile_market_family"])
    # §9 invariant: every percentile stays in [0, 1] across the whole output
    for r in out["records"]:
        for field in ("percentile_market_family", "percentile_sector",
                      "percentile_combined"):
            if r[field] is not None:
                assert 0.0 <= r[field] <= 1.0, (r["company_id"], field)


# ---------------------------------------------------------------------------
# 10. Insufficient family peers (spec scenario 10)
# ---------------------------------------------------------------------------
def test_insufficient_family_peers_yields_no_percentile():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(7)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    assert out["records"]
    for r in out["records"]:
        assert r["normalization_status"] == "insufficient_peers"
        assert r["percentile_market_family"] is None
        assert r["percentile_sector"] is None
        assert r["percentile_combined"] is None
        assert r["null_reasons"]["percentile_combined"] == "insufficient_peers"


# ---------------------------------------------------------------------------
# 11. Families never mix (spec scenario 11)
# ---------------------------------------------------------------------------
def test_bank_and_general_never_share_a_population():
    mets = {f"G{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(11)}
    mets["B1"] = company_metrics(ocf_ttm=500.0)
    mets["B2"] = company_metrics(ocf_ttm=600.0)
    meta = general_meta(mets, industry="Universal")
    meta["B1"]["model_family"] = "bank"
    meta["B2"]["model_family"] = "bank"
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    recs = cash_recs(out)
    assert recs["G00"]["n_valid_market_family"] == 11
    assert recs["G00"]["normalization_status"] == "ranked"
    # the two banks rank only against each other -> insufficient peers,
    # even though 13 companies share the same industry label
    assert recs["B1"]["n_valid_market_family"] == 2
    assert recs["B1"]["normalization_status"] == "insufficient_peers"
    fams = out["populations"]["cash_conversion"]["families"]
    assert fams["general"]["n_valid"] == 11
    assert fams["bank"]["n_valid"] == 2
    assert fams["general"]["sectors"][
        "family:general|industry:Universal"]["n_valid"] == 11
    assert fams["bank"]["sectors"][
        "family:bank|industry:Universal"]["n_valid"] == 2


# ---------------------------------------------------------------------------
# 12. Composite factors: components rank separately (spec scenario 12,
#     updated by step 2-B-3-B — general-family composites now blend, so the
#     pending_blend status itself is asserted for specialized families in
#     the 2-B-3-B section below)
# ---------------------------------------------------------------------------
def test_composite_pending_blend_components_ranked_separately():
    mets = {f"C{i:02d}": company_metrics(net_profit_ttm=80.0 + 10.0 * i,
                                         operating_profit_ttm=120.0 + 10.0 * i,
                                         ocf_ttm=40.0 + 5.0 * i,
                                         debt_ratio=0.2 + 0.05 * i)
            for i in range(11)}
    bases = {cid: {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}
             for cid in mets}
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    for fid in ("margins", "earnings_growth"):
        assert not [r for r in out["records"]
                    if r["factor_id"] == fid and r["component_id"] is None]
    comp_ids = {r["component_id"] for r in out["records"]
                if r["factor_id"] in ("margins", "earnings_growth")}
    assert comp_ids == {"operating_margin_pct", "net_margin_pct",
                        "net_profit_growth_pct", "operating_profit_growth_pct"}
    summary = out["factors"]["C05"]["margins"]
    assert summary["normalization_status"] == "blended"   # 2-B-3-B contract
    assert "percentile_combined" not in summary   # a score, never a percentile
    assert 0.0 <= summary["factor_blend_score"] <= 1.0
    assert all(d["normalization_status"] == "ranked"
               for d in summary["components"].values())
    # singles carry their rank at factor level
    single = out["factors"]["C05"]["cash_conversion"]
    assert single["composite"] is False
    assert single["normalization_status"] == "ranked"
    assert 0.0 <= single["percentile_combined"] <= 1.0


# ---------------------------------------------------------------------------
# 13. Anomaly warning without exclusion (spec scenario 13)
# ---------------------------------------------------------------------------
def test_anomaly_value_still_ranked_with_warnings():
    mets = {f"C{i:02d}": company_metrics(debt_ratio=0.2 + 0.05 * i)
            for i in range(11)}
    mets["DIST"] = company_metrics(debt_ratio=2.5)
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = {r["company_id"]: r for r in out["records"]
            if r["factor_id"] == "leverage"}
    d = recs["DIST"]
    assert d["normalization_status"] == "ranked"
    assert d["percentile_market_family"] == pytest.approx(0.0)  # worst leverage
    assert d["raw_value"] == pytest.approx(2.5)
    text = " ".join(d["warnings"])
    assert "negative_equity" in text
    assert "financial_distress_or_anomaly" in text


# ---------------------------------------------------------------------------
# 14. Look-ahead data never ranks (spec scenario 14)
# ---------------------------------------------------------------------------
def test_data_published_after_as_of_excluded():
    mets = {f"C{i:02d}": company_metrics() for i in range(11)}
    mets["LATE"] = company_metrics()
    prov = {"LATE": {"available_at": dt.datetime(2026, 12, 1),
                     "source_ref": "codal:late"}}
    as_of = dt.datetime(2026, 6, 30)
    raw = build_raw(mets, provenance=prov, as_of=as_of)
    assert raw["LATE"]["margins"]["status"] == "invalid"  # raw-layer look-ahead
    out = SN.normalize_q_cross_section(raw, general_meta(mets))
    assert not [r for r in out["records"]
                if r["company_id"] == "LATE" and r["factor_id"] == "margins"]
    pop = out["populations"]["margins.operating_margin_pct"]
    assert pop["excluded"] == {"invalid": 1}
    assert pop["families"]["general"]["n_valid"] == 11


# ---------------------------------------------------------------------------
# 15. historical_strict vs current_exploratory (spec scenarios 15 + §8)
# ---------------------------------------------------------------------------
_VERIFIED_TS = dt.datetime(2026, 1, 15)
_STRICT_AS_OF = dt.datetime(2026, 6, 30)


def _strict_fixture():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(11)}
    mets["NOPROV"] = company_metrics(ocf_ttm=999.0)
    # source_period is REQUIRED for cash_conversion: CFO and net profit must
    # be provably same-window before the raw layer verifies PIT at all.
    prov = {cid: {"available_at": _VERIFIED_TS, "source_ref": f"codal:{cid}",
                  "source_period": "1404-12"}
            for cid in mets}
    prov["NOPROV"] = {"available_at": _VERIFIED_TS}  # bare timestamp
    return mets, prov


def test_historical_strict_ranks_only_verified_and_excludes_peers():
    mets, prov = _strict_fixture()
    raw = build_raw(mets, provenance=prov)
    out = SN.normalize_q_cross_section(
        raw, general_meta(mets), as_of=_STRICT_AS_OF,
        pit_policy=SN.PIT_HISTORICAL_STRICT)
    recs = cash_recs(out)
    assert recs["NOPROV"]["normalization_status"] == "not_ranked_pit_strict"
    assert recs["NOPROV"]["percentile_market_family"] is None
    assert recs["NOPROV"]["percentile_combined"] is None
    assert (recs["NOPROV"]["null_reasons"]["percentile_combined"]
            == "pit_not_verified_historical_strict")
    assert recs["NOPROV"]["pit_status"] == SR.PIT_UNVERIFIED
    # the unverified company is ALSO kept out of the peer population
    assert recs["C00"]["n_valid_market_family"] == 11
    assert recs["C00"]["normalization_status"] == "ranked"
    pop = out["populations"]["cash_conversion"]
    assert pop["excluded_pit_strict"] == 1
    assert pop["families"]["general"]["n_valid"] == 11


def test_current_exploratory_ranks_unverified_with_warning():
    mets, prov = _strict_fixture()
    raw = build_raw(mets, provenance=prov)
    out = SN.normalize_q_cross_section(raw, general_meta(mets))
    recs = cash_recs(out)
    assert recs["NOPROV"]["normalization_status"] == "ranked"
    assert recs["NOPROV"]["pit_status"] == SR.PIT_UNVERIFIED
    assert any(w.startswith("pit_unverified_exploratory")
               for w in recs["NOPROV"]["warnings"])
    assert recs["C00"]["n_valid_market_family"] == 12
    assert not any(w.startswith("pit_unverified_exploratory")
                   for w in recs["C00"]["warnings"])


def test_historical_strict_requires_as_of():
    mets, prov = _strict_fixture()
    with pytest.raises(ValueError):
        SN.normalize_q_cross_section(build_raw(mets), general_meta(mets),
                                     pit_policy=SN.PIT_HISTORICAL_STRICT)


# ---------------------------------------------------------------------------
# 16. Determinism (spec scenario 16)
# ---------------------------------------------------------------------------
def test_output_identical_regardless_of_company_order():
    mets = {f"C{i:02d}": company_metrics(net_profit_ttm=80.0 + 10.0 * i,
                                         operating_profit_ttm=120.0 + 10.0 * i,
                                         ocf_ttm=40.0 + 5.0 * i,
                                         debt_ratio=0.2 + 0.05 * i)
            for i in range(11)}
    mets["DIST"] = company_metrics(debt_ratio=2.5)
    bases = {cid: {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}
             for cid in mets}
    raw = build_raw(mets, prev_bases=bases)
    meta = general_meta(mets, industry="Metals")
    meta["DIST"]["industry"] = "Chem"
    out1 = SN.normalize_q_cross_section(raw, meta)
    out2 = SN.normalize_q_cross_section(
        dict(reversed(list(raw.items()))),
        dict(reversed(list(meta.items()))))
    assert out1 == out2


# ---------------------------------------------------------------------------
# 17. No database dependency (spec scenario 17)
# ---------------------------------------------------------------------------
def _module_top_level_imports(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_no_database_dependency(monkeypatch):
    # white-box: the module's own imports stay within stdlib + the sanctioned
    # v2/v4 modules (score_v4 is the reused percentile engine, exactly like
    # score_v2.py; math is the stdlib finite guard added in step 2-B-2.1);
    # black-box: a full ranking runs with no DB env configured.
    mods = _module_top_level_imports(PKG / "score_v2_normalize.py")
    allowed = {"__future__", "dataclasses", "math", "score_v2_config",
               "score_v2_raw", "score_v4"}
    assert mods <= allowed, mods - allowed
    monkeypatch.delenv("CDF_PILOT_DB", raising=False)
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(11)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    assert cash_recs(out)["C00"]["normalization_status"] == "ranked"


# ---------------------------------------------------------------------------
# Input validation + output contract
# ---------------------------------------------------------------------------
def test_unknown_industry_warns_and_joins_no_sector():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(11)}
    mets["UNK"] = company_metrics(ocf_ttm=900.0)
    meta = general_meta(mets, industry="Metals")
    meta["UNK"]["industry"] = None
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    recs = cash_recs(out)
    u = recs["UNK"]
    assert u["normalization_status"] == "ranked"
    assert any(w.startswith("industry_unknown") for w in u["warnings"])
    assert u["percentile_sector"] is None
    assert u["null_reasons"]["percentile_sector"] == "industry_unknown"
    assert u["n_valid_sector"] is None
    assert u["percentile_combined"] == u["percentile_market_family"]
    # the unknown-industry company never leaks into the Metals sector pool
    assert recs["C00"]["n_valid_sector"] == 11
    sectors = out["populations"]["cash_conversion"]["families"]["general"][
        "sectors"]
    assert set(sectors) == {"family:general|industry:Metals"}


def test_meta_validation_errors_are_loud():
    mets = {"C1": company_metrics()}
    raw = build_raw(mets)
    with pytest.raises(ValueError):
        SN.normalize_q_cross_section(raw, {"C1": {"model_family": "hedge fund",
                                                  "industry": "X"}})
    with pytest.raises(ValueError):
        SN.normalize_q_cross_section(raw, {})  # no meta for C1
    with pytest.raises(ValueError):
        SN.normalize_q_cross_section(raw, {"C1": {"industry": "X"}})


def test_policy_is_configurable_same_data_two_outcomes():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(5)}
    raw = build_raw(mets)
    meta = general_meta(mets)
    strict_default = SN.normalize_q_cross_section(raw, meta)
    assert (cash_recs(strict_default)["C00"]["normalization_status"]
            == "insufficient_peers")  # 5 < default family_min_n 10
    relaxed = SN.normalize_q_cross_section(raw, meta, policy=SMALL)
    assert cash_recs(relaxed)["C00"]["normalization_status"] == "ranked"
    assert relaxed["policy"]["family_min_n"] == 3
    assert strict_default["policy"]["family_min_n"] == 10


def test_record_contract_fields_present():
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(11)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    required = {"company_id", "factor_id", "component_id", "raw_value",
                "normalized_input", "percentile_market_family",
                "percentile_sector", "percentile_combined", "direction",
                "peer_group", "n_valid_market_family", "n_valid_sector",
                "effective_sector_weight", "validation_status", "pit_status",
                "warnings", "normalization_status"}
    for r in out["records"]:
        assert required <= set(r), required - set(r)
        assert r["validation_status"] == "valid"
        assert r["peer_group"].startswith("family:")


# ===========================================================================
# Step 2-B-2.1 — audit hardening: boundary sizes, independent numeric
# references, non-finite defense and the cross-layer look-ahead guard.
# ===========================================================================
NOWIN = SN.RankPolicy(family_min_n=3, winsor_min_n=10**6)  # disable winsor


# ---------------------------------------------------------------------------
# §4 sample-size boundaries: sector weight at n = 4/5/9/10/19/20/21
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("n,expected_w", [
    (4, 0.0),
    (5, 0.0),
    (9, 0.65 * 4.0 / 15.0),
    (10, 0.65 * 5.0 / 15.0),
    (19, 0.65 * 14.0 / 15.0),
    (20, 0.65),
    (21, 0.65),
])
def test_sector_weight_boundaries_n_4_to_21(n, expected_w):
    # n sector peers in "Metals" plus fillers in "Chem" keep the FAMILY
    # population >= 10, so only the sector-size rule moves the weight.
    mets, meta = _two_industry_cash_fixture(n, max(13 - n, 3))
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    r = cash_recs(out)["M00"]
    assert r["n_valid_sector"] == n
    assert r["effective_sector_weight"] == pytest.approx(expected_w)
    if n < 5:
        assert r["percentile_sector"] is None
        assert r["null_reasons"]["percentile_sector"] == "sector_too_small"
    else:
        assert r["percentile_sector"] is not None
        assert r["percentile_combined"] == pytest.approx(
            expected_w * r["percentile_sector"]
            + (1.0 - expected_w) * r["percentile_market_family"])


# ---------------------------------------------------------------------------
# §4 family_min_n boundary: 9 peers insufficient, 10 ranked
# ---------------------------------------------------------------------------
def test_family_min_n_boundary_9_vs_10():
    for n, expected in ((9, "insufficient_peers"), (10, "ranked")):
        mets = {f"C{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
                for i in range(n)}
        out = SN.normalize_q_cross_section(build_raw(mets),
                                           general_meta(mets))
        r = cash_recs(out)["C00"]
        assert r["normalization_status"] == expected, n
        if expected == "insufficient_peers":
            assert r["percentile_combined"] is None
            assert r["null_reasons"]["percentile_combined"] == \
                "insufficient_peers"
        else:
            assert 0.0 <= r["percentile_combined"] <= 1.0


# ---------------------------------------------------------------------------
# §4 midrank verified against an independent reference implementation
#    (mean of the tied 0-based ranks / (n-1)) — NOT by calling S4.midrank
# ---------------------------------------------------------------------------
def test_midrank_matches_independent_reference():
    vals = [3.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0, 2.0]   # ties on 1, 2 and 3
    mets = {f"C{i}": company_metrics(ocf_ttm=v * 20.0)
            for i, v in enumerate(vals)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets),
                                       policy=NOWIN)
    recs = cash_recs(out)
    s = sorted(vals)
    for i, v in enumerate(vals):
        positions = [j for j, x in enumerate(s) if x == v]
        expected = (sum(positions) / len(positions)) / (len(s) - 1)
        assert recs[f"C{i}"]["percentile_market_family"] == \
            pytest.approx(expected), (i, v)

    # same companies, leverage: lower is better -> inverted reference
    drs = [0.2, 0.5, 0.2, 0.8, 0.5, 0.9, 0.1, 0.8]
    mets2 = {f"C{i}": company_metrics(debt_ratio=d)
             for i, d in enumerate(drs)}
    out2 = SN.normalize_q_cross_section(build_raw(mets2), general_meta(mets2),
                                        policy=NOWIN)
    lev = {r["company_id"]: r for r in out2["records"]
           if r["factor_id"] == "leverage"}
    s2 = sorted(drs)
    for i, d in enumerate(drs):
        positions = [j for j, x in enumerate(s2) if x == d]
        p = (sum(positions) / len(positions)) / (len(s2) - 1)
        assert lev[f"C{i}"]["percentile_market_family"] == \
            pytest.approx(1.0 - p), (i, d)


# ---------------------------------------------------------------------------
# §5 pin the one private V4 helper the bounds reuse: linear interpolation
#    between order statistics at q*(n-1)
# ---------------------------------------------------------------------------
def test_v4_percentile_interpolation_characterization():
    p = SN.S4._percentile
    assert p([float(x) for x in range(10)], 0.5) == pytest.approx(4.5)
    assert p([10.0, 20.0], 0.99) == pytest.approx(19.9)   # 10*0.01 + 20*0.99
    assert p([7.0], 0.01) == pytest.approx(7.0)
    # the module's parametric bounds reproduce exactly these numbers
    # (P1: idx 0.09 -> 0*0.91 + 1*0.09;  P99: idx 8.91 -> 8*0.09 + 9*0.91)
    pol = SN.RankPolicy(family_min_n=3, winsor_min_n=10)
    assert SN._winsor_bounds([float(x) for x in range(10)], pol) == \
        pytest.approx((0.09, 8.91))


# ---------------------------------------------------------------------------
# §2/§4 non-finite defense: ratio overflow must never reach percentiles
# ---------------------------------------------------------------------------
def test_non_finite_ratio_overflow_excluded():
    # step 2-B-2.3: the raw layer now closes the overflow hole itself — a
    # ratio of FINITE inputs that computes to +/-inf is invalid
    # (non_finite_result, value None), so normalization receives no
    # eligible value for the overflowing component and the excluded count
    # carries the raw status. The normalization-side finite guard remains
    # untouched as the independent second defense (exercised on its own in
    # the next test).
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=100.0) for i in range(22)}
    mets["OVF"] = company_metrics(revenue_ttm=1e-300,
                                  operating_profit_ttm=1e308,
                                  net_profit_ttm=100.0)
    raw = build_raw(mets)
    part = raw["OVF"]["margins"]["components"]["operating_margin_pct"]
    assert part["status"] == "invalid"
    assert part["value"] is None
    assert "non_finite_result" in part["reason"]
    out = SN.normalize_q_cross_section(raw, general_meta(mets))
    assert not [r for r in out["records"]
                if r["company_id"] == "OVF"
                and r["component_id"] == "operating_margin_pct"]
    pop = out["populations"]["margins.operating_margin_pct"]
    assert pop["excluded"] == {"invalid": 1}
    assert pop["families"]["general"]["n_valid"] == 22
    w = pop["families"]["general"]["winsor"]
    assert (not w["applied"]) or (math.isfinite(w["low"])
                                  and math.isfinite(w["high"]))
    # the finite sibling component still ranks the company normally
    nm = [r for r in out["records"] if r["company_id"] == "OVF"
          and r["component_id"] == "net_margin_pct"]
    assert len(nm) == 1 and nm[0]["normalization_status"] == "ranked"
    # factor rollup: the raw-invalid component is NAMED, never a silent crash
    comp = out["factors"]["OVF"]["margins"]["components"]
    assert comp["operating_margin_pct"]["normalization_status"] == \
        "not_ranked_raw_invalid"
    assert comp["operating_margin_pct"]["percentile_combined"] is None
    assert comp["net_margin_pct"]["normalization_status"] == "ranked"
    assert all(math.isfinite(r["raw_value"]) for r in out["records"])


# ---------------------------------------------------------------------------
# §1b second defense: the normalization finite guard stands on its own
# (step 2-B-2.3) — a hypothetical raw regression or a new consumer handing
# this layer a "valid" +/-inf is still refused, independently of Raw.
# ---------------------------------------------------------------------------
def test_normalization_finite_guard_is_independent_second_defense():
    # Deliberately VIOLATE the raw contract: inject status "valid" with
    # value +inf directly into a deep copy of the raw structure (the part
    # schema the collector reads — pit_status/warnings/... — is already
    # complete on every assembled part) and normalize WITHOUT re-running
    # build_q_raw. The guard must exclude the value under its own
    # "non_finite" key and leave the healthy population, its winsor bounds
    # and every healthy rank untouched, with no caller-side mutation and
    # no stray exception.
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=100.0) for i in range(22)}
    mets["OVF"] = company_metrics(revenue_ttm=1e-300,
                                  operating_profit_ttm=1e308,
                                  net_profit_ttm=100.0)
    raw = build_raw(mets)
    pristine = copy.deepcopy(raw)
    baseline = SN.normalize_q_cross_section(raw, general_meta(mets))
    assert raw == pristine        # the layer never mutates its caller's input
    assert "non_finite" not in baseline["populations"][
        "margins.operating_margin_pct"]["excluded"]

    injected = copy.deepcopy(raw)
    part = injected["OVF"]["margins"]["components"]["operating_margin_pct"]
    part.update({"status": "valid", "value": float("inf")})
    snapshot = copy.deepcopy(injected)          # caller-side reference state

    out = SN.normalize_q_cross_section(injected, general_meta(mets))

    # the caller's input structure is never mutated by this layer
    assert injected == snapshot

    # the guard's own exclusion key fired for exactly this one value
    pop = out["populations"]["margins.operating_margin_pct"]
    base_pop = baseline["populations"]["margins.operating_margin_pct"]
    assert pop["excluded"] == {"non_finite": 1}
    assert base_pop["excluded"] == {"invalid": 1}
    assert pop["families"]["general"]["n_valid"] == 22
    assert pop["families"]["general"]["n_valid"] == \
        base_pop["families"]["general"]["n_valid"]
    w = pop["families"]["general"]["winsor"]
    assert (not w["applied"]) or (math.isfinite(w["low"])
                                  and math.isfinite(w["high"]))

    # no record may exist for the injected value; the factor rollup names
    # the guard status, never a fabricated percentile
    assert not [r for r in out["records"]
                if r["company_id"] == "OVF"
                and r["component_id"] == "operating_margin_pct"]
    comp = out["factors"]["OVF"]["margins"]["components"]
    assert comp["operating_margin_pct"]["normalization_status"] == \
        "not_ranked_non_finite"
    assert comp["operating_margin_pct"]["percentile_combined"] is None
    # the healthy sibling component still ranks normally
    assert comp["net_margin_pct"]["normalization_status"] == "ranked"

    # every healthy company keeps its exact baseline percentiles
    def _healthy_pct(res):
        return {(r["company_id"], r["factor_id"], r["component_id"]):
                (r["percentile_market_family"], r["percentile_sector"],
                 r["percentile_combined"], r["n_valid_market_family"])
                for r in res["records"] if r["company_id"] != "OVF"}
    assert _healthy_pct(out) == _healthy_pct(baseline)


# ---------------------------------------------------------------------------
# §2 look-ahead across the layer boundary (historical_strict headline test)
# ---------------------------------------------------------------------------
def _late_company_fixture():
    """21 verified companies + one company whose attributable provenance is
    published AFTER as_of, built through a raw layer WITHOUT as_of — the
    raw layer marks it 'verified' (its own PIT-vs-as_of check never fired)."""
    mets = {f"C{i:02d}": company_metrics(ocf_ttm=100.0 + 7.0 * i)
            for i in range(21)}
    mets["LATE"] = company_metrics(ocf_ttm=1600.0)     # mid-high ratio 16
    prov = {cid: {"available_at": _VERIFIED_TS, "source_ref": f"codal:{cid}",
                  "source_period": "1404-12"} for cid in mets}
    prov["LATE"]["available_at"] = dt.datetime(2026, 8, 1)   # > as_of
    meta = general_meta(mets, industry="FOL")
    return mets, prov, meta


def test_future_publication_never_shifts_strict_ranks():
    mets, prov, meta = _late_company_fixture()
    raw = build_raw(mets, provenance=prov)             # no as_of at raw
    assert raw["LATE"]["cash_conversion"]["pit_status"] == SR.PIT_VERIFIED

    with_late = SN.normalize_q_cross_section(
        raw, meta, as_of=_STRICT_AS_OF,
        pit_policy=SN.PIT_HISTORICAL_STRICT)
    keep = [c for c in mets if c != "LATE"]
    without = SN.normalize_q_cross_section(
        build_raw({c: mets[c] for c in keep},
                  provenance={c: prov[c] for c in keep}),
        general_meta(keep, industry="FOL"),
        as_of=_STRICT_AS_OF, pit_policy=SN.PIT_HISTORICAL_STRICT)

    late = cash_recs(with_late)["LATE"]
    assert late["normalization_status"] == "not_ranked_after_as_of"
    assert late["percentile_market_family"] is None
    assert late["percentile_sector"] is None
    assert late["percentile_combined"] is None
    assert late["null_reasons"]["percentile_combined"] == "published_after_as_of"
    assert late["raw_value"] == pytest.approx(16.0)   # value kept, rank refused

    # adding the future company moved NOTHING for the allowed companies:
    # not any percentile, not any peer count, not the winsor bounds
    a, b = cash_recs(with_late), cash_recs(without)
    for cid in b:
        for f in ("percentile_market_family", "percentile_sector",
                  "percentile_combined"):
            assert a[cid][f] == pytest.approx(b[cid][f]), (cid, f)
        assert a[cid]["n_valid_market_family"] == \
            b[cid]["n_valid_market_family"]
    pa = with_late["populations"]["cash_conversion"]["families"]["general"]
    pb = without["populations"]["cash_conversion"]["families"]["general"]
    assert pa["winsor"] == pb["winsor"]
    assert pa["winsor"]["applied"] is True      # bounds exist AND match
    assert with_late["populations"]["cash_conversion"][
        "excluded_after_as_of"] == 1
    assert without["populations"]["cash_conversion"].get(
        "excluded_after_as_of", 0) == 0


def test_future_publication_excluded_in_exploratory_with_as_of():
    mets, prov, meta = _late_company_fixture()
    raw = build_raw(mets, provenance=prov)
    out = SN.normalize_q_cross_section(raw, meta, as_of=_STRICT_AS_OF)
    late = cash_recs(out)["LATE"]
    assert late["normalization_status"] == "not_ranked_after_as_of"
    assert late["percentile_combined"] is None
    assert out["populations"]["cash_conversion"]["excluded_after_as_of"] == 1
    # without an as_of the exploratory layer cannot judge publication dates:
    # the guard is silent and the company ranks (documented limitation —
    # callers that care about look-ahead MUST pass as_of)
    out_open = SN.normalize_q_cross_section(raw, meta)
    assert cash_recs(out_open)["LATE"]["normalization_status"] == "ranked"


# ---------------------------------------------------------------------------
# §4 population accounting invariants (one observation per company, counts
# independent per factor/component, family isolation, unknown industry)
# ---------------------------------------------------------------------------
def test_population_accounting_invariants():
    mets = {f"G{i:02d}": company_metrics(ocf_ttm=40.0 + 5.0 * i)
            for i in range(12)}
    del mets["G11"]["ocf_ttm"]                           # cash missing
    mets["LOSS"] = company_metrics(net_profit_ttm=-5.0)  # cash not_applicable
    mets["B1"] = company_metrics(ocf_ttm=500.0)
    mets["B2"] = company_metrics(ocf_ttm=600.0)
    meta = general_meta(mets, industry="Metals")
    for cid in ("G00", "G01", "B1", "B2"):
        meta[cid]["industry"] = "Chem"
    meta["LOSS"]["industry"] = None                      # unknown industry
    for cid in ("B1", "B2"):
        meta[cid]["model_family"] = "bank"
    out = SN.normalize_q_cross_section(build_raw(mets), meta, policy=SMALL)

    # at most ONE observation per company per factor/component
    seen = set()
    for r in out["records"]:
        key = (r["company_id"], r["factor_id"], r["component_id"] or "")
        assert key not in seen, key
        seen.add(key)

    # peer counts are independent per factor: cash loses G11 + LOSS,
    # leverage ranks all 13 general companies
    pops = out["populations"]
    assert pops["cash_conversion"]["families"]["general"]["n_valid"] == 11
    assert pops["leverage"]["families"]["general"]["n_valid"] == 13
    assert pops["cash_conversion"]["excluded"] == {"missing": 1,
                                                   "not_applicable": 1}

    # every declared population re-counts to exactly its own ranked records
    for key, pop in pops.items():
        fid, _, comp = key.partition(".")
        comp_id = comp or None
        for fam, fp in pop["families"].items():
            n = len([r for r in out["records"]
                     if r["factor_id"] == fid
                     and r["component_id"] == comp_id
                     and r["normalization_status"] in ("ranked",
                                                       "insufficient_peers")
                     and r["peer_group"].startswith(f"family:{fam}")])
            assert n == fp["n_valid"], (key, fam)

    # unknown industry joins no sector population but keeps its family rank
    loss = [r for r in out["records"] if r["company_id"] == "LOSS"
            and r["factor_id"] == "leverage"][0]
    assert loss["normalization_status"] == "ranked"
    assert loss["n_valid_sector"] is None
    assert loss["null_reasons"]["percentile_sector"] == "industry_unknown"
    # same industry label, different families: sector keys stay namespaced
    lf = pops["leverage"]["families"]
    assert set(lf["general"]["sectors"]) == {
        "family:general|industry:Metals", "family:general|industry:Chem"}
    assert set(lf["bank"]["sectors"]) == {"family:bank|industry:Chem"}


# ===========================================================================
# Step 2-B-3-B — the approved composite blend contract (general family ONLY):
# factor_blend_score = config-weighted mean of the component
# percentile_combined values, produced ONLY when EVERY component is valid
# AND ranked. All-or-nothing: no partial blend, no weight redistribution, no
# fabricated substitutes, never re-ranked, industry weighting applied
# exactly once. Scenarios below follow the step's mandated test list 1-26.
# ===========================================================================
def _margins_ladder(n: int = 11) -> dict:
    """n companies with strictly increasing operating AND net margins over a
    fixed revenue: both components rank company i at percentile i/(n-1)
    (independent midrank reference: mean position / (n-1))."""
    return {f"C{i:02d}": company_metrics(
        operating_profit_ttm=100.0 + 10.0 * i, net_profit_ttm=50.0 + 5.0 * i)
        for i in range(n)}


def _growth_ladder(n: int = 11):
    """n companies with strictly increasing net AND operating profit growth
    against a fixed prior base, plus the matching prev_bases."""
    mets = {f"C{i:02d}": company_metrics(
        net_profit_ttm=80.0 + 10.0 * i, operating_profit_ttm=120.0 + 10.0 * i)
        for i in range(n)}
    bases = {cid: {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}
             for cid in mets}
    return mets, bases


def _component_records(out, cid: str, fid: str) -> dict:
    return {r["component_id"]: r for r in out["records"]
            if r["company_id"] == cid and r["factor_id"] == fid}


def _blend_of(out, cid: str, fid: str):
    return out["factors"][cid][fid]


# ---------------------------------------------------------------------------
# 1+4. exact weighted output; equal components -> equal contributions
# ---------------------------------------------------------------------------
def test_blend_margins_exact_weighted_score_general():
    mets = _margins_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    for i in range(11):
        cid = f"C{i:02d}"
        p = i / 10.0                      # independent midrank reference
        f = _blend_of(out, cid, "margins")
        assert f["composite"] is True
        assert f["normalization_status"] == "blended"
        assert f["factor_blend_score"] == pytest.approx(0.6 * p + 0.4 * p)
        recs = _component_records(out, cid, "margins")
        assert recs["operating_margin_pct"]["percentile_combined"] == \
            pytest.approx(p)
        assert recs["net_margin_pct"]["percentile_combined"] == \
            pytest.approx(p)
        b = f["blend"]
        assert b["family"] == "general"
        assert b["method"] == SN.BLEND_METHOD
        assert b["weights"] == CFG.COMPOSITE_COMPONENT_WEIGHTS["general"][
            "margins"]
        assert b["coverage_weight"] == pytest.approx(1.0)
        assert b["contributions"]["operating_margin_pct"] == \
            pytest.approx(0.6 * p)
        assert b["contributions"]["net_margin_pct"] == pytest.approx(0.4 * p)
        # explainability echo: populations, raw values, PIT, warnings
        for comp, d in f["components"].items():
            assert d["normalization_status"] == "ranked"
            assert d["raw_status"] == "valid"
            assert d["raw_value"] == pytest.approx(recs[comp]["raw_value"])
            assert d["pit_status"] == recs[comp]["pit_status"]
            assert d["n_valid_market_family"] == 11
            assert d["weight"] == pytest.approx(
                CFG.COMPOSITE_COMPONENT_WEIGHTS["general"]["margins"][comp])
            assert d["contribution"] == pytest.approx(
                b["contributions"][comp])
            assert isinstance(d["warnings"], list)
            assert "available_at" in d


def test_blend_earnings_growth_exact_weighted_general():
    mets, bases = _growth_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    for i in range(11):
        cid = f"C{i:02d}"
        p = i / 10.0
        f = _blend_of(out, cid, "earnings_growth")
        assert f["normalization_status"] == "blended"
        assert f["factor_blend_score"] == pytest.approx(0.5 * p + 0.5 * p)
        assert f["blend"]["weights"] == \
            CFG.COMPOSITE_COMPONENT_WEIGHTS["general"]["earnings_growth"]
        assert f["blend"]["coverage_weight"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. one component high, one low -> the weights actually bite
# ---------------------------------------------------------------------------
def test_blend_one_high_one_low_component():
    mets = {f"C{i:02d}": company_metrics(
        operating_profit_ttm=100.0 + 10.0 * i,     # increasing margins
        net_profit_ttm=200.0 - 5.0 * i)            # decreasing margins
        for i in range(11)}
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    best_op = _blend_of(out, "C10", "margins")
    assert best_op["factor_blend_score"] == pytest.approx(0.6 * 1.0 + 0.4 * 0.0)
    assert best_op["blend"]["contributions"]["operating_margin_pct"] == \
        pytest.approx(0.6)
    assert best_op["blend"]["contributions"]["net_margin_pct"] == \
        pytest.approx(0.0)
    assert _blend_of(out, "C00", "margins")["factor_blend_score"] == \
        pytest.approx(0.6 * 0.0 + 0.4 * 1.0)


# ---------------------------------------------------------------------------
# 4b. both components equal -> score equals the shared percentile
# ---------------------------------------------------------------------------
def test_blend_both_components_equal():
    mets = _margins_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    f = _blend_of(out, "C05", "margins")            # median company
    recs = _component_records(out, "C05", "margins")
    p_op = recs["operating_margin_pct"]["percentile_combined"]
    p_net = recs["net_margin_pct"]["percentile_combined"]
    assert p_op == pytest.approx(0.5)
    assert p_net == pytest.approx(0.5)
    assert f["factor_blend_score"] == pytest.approx(0.5)
    assert f["blend"]["contributions"]["operating_margin_pct"] == \
        pytest.approx(0.3)
    assert f["blend"]["contributions"]["net_margin_pct"] == \
        pytest.approx(0.2)


# ---------------------------------------------------------------------------
# 5+6. real zero and real one percentiles blend to 0.0 / 1.0 (never missing)
# ---------------------------------------------------------------------------
def test_blend_real_zero_percentile_scores_zero_not_missing():
    mets = _margins_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    recs = _component_records(out, "C00", "margins")
    assert recs["operating_margin_pct"]["percentile_combined"] == 0.0
    assert recs["net_margin_pct"]["percentile_combined"] == 0.0
    f = _blend_of(out, "C00", "margins")
    assert f["normalization_status"] == "blended"
    assert f["factor_blend_score"] == 0.0           # a real zero, not None


def test_blend_real_one_percentile_scores_one():
    mets = _margins_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    f = _blend_of(out, "C10", "margins")
    assert f["normalization_status"] == "blended"
    assert f["factor_blend_score"] == 1.0


# ---------------------------------------------------------------------------
# 7+16+17. one missing component: pending_data, score None, weight NEVER
# redistributed — even at coverage_weight 0.6 or 0.4 (and min_axis_coverage
# never licenses a partial blend)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cid,expected_cov", [("OP_ONLY", 0.6),
                                              ("NET_ONLY", 0.4)])
def test_blend_missing_component_blocks_score_and_never_redistributes(
        cid, expected_cov):
    mets = _margins_ladder()
    mets[cid] = company_metrics(
        net_profit_ttm=None if cid == "OP_ONLY" else 100.0,
        operating_profit_ttm=None if cid == "NET_ONLY" else 150.0)
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    f = _blend_of(out, cid, "margins")
    assert f["normalization_status"] == "pending_data"
    assert f["factor_blend_score"] is None
    # diagnostic coverage shows the ranked share of the internal weight ...
    assert f["blend"]["coverage_weight"] == pytest.approx(expected_cov)
    # ... but the config weights stay untouched (no renormalization to the
    # present component) and no score/contributions are produced
    assert f["blend"]["weights"] == \
        CFG.COMPOSITE_COMPONENT_WEIGHTS["general"]["margins"]
    assert "contributions" not in f["blend"]
    missing_comp = ("net_margin_pct" if cid == "OP_ONLY"
                    else "operating_margin_pct")
    assert missing_comp in f["reason"]
    assert "(missing)" in f["reason"]
    ranked_comp = ("operating_margin_pct" if cid == "OP_ONLY"
                   else "net_margin_pct")
    assert f["components"][ranked_comp]["normalization_status"] == "ranked"
    assert f["components"][missing_comp]["normalization_status"] == \
        "not_ranked_raw_missing"
    assert f["components"][missing_comp]["contribution"] is None
    # the ranked component keeps its own diagnostic contribution, but no
    # factor-level score or contributions block is built from it
    rc = f["components"][ranked_comp]
    assert rc["contribution"] == pytest.approx(
        rc["weight"] * rc["percentile_combined"])


# ---------------------------------------------------------------------------
# 8. one invalid component -> unavailable (never repaired into a blend)
# ---------------------------------------------------------------------------
def test_blend_invalid_component_yields_unavailable():
    mets = _margins_ladder()
    mets["BADNET"] = company_metrics(net_profit_ttm=float("nan"))
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    f = _blend_of(out, "BADNET", "margins")
    assert f["normalization_status"] == "unavailable"
    assert f["factor_blend_score"] is None
    assert "net_margin_pct (not_ranked_raw_invalid)" in f["reason"]
    assert f["components"]["net_margin_pct"]["raw_status"] == "invalid"
    assert f["components"]["operating_margin_pct"]["normalization_status"] == \
        "ranked"
    assert f["blend"]["coverage_weight"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# 9. one not_applicable component -> pending_data, reason names the state
# ---------------------------------------------------------------------------
def test_blend_not_applicable_component_yields_pending_data():
    mets, bases = _growth_ladder()
    mets["NA_NET"] = company_metrics()
    bases["NA_NET"] = {"net_profit_prev": 0.0,          # zero base
                       "operating_profit_prev": 120.0}
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    f = _blend_of(out, "NA_NET", "earnings_growth")
    assert f["normalization_status"] == "pending_data"
    assert f["factor_blend_score"] is None
    assert "(not_applicable)" in f["reason"]
    assert "net_profit_growth_pct" in f["reason"]
    assert f["components"]["net_profit_growth_pct"][
        "normalization_status"] == "not_ranked_raw_not_applicable"
    assert f["components"]["operating_profit_growth_pct"][
        "normalization_status"] == "ranked"
    assert f["blend"]["coverage_weight"] == pytest.approx(0.5)
    # healthy sibling still blends
    assert _blend_of(out, "C05", "earnings_growth")[
        "normalization_status"] == "blended"


# ---------------------------------------------------------------------------
# 10. insufficient component peers -> insufficient_peers, and the refusal
#     priority puts it above missing (mixed company: insufficient + missing)
# ---------------------------------------------------------------------------
def test_blend_insufficient_peers_and_priority_over_missing():
    mets = {f"C{i:02d}": company_metrics() for i in range(15)}
    bases = {f"C{i:02d}": {"net_profit_prev": 80.0,
                           "operating_profit_prev": 120.0}
             for i in range(5)}
    bases["C05"] = {"net_profit_prev": 80.0}    # op base absent -> op missing
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    # C00: both growth components ranked but family n=6 < 10 -> refuse
    f00 = _blend_of(out, "C00", "earnings_growth")
    assert f00["normalization_status"] == "insufficient_peers"
    assert f00["factor_blend_score"] is None
    assert all(d["normalization_status"] == "insufficient_peers"
               for d in f00["components"].values())
    # C05: net insufficient AND op missing — insufficient_peers wins
    f05 = _blend_of(out, "C05", "earnings_growth")
    assert f05["normalization_status"] == "insufficient_peers"
    assert f05["components"]["net_profit_growth_pct"][
        "normalization_status"] == "insufficient_peers"
    assert f05["components"]["operating_profit_growth_pct"][
        "normalization_status"] == "not_ranked_raw_missing"
    # C10: both components missing -> pending_data
    f10 = _blend_of(out, "C10", "earnings_growth")
    assert f10["normalization_status"] == "pending_data"
    # margins are independent: blended everywhere
    assert _blend_of(out, "C00", "margins")["normalization_status"] == \
        "blended"
    assert _blend_of(out, "C10", "margins")["normalization_status"] == \
        "blended"


# ---------------------------------------------------------------------------
# 11. both components missing -> pending_data at coverage_weight 0.0
# ---------------------------------------------------------------------------
def test_blend_both_components_missing_yields_pending_data():
    mets = _margins_ladder()
    mets["NOREV"] = company_metrics(revenue_ttm=None)
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    f = _blend_of(out, "NOREV", "margins")
    assert f["normalization_status"] == "pending_data"
    assert f["factor_blend_score"] is None
    assert f["blend"]["coverage_weight"] == pytest.approx(0.0)
    for comp in ("operating_margin_pct", "net_margin_pct"):
        assert f["components"][comp]["normalization_status"] == \
            "not_ranked_raw_missing"
    assert "(missing)" in f["reason"]


# ---------------------------------------------------------------------------
# 12. a component published after as_of is refused in BOTH policies ->
#     unavailable (normalize-side look-ahead guard)
# ---------------------------------------------------------------------------
def test_blend_after_as_of_component_yields_unavailable():
    mets, bases = _growth_ladder()
    mets["LATE"] = company_metrics()
    bases["LATE"] = {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}
    prov = {cid: {"available_at": _VERIFIED_TS,
                  "source_ref": f"codal:{cid}",
                  "source_period": "1404-12"} for cid in mets}
    prov["LATE"]["available_at"] = dt.datetime(2026, 8, 1)   # > as_of
    raw = build_raw(mets, prev_bases=bases, provenance=prov)  # raw sees NO as_of
    out = SN.normalize_q_cross_section(raw, general_meta(mets),
                                       as_of=_STRICT_AS_OF)
    for fid in ("margins", "earnings_growth"):
        f = _blend_of(out, "LATE", fid)
        assert f["normalization_status"] == "unavailable", fid
        assert f["factor_blend_score"] is None
        assert "not_ranked_after_as_of" in f["reason"]
        assert all(d["normalization_status"] == "not_ranked_after_as_of"
                   for d in f["components"].values())
    # healthy companies blend normally in the same cross-section
    assert _blend_of(out, "C05", "margins")["normalization_status"] == \
        "blended"


# ---------------------------------------------------------------------------
# 13. historical_strict: unverified PIT never builds a composite; the same
#     raw data under current_exploratory blends with the PIT warning kept
# ---------------------------------------------------------------------------
def test_blend_historical_strict_unverified_pit_blocks_exploratory_blends():
    mets, bases = _growth_ladder()
    mets["NOPROV"] = company_metrics()
    bases["NOPROV"] = {"net_profit_prev": 80.0,
                       "operating_profit_prev": 120.0}
    prov = {cid: {"available_at": _VERIFIED_TS,
                  "source_ref": f"codal:{cid}",
                  "source_period": "1404-12"} for cid in mets}
    prov["NOPROV"] = {"available_at": _VERIFIED_TS}     # bare timestamp
    raw = build_raw(mets, prev_bases=bases, provenance=prov)

    strict = SN.normalize_q_cross_section(
        raw, general_meta(mets), as_of=_STRICT_AS_OF,
        pit_policy=SN.PIT_HISTORICAL_STRICT)
    for fid in ("margins", "earnings_growth"):
        f = _blend_of(strict, "NOPROV", fid)
        assert f["normalization_status"] == "unavailable", fid
        assert f["factor_blend_score"] is None
        assert "not_ranked_pit_strict" in f["reason"]
        assert all(d["pit_status"] == SR.PIT_UNVERIFIED
                   for d in f["components"].values())
    assert _blend_of(strict, "C05", "margins")["normalization_status"] == \
        "blended"

    explor = SN.normalize_q_cross_section(raw, general_meta(mets))
    assert explor["pit_policy"] == "current_exploratory"   # never backtest
    f = _blend_of(explor, "NOPROV", "margins")
    assert f["normalization_status"] == "blended"
    recs = _component_records(explor, "NOPROV", "margins")
    expected = 0.6 * recs["operating_margin_pct"]["percentile_combined"] \
        + 0.4 * recs["net_margin_pct"]["percentile_combined"]
    assert f["factor_blend_score"] == pytest.approx(expected)
    # the exploratory unverified-PIT warning is preserved on the component
    assert any(w.startswith("pit_unverified_exploratory")
               for w in f["components"]["operating_margin_pct"]["warnings"])


# ---------------------------------------------------------------------------
# 14. anomaly warning on a valid component: blend proceeds, warning kept,
#     no numeric penalty anywhere
# ---------------------------------------------------------------------------
def test_blend_anomaly_warning_preserved_no_numeric_penalty():
    # no-penalty proof at constant population and rank structure: ANOM (net
    # margin 2000%, past the anomaly band) and CLEAN_MAX (net margin 20%,
    # unremarkable) occupy EXACTLY the same rank positions, so every rank —
    # and therefore every score — must be identical; the only allowed
    # difference is the anomaly warning on ANOM.
    mets = _margins_ladder()
    mets["X12"] = company_metrics(net_profit_ttm=20000.0)   # 2000%: anomaly
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    f = _blend_of(out, "X12", "margins")
    assert f["normalization_status"] == "blended"
    assert f["factor_blend_score"] is not None
    recs = _component_records(out, "X12", "margins")
    assert any(w.startswith("magnitude_anomaly")
               for w in recs["net_margin_pct"]["warnings"])
    assert any(w.startswith("magnitude_anomaly")
               for w in f["components"]["net_margin_pct"]["warnings"])
    expected = 0.6 * recs["operating_margin_pct"]["percentile_combined"] \
        + 0.4 * recs["net_margin_pct"]["percentile_combined"]
    assert f["factor_blend_score"] == pytest.approx(expected)  # plain mean

    # same ranks, same population size, no warning -> identical numbers
    mets2 = _margins_ladder()
    mets2["X12"] = company_metrics(net_profit_ttm=200.0)    # 20%: max, clean
    out2 = SN.normalize_q_cross_section(build_raw(mets2), general_meta(mets2))
    for cid in mets:
        for comp in ("operating_margin_pct", "net_margin_pct"):
            a = _component_records(out, cid, "margins")[comp]
            b = _component_records(out2, cid, "margins")[comp]
            assert a["percentile_combined"] == \
                pytest.approx(b["percentile_combined"]), (cid, comp)
    f2 = _blend_of(out2, "X12", "margins")
    assert f2["factor_blend_score"] == \
        pytest.approx(f["factor_blend_score"])
    assert not any(w.startswith("magnitude_anomaly")
                   for w in f2["components"]["net_margin_pct"]["warnings"])


# ---------------------------------------------------------------------------
# 15. tiny-base growth (+2900%, anomaly band): valid, warned, blended —
#     the warning never becomes a new penalty
# ---------------------------------------------------------------------------
def test_blend_growth_tiny_base_anomaly_blends_without_penalty():
    mets, bases = _growth_ladder()
    mets["TINY"] = company_metrics(net_profit_ttm=30.0,
                                   operating_profit_ttm=150.0)
    bases["TINY"] = {"net_profit_prev": 1.0, "operating_profit_prev": 120.0}
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    f = _blend_of(out, "TINY", "earnings_growth")
    assert f["normalization_status"] == "blended"
    recs = _component_records(out, "TINY", "earnings_growth")
    assert recs["net_profit_growth_pct"]["raw_value"] == \
        pytest.approx(2900.0)
    assert any(w.startswith("magnitude_anomaly")
               for w in recs["net_profit_growth_pct"]["warnings"])
    expected = 0.5 * recs["operating_profit_growth_pct"]["percentile_combined"] \
        + 0.5 * recs["net_profit_growth_pct"]["percentile_combined"]
    assert f["factor_blend_score"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 18. the composite output is a SCORE, never re-ranked into a percentile
# ---------------------------------------------------------------------------
def test_blend_score_is_not_a_percentile_and_never_re_ranked():
    mets = _margins_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    for i in range(11):
        cid = f"C{i:02d}"
        f = _blend_of(out, cid, "margins")
        assert "percentile_combined" not in f
        recs = _component_records(out, cid, "margins")
        exact = 0.6 * recs["operating_margin_pct"]["percentile_combined"] \
            + 0.4 * recs["net_margin_pct"]["percentile_combined"]
        assert f["factor_blend_score"] == pytest.approx(exact)
    # and the composite still produces no factor-level record
    assert not [r for r in out["records"]
                if r["factor_id"] == "margins" and r["component_id"] is None]


# ---------------------------------------------------------------------------
# 19. the industry/family weighting is applied exactly ONCE (inside the
#     component ranks) — never again at composite level
# ---------------------------------------------------------------------------
def test_blend_applies_industry_weight_exactly_once():
    mets = {f"M{i:02d}": company_metrics(
        operating_profit_ttm=100.0 + 10.0 * i, net_profit_ttm=50.0 + 5.0 * i)
        for i in range(12)}
    for i in range(3):
        mets[f"K{i:02d}"] = company_metrics(
            operating_profit_ttm=300.0 + 10.0 * i,
            net_profit_ttm=150.0 + 5.0 * i)
    meta = general_meta(mets, industry="Metals")
    for cid in ("K00", "K01", "K02"):
        meta[cid]["industry"] = "Chem"
    out = SN.normalize_q_cross_section(build_raw(mets), meta)
    recs = _component_records(out, "M06", "margins")
    op = recs["operating_margin_pct"]
    assert op["effective_sector_weight"] == pytest.approx(0.65 * 7.0 / 15.0)
    assert op["effective_sector_weight"] > 0.0
    # the combined percentile really differs from the family-only rank ...
    assert op["percentile_combined"] != pytest.approx(
        op["percentile_market_family"])
    # ... and the blend consumes exactly that combined value — a second
    # application of the sector weight would break this equality
    f = _blend_of(out, "M06", "margins")
    expected = 0.6 * recs["operating_margin_pct"]["percentile_combined"] \
        + 0.4 * recs["net_margin_pct"]["percentile_combined"]
    assert f["factor_blend_score"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 20. the layer never mutates its caller's input (blend fields included)
# ---------------------------------------------------------------------------
def test_blend_never_mutates_caller_input():
    mets, bases = _growth_ladder()
    mets["OP_ONLY"] = company_metrics(net_profit_ttm=None)
    bases["OP_ONLY"] = {"net_profit_prev": 80.0,
                        "operating_profit_prev": 120.0}
    raw = build_raw(mets, prev_bases=bases)
    meta = general_meta(mets)
    raw_snapshot = copy.deepcopy(raw)
    meta_snapshot = copy.deepcopy(meta)
    SN.normalize_q_cross_section(raw, meta)
    assert raw == raw_snapshot
    assert meta == meta_snapshot


# ---------------------------------------------------------------------------
# 21. fully deterministic regardless of company order — blend fields
#     included in the whole-output equality
# ---------------------------------------------------------------------------
def test_blend_output_identical_regardless_of_company_order():
    mets, bases = _growth_ladder()
    mets["OP_ONLY"] = company_metrics(net_profit_ttm=None)
    mets["BADNET"] = company_metrics(net_profit_ttm=float("nan"))
    mets["NOREV"] = company_metrics(revenue_ttm=None)
    raw = build_raw(mets, prev_bases=bases)
    meta = general_meta(mets)
    out1 = SN.normalize_q_cross_section(raw, meta)
    out2 = SN.normalize_q_cross_section(
        dict(reversed(list(raw.items()))),
        dict(reversed(list(meta.items()))))
    assert out1 == out2


# ---------------------------------------------------------------------------
# 22. the shipped weight table: ratified values, general-only scope, and a
#     fully validated, order-independent validation contract
# ---------------------------------------------------------------------------
def test_composite_component_weights_config_validation():
    check = CFG._validate_composite_component_weights
    check(CFG.COMPOSITE_COMPONENT_WEIGHTS)          # the shipped table passes
    # ratified calibration and scope: general ONLY, exact weights
    assert set(CFG.COMPOSITE_COMPONENT_WEIGHTS) == {"general"}
    assert CFG.COMPOSITE_COMPONENT_WEIGHTS["general"]["margins"] == {
        "operating_margin_pct": 0.60, "net_margin_pct": 0.40}
    assert CFG.COMPOSITE_COMPONENT_WEIGHTS["general"]["earnings_growth"] == {
        "operating_profit_growth_pct": 0.50, "net_profit_growth_pct": 0.50}
    # key order never matters (math.fsum over sorted keys)
    check({"general": {"margins": {"net_margin_pct": 0.40,
                                   "operating_margin_pct": 0.60}}})
    # sum tolerance: 5e-10 drift passes, 1e-8 fails
    check({"general": {"margins": {"operating_margin_pct": 0.6,
                                   "net_margin_pct": 0.4 + 5e-10}}})
    with pytest.raises(ValueError):
        check({"general": {"margins": {"operating_margin_pct": 0.6,
                                       "net_margin_pct": 0.4 + 1e-8}}})
    bad_tables = [
        {"special": {"margins": {"a": 1.0}}},                     # family
        {"general": {"nope": {"a": 1.0}}},                        # factor id
        {"general": {"roic": {"a": 1.0}}},                        # not READY
        {"general": {"margins": {}}},                             # empty map
        {"general": {"margins": {"operating_margin_pct": 1.0}}},
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": "0.4"}}},      # non-number
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": True}}},       # bool
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": float("nan")}}},
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": float("inf")}}},
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": -0.4}}},       # negative
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": 0.0}}},        # not positive
        {"general": {"margins": {"operating_margin_pct": 0.6,
                                 "net_margin_pct": 0.3}}},        # sum != 1
        "not a table",
        {},
    ]
    for bad in bad_tables:
        with pytest.raises(ValueError):
            check(bad)


def test_config_weights_match_raw_components_exactly():
    """The table's component keys are EXACTLY the raw layer's real components
    (cross-layer pin; the runtime twin of this guard refuses a mismatched
    blend in normalize)."""
    mets = {"C1": company_metrics()}
    bases = {"C1": {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}}
    raw = build_raw(mets, prev_bases=bases)
    tbl = CFG.COMPOSITE_COMPONENT_WEIGHTS["general"]
    for fid in ("margins", "earnings_growth"):
        assert set(tbl[fid]) == set(raw["C1"][fid]["components"]), fid


def test_weight_config_mismatch_refuses_blend(monkeypatch):
    bad = copy.deepcopy(CFG.COMPOSITE_COMPONENT_WEIGHTS)
    bad["general"]["margins"] = {"operating_margin_pct": 0.5,
                                 "net_margin_pct": 0.4,
                                 "bogus_pct": 0.1}
    monkeypatch.setattr(CFG, "COMPOSITE_COMPONENT_WEIGHTS", bad)
    mets = _margins_ladder()
    bases = {cid: {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}
             for cid in mets}
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    m = _blend_of(out, "C05", "margins")
    assert m["normalization_status"] == "pending_blend"    # refused, no blend
    assert "factor_blend_score" not in m
    assert "blend" not in m
    assert "component-weight config does not match" in m["reason"]
    # the refused factor's component detail stays in the legacy shape
    assert set(m["components"]["operating_margin_pct"]) == {
        "normalization_status", "percentile_combined"}
    # the untouched sibling factor and the singles keep working normally
    g = _blend_of(out, "C05", "earnings_growth")
    assert g["normalization_status"] == "blended"
    s = _blend_of(out, "C05", "cash_conversion")
    assert s["normalization_status"] == "ranked"


# ---------------------------------------------------------------------------
# 23. bank / insurance / investment keep pending_blend — presence in
#     FAMILY_WEIGHTS activates nothing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("family", ["bank", "insurance", "investment"])
def test_pending_blend_preserved_for_specialized_families(family):
    mets, bases = _growth_ladder()
    meta = {cid: {"model_family": family, "industry": "Metals"}
            for cid in mets}
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       meta)
    for cid in ("C00", "C05", "C10"):
        for fid in ("margins", "earnings_growth"):
            f = _blend_of(out, cid, fid)
            assert f["normalization_status"] == "pending_blend", (family, cid)
            assert "factor_blend_score" not in f
            assert "blend" not in f
            assert f["reason"] == (
                "no approved component blend contract yet — "
                "component ranks are kept separate; the factor "
                "itself gets no percentile")
            assert all(d["normalization_status"] == "ranked"
                       for d in f["components"].values())


# ---------------------------------------------------------------------------
# 24. raw/record contract preserved: legacy keys survive additively
# ---------------------------------------------------------------------------
def test_record_and_factor_contract_preserved_under_blend():
    mets = _margins_ladder()
    out = SN.normalize_q_cross_section(build_raw(mets), general_meta(mets))
    required = {"company_id", "factor_id", "component_id", "raw_value",
                "normalized_input", "percentile_market_family",
                "percentile_sector", "percentile_combined", "direction",
                "peer_group", "n_valid_market_family", "n_valid_sector",
                "effective_sector_weight", "validation_status", "pit_status",
                "warnings", "normalization_status"}
    for r in out["records"]:
        assert required <= set(r), required - set(r)
    f = _blend_of(out, "C05", "margins")
    for legacy in ("company_id", "factor_id", "component_id", "composite",
                   "normalization_status", "reason", "components", "warnings"):
        assert legacy in f, legacy
    for comp, d in f["components"].items():
        assert {"normalization_status", "percentile_combined"} <= set(d)
        assert {"raw_status", "raw_value", "pit_status", "available_at",
                "weight", "contribution", "warnings",
                "n_valid_market_family", "n_valid_sector"} <= set(d)


# ---------------------------------------------------------------------------
# 25. every produced number is finite and inside [0, 1] — never NaN/inf
# ---------------------------------------------------------------------------
def test_blend_scores_always_finite_or_none():
    fixtures = []
    mets, bases = _growth_ladder()
    mets["OP_ONLY"] = company_metrics(net_profit_ttm=None)
    mets["BADNET"] = company_metrics(net_profit_ttm=float("nan"))
    mets["NOREV"] = company_metrics(revenue_ttm=None)
    fixtures.append((mets, bases, "general"))
    m2 = _margins_ladder()
    fixtures.append((m2, None, "general"))
    fixtures.append((_growth_ladder()[0], _growth_ladder()[1], "bank"))
    for m, b, fam in fixtures:
        meta = {cid: {"model_family": fam, "industry": "Metals"}
                for cid in m}
        out = SN.normalize_q_cross_section(
            build_raw(m, prev_bases=b or {}), meta)
        for cid, factors in out["factors"].items():
            for fid, f in factors.items():
                if not f.get("composite"):
                    continue
                score = f.get("factor_blend_score")
                assert score is None or (
                    math.isfinite(score) and 0.0 <= score <= 1.0), (cid, fid)
                blend = f.get("blend")
                if blend is not None:
                    assert math.isfinite(blend["coverage_weight"])
                    assert 0.0 <= blend["coverage_weight"] <= 1.0
                    for c in blend.get("contributions", {}).values():
                        assert math.isfinite(c) and 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# 26. both components valid with DIFFERENT ranking populations: the blend
#     proceeds and each component's independent n stays visible
# ---------------------------------------------------------------------------
def test_blend_independent_component_populations_recorded():
    mets, bases = _growth_ladder(15)
    for i in range(12, 15):                     # C12..C14: no growth bases
        del bases[f"C{i:02d}"]
    out = SN.normalize_q_cross_section(build_raw(mets, prev_bases=bases),
                                       general_meta(mets))
    fm = _blend_of(out, "C05", "margins")
    fg = _blend_of(out, "C05", "earnings_growth")
    assert fm["normalization_status"] == "blended"
    assert fg["normalization_status"] == "blended"      # 12 >= family_min_n
    assert fm["blend"]["coverage_weight"] == pytest.approx(1.0)
    assert fg["blend"]["coverage_weight"] == pytest.approx(1.0)
    # margins components ranked over 15 companies, growth components over 12
    for comp in ("operating_margin_pct", "net_margin_pct"):
        assert fm["components"][comp]["n_valid_market_family"] == 15
    for comp in ("net_profit_growth_pct", "operating_profit_growth_pct"):
        assert fg["components"][comp]["n_valid_market_family"] == 12
        rec = [r for r in out["records"] if r["company_id"] == "C05"
               and r["component_id"] == comp][0]
        assert rec["n_valid_market_family"] == 12
        assert fg["components"][comp]["percentile_combined"] == \
            pytest.approx(rec["percentile_combined"])


# ---------------------------------------------------------------------------
# Step 2-B-5: the new single-component factors rank like any other unit
# ---------------------------------------------------------------------------
def test_2b5_singles_rank_within_family_with_config_direction():
    # roe_level / margin_trend / revenue_growth flow through the same
    # collect->winsor->midrank machinery; higher raw = higher percentile
    mets, meta = {}, general_meta([f"C{i}" for i in range(11)])
    for i in range(11):
        cid = f"C{i}"
        mets[cid] = company_metrics(roe=10.0 + i, margin_trend=1.0 + i,
                                    revenue_growth=5.0 + i)
        mets[cid]["margin_trend"] = None  # engine field never used directly
    raw = {}
    bases = {f"C{i}": {"operating_profit_prev": 100.0,
                       "revenue_prev": 1000.0} for i in range(11)}
    for cid, m in mets.items():
        m2 = dict(m)
        m2["operating_profit_ttm"] = 150.0 + 10 * int(cid[1:])
        raw[cid] = SR.build_q_raw({cid: m2}, prev_bases={cid: bases[cid]})[cid]
    out = SN.normalize_q_cross_section(raw, meta, policy=SMALL)
    for fid in ("roe_level", "margin_trend", "revenue_growth"):
        recs = {r["company_id"]: r for r in out["records"]
                if r["factor_id"] == fid}
        assert set(recs) == set(mets)
        assert recs["C0"]["percentile_market_family"] == pytest.approx(0.0)
        assert recs["C10"]["percentile_market_family"] == pytest.approx(1.0)
        assert all(0.0 <= r["percentile_combined"] <= 1.0
                   for r in recs.values())
        f = out["factors"]["C5"][fid]
        assert f["composite"] is False
        assert f["normalization_status"] == SN.NR_RANKED


def test_out_of_scope_factor_ids_never_rank():
    # the raw scope is the only door into normalization: hand-injected
    # records for factors outside IN_SCOPE_FACTORS (roe_stability, or a
    # bogus id) are ignored by design — they can only re-enter through a
    # raw-layer contract change. interest_coverage / earnings_quality took
    # exactly that path in 2-B-7 (the same-window expense-TTM channel) and
    # are in-scope now; roe_stability and everything unknown stay filtered.
    mets = {f"C{i}": company_metrics() for i in range(11)}
    raw = SR.build_q_raw(mets)
    for cid in raw:
        raw[cid]["roe_stability"] = dict(
            raw[cid]["leverage"], factor_id="roe_stability")
        raw[cid]["totally_bogus"] = dict(
            raw[cid]["leverage"], factor_id="totally_bogus")
    out = SN.normalize_q_cross_section(raw, general_meta(list(mets)),
                                       policy=SMALL)
    for banned in ("roe_stability", "totally_bogus"):
        assert all(r["factor_id"] != banned for r in out["records"])
        assert all(banned not in f
                   for f in out["factors"].values())
    # the 2-B-7 pair, in contrast, is inside the raw scope: its rollups are
    # produced (raw-missing here — company_metrics carries no channel)
    for f in out["factors"].values():
        assert "interest_coverage" in f and "earnings_quality" in f
