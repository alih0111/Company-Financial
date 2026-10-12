"""Observed-Q aggregation pilot tests (step 2-B-6) — pure, no database.

Covers score_v2_q_observed.build_q_observed_report() and q_weight_table()
on synthetic raw+normalize worlds shaped exactly like the real pipeline's
output (score_v2_raw.build_q_raw -> score_v2_normalize.normalize_q_cross_
section), plus hand-crafted rollup worlds for exact arithmetic:

  * the general Q weight table sums to exactly 40 and clarifies the
    implementation/aggregation status of roic, margin_trend, roe_stability
    and the two window-audit-blocked factors
  * any weight-table inconsistency STOPS the aggregation
    (QWeightInconsistency) — the table is never auto-fixed
  * the step 2-B-6 conservative policy: earnings_growth's own blended
    scores are preserved as diagnostics but never consumed; no weight is
    redistributed
  * missing is never zero performance; q_observed_points is the plain
    weighted sum (NEVER divided by covered_weight) and can never exceed
    covered_weight
  * blocked / insufficient_peers / score-refused factors never aggregate
  * essential gate + coverage threshold drive pilot_eligible
  * Data Confidence and Risk Gate stay independent: not_evaluated, real
    warnings preserved, no numeric confidence, no risk penalty
  * no final Q/V/T/total key exists anywhere; the only aggregate is
    q_observed_points
  * results are deterministic and independent of input dict order

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2_q_observed.py -q
"""

from __future__ import annotations

import json
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
import score_v2_q_observed as QO  # noqa: E402
import score_v2_raw as SR  # noqa: E402

FORBIDDEN_SCORE_KEYS = {"quality_score", "valuation_score", "timing_score",
                        "total_score", "quant_score", "q_final_score"}

AGGREGABLE = ("roe_level", "margins", "margin_trend", "cash_conversion",
              "leverage", "revenue_growth", "interest_coverage",
              "earnings_quality")


# ---------------------------------------------------------------------------
# synthetic raw+normalize world (the real pipeline, tiny population)
# ---------------------------------------------------------------------------
def base_metrics(**over) -> dict:
    m = {
        "symbol": "SYM", "security_id": "sec",
        "revenue_ttm": 1000.0,
        "net_profit_ttm": 100.0,
        "operating_profit_ttm": 150.0,
        "ocf_ttm": 90.0,
        "debt_ratio": 0.4,
        "roe": 20.0,
        "revenue_growth": 12.0,
    }
    m.update(over)
    return {k: v for k, v in m.items() if v is not ...}


def full_bases() -> dict:
    # net/op feed earnings_growth; op+revenue feed margin_trend
    return {"net_profit_prev": 80.0, "operating_profit_prev": 120.0,
            "revenue_prev": 1000.0}


def eg_only_bases() -> dict:
    # earnings_growth resolvable, margin_trend NOT (no revenue_prev)
    return {"net_profit_prev": 80.0, "operating_profit_prev": 120.0}


def build_world(specs: list) -> tuple:
    """specs: (cid, family, metrics-overrides, bases-or-None) — raw + normalize
    over the REAL layers, general ranks need >= family_min_n (10) peers."""
    metrics, bases, meta = {}, {}, {}
    for cid, family, over, b in specs:
        metrics[cid] = base_metrics(symbol=cid, security_id=f"sec-{cid}",
                                    **over)
        if b:
            bases[cid] = b
        meta[cid] = {"model_family": family,
                     "industry": "Metals" if family == "general" else None}
    raw = SR.build_q_raw(metrics, prev_bases=bases)
    out = SN.normalize_q_cross_section(raw, meta)
    return raw, out, meta


def world_specs() -> list:
    specs = []
    for i in range(12):
        specs.append((f"E{i:02d}", "general",
                      {"net_profit_ttm": 100.0 + 10 * i,
                       "operating_profit_ttm": 150.0 + 10 * i,
                       "ocf_ttm": 90.0 + 5 * i,
                       "debt_ratio": 0.30 + 0.02 * i,
                       "roe": 15.0 + 2 * i,
                       "revenue_growth": 8.0 + 2 * i},
                      full_bases()))
    specs += [
        # missing the essential roe_level -> eligible False, coverage met
        ("NOROE", "general", {"roe": ...}, full_bases()),
        # missing cash only -> covered 24 -> eligible True
        ("NOCASH", "general", {"ocf_ttm": None}, full_bases()),
        # roe + margins only -> covered 13, below threshold
        ("PARTIAL", "general",
         {"ocf_ttm": None, "debt_ratio": None, "revenue_growth": None}, None),
        # nothing measurable -> zero coverage, points None
        ("ZERO", "general",
         {"revenue_ttm": None, "net_profit_ttm": None,
          "operating_profit_ttm": None, "ocf_ttm": None,
          "debt_ratio": None, "roe": None, "revenue_growth": None}, None),
        # a real loss over positive equity: negative ROE stays a valid value
        ("NEGROE", "general", {"roe": -15.0}, None),
        # essentials + cash only (covered 17); with earnings_growth's
        # policy-excluded weight the counterfactual reaches 20 -> delta 1
        ("NOLEV", "general",
         {"debt_ratio": None, "revenue_growth": None}, eg_only_bases()),
        # another model family: never aggregated here
        ("BANK1", "bank", {}, full_bases()),
    ]
    return specs


@pytest.fixture(scope="module")
def world():
    raw, out, meta = build_world(world_specs())
    rep = QO.build_q_observed_report(out, raw, meta,
                                     symbols={cid: cid
                                              for cid in meta})
    return raw, out, meta, rep


def _walk(d):
    if isinstance(d, dict):
        for k, v in d.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(d, (list, tuple)):
        for v in d:
            yield from _walk(v)


# ---------------------------------------------------------------------------
# A. weight table (mission §2)
# ---------------------------------------------------------------------------
def test_weight_table_sums_exactly_to_axis_target():
    t = QO.q_weight_table("general")
    assert t["target_weight"] == 40
    assert t["total_weight"] == 40
    assert set(t["weights"]) == set(CFG.FAMILY_WEIGHTS["general"]) - {
        f for f in CFG.FAMILY_WEIGHTS["general"]
        if CFG.V2_QVT_FACTORS[f]["axis"] != "quality"}
    assert set(t["rows"]) == set(t["weights"])


def test_weight_table_clarifies_blocked_and_parked_factors():
    rows = QO.q_weight_table("general")["rows"]
    assert sorted(f for f, r in rows.items() if r["in_aggregation_scope"]) \
        == sorted(AGGREGABLE)
    # 2-B-7: the expense-TTM pair is inside the aggregation scope now
    assert rows["earnings_quality"]["implementation"] == "implemented"
    assert rows["interest_coverage"]["implementation"] == "implemented"
    assert rows["roe_stability"]["implementation"] == "not_implemented"
    assert rows["earnings_growth"]["implementation"] == "implemented"
    assert rows["earnings_growth"]["scope_category"] == "policy_excluded"
    assert rows["earnings_growth"]["weight"] == 3  # unusable, NOT moved
    assert rows["interest_coverage"]["weight"] == 3  # untouched by 2-B-7
    assert rows["earnings_quality"]["weight"] == 3   # untouched by 2-B-7
    # roic carries a design target but is in no family map
    roic = QO.q_weight_table("general")["factors_not_in_family_map"]["roic"]
    assert roic["target_weight"] == 5
    assert roic["availability"] == "needs_development"
    assert roic["essential"] is False
    assert CFG.AXIS_WEIGHTS["quality"] == 40  # the real target, unchanged


def test_weight_table_stops_on_inconsistent_sum(monkeypatch):
    broken = {**CFG.FAMILY_WEIGHTS,
              "general": {k: v for k, v
                          in CFG.FAMILY_WEIGHTS["general"].items()
                          if k != "earnings_growth"}}   # 40 - 3 = 37
    monkeypatch.setattr(CFG, "FAMILY_WEIGHTS", broken)
    with pytest.raises(QO.QWeightInconsistency):
        QO.q_weight_table("general")


def test_weight_table_stops_on_stale_policy(monkeypatch):
    monkeypatch.setattr(
        SR, "IN_SCOPE_FACTORS",
        tuple(f for f in SR.IN_SCOPE_FACTORS if f != "earnings_growth"))
    with pytest.raises(QO.QWeightInconsistency):
        QO.q_weight_table("general")


def test_weight_table_stops_on_undocumented_raw_scope_gap(monkeypatch):
    monkeypatch.setattr(QO, "_NOT_IN_RAW_SCOPE",
                        {k: v for k, v in QO._NOT_IN_RAW_SCOPE.items()
                         if k != "roe_stability"})
    with pytest.raises(QO.QWeightInconsistency):
        QO.q_weight_table("general")


def test_weight_table_stops_on_stale_blocker_note(monkeypatch):
    monkeypatch.setattr(
        QO, "_NOT_IN_RAW_SCOPE",
        {**QO._NOT_IN_RAW_SCOPE,
         "leverage": ("blocked_at_raw_layer", "stale note")})
    with pytest.raises(QO.QWeightInconsistency):
        QO.q_weight_table("general")


# ---------------------------------------------------------------------------
# B. hand-crafted rollup world — exact arithmetic contracts (mission §4)
# ---------------------------------------------------------------------------
def hand_rollup(status_score, composite=False):
    r = {"composite": composite,
         "normalization_status": ("blended" if composite else "ranked"),
         "warnings": []}
    if composite:
        r["factor_blend_score"] = status_score
        r["blend"] = {"components": {}}
        # the blend-time component detail (where component PIT lives)
        r["components"] = {
            "operating_margin_pct": {"pit_status": "unverified_no_publication_date"},
            "net_margin_pct": {"pit_status": "verified"},
        }
    else:
        r["percentile_combined"] = status_score
    return r


def hand_world():
    factors = {
        "C1": {
            "roe_level": hand_rollup(0.8),
            "margins": hand_rollup(0.5, composite=True),
            # cash_conversion: raw data absent -> honest raw_missing reason
            "cash_conversion": {"composite": False,
                                "normalization_status": "not_ranked_raw_missing",
                                "warnings": []},
            "margin_trend": {"composite": False,
                             "normalization_status": "insufficient_peers",
                             "warnings": []},
            "leverage": {"composite": False,
                         "normalization_status": "ranked",
                         "percentile_combined": 2.5,  # out of range
                         "warnings": []},
            "revenue_growth": {"composite": False,
                               "normalization_status": "not_ranked_raw_missing",
                               "warnings": []},
            # policy-excluded, its own score stays visible
            "earnings_growth": hand_rollup(0.9, composite=True),
            # the 2-B-7 expense pair has no rollup in this hand world: an
            # honest "no normalize rollup" refusal, never a fake score
        },
    }
    return {"records": [], "factors": factors, "as_of": None,
            "pit_policy": "current_exploratory"}


@pytest.fixture()
def hand_rep():
    return QO.build_q_observed_report(hand_world(), {}, {
        "C1": {"model_family": "general", "industry": "Metals"}})


def test_points_are_the_plain_weighted_sum_never_renormalized(hand_rep):
    e = hand_rep["companies"]["C1"]
    # 7*0.8 + 6*0.5 = 8.6 — NOT divided by covered_weight (8.6/0.325 = 26.5)
    assert e["q_observed_points"] == pytest.approx(7 * 0.8 + 6 * 0.5)
    assert e["covered_weight"] == pytest.approx(13.0)
    assert e["coverage_ratio"] == pytest.approx(13.0 / 40.0)
    assert e["missing_weight"] == pytest.approx(27.0)
    assert e["coverage_threshold_met"] is False
    assert e["pilot_eligible"] is False


def test_points_never_exceed_covered_weight(hand_rep):
    e = hand_rep["companies"]["C1"]
    assert e["q_observed_points"] <= e["covered_weight"] + 1e-9


def test_missing_is_never_zero_performance(hand_rep):
    f = hand_rep["companies"]["C1"]["factors"]["cash_conversion"]
    assert f["included"] is False
    assert f["contribution_points"] is None          # no share, not a zero
    assert f["not_included_reason"].startswith("raw_missing")
    assert "zero-performance" in f["not_included_reason"]
    # and the absent weight really is absent from the covered sum
    assert hand_rep["companies"]["C1"]["covered_weight"] == pytest.approx(13)


def test_missing_rollup_gets_an_honest_reason(hand_rep):
    f = hand_rep["companies"]["C1"]["factors"]["cash_conversion"]
    assert f["normalization_status"] == "not_ranked_raw_missing"
    assert f["score"] is None and f["score_kind"] is None


def test_scores_refused_and_insufficient_never_aggregate(hand_rep):
    f = hand_rep["companies"]["C1"]["factors"]
    assert f["leverage"]["included"] is False
    assert f["leverage"]["score"] is None
    assert f["leverage"]["not_included_reason"].startswith("score_refused")
    assert f["margin_trend"]["included"] is False
    assert f["margin_trend"]["not_included_reason"].startswith(
        "insufficient_peers")
    assert f["margin_trend"]["weight"] == 3  # weight untouched, just unused


def test_policy_excluded_factor_score_preserved_never_consumed(hand_rep):
    f = hand_rep["companies"]["C1"]["factors"]["earnings_growth"]
    assert f["score"] == pytest.approx(0.9)          # diagnostic, preserved
    assert f["included"] is False
    assert f["contribution_points"] is None
    assert f["not_included_reason"].startswith("policy_excluded_step_2b6")
    assert f["weight"] == 3
    # the 2-B-7 expense pair: implemented, in scope, but no rollup exists in
    # this hand world — an honest refusal, never a fake score or weight move
    for fid in ("interest_coverage", "earnings_quality"):
        b = hand_rep["companies"]["C1"]["factors"][fid]
        assert b["included"] is False
        assert b["implementation"] == "implemented"
        assert b["in_aggregation_scope"] is True
        assert b["not_included_reason"].startswith("no normalize rollup")
    # config weights reach every company unchanged — no redistribution
    assert {fid: v["weight"]
            for fid, v in hand_rep["companies"]["C1"]["factors"].items()} \
        == QO.q_weight_table("general")["weights"]


def test_only_aggregate_key_is_q_observed_points(hand_rep):
    for k, _v in _walk(hand_rep):
        assert k not in FORBIDDEN_SCORE_KEYS, k
    assert "q_observed_points" in hand_rep["companies"]["C1"]


def test_pit_states_cover_composite_components_and_singles(hand_rep):
    # margins (composite) contributes BOTH components' pit states; the
    # hand world has no normalize records, so singles contribute none there
    dc = hand_rep["companies"]["C1"]["data_confidence"]
    assert dc["pit_status_counts"] == {
        "unverified_no_publication_date": 1, "verified": 1}


# ---------------------------------------------------------------------------
# C. the real-layer world — eligibility, diagnostics, determinism
# ---------------------------------------------------------------------------
def test_world_summary_counts(world):
    _raw, _out, _meta, rep = world
    s = rep["summary"]
    assert s["n_companies_total"] == 19
    assert s["n_general"] == 18
    assert s["n_family_out_of_scope"] == 1
    # eligible: E00..E11 (28) + NOCASH (24) + NEGROE (25)
    assert s["n_pilot_eligible"] == 14
    assert s["n_essentials_satisfied"] == 16
    # coverage>=50%: E(28)x12 + NOROE (21) + NOCASH (24) + NEGROE (25);
    # NOROE still fails the essential gate, so eligible stays 14
    assert s["n_coverage_threshold_met"] == 15
    assert s["n_any_score"] == 17
    assert s["n_zero_coverage"] == 1
    assert s["max_covered_weight_observed"] == pytest.approx(28.0)
    assert s["covered_weight_distribution"] == {
        "0": 1, "13": 1, "17": 1, "21": 1, "24": 1, "25": 1, "28": 12}
    assert s["n_scored_by_factor"] == {
        "roe_level": 16, "margins": 17, "cash_conversion": 15,
        "leverage": 15, "revenue_growth": 15, "margin_trend": 14}
    # the policy-excluded factor is never counted as scored
    assert "earnings_growth" not in s["n_scored_by_factor"]


def test_policy_effect_counterfactual(world):
    _raw, _out, _meta, rep = world
    eff = rep["summary"]["eligibility_policy_effect"]
    # NOLEV (covered 17) would clear the 50% bar only with earnings_growth
    assert eff["n_eligible_under_policy"] == 14
    assert eff["n_eligible_if_policy_exclusions_lifted"] == 15
    assert eff["delta"] == 1


def test_company_entries_eligibility_and_essential_gate(world):
    _raw, _out, _meta, rep = world
    c = rep["companies"]
    ok = c["E00"]
    assert ok["pilot_eligible"] is True
    assert ok["essential_status"] == {"required": ["margins", "roe_level"],
                                      "missing": [],
                                      "all_satisfied": True}
    assert ok["coverage_threshold_met"] is True
    assert ok["q_observed_points"] <= ok["covered_weight"] + 1e-9
    assert ok["covered_weight"] == pytest.approx(28.0)
    no_roe = c["NOROE"]
    assert no_roe["essential_status"]["missing"] == ["roe_level"]
    assert no_roe["essential_status"]["all_satisfied"] is False
    assert no_roe["coverage_threshold_met"] is True   # 21/40 = 0.525
    assert no_roe["pilot_eligible"] is False          # essential gate closes
    neg = c["NEGROE"]
    assert neg["factors"]["roe_level"]["included"] is True  # valid loss data
    zero = c["ZERO"]
    assert zero["q_observed_points"] is None          # no score from no data
    assert zero["covered_weight"] == 0.0
    assert zero["coverage_ratio"] == 0.0
    assert zero["essential_status"]["missing"] == ["margins", "roe_level"]
    bank = c["BANK1"]
    assert bank["aggregation_status"] == "family_out_of_scope"
    assert "q_observed_points" not in bank


def test_negative_roe_is_a_value_not_a_disqualification(world):
    raw, _out, _meta, rep = world
    assert raw["NEGROE"]["roe_level"]["status"] == "valid"
    assert raw["NEGROE"]["roe_level"]["raw_value"] == pytest.approx(-15.0)
    # the loss ranks low (higher-is-better) but it ranks — it is data
    assert rep["companies"]["NEGROE"]["factors"]["roe_level"]["score"] \
        is not None
    assert rep["companies"]["NEGROE"]["q_observed_points"] is not None


def test_zero_coverage_produces_no_score_not_a_zero(world):
    _raw, _out, _meta, rep = world
    e = rep["companies"]["ZERO"]
    assert e["aggregation_status"] == "aggregated"
    assert e["q_observed_points"] is None
    assert all(f["included"] is False for f in e["factors"].values())
    assert e["diagnostic_counts"].get("missing", 0) >= 4


def test_data_confidence_stays_independent(world):
    _raw, _out, _meta, rep = world
    for cid in ("E00", "ZERO"):
        dc = rep["companies"][cid]["data_confidence"]
        assert dc["status"] == "not_evaluated"
        assert set(dc) == {"status", "covered_weight", "coverage_ratio",
                           "pit_status_counts", "missing_reasons", "note"}
        assert isinstance(dc["pit_status_counts"], dict)
        assert isinstance(dc["missing_reasons"], dict)
    # reasons name the real gaps
    zr = rep["companies"]["ZERO"]["data_confidence"]["missing_reasons"]
    assert zr["roe_level"].startswith("raw_missing")
    assert zr["cash_conversion"].startswith("raw_missing")


def test_risk_gate_not_evaluated_with_real_warnings_only(world):
    _raw, _out, _meta, rep = world
    for cid in ("E00", "ZERO"):
        rg = rep["companies"][cid]["risk_gate"]
        assert rg["status"] == "not_evaluated"
        assert rg["final_evaluation"] == "not_evaluated"
        # no warnings is NEVER a clearance verdict
        assert "low_risk" not in rg and "risk_cleared" not in rg
        assert "no risk penalty" in rg["note"]
    assert rep["companies"]["E00"]["risk_gate"]["financial_warnings"] == []
    assert rep["companies"]["E00"]["risk_gate"]["flags"] == {}


def test_risk_gate_reports_real_distress_when_present():
    # an isolated world: negative equity + a magnitude anomaly, really emitted
    specs = [(f"R{i:02d}", "general", {}, None) for i in range(10)]
    specs.append(("RISKY", "general",
                  {"debt_ratio": 1.5, "roe": 1500.0}, None))
    raw, out, meta = build_world(specs)
    rep = QO.build_q_observed_report(out, raw, meta)
    rg = rep["companies"]["RISKY"]["risk_gate"]
    assert rg["status"] == "not_evaluated"          # evidence only, no verdict
    assert any(w.startswith("negative_equity") for w in rg["financial_warnings"])
    assert rg["flags"]["negative_equity"] == 1
    assert rg["flags"]["magnitude_anomaly"] >= 1
    # the warnings did not touch the points: no penalty keys anywhere
    e = rep["companies"]["RISKY"]
    assert e["q_observed_points"] <= e["covered_weight"] + 1e-9
    clean = rep["companies"]["R00"]["risk_gate"]
    assert clean["financial_warnings"] == []
    assert clean["final_evaluation"] == "not_evaluated"


def test_report_is_deterministic_and_order_independent():
    raw, out, meta = build_world(world_specs())
    rep_a = QO.build_q_observed_report(out, raw, meta)
    rep_b = QO.build_q_observed_report(out, raw, meta)
    assert json.dumps(rep_a, sort_keys=True) == json.dumps(rep_b,
                                                           sort_keys=True)
    # reversed construction order must not move a single number
    specs = list(reversed(world_specs()))
    raw_r, out_r, meta_r = build_world(specs)
    rep_r = QO.build_q_observed_report(out_r, raw_r, meta_r)
    assert json.dumps(rep_a, sort_keys=True) == json.dumps(rep_r,
                                                           sort_keys=True)


def test_display_sample_is_deterministic_variety_not_a_ranking(world):
    _raw, _out, _meta, rep = world
    picks = rep["display_sample"]
    assert len(picks) == 19          # the whole world (limit 20 > population)
    assert len(set(picks)) == 19
    assert picks[:4] == ["E00", "NOROE", "NOLEV", "BANK1"]  # round-robin
    assert "ZERO" in picks           # an essential-gap company
    assert picks == QO.select_display_sample(rep["companies"], 20)
    assert picks == QO.select_display_sample(
        {k: rep["companies"][k] for k in reversed(list(rep["companies"]))}, 20)
    # the sample carries no rank field and no order semantics beyond display
    for cid in picks:
        assert "rank" not in rep["companies"][cid]


def test_walk_whole_report_no_forbidden_keys_and_scores_in_range(world):
    _raw, _out, _meta, rep = world
    for k, _v in _walk(rep):
        assert k not in FORBIDDEN_SCORE_KEYS, k
    # every consumed "score" is a normalized [0, 1] value
    for cid, e in rep["companies"].items():
        for fid, f in (e.get("factors") or {}).items():
            if f["included"]:
                assert isinstance(f["score"], float)
                assert 0.0 <= f["score"] <= 1.0
                assert f["contribution_points"] \
                    == pytest.approx(f["weight"] * f["score"])


def test_coverage_threshold_override_is_validated(world):
    raw, out, meta = build_world(world_specs())
    with pytest.raises(ValueError):
        QO.build_q_observed_report(out, raw, meta, coverage_threshold=0.0)
    strict = QO.build_q_observed_report(out, raw, meta,
                                        coverage_threshold=0.7)
    # 28/40 = 0.7 still clears at exactly the threshold; 25 does not
    assert strict["companies"]["E00"]["pilot_eligible"] is True
    assert strict["companies"]["NEGROE"]["pilot_eligible"] is False
    assert strict["summary"]["n_pilot_eligible"] == 12
