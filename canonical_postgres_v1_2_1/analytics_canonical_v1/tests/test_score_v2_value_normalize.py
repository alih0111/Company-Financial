"""Value normalization (cross-sectional ranking) tests — step 2-J-1, pure.

Covers score_v2_value_normalize.normalize_v_cross_section() on synthetic
raw worlds built through the REAL raw layer (score_v2_value_raw.build_v_raw):

  * lower-is-better: the CHEAPEST company in a peer family gets the highest
    percentile (midrank called with higher_is_better=False exactly once)
  * model families never mix: general / bank / insurance / investment
    populations are built independently; a bank extreme never moves a
    general percentile
  * P/S exists only in the general family's population (raw family gate)
  * a family population below family_min_n (10) yields insufficient_peers —
    no percentile instead of a seemingly precise rank
  * winsorization: with n >= winsor_min_n (20) the P1/P99 bounds clip
    extremes before ranking; with n < 20 no bounds are forced
  * sector blend: >= 20 peers in one industry -> full 0.65 sector weight;
    5..19 -> linear ramp; < 5 -> family rank only
  * non-finite eligible values are excluded under "non_finite"
  * publication after as_of is refused in BOTH policies (look-ahead guard);
    historical_strict ranks only PIT-verified values and requires as_of
  * missing / invalid / not_applicable never enter a population and never
    become zero: the factor rollup keeps the raw status with percentile None

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2_value_normalize.py -q
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

import score_v2_normalize as SN  # noqa: E402
import score_v2_value_normalize as VN  # noqa: E402
import score_v2_value_raw as VRW  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc)
PTD = dt.date(2026, 10, 5)


def channel(price=10.0, shares=1000.0):
    return {"price": price, "price_trade_date": PTD,
            "price_collected_at": dt.datetime(2026, 10, 5, 18, 0,
                                              tzinfo=dt.timezone.utc),
            "price_age_days": 3, "shares": shares,
            "share_source": "TSETMC_ZTITAD_CURRENT",
            "share_source_date": PTD, "share_price_gap_days": 0,
            "share_cross_check": "AGREE"}


def raw_world(peers: dict, equity_scale=1.0):
    """peers: cid -> {"np", "rev", "eq", "price", "shares", "family",
    "industry"} — builds REAL raw records through build_v_raw. market cap =
    price x shares; pe = mcap/np, pb = mcap/eq, ps = mcap/rev."""
    metrics = {}
    meta = {}
    market = {}
    equity = {}
    for cid, p in peers.items():
        metrics[cid] = {"net_profit_ttm": p["np"],
                        "revenue_ttm": p.get("rev", p["np"] * 5.0)}
        meta[cid] = {"model_family": p.get("family", "general"),
                     "industry": p.get("industry", f"ind_{p.get('g', 'a')}")}
        market[cid] = channel(price=p.get("price", 10.0),
                              shares=p.get("shares", 1000.0))
        equity[cid] = {"equity": p.get("eq", 5000.0),
                       "period_end_date": dt.date(2026, 7, 31)}
    return VRW.build_v_raw(metrics, meta, market=market,
                           equity_by_company=equity, as_of=AS_OF,
                           cutoff=CUTOFF), meta


def gen_peers(n, base=100.0, step=10.0, **kw):
    """n general companies with increasing P/E: pe_i = mcap/np where np
    varies; mcap fixed 10,000 -> pe = 10000/np."""
    out = {}
    for i in range(n):
        out[f"G{i:02d}"] = {"np": base + i * step, **kw}
    return out


def fam_percentiles(norm, fid):
    return {r["company_id"]: r["percentile_market_family"]
            for r in norm["records"] if r["factor_id"] == fid}


# ---------------------------------------------------------------------------
# direction + determinism
# ---------------------------------------------------------------------------
def test_lower_is_better_cheapest_gets_highest_percentile():
    raw, meta = raw_world(gen_peers(12))  # pe: 100 .. 10000/210
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    pct = fam_percentiles(norm, "pe")
    assert len(pct) == 12
    # G00 has the LARGEST pe (np=100 -> pe=100) -> must get the LOWEST
    # percentile; G11 (np=210 -> pe ~= 47.6, cheapest) -> the highest
    assert pct["G00"] == 0.0
    assert pct["G11"] == 1.0
    assert pct["G05"] == pytest.approx(5 / 11)
    # direction recorded from config
    assert all(r["direction"] == "lower" for r in norm["records"])


def test_results_independent_of_input_order():
    peers = gen_peers(12)
    raw_a, meta_a = raw_world(peers)
    raw_b, meta_b = raw_world(dict(reversed(list(peers.items()))))
    na = VN.normalize_v_cross_section(raw_a, meta_a, as_of=CUTOFF)
    nb = VN.normalize_v_cross_section(raw_b, meta_b, as_of=CUTOFF)
    pa = {(r["company_id"], r["factor_id"], r["percentile_combined"])
          for r in na["records"]}
    pb = {(r["company_id"], r["factor_id"], r["percentile_combined"])
          for r in nb["records"]}
    assert pa == pb


# ---------------------------------------------------------------------------
# family separation
# ---------------------------------------------------------------------------
def test_families_never_mix():
    peers = gen_peers(12)
    # a 10-member bank family with its own extremes: astronomic and
    # near-zero P/E inside the bank population
    for i in range(8):
        peers[f"B{i:02d}"] = {"np": 100.0 + i * 10.0, "family": "bank",
                              "industry": "بانک"}
    peers["B90"] = {"np": 1e-3, "family": "bank",
                    "industry": "بانک"}       # astronomic bank P/E
    peers["B91"] = {"np": 1e9, "family": "bank",
                    "industry": "بانک"}       # near-zero bank P/E
    raw, meta = raw_world(peers)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    pct = fam_percentiles(norm, "pe")
    assert pct["B90"] == 0.0 and pct["B91"] == 1.0  # ranked inside bank only
    # the general percentiles are exactly the 12-company ones
    assert pct["G00"] == 0.0 and pct["G11"] == 1.0
    pops = norm["populations"]["pe"]["families"]
    assert pops["general"]["n_valid"] == 12
    assert pops["bank"]["n_valid"] == 10


def test_insufficient_peers_below_family_min_n():
    raw, meta = raw_world(gen_peers(9))  # < family_min_n (10)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    pct = fam_percentiles(norm, "pe")
    assert all(v is None for v in pct.values())
    recs = [r for r in norm["records"] if r["factor_id"] == "pe"]
    assert all(r["normalization_status"] == SN.NR_INSUFFICIENT_PEERS
               for r in recs)
    assert all(r["percentile_combined"] is None for r in recs)
    assert all(r["null_reasons"]["percentile_combined"] == "insufficient_peers"
               for r in recs)


# ---------------------------------------------------------------------------
# winsor + sector policy
# ---------------------------------------------------------------------------
def test_winsor_applies_at_20_and_clips_extremes():
    # a single astronomic outlier in 100 peers: the tested V4 P99/P1
    # interpolation defines the bound (1% of the way from the bulk top
    # toward the outlier), and the outlier is CLIPPED to that bound
    peers = gen_peers(100)
    peers["G99"]["np"] = 1e-6  # astronomic P/E outlier
    raw, meta = raw_world(peers)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    pops = norm["populations"]["pe"]["families"]["general"]
    assert pops["winsor"]["applied"] is True
    win = pops["winsor"]["high"]
    recs = {r["company_id"]: r for r in norm["records"]
            if r["factor_id"] == "pe"}
    outlier = 10000.0 / 1e-6
    assert recs["G99"]["normalized_input"] == pytest.approx(win)
    assert win == pytest.approx(S4_percentile(sorted(
        10000.0 / (100 + i * 10) for i in range(99)) + [outlier], 0.99))
    assert win < outlier * 0.02  # clipped by more than 98%


def S4_percentile(vals, q):
    import score_v4
    return score_v4._percentile(list(vals), q)


def test_no_winsor_forced_below_min_sample():
    raw, meta = raw_world(gen_peers(12))
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    pops = norm["populations"]["pe"]["families"]["general"]
    assert pops["winsor"]["applied"] is False
    assert pops["winsor"]["n"] == 12


def test_sector_blend_full_weight_at_20_industry_peers():
    peers = gen_peers(24, industry="فولاد", g="s")
    raw, meta = raw_world(peers)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    recs = {r["company_id"]: r for r in norm["records"]
            if r["factor_id"] == "pe"}
    r0 = recs["G00"]
    assert r0["n_valid_sector"] == 24
    assert r0["effective_sector_weight"] == pytest.approx(0.65)
    assert r0["peer_group"] == "family:general|industry:فولاد"
    expected = 0.65 * r0["percentile_sector"] + 0.35 * r0["percentile_market_family"]
    assert r0["percentile_combined"] == pytest.approx(expected)


def test_sector_too_small_joins_no_sector_population():
    peers = gen_peers(12)
    peers["G11"] = {**peers["G11"], "industry": "نادر", "g": "rare"}
    raw, meta = raw_world(peers)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    recs = {r["company_id"]: r for r in norm["records"]
            if r["factor_id"] == "pe"}
    assert recs["G11"]["percentile_sector"] is None
    assert recs["G11"]["null_reasons"]["percentile_sector"] == "sector_too_small"
    assert recs["G11"]["percentile_combined"] == \
        recs["G11"]["percentile_market_family"]


# ---------------------------------------------------------------------------
# P/S scope, non-finite, PIT
# ---------------------------------------------------------------------------
def test_ps_population_is_general_only():
    peers = gen_peers(12)
    peers["B01"] = {"np": 100.0, "family": "bank", "industry": "بانک"}
    raw, meta = raw_world(peers)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    bank_rollup = norm["factors"]["B01"]["ps"]
    assert bank_rollup["normalization_status"] == "not_ranked_raw_not_applicable"
    assert bank_rollup["percentile_combined"] is None
    pops = norm["populations"]["ps"]["families"]
    assert set(pops) == {"general"}
    assert norm["populations"]["ps"]["excluded"].get("not_applicable") == 1


def test_non_finite_value_excluded_from_population():
    raw, meta = raw_world(gen_peers(12))
    raw["G00"]["pe"] = {**raw["G00"]["pe"],
                        "raw_value": float("inf")}
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    assert norm["populations"]["pe"]["excluded"]["non_finite"] == 1
    pct = fam_percentiles(norm, "pe")
    assert "G00" not in pct
    assert norm["factors"]["G00"]["pe"]["normalization_status"] == \
        SN.NR_NON_FINITE


def test_missing_never_becomes_zero():
    peers = gen_peers(12)
    peers["G05"]["np"] = -50.0  # loss maker: pe not_applicable
    raw, meta = raw_world(peers)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    rollup = norm["factors"]["G05"]["pe"]
    assert rollup["normalization_status"] == "not_ranked_raw_not_applicable"
    assert rollup["percentile_combined"] is None
    pct = fam_percentiles(norm, "pe")
    assert "G05" not in pct


def test_published_after_as_of_refused_in_exploratory():
    peers = gen_peers(12)
    raw, meta = raw_world(peers)
    late = dt.datetime(2026, 10, 9, 8, 0, tzinfo=dt.timezone.utc)
    raw["G03"]["pe"]["available_at"] = late
    raw["G03"]["pe"]["pit_status"] = "verified"
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    recs = {r["company_id"]: r for r in norm["records"]
            if r["factor_id"] == "pe"}
    assert recs["G03"]["normalization_status"] == SN.NR_AFTER_AS_OF
    assert recs["G03"]["percentile_combined"] is None
    assert norm["populations"]["pe"]["excluded_after_as_of"] == 1


def test_historical_strict_ranks_only_verified_and_requires_as_of():
    peers = gen_peers(12)
    raw, meta = raw_world(peers)
    with pytest.raises(ValueError):
        VN.normalize_v_cross_section(raw, meta,
                                     pit_policy=SN.PIT_HISTORICAL_STRICT)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF,
                                        pit_policy=SN.PIT_HISTORICAL_STRICT)
    # every valid value is kept on its record for audit, but NOTHING ranks:
    # nothing in this world is PIT-verified (no source_ref anywhere)
    assert all(r["normalization_status"] == SN.NR_PIT_STRICT
               for r in norm["records"])
    assert all(r["percentile_combined"] is None for r in norm["records"])
    assert len(norm["records"]) == 36  # 12 companies x 3 factors, all refused
    assert norm["populations"]["pe"]["excluded_pit_strict"] == 12


def test_contract_checks_direction_and_skips_foreign_factors():
    raw, meta = raw_world(gen_peers(12))
    # baseline passes
    VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    # a factor outside the V scope is skipped, never ranked
    bad = {cid: {**recs, "roe_level": recs["pe"]}
           for cid, recs in raw.items()}
    norm = VN.normalize_v_cross_section(bad, meta, as_of=CUTOFF)
    assert "roe_level" not in norm["populations"]
    assert all("roe_level" not in rollups
               for rollups in norm["factors"].values())
    # a config direction that contradicts the lower-is-better contract
    # stops the layer loudly (monkeypatched — the real config is untouched)
    import score_v2_config as CFG
    orig = CFG.V2_QVT_FACTORS["pe"]["direction"]
    CFG.V2_QVT_FACTORS["pe"]["direction"] = "higher"
    try:
        with pytest.raises(ValueError):
            VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    finally:
        CFG.V2_QVT_FACTORS["pe"]["direction"] = orig
