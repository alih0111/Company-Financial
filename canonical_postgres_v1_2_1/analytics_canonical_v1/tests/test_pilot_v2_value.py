"""Observed-V pilot tests (step 2-J-1) — pure, no database.

Covers pilot_v2_value on synthetic worlds shaped exactly like the real
pipeline's inputs (engine metrics + market channel + report index stubs):

  * every family's V weight table sums to exactly 35 and carries only the
    READY raw-scope factors; any inconsistency STOPS the aggregation
    (VWeightInconsistency) — never auto-fixed; ev_ebit / fcf_yield stay in
    no family map and are never scored (needs_development)
  * v_observed_points is the plain weighted sum over scored factors (never
    divided by covered_weight, never renormalized), a missing factor has no
    score share, companies are never ranked by points
  * the essential gate (pe + pb) and the 0.50 coverage threshold drive
    pilot_eligible
  * Data Confidence and Risk Gate stay not_evaluated; real warnings are
    preserved; no numeric confidence or penalty touches the points
  * no forbidden aggregate key exists anywhere (no valuation_score / v_final
    / qvt total / Q+V combination)
  * the market channel resolves ONLY from engine-owned rows and records
    price trade date, share snapshot date, their gap and the freshness diag
  * equity resolution reads the engine's OWN latest report cell (max
    fy*12+fm), and a company without total_equity gets no entry
  * the sentinel-leg audit names the exact consumed legs per resolution path
  * the engine cross-check verifies the raw construction against the
    engine's own direct valuation and lists divergences loudly
  * the coverage summary answers the mission's counting questions and the
    Q-axis overlap stays a COUNT (the axes are never combined)
  * an end-to-end stub-engine run produces the full report deterministically

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_pilot_v2_value.py -q
"""

from __future__ import annotations

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
import score_v2_normalize as SN  # noqa: E402
import score_v2_value_raw as VRW  # noqa: E402
import pilot_v2_value as PV  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc)
PTD = dt.date(2026, 10, 5)

FORBIDDEN_AGGREGATE_KEYS = {"valuation_score", "v_final_score",
                            "v_final", "total_score", "qvt_score",
                            "qvt_total", "quality_score", "timing_score",
                            "quant_score", "qv_score", "q_plus_v"}


def channel(price=10.0, shares=1000.0):
    return {"price": price, "price_trade_date": PTD,
            "price_collected_at": dt.datetime(2026, 10, 5, 18, 0,
                                              tzinfo=dt.timezone.utc),
            "price_age_days": 3, "shares": shares,
            "share_source": "TSETMC_ZTITAD_CURRENT",
            "share_source_date": PTD, "share_price_gap_days": 0,
            "share_cross_check": "AGREE"}


def raw_world(peers: dict):
    """Real raw + normalize output over synthetic general peers. Each peer:
    np (net profit TTM), price, shares, industry; mcap = 10,000 unless
    price/shares overridden."""
    import score_v2_value_normalize as VN
    metrics, meta, market, equity = {}, {}, {}, {}
    for cid, p in peers.items():
        metrics[cid] = {"net_profit_ttm": p["np"],
                        "revenue_ttm": p.get("rev", p["np"] * 5.0)}
        meta[cid] = {"model_family": p.get("family", "general"),
                     "industry": p.get("industry", "صنعت مشترک")}
        market[cid] = channel(price=p.get("price", 10.0),
                              shares=p.get("shares", 1000.0))
        equity[cid] = {"equity": p.get("eq", 5000.0),
                       "period_end_date": dt.date(2026, 7, 31)}
    raw = VRW.build_v_raw(metrics, meta, market=market,
                          equity_by_company=equity, as_of=AS_OF,
                          cutoff=CUTOFF)
    norm = VN.normalize_v_cross_section(raw, meta, as_of=CUTOFF)
    return raw, meta, norm


# ---------------------------------------------------------------------------
# weight tables
# ---------------------------------------------------------------------------
def test_every_family_v_table_sums_to_exactly_35():
    for fam in CFG.FAMILIES:
        t = PV.v_weight_table(fam)
        assert t["target_weight"] == 35
        assert t["total_weight"] == 35
        assert set(t["weights"]) <= {"pe", "pb", "ps"}
        for fid, w in t["weights"].items():
            assert CFG.FAMILY_WEIGHTS[fam][fid] == w


def test_general_vs_specialized_maps_and_blocked_planned_factors():
    g = PV.v_weight_table("general")
    assert g["weights"] == {"pb": 12, "pe": 13, "ps": 10}
    for fam in ("bank", "insurance", "investment"):
        t = PV.v_weight_table(fam)
        assert t["weights"] == {"pb": 22, "pe": 13}
        assert "ps" not in t["weights"]
    planned = g["factors_not_in_family_map"]
    assert set(planned) == {"ev_ebit", "fcf_yield"}
    for fid, spec in planned.items():
        assert spec["availability"] == CFG.NEEDS_DEVELOPMENT


def test_broken_v_weight_table_stops_aggregation(monkeypatch):
    broken = dict(CFG.FAMILY_WEIGHTS["general"])
    broken["pe"] = 40  # sum != 35
    monkeypatch.setitem(CFG.FAMILY_WEIGHTS, "general", broken)
    with pytest.raises(PV.VWeightInconsistency):
        PV.v_weight_table("general")
    planned_leak = dict(CFG.FAMILY_WEIGHTS["general"])
    planned_leak["ev_ebit"] = 1  # needs_development must never be mapped
    monkeypatch.setitem(CFG.FAMILY_WEIGHTS, "general", planned_leak)
    with pytest.raises(PV.VWeightInconsistency):
        PV.v_weight_table("general")


# ---------------------------------------------------------------------------
# score admission + aggregation arithmetic
# ---------------------------------------------------------------------------
def _rollup(status, pct):
    return {"normalization_status": status, "percentile_combined": pct}


def test_score_admission_refuses_bad_scores():
    assert PV._scored_factor(_rollup(SN.NR_RANKED, 0.5)) == (0.5,
                                                             "percentile_combined")
    assert PV._scored_factor(_rollup(SN.NR_RANKED, None)) == (None, None)
    assert PV._scored_factor(_rollup(SN.NR_RANKED, 1.5)) == (None, None)
    assert PV._scored_factor(_rollup(SN.NR_RANKED, float("nan"))) == \
        (None, None)
    assert PV._scored_factor(_rollup(SN.NR_INSUFFICIENT_PEERS, None)) == \
        (None, None)
    assert PV._scored_factor(None) == (None, None)


def test_points_are_plain_weighted_sum_never_renormalized():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)
    # every peer: pe/pb/ps all valid and ranked -> covered 35, points < 35
    for cid, e in report["companies"].items():
        assert e["covered_weight"] == 35.0
        assert e["missing_weight"] == 0.0
        assert e["v_observed_points"] == pytest.approx(sum(
            e["factors"][f]["contribution_points"]
            for f in ("pe", "pb", "ps")))
        assert e["v_observed_points"] <= e["covered_weight"]
        assert e["pilot_eligible"] is True
        assert e["coverage_ratio"] == pytest.approx(1.0)


def test_missing_factor_has_no_score_share_and_essential_gate_bites():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    # loss maker with a HEALTHY revenue line: pe refused, pb/ps computable
    peers["G07"] = {"np": -500.0, "rev": 2000.0}
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)
    e = report["companies"]["G07"]
    assert e["covered_weight"] == 22.0  # pb 12 + ps 10, pe 13 never moved
    assert e["missing_weight"] == 13.0
    assert e["v_observed_points"] == pytest.approx(sum(
        e["factors"][f]["contribution_points"] for f in ("pb", "ps")))
    assert e["v_observed_points"] is not None
    # pe is ESSENTIAL: eligible False even with 22/35 covered (>= 0.5)
    assert e["essential_status"]["missing"] == ["pe"]
    assert e["pilot_eligible"] is False
    reason = e["factors"]["pe"]["not_included_reason"]
    assert "not_applicable" in reason
    assert e["factors"]["pe"]["weight"] == 13  # weight preserved, not moved


def test_coverage_threshold_refuses_partial_coverage():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    # pe AND pb both refused (loss + negative book) but ps fine with
    # positive revenue: only ps (10) covers — below the 17.5 threshold
    peers["G03"] = {"np": -1.0, "rev": 2000.0, "eq": -1.0}
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)
    e = report["companies"]["G03"]
    assert e["covered_weight"] == 10.0
    assert e["coverage_threshold_met"] is False
    assert e["pilot_eligible"] is False
    assert set(e["essential_status"]["missing"]) == {"pe", "pb"}


def test_insufficient_peers_yields_no_score_and_no_points():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(9)}
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)
    e = report["companies"]["G00"]
    assert e["covered_weight"] == 0.0
    assert e["v_observed_points"] is None
    assert e["diagnostic_counts"] == {"insufficient_peers": 3}
    assert e["pilot_eligible"] is False
    assert report["summary"]["n_any_score"] == 0


def test_no_ranking_of_companies_and_no_forbidden_keys():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)

    def _walk(node):
        if isinstance(node, dict):
            for k in node:
                assert k not in FORBIDDEN_AGGREGATE_KEYS, k
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)
    _walk(report)
    # companies are stored in company-id order and carry no rank field
    ids = list(report["companies"])
    assert ids == sorted(ids)
    assert all("rank" not in k for e in report["companies"].values()
               for k in e)
    assert report["summary"]["policy"]["ranking"].startswith(
        "companies are never ranked")


def test_independent_systems_stay_not_evaluated():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    raw, meta, norm = raw_world(peers)
    raw["G02"]["pe"]["warnings"] = ["stale_price: latest trade is 30 days "
                                    "before as_of"]
    report = PV.build_v_observed_report(norm, raw, meta)
    e = report["companies"]["G02"]
    assert e["data_confidence"]["status"] == "not_evaluated"
    assert e["risk_gate"]["status"] == "not_evaluated"
    assert e["risk_gate"]["final_evaluation"] == "not_evaluated"
    assert any(w.startswith("stale_price")
               for w in e["risk_gate"]["financial_warnings"])
    assert e["v_observed_points"] is not None  # warnings never touch points


def test_display_sample_deterministic_bucket_round_robin():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    peers["G07"]["np"] = -500.0
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta, display_limit=5)
    picks = report["display_sample"]
    assert len(picks) == 5
    assert picks == PV.select_display_sample(report["companies"], 5)
    # eligible bucket first, deterministic company-id order inside buckets
    assert report["companies"][picks[0]]["pilot_eligible"] is True


# ---------------------------------------------------------------------------
# engine-adjacent resolution
# ---------------------------------------------------------------------------
def _stub_engine(peers):
    """A stub with the engine attributes the pilot reads: metrics, prices,
    current_shares, stmt, codal_titles, subjects, report_index()."""
    securities = {cid: f"sec-{cid}" for cid in peers}
    prices = []
    for cid, p in peers.items():
        prices.append({"security_id": securities[cid],
                       "trade_date": p.get("ptd", PTD),
                       "collected_at": dt.datetime(2026, 10, 5, 18, 0,
                                                   tzinfo=dt.timezone.utc),
                       "closing_price_rial": p.get("price", 10.0),
                       "last_price_rial": p.get("price", 10.0)})
    current_shares = {securities[cid]: {
        "shares": 1000.0, "source": "TSETMC_ZTITAD_CURRENT",
        "collected_at": dt.datetime(2026, 10, 2, 15, 0,
                                    tzinfo=dt.timezone.utc),
        "source_as_of": None, "fallback_used": False,
        "cross_check_status": "TSETMC_ONLY"} for cid in peers}
    rep_index = {}
    for cid, p in peers.items():
        rep_index[cid] = {
            (1405, 6): {"_period": dt.date(2026, 8, 31), "_ver": 1,
                        "total_equity": {1: p.get("eq"),
                                         2: None, 3: None}},
            (1404, 12): {"_period": dt.date(2026, 3, 20), "_ver": 1,
                         "net_profit": {1: p.get("np", 100.0)}},
        }
    metrics = {}
    for cid, p in peers.items():
        eq_val = p.get("eq")
        np_val = p.get("np", 100.0)
        rev_val = p.get("rev", np_val * 5.0)
        mcap = p.get("price", 10.0) * 1000.0
        metrics[cid] = {
            "security_id": securities[cid],
            "latest_price": p.get("price", 10.0),
            "shares_outstanding": 1000.0,
            "net_profit_ttm": np_val,
            "revenue_ttm": rev_val,
            "market_cap": mcap,
            # the REAL engine's own gates (compute_metrics.direct_valuation):
            # pe exists for any nonzero profit (negative for a loss maker),
            # ps needs revenue > 0, pb needs equity > 0
            "pe": (mcap / np_val) if np_val not in (None, 0) else None,
            "ps": (mcap / rev_val)
            if (rev_val is not None and rev_val > 0) else None,
            "pb": (mcap / eq_val) if (eq_val and eq_val > 0) else None,
            "_valuation_prov": {"share_source": "TSETMC_ZTITAD_CURRENT"},
            "_ttm_prov": {"net_profit_ttm": "DIRECT_CANONICAL"},
        }
    return SimpleNamespace(
        metrics=metrics, prices=prices, current_shares=current_shares,
        stmt=[], codal_titles=[], subjects={},
        superseded=set(), compute=lambda: None,
        report_index=lambda: rep_index)


def test_build_market_channel_from_engine_rows():
    eng = _stub_engine({"G00": {}, "G01": {"price": 0.0}})
    ch, diag = PV.build_market_channel(eng, AS_OF)
    assert ch["G00"]["price"] == 10.0
    assert ch["G00"]["price_trade_date"] == PTD
    assert ch["G00"]["price_age_days"] == 3
    assert ch["G00"]["shares"] == 1000.0
    # share snapshot (10-02) is 3 days older than the price date (10-05)
    assert ch["G00"]["share_price_gap_days"] == 3
    assert ch["G01"]["price"] == 0.0  # echoed verbatim; the raw gate refuses
    assert diag["n_with_price"] == 2
    assert diag["n_with_shares"] == 2
    assert diag["n_with_both"] == 2
    assert diag["n_share_older_than_price"] == 2
    assert diag["n_price_after_as_of"] == 0


def test_resolve_equity_reads_engine_latest_cell_only():
    eng = _stub_engine({"G00": {"eq": 7777.0}, "G01": {"eq": None}})
    eq = PV.resolve_equity(eng)
    assert eq["G00"] == {"equity": 7777.0,
                         "period_end_date": dt.date(2026, 8, 31)}
    assert "G01" not in eq  # no total_equity -> no entry, never 0


def test_sentinel_leg_audit_names_exact_legs_per_path():
    eng = _stub_engine({"G00": {}, "G01": {}})
    eng.metrics["G00"]["_ttm_prov"]["net_profit_ttm"] = "DIRECT_CANONICAL"
    eng.metrics["G01"]["_ttm_prov"]["net_profit_ttm"] = "REPORT_CHAIN_TTM"
    sentinel_cells = {
        "G00": {(1405, 6, "net_profit", 2)},               # direct: o2 leg
        "G01": {(1404, 6, "net_profit", 1)},               # chain prior-ytd
    }
    legs, diag = PV.net_profit_sentinel_legs(eng, sentinel_cells, {})
    assert legs["G00"] == ["net_profit@1405/6(order 2)"]
    assert legs["G01"] == ["net_profit@1404/6(order 1)"]
    assert diag["n_with_sentinel_legs"] == 2
    # an unresolved TTM never produces legs
    eng.metrics["G00"]["_ttm_prov"]["net_profit_ttm"] = \
        "MISSING_PRIOR_ANNUAL"
    legs, diag = PV.net_profit_sentinel_legs(eng, sentinel_cells, {})
    assert "G00" not in legs
    assert legs.get("G01") == ["net_profit@1404/6(order 1)"]
    assert diag["n_unresolved_ttm"] == 1


def test_engine_cross_check_agrees_and_lists_divergences():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0, "eq": 5000.0}
             for i in range(4)}
    eng = _stub_engine(peers)
    raw = VRW.build_v_raw(
        eng.metrics, {c: {"model_family": "general"} for c in peers},
        market={c: channel() for c in peers},
        equity_by_company={c: {"equity": 5000.0,
                               "period_end_date": dt.date(2026, 7, 31)}
                           for c in peers},
        as_of=AS_OF, cutoff=CUTOFF)
    cross = PV.engine_cross_check(raw, eng)
    assert cross["n_mismatches"] == 0
    assert cross["agreements"]["market_cap"] == 4
    assert cross["agreements"]["pe"] == 4
    assert cross["agreements"]["pb"] == 4
    assert cross["agreements"]["ps"] == 4
    # a raw refusal where the engine has a value is listed, not hidden
    raw2 = VRW.build_v_raw(
        eng.metrics, {c: {"model_family": "general"} for c in peers},
        market={c: channel() for c in peers},
        equity_by_company={c: {"equity": 5000.0,
                               "period_end_date": dt.date(2026, 7, 31)}
                           for c in peers},
        as_of=AS_OF, cutoff=CUTOFF)
    raw2["G00"]["pe"]["status"] = "not_applicable"
    raw2["G00"]["pe"]["raw_value"] = None
    cross2 = PV.engine_cross_check(raw2, eng)
    assert cross2["n_mismatches"] == 1
    assert cross2["mismatches"][0]["what"] == "pe"


# ---------------------------------------------------------------------------
# coverage summary + Q overlap
# ---------------------------------------------------------------------------
def test_coverage_summary_answers_mission_questions():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    peers["G07"] = {"np": -500.0, "rev": 2000.0}     # negative profit
    peers["G08"] = {"np": 100.0, "price": 0.0}       # invalid price
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)
    summary = PV.build_coverage_summary(raw, report, q_eligible=None)
    assert summary["n_pe_valid"] == 10   # 12 - loss maker - zero price
    assert summary["n_pb_valid"] == 11
    assert summary["n_ps_valid"] == 11
    assert summary["n_all_three_valid"] == 10
    assert summary["n_blocked_negative_net_profit"] == 1
    assert summary["n_no_price_data"] == 0  # a zero price is invalid, not absent
    assert summary["n_scored_by_factor"]["pe"] == 10


def test_q_overlap_is_a_count_never_a_combination():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    raw, meta, norm = raw_world(peers)
    report = PV.build_v_observed_report(norm, raw, meta)
    summary = PV.build_coverage_summary(raw, report,
                                        q_eligible={"G00", "G01", "MISSING"})
    assert summary["n_q_axis_pilot_eligible"] == 3
    assert summary["n_q_eligible_with_any_v_points"] == 2
    assert summary["n_q_eligible_also_v_eligible"] == 2


def test_load_q_eligible_reads_saved_artifact(tmp_path):
    artifact = {"stage": "q_observed_pilot", "as_of": "2026-10-08 "
                                                        "23:59:00+00:00",
                "companies": {"A": {"pilot_eligible": True},
                              "B": {"pilot_eligible": False},
                              "C": {"pilot_eligible": True}}}
    p = tmp_path / "q_report.json"
    p.write_text(json.dumps(artifact), encoding="utf-8")
    eligible, diag = PV.load_q_eligible(p)
    assert eligible == {"A", "C"}
    assert diag["n_pilot_eligible"] == 2


# ---------------------------------------------------------------------------
# end-to-end through run_value_pilot with a stub engine
# ---------------------------------------------------------------------------
def test_run_value_pilot_end_to_end_stub():
    peers = {f"G{i:02d}": {"np": 100.0 + i * 10.0} for i in range(12)}
    peers["G11"] = {"np": -900.0, "rev": 2000.0}  # one loss maker, healthy rev
    for p in peers.values():
        p.setdefault("eq", 5000.0)  # every stub company carries book value
    eng = _stub_engine(peers)
    eng.compute = lambda: None  # the stub engine arrives pre-computed
    report = PV.run_value_pilot(AS_OF, CUTOFF, engine=eng, sector_map={},
                                q_eligible={"G00", "G01"})
    assert report["stage"] == "pilot_v2_value_exploratory"
    for fam in CFG.FAMILIES:
        assert report["weight_tables"][fam]["total_weight"] == 35
    vs = report["v_observed_report"]["summary"]
    assert vs["n_companies_total"] == 12
    assert vs["n_pilot_eligible"] == 11
    assert report["engine_cross_check"]["n_mismatches"] == 1
    m = report["engine_cross_check"]["mismatches"][0]
    # the ONLY divergence is the loss maker: the engine carries a negative
    # P/E, the raw layer refuses it by design (stricter, not arithmetic)
    assert m["company_id"] == "G11" and m["what"] == "pe"
    cov = report["coverage_summary"]
    assert cov["n_blocked_negative_net_profit"] == 1
    assert cov["n_q_eligible_with_any_v_points"] == 2
    assert "not_modified" in report
    # determinism: same inputs -> identical points
    again = PV.run_value_pilot(AS_OF, CUTOFF, engine=_stub_engine(peers),
                               sector_map={}, q_eligible={"G00", "G01"})
    a = {c: e["v_observed_points"] for c, e
         in report["v_observed_report"]["companies"].items()}
    b = {c: e["v_observed_points"] for c, e
         in again["v_observed_report"]["companies"].items()}
    assert a == b
