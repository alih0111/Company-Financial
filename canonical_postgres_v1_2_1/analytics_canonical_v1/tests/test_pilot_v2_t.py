"""Observed-T pilot tests (step 2-D-1) — pure, no database.

Covers pilot_v2_t on synthetic worlds shaped exactly like the real
pipeline's inputs (engine metrics + engine price rows):

  * every family's T weight table sums to exactly 25 and carries only the
    READY raw-scope factors; any inconsistency STOPS the aggregation
    (TWeightInconsistency) — never auto-fixed; distance_from_52w_high stays
    in no family map and is never scored (needs_development)
  * t_observed_points is the plain weighted sum over scored factors (never
    divided by covered_weight, never renormalized), a missing/refused
    factor has no score share, companies are never ranked by points
  * the essential gate (momentum_6m_rel + liquidity) and the 0.50 coverage
    threshold drive pilot_eligible
  * Data Confidence and Risk Gate stay not_evaluated; trading warnings are
    preserved; no penalty touches the points
  * no forbidden aggregate key exists anywhere (no timing_score / t_final /
    qvt total / Q+V+T combination)
  * the engine cross-check verifies liquidity against the V1 engine's own
    avg_trade_value_30d and lists divergences loudly; no 6m momentum
    counterpart is claimed
  * the coverage summary answers the mission's counting questions and the
    Q/V/T overlap stays a COUNT (the axes are never combined)
  * an end-to-end stub-engine run produces the full report deterministically
    without mutating the engine's price rows

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_pilot_v2_t.py -q
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import score_v2_config as CFG  # noqa: E402
import pilot_v2_t as PT  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc)
IND = "فولاد"

FORBIDDEN_AGGREGATE_KEYS = {"timing_score", "t_final_score", "t_final",
                            "total_score", "qvt_score", "qvt_total",
                            "quality_score", "valuation_score",
                            "quant_score", "qv_score", "qt_score",
                            "vt_score", "q_plus_v_plus_t"}


def weekdays(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)
        d += dt.timedelta(days=0)


def seg_closes(d0, d1, c0, c1):
    days = list(weekdays(d0, d1))
    if not days:
        return {}
    if len(days) == 1:
        return {days[0]: c1}
    k = len(days) - 1
    return {d: c0 * math.pow(c1 / c0, i / k) for i, d in enumerate(days)}


def peer_path(final: float) -> dict:
    path = {}
    path.update(seg_closes(dt.date(2026, 3, 2), dt.date(2026, 4, 8),
                           1000.0, 1000.0))
    path.update(seg_closes(dt.date(2026, 4, 9), dt.date(2026, 7, 8),
                           1000.0, 1250.0))
    path.update(seg_closes(dt.date(2026, 7, 9), dt.date(2026, 10, 5),
                           1250.0, final))
    return path


def price_rows(sid: str, path: dict, tv: float = 1e9) -> list:
    """Engine-order rows: trade_date DESC, collected_at DESC."""
    return [{"security_id": sid, "trade_date": d,
             "collected_at": dt.datetime(2026, 10, 6, 10, 0,
                                         tzinfo=dt.timezone.utc),
             "closing_price_rial": path[d], "last_price_rial": path[d],
             "trade_value_rial": tv}
            for d in sorted(path, reverse=True)]


def default_specs() -> dict:
    specs = {}
    for i in range(12):
        specs[f"G{i:02d}"] = {"ret": -0.2 + i * 0.06}
    specs["GX"] = {"ret": 0.3, "gap_date": dt.date(2026, 9, 15)}
    specs["GL"] = {"ret": 0.1, "recent_only": True}
    return specs


def stub_engine(specs: dict) -> SimpleNamespace:
    metrics, prices, subjects = {}, [], {}
    for cid, s in specs.items():
        sid = f"sec-{cid}"
        final = 1000.0 * (1.0 + s["ret"])
        path = peer_path(final)
        if s.get("recent_only"):
            path = {d: c for d, c in path.items()
                    if d >= dt.date(2026, 8, 3)}
        if s.get("gap_date"):
            path[s["gap_date"]] = path[s["gap_date"]] * 0.75
        prices.extend(price_rows(sid, path, tv=s.get("tv", 1e9)))
        metrics[cid] = {"security_id": sid,
                        "avg_trade_value_30d": s.get("eng_liq", 1e9),
                        "volatility_30d": s.get("eng_vol")}
        subjects[cid] = {"symbol": cid, "display_name": cid}
    return SimpleNamespace(metrics=metrics, prices=prices,
                           subjects=subjects, stmt=[], codal_titles=[],
                           superseded=set(), current_shares={},
                           compute=lambda: None)


def run(specs=None, q=None, v=None):
    specs = default_specs() if specs is None else specs
    eng = stub_engine(specs)
    frozen = copy.deepcopy(eng.prices)
    sector_map = {cid: IND for cid in specs}
    q = q if q is not None else {f"G{i:02d}" for i in range(5)}
    v = v if v is not None else {f"G{i:02d}" for i in range(3)}
    rep = PT.run_t_pilot(AS_OF, CUTOFF, engine=eng, sector_map=sector_map,
                         q_eligible=q, v_eligible=v)
    assert eng.prices == frozen  # the engine's rows are never mutated
    return rep


# ---------------------------------------------------------------------------
# weight tables
# ---------------------------------------------------------------------------
def test_weight_tables_all_families_sum_to_25():
    for fam in CFG.FAMILIES:
        t = PT.t_weight_table(fam)
        assert t["target_weight"] == 25
        assert t["total_weight"] == pytest.approx(25)
        assert math.fsum(t["weights"].values()) == pytest.approx(25)


def test_weight_table_general_rows_exact():
    t = PT.t_weight_table("general")
    assert t["weights"] == {"liquidity": 4, "low_volatility": 4,
                            "momentum_3m_rel": 5, "momentum_6m_rel": 7,
                            "relative_strength_6m_sector": 5}
    assert {f for f, r in t["rows"].items() if r["essential"]} == \
        {"momentum_6m_rel", "liquidity"}
    assert t["rows"]["low_volatility"]["direction"] == "lower"
    for fam in ("bank", "insurance", "investment"):
        assert PT.t_weight_table(fam)["weights"] == t["weights"]


def test_needs_development_factor_in_no_family_map():
    for fam in CFG.FAMILIES:
        t = PT.t_weight_table(fam)
        assert set(t["factors_not_in_family_map"]) == \
            {"distance_from_52w_high"}
        spec = t["factors_not_in_family_map"]["distance_from_52w_high"]
        assert spec["availability"] == CFG.NEEDS_DEVELOPMENT
        assert spec["target_weight"] == 4


def test_broken_weight_sum_stops(monkeypatch):
    monkeypatch.setitem(CFG.FAMILY_WEIGHTS["general"],
                        "momentum_6m_rel", 70)
    with pytest.raises(PT.TWeightInconsistency, match="sum to"):
        PT.t_weight_table("general")


def test_needs_development_leak_stops(monkeypatch):
    monkeypatch.setitem(CFG.FAMILY_WEIGHTS["general"],
                        "distance_from_52w_high", 4)
    with pytest.raises(PT.TWeightInconsistency,
                       match="needs_development"):
        PT.t_weight_table("general")


def test_unmapped_scope_leak_stops(monkeypatch):
    monkeypatch.setitem(CFG.V2_QVT_FACTORS, "fake_timing_factor",
                        {"axis": "timing", "direction": "higher",
                         "availability": CFG.READY, "target_weight": 5,
                         "essential": False, "note": "x"})
    monkeypatch.setitem(CFG.FAMILY_WEIGHTS["general"],
                        "fake_timing_factor", 5)
    with pytest.raises(PT.TWeightInconsistency, match="absent"):
        PT.t_weight_table("general")


# ---------------------------------------------------------------------------
# aggregation semantics
# ---------------------------------------------------------------------------
def test_points_plain_weighted_sum_full_coverage():
    rep = run()
    e = rep["t_observed_report"]["companies"]["G05"]
    assert e["covered_weight"] == pytest.approx(25.0)
    assert e["missing_weight"] == pytest.approx(0.0)
    assert e["coverage_ratio"] == pytest.approx(1.0)
    pts = math.fsum(f["contribution_points"]
                    for f in e["factors"].values() if f["included"])
    assert e["t_observed_points"] == pytest.approx(pts)
    assert e["t_observed_points"] <= 25.0  # never renormalized above target
    assert e["essential_status"]["all_satisfied"] is True
    assert e["pilot_eligible"] is True


def test_essential_gate_blocks_gap_company():
    rep = run()
    e = rep["t_observed_report"]["companies"]["GX"]
    assert e["factors"]["momentum_6m_rel"]["raw_status"] == "invalid"
    assert e["essential_status"]["missing"] == ["momentum_6m_rel"]
    assert e["covered_weight"] == pytest.approx(4.0)  # liquidity only
    assert e["pilot_eligible"] is False
    assert e["data_confidence"]["missing_reasons"]["momentum_6m_rel"]


def test_short_history_company_below_coverage_threshold():
    rep = run()
    e = rep["t_observed_report"]["companies"]["GL"]
    # liquidity + low_volatility only: covered 8 of 25 < 12.5 threshold
    assert e["covered_weight"] == pytest.approx(8.0)
    assert e["coverage_threshold_met"] is False
    assert e["pilot_eligible"] is False
    assert "momentum_6m_rel" in e["data_confidence"]["missing_reasons"]


def test_no_forbidden_aggregate_keys_anywhere():
    rep = run()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                assert k not in PT.FORBIDDEN_AGGREGATE_KEYS, k
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(rep)


def test_independent_systems_not_evaluated_and_warnings_kept():
    rep = run()
    e = rep["t_observed_report"]["companies"]["GX"]
    assert e["data_confidence"]["status"] == "not_evaluated"
    assert e["risk_gate"]["final_evaluation"] == "not_evaluated"
    assert any("suspected_unadjusted_gap" in w
               for w in e["risk_gate"]["trading_warnings"])


def test_companies_never_ranked_by_points():
    rep = run()
    companies = rep["t_observed_report"]["companies"]
    assert list(companies) == sorted(companies)  # deterministic cid order
    assert "ranking" not in rep["t_observed_report"]
    assert "ranking" not in rep


def test_display_sample_deterministic_and_bounded():
    rep = run()
    s1 = rep["t_observed_report"]["display_sample"]
    s2 = run()["t_observed_report"]["display_sample"]
    assert s1 == s2
    assert len(s1) <= 24
    assert {"G00", "GX"} & set(s1)


# ---------------------------------------------------------------------------
# engine cross-check
# ---------------------------------------------------------------------------
def test_cross_check_liquidity_agrees_with_engine():
    rep = run()
    x = rep["engine_cross_check"]
    assert x["agreements"]["liquidity"] == 14
    assert x["n_engine_values_seen"]["liquidity"] == 14
    assert x["n_momentum_comparisons"] == 0  # no V1 6m momentum counterpart


def test_cross_check_vol_divergence_documented():
    specs = default_specs()
    specs["G00"]["eng_vol"] = 99.0
    rep = run(specs)
    x = rep["engine_cross_check"]
    assert x["agreements"].get("low_volatility", 0) == 0
    div = [d for d in x["divergences"]
           if d["company_id"] == "G00" and d["what"] == "low_volatility"]
    assert div and "note" in div[0]


# ---------------------------------------------------------------------------
# coverage summary + boundaries
# ---------------------------------------------------------------------------
def test_coverage_summary_census_and_triple_overlap():
    rep = run()
    cov = rep["coverage_summary"]
    census = cov["raw_reason_census"]
    assert census["n_mom6_gap_blocked"] == 1
    assert census["n_mom3_gap_blocked"] == 1
    assert census["n_rs6_gap_blocked"] == 1
    assert census["n_vol_gap_blocked"] == 1
    assert census["n_mom6_insufficient_history"] == 1
    assert cov["n_scored_by_factor"]["momentum_6m_rel"] == 12
    assert cov["n_t_pilot_eligible"] == 12
    assert cov["n_q_axis_pilot_eligible"] == 5
    assert cov["n_v_axis_pilot_eligible"] == 3
    assert cov["n_q_and_v_eligible"] == 3
    assert cov["n_q_v_t_all_eligible"] == 3


def test_run_is_deterministic():
    a = run()
    b = run()
    da = json.dumps(a, sort_keys=True, default=str, ensure_ascii=False)
    db = json.dumps(b, sort_keys=True, default=str, ensure_ascii=False)
    assert da == db


def test_boundaries_preserved_in_report():
    rep = run()
    assert "2-B-8" in rep["not_modified"]
    assert "2-J-1" in rep["not_modified"]
    assert rep["stage"] == "pilot_v2_t_exploratory"
    t = rep["t_observed_report"]
    assert t["summary"]["n_companies_total"] == 14
    assert t["summary"]["n_any_score"] == 14
    assert t["summary"]["n_pilot_eligible"] == 12
    dist = t["summary"]["covered_weight_distribution"]
    assert dist == {"4": 1, "8": 1, "25": 12}
