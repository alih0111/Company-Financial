"""Pilot tests for pilot_v2_qvt (step 2-B-4) — pure fixtures, NO database.

Covers the pilot's own additive logic only (the underlying raw / normalize
layers have their own suites, which must keep passing untouched):

  * resolve_prev_bases: the engine's own prior-year TTM replication, the
    provenance-code cross-check (a diverging base is DROPPED, never trusted),
    the no-guess fiscal guard and missing-report handling.
  * build_provenance: REAL collected_at timestamps only, superseded rows
    excluded, never a fabricated source_ref.
  * build_company_meta: real industry passthrough, unknown industry ->
    general/unclassified (contract behavior, never an invented group).
  * reason_bucket: honest, distinguishable refusal categories.
  * run_pilot end-to-end on an injected fake engine: full population report
    with composite blends for general only, explicit refusals, NO final
    Q/V/T/total score anywhere, every score finite in [0,1], JSON-serializable.
  * read-only static guard: the pilot module performs no SQL execution and
    never calls the metrics engine's store path.

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_pilot_v2_qvt.py -q
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import pilot_v2_qvt as PILOT  # noqa: E402
import report_chain_ttm as RC  # noqa: E402

AS_OF = dt.date(2026, 9, 24)
CUTOFF = dt.datetime(2026, 9, 24, 20, 41, 2, tzinfo=dt.timezone.utc)
COLLECTED = dt.datetime(2026, 9, 10, 8, 0, 0, tzinfo=dt.timezone.utc)

FORBIDDEN_SCORE_KEYS = {"quality_score", "valuation_score", "timing_score",
                        "total_score", "quant_score"}


# ---------------------------------------------------------------------------
# fixture: a tiny canonical world shaped like Engine.compute() output
# ---------------------------------------------------------------------------
def cell(net=None, op=None, rev=1000.0):
    d = {}
    if net is not None:
        d["net_profit"] = {1: net}
    if op is not None:
        d["operating_profit"] = {1: op}
    if rev is not None:
        d["revenue"] = {1: rev}
    return d


def rep_for(net_base=40.0, op_base=70.0):
    """Latest annual cell (1404,12) + prior annual (1403,12): the prev-year
    TTM resolves DIRECT for both profit metrics. Since 2-B-7 the latest cell
    also carries the expense lines' order-1 values (an fm=12 report's annual
    order-1 IS the same-window expense TTM)."""
    return {(1404, 12): {**cell(net=100.0, op=120.0),
                         "finance_cost": {1: -25.0},
                         "other_non_operating": {1: 6.0}},
            (1403, 12): cell(net=net_base, op=op_base)}


def prev_prov_codes(rep):
    """The provenance codes the real engine would have recorded for the
    prev-year TTM tags (the same resolution the pilot replicates). Since
    2-B-5 this includes revenue_prev (margin_trend's prior-year base)."""
    prov = {}
    latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
    prev = (latest[0] - 1, latest[1])
    for metric, tag in (("net_profit", "net_profit_prev"),
                        ("operating_profit", "operating_profit_prev"),
                        ("revenue", "revenue_prev")):
        v, p = RC.resolve_ttm(rep, metric, *prev)
        if v is not None:
            prov[tag] = p
    return prov


def make_world():
    """15 companies: 12 healthy general (metals/chemicals), 1 general with a
    missing net profit (one-component reality), 1 general interim (fm=9)
    reporter whose other_nonop comparable leg is absent, 1 bank (no blend
    contract)."""
    metrics, rep_index, subjects, stmt, sector_map = {}, {}, {}, [], {}
    for i in range(12):
        cid = f"G{i:02d}"
        metrics[cid] = {
            "symbol": f"SYM{i:02d}", "security_id": f"sec-{i}",
            "revenue_ttm": 1000.0,
            "net_profit_ttm": 50.0 + 10 * i,
            "operating_profit_ttm": 80.0 + 10 * i,
            "ocf_ttm": 40.0 + 5 * i,
            "debt_ratio": 0.30 + 0.03 * i,
            "net_profit_growth": 25.0,        # engine percents — the raw
            "operating_profit_growth": 14.0,  # layer must ignore them
        }
        rep_index[cid] = rep_for()
        subjects[cid] = {"symbol": f"SYM{i:02d}",
                         "display_name": f"Company {i}"}
        stmt.append({"company_id": cid, "report_id": f"r-{cid}",
                     "collected_at": COLLECTED})
        sector_map[cid] = "فلزات" if i < 6 else "شیمی"
    metrics["BROKE"] = {
        "symbol": "BROKE1", "security_id": "sec-b",
        "revenue_ttm": 500.0, "net_profit_ttm": None,
        "operating_profit_ttm": 60.0, "ocf_ttm": None,
        "debt_ratio": 0.5, "net_profit_growth": None,
        "operating_profit_growth": 10.0,
    }
    rep_index["BROKE"] = rep_for()
    subjects["BROKE"] = {"symbol": "BROKE1", "display_name": "Broken Co"}
    stmt.append({"company_id": "BROKE", "report_id": "r-BROKE",
                 "collected_at": COLLECTED})
    metrics["INT9"] = {
        "symbol": "INT91", "security_id": "sec-i",
        "revenue_ttm": 1000.0, "net_profit_ttm": 45.0,
        "operating_profit_ttm": 90.0, "ocf_ttm": 45.0,
        "debt_ratio": 0.4, "revenue_growth": 15.0,
        "net_profit_growth": None, "operating_profit_growth": None,
    }
    # interim (fm=9) latest report: finance_cost carries all three legs (the
    # within-report TTM resolves), other_non_operating is missing its
    # order-2 comparative (the channel honestly stays unresolved)
    rep_index["INT9"] = {
        (1404, 9): {"net_profit": {1: 45.0}, "operating_profit": {1: 90.0},
                    "revenue": {1: 1000.0},
                    "finance_cost": {1: -30.0, 2: -10.0, 3: -100.0},
                    "other_non_operating": {1: 20.0, 3: 10.0}},
        (1403, 9): {"net_profit": {1: 40.0, 2: 10.0, 3: 35.0},
                    "operating_profit": {1: 70.0, 2: 20.0, 3: 65.0},
                    "revenue": {1: 1000.0, 2: 900.0, 3: 980.0}},
    }
    subjects["INT9"] = {"symbol": "INT91", "display_name": "Interim Co"}
    stmt.append({"company_id": "INT9", "report_id": "r-INT9",
                 "collected_at": COLLECTED})
    sector_map["INT9"] = "شیمی"
    metrics["BANK"] = {
        "symbol": "BANK1", "security_id": "sec-k",
        "revenue_ttm": 900.0, "net_profit_ttm": 70.0,
        "operating_profit_ttm": 90.0, "ocf_ttm": 50.0,
        "debt_ratio": 0.6, "net_profit_growth": 12.0,
        "operating_profit_growth": 8.0,
    }
    rep_index["BANK"] = rep_for()
    subjects["BANK"] = {"symbol": "BANK1", "display_name": "A Bank"}
    stmt.append({"company_id": "BANK", "report_id": "r-BANK",
                 "collected_at": COLLECTED})
    sector_map["BANK"] = "بانک"
    for cid in metrics:
        metrics[cid]["_ttm_prov"] = prev_prov_codes(rep_index[cid])
    return metrics, rep_index, subjects, stmt, sector_map


class FakeEngine:
    """Duck-typed compute_metrics.Engine: compute() materializes the fixture,
    report_index() is deterministic — no database anywhere."""

    def __init__(self):
        (self._metrics, self._rep_index, self._subjects,
         self._stmt, _) = make_world()

    def compute(self):
        self.metrics = self._metrics
        self.subjects = self._subjects
        self.stmt = list(self._stmt)
        self.superseded = set()
        self.codal_titles = []
        return self.metrics

    def report_index(self):
        return self._rep_index


def pilot_engine():
    eng = FakeEngine()
    eng.compute()
    return eng


# ---------------------------------------------------------------------------
# resolve_prev_bases
# ---------------------------------------------------------------------------
def test_prev_bases_resolved_from_engine_own_values():
    bases, diag = PILOT.resolve_prev_bases(pilot_engine())
    assert bases["G00"] == {"net_profit_prev": 40.0,
                            "operating_profit_prev": 70.0,
                            "revenue_prev": 1000.0}
    assert diag["n_net_base"] == 15 and diag["n_op_base"] == 15
    assert diag["n_rev_base"] == 15
    assert diag["n_prov_mismatch"] == 0 and diag["n_unresolved"] == 0


def test_prev_base_dropped_when_replication_disagrees_with_engine_tag():
    eng = pilot_engine()
    eng.metrics["G00"]["_ttm_prov"]["net_profit_prev"] = RC.PROV_CHAIN
    bases, diag = PILOT.resolve_prev_bases(eng)
    assert "net_profit_prev" not in bases["G00"]
    assert bases["G00"]["operating_profit_prev"] == 70.0
    assert diag["n_prov_mismatch"] == 1


def test_prev_base_missing_when_prior_cell_absent():
    eng = pilot_engine()
    del eng._rep_index["G01"][(1403, 12)]
    bases, diag = PILOT.resolve_prev_bases(eng)
    assert "G01" not in bases
    assert diag["n_unresolved"] >= 2
    assert diag["n_no_base_at_all"] >= 1


def test_company_without_report_is_counted_not_guessed():
    eng = pilot_engine()
    del eng._rep_index["G02"]
    bases, diag = PILOT.resolve_prev_bases(eng)
    assert "G02" not in bases
    assert diag["n_no_report"] == 1


# ---------------------------------------------------------------------------
# build_provenance
# ---------------------------------------------------------------------------
def test_provenance_uses_real_timestamps_only_and_never_fabricates_ref():
    eng = pilot_engine()
    eng.stmt.append({"company_id": "G00", "report_id": "r-superseded",
                     "collected_at": COLLECTED})
    eng.stmt.append({"company_id": "G01", "report_id": "r-none",
                     "collected_at": None})
    eng.superseded = {"r-superseded"}
    prov, diag = PILOT.build_provenance(eng)
    assert set(prov["G00"]) == {"available_at"}       # no invented source_ref
    assert prov["G00"]["available_at"] == COLLECTED
    assert diag["n_with_real_available_at"] == 15
    assert diag["n_superseded_rows_skipped"] == 1


# ---------------------------------------------------------------------------
# build_company_meta
# ---------------------------------------------------------------------------
def test_company_meta_real_industry_and_unknown_industry_contract():
    eng = pilot_engine()
    sector_map = {"G00": "بانک", "G01": None}
    meta, detail = PILOT.build_company_meta(eng, sector_map)
    assert meta["G00"] == {"model_family": "bank", "industry": "بانک"}
    assert meta["G01"] == {"model_family": "general", "industry": None}
    assert detail["G01"]["family_status"] == "unclassified"
    assert detail["G00"]["family_status"] == "classified"
    # a company absent from the sector map entirely stays general/unclassified
    assert meta["G02"]["model_family"] == "general"


# ---------------------------------------------------------------------------
# reason buckets
# ---------------------------------------------------------------------------
def test_reason_buckets_distinguish_refusal_families():
    no_contract = {"normalization_status": "pending_blend",
                   "reason": "no approved component blend contract yet — "
                             "component ranks are kept separate; the factor "
                             "itself gets no percentile"}
    mismatch = {"normalization_status": "pending_blend",
                "reason": "component-weight config does not match the raw "
                          "components of this factor — no blend"}
    missing = {"normalization_status": "pending_data",
               "components": {"net_margin_pct":
                              {"normalization_status":
                               "not_ranked_raw_missing"}}}
    na = {"normalization_status": "pending_data",
          "components": {"cash_conversion":
                         {"normalization_status":
                          "not_ranked_raw_not_applicable"}}}
    peers = {"normalization_status": "insufficient_peers"}
    scored = {"normalization_status": "blended", "factor_blend_score": 0.5}
    assert PILOT.reason_bucket("margins", no_contract) == \
        "pending_blend: no component blend contract for this family"
    assert PILOT.reason_bucket("margins", mismatch) == \
        "pending_blend: weight-config mismatch refusal"
    assert PILOT.reason_bucket("margins", missing) == \
        "pending_data: a component is missing"
    assert PILOT.reason_bucket("cash_conversion", na) == \
        "pending_data: a component is not_applicable"
    assert PILOT.reason_bucket("leverage", peers) == "insufficient_peers"
    assert PILOT.reason_bucket("margins", scored) is None


# ---------------------------------------------------------------------------
# run_pilot end-to-end on the injected fake engine (no database)
# ---------------------------------------------------------------------------
def _walk(d):
    if isinstance(d, dict):
        for k, v in d.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(d, (list, tuple)):
        for v in d:
            yield from _walk(v)


def _score_values(d):
    if isinstance(d, dict):
        for k, v in d.items():
            if k == "null_reasons":
                continue  # reason STRINGS live there, never numeric scores
            if k in ("score", "factor_blend_score", "percentile_combined",
                     "contribution", "percentile_market_family",
                     "percentile_sector") and v is not None:
                yield v
            yield from _score_values(v)
    elif isinstance(d, list):
        for v in d:
            yield from _score_values(v)


@pytest.fixture()
def pilot_report():
    return PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25,
                           engine=FakeEngine(),
                           sector_map=dict(make_world()[4]))


def test_run_pilot_population_and_coverage_counts(pilot_report):
    r = pilot_report
    assert r["stage"] == PILOT.STAGE
    assert r["pit_policy"] == "current_exploratory"
    assert r["population"]["n_companies_in_metrics"] == 15
    assert r["population"]["by_model_family"] == {"bank": 1, "general": 14}
    assert r["population"]["n_industry_unknown"] == 1  # BROKE: no mapping —
    # the normalization contract ranks it family-wide with industry_unknown

    m = r["coverage"]["margins"]
    assert m["n_population"] == 15
    assert m["raw_valid"] == 14          # BROKE's net margin is missing
    assert m["raw_missing"] == 1
    assert m["composite_blended"] == 13  # general only — the bank stays out
    assert m["one_component_only"] == 1  # BROKE: operating margin still valid
    assert m["pending_blend"] == 1       # bank: no contract, kept verbatim

    g = r["coverage"]["earnings_growth"]
    assert g["composite_blended"] == 13 and g["pending_blend"] == 1

    c = r["coverage"]["cash_conversion"]
    assert c["single_ranked"] == 13
    assert c["insufficient_peers"] == 1  # bank family of one: no ranks
    assert c["raw_missing"] == 1         # BROKE has no ocf_ttm

    assert r["coverage"]["margins"]["scored_by_family"] == {"general": 13}
    # full-population warning census + named issues trail (fixture: clean)
    assert isinstance(m["warning_kinds"], dict)
    assert r["issues"] == {}


def test_run_pilot_refusal_reasons_are_categorized(pilot_report):
    r = pilot_report["refusal_reasons"]
    assert r["margins"]["pending_data: a component is missing"] == 1
    assert r["margins"][
        "pending_blend: no component blend contract for this family"] == 1
    assert r["cash_conversion"]["single factor raw status: missing"] == 1
    assert r["cash_conversion"]["insufficient_peers"] == 1


def test_run_pilot_has_no_final_scores_and_all_scores_in_unit_range(
        pilot_report):
    r = pilot_report
    for k, _v in _walk(r):
        assert k not in FORBIDDEN_SCORE_KEYS, \
            "pilot must never produce a final Q/V/T/total score"
    vals = list(_score_values(r))
    assert vals, "pilot report is expected to carry normalized scores"
    for v in vals:
        assert isinstance(v, (int, float)) and 0.0 <= v <= 1.0


def test_run_pilot_sample_mixes_scored_and_unscored_and_is_deterministic():
    a = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25, engine=FakeEngine(),
                        sector_map=dict(make_world()[4]))
    b = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25, engine=FakeEngine(),
                        sector_map=dict(make_world()[4]))
    assert json.dumps(a, default=str, sort_keys=True) == \
        json.dumps(b, default=str, sort_keys=True)
    syms = [c["symbol"] for c in a["companies"]]
    assert len(syms) == 14
    assert "BANK1" in syms   # the unscored company is always kept
    assert "INT91" in syms   # the interim reporter ranks, so it ranks high
    top = a["companies"][0]
    # healthy G* companies score 7 factors (margins, eg, cash, leverage,
    # margin_trend, ic, eq — the fixture carries no revenue_growth key);
    # INT9 scores 6 (its revenue_growth is the family's only valid value,
    # refused by the insufficient-peers contract) so SYM00 leads on ties
    assert top["n_scored_factors"] == 7
    assert top["symbol"] == "SYM00"
    assert top["model_family"] == "general"


def test_run_pilot_sample_company_entries_carry_the_contracted_fields():
    r = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25, engine=FakeEngine(),
                        sector_map=dict(make_world()[4]))
    by_symbol = {c["symbol"]: c for c in r["companies"]}

    full = by_symbol["SYM11"]
    assert full["display_name"] == "Company 11"
    assert full["family_status"] == "classified"
    f = full["factors"]["margins"]
    assert f["raw_status"] == "valid"
    assert set(f["raw_components"]) == {"operating_margin_pct",
                                        "net_margin_pct"}
    assert f["normalization_status"] == "blended"
    assert 0.0 <= f["score"] <= 1.0
    assert f["blend"]["method"] == PILOT.SN.BLEND_METHOD
    assert f["components"]["operating_margin_pct"]["pit_status"] is not None
    assert f["components"]["operating_margin_pct"]["available_at"] == COLLECTED
    assert any(w.startswith("pit_unverified_exploratory")
               for comp in f["components"].values()
               for w in comp.get("warnings", []))

    interim = by_symbol["INT91"]["factors"]["earnings_quality"]
    # INT9's other_nonop order-2 comparative leg is absent: the raw record
    # exists, the honest missing state flows through — never a guessed value
    assert interim["raw_status"] == "missing"
    assert interim["normalization_status"] == "not_ranked_raw_missing"
    assert interim["ttm_evidence"]["legs"]["prior_year_same_period_order2"][
        "value"] is None
    assert interim["ttm_evidence"]["state"] == "unresolved_missing_order2"
    assert interim["ttm_evidence"]["prov_code"] == RC.PROV_INSUFFICIENT

    bank = by_symbol["BANK1"]["factors"]["margins"]
    assert bank["normalization_status"] == "pending_blend"
    assert "score" not in bank and "factor_blend_score" not in bank


def test_run_pilot_report_is_json_serializable_with_disclaimer(pilot_report):
    text = json.dumps(pilot_report, default=str)
    assert "EXPLORATORY ONLY" in text
    assert "never backtest-verified evidence" in text


# ---------------------------------------------------------------------------
# 2-B-4.1: the separate economic-validity diagnostic label for
# earnings_growth — detection only, never a change of base/status/score
# ---------------------------------------------------------------------------
def test_economic_validity_label_and_counts_on_clean_population(pilot_report):
    ev = pilot_report["economic_validity"]
    assert ev["factor_id"] == "earnings_growth"
    assert ev["label"] == PILOT.ECONOMIC_VALIDITY_LABEL
    assert ev["label_fa"] == "اعتبار اقتصادی بررسی‌نشده"
    assert ev["sentinel_census_rows_by_metric"] == {}
    comps = ev["components"]
    # BROKE's net profit is missing -> 14 valid net growth values, 15 op
    assert comps["net_profit_growth_pct"]["n_valid_growth_values"] == 14
    assert comps["operating_profit_growth_pct"]["n_valid_growth_values"] == 15
    for c in comps.values():
        assert c["n_sentinel_affected"] == 0
        assert c["affected_symbols"] == []
    assert "changes no raw status" in ev["note"]


def test_sentinel_base_flags_detects_exact_value_and_leg_cells():
    eng = pilot_engine()
    bases, _ = PILOT.resolve_prev_bases(eng)
    assert PILOT.sentinel_base_flags(eng, bases) == {}  # clean fixture

    # a legacy sentinel fact inside G00's prior-year annual cell (the rep
    # cell itself carries the constant — the same store shape as the real
    # sentinel rows: value AND fact position agree)
    eng._rep_index["G00"][(1403, 12)]["operating_profit"] = {1: 1_000_000.0}
    cells = {"G00": {(1403, 12, "operating_profit", 1)}}
    flags = PILOT.sentinel_base_flags(eng, bases, sentinel_cells=cells)
    # the supplied base (70.0) is real, but BOTH the re-resolved value and
    # the consumed leg cell are the sentinel constant
    assert flags["G00"]["operating_profit_prev"] == \
        ["resolved_base_exact_sentinel_value", "prev_cell_o1"]
    assert "net_profit_prev" not in flags["G00"]

    # the exact constant as the supplied base value itself
    flags_exact = PILOT.sentinel_base_flags(
        eng, {"G00": {"operating_profit_prev": 1_000_000.0}})
    assert flags_exact["G00"]["operating_profit_prev"] == \
        ["base_exact_sentinel_value"]

    # chain path: with explicit fiscal-calendar evidence the chain anchors on
    # the real annual cell; the sentinel sits on the prior comparable YTD leg
    eng2 = pilot_engine()
    eng2._rep_index["G01"] = {
        (1404, 3): {"operating_profit": {1: 30.0}},
        (1403, 3): {"operating_profit": {1: 20.0}},
        (1402, 12): {"operating_profit": {1: 70.0}},
        (1402, 3): {"operating_profit": {1: 1_000_000.0}},
    }
    eng2.codal_titles = [{
        "company_id": "G01",
        "title": "اطلاعات و صورت‌های مالی ۱۲ ماهه منتهی به 1402/12/29",
        "period_end_date": dt.date(2024, 3, 19)}]
    bases2 = {"G01": {"operating_profit_prev":
                      70.0 + 20.0 - 1_000_000.0}}
    flags_chain = PILOT.sentinel_base_flags(
        eng2, bases2, sentinel_cells={
            "G01": {(1402, 3, "operating_profit", 1)}})
    assert flags_chain["G01"]["operating_profit_prev"] == \
        ["prior_comparable_ytd_o1"]


def test_sentinel_stmt_rows_add_label_only_and_change_nothing_else():
    control = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25,
                              engine=FakeEngine(),
                              sector_map=dict(make_world()[4]))
    eng = FakeEngine()
    # a real-shaped legacy sentinel fact row for G00's prior-year cell — but
    # the fixture rep cell keeps its real value, so no base may be flagged
    eng._stmt.append({
        "company_id": "G00", "report_id": "r-sentinel",
        "collected_at": COLLECTED, "statement_type": "income_statement",
        "metric_code": "operating_profit", "period_order": 1,
        "canonical_value": 1_000_000.0, "canonical_unit": "rial",
        "fiscal_year": 1403, "fiscal_month": 12,
        "period_end_date": dt.date(2025, 3, 20)})
    flagged = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25, engine=eng,
                              sector_map=dict(make_world()[4]))
    ev = flagged["economic_validity"]
    assert ev["sentinel_census_rows_by_metric"] == {"operating_profit": 1}
    for c in ev["components"].values():
        assert c["n_sentinel_affected"] == 0  # no false positive

    def without_section(r):
        keep = {"economic_validity", "growth_quarantine",
                "next_factor_readiness", "factor_batch_2b5", "q_readiness",
                "q_observed", "expense_ttm", "factor_batch_2b7"}
        return json.dumps({k: v for k, v in r.items() if k not in keep},
                          default=str, sort_keys=True)

    # the diagnostic is pure observation: nothing else in the report moved,
    # and nothing was quarantined — the inert sentinel row is counted, never
    # turned into a removal
    assert without_section(flagged) == without_section(control)
    qi = flagged["growth_quarantine"]["quarantine"]
    assert qi["n_quarantined_tags"] == 0
    assert qi["cell_census"]["inert_cells"] == 1


# ---------------------------------------------------------------------------
# 2-B-4.2: temporary quarantine of legacy-sentinel prior-year bases
# ---------------------------------------------------------------------------
def add_legacy_sentinel(eng, cid, fy, fm, metric="operating_profit",
                        order=1, value=1_000_000.0):
    """Shape the store the way 2-B-4.1 found it: the sentinel fact row exists
    AND the rep-index cell winner is the constant (i.e. the cell is
    actually consumed by TTM resolution)."""
    row = {
        "company_id": cid, "report_id": f"r-legacy-{cid}",
        "collected_at": COLLECTED, "statement_type": "income_statement",
        "metric_code": metric, "period_order": order,
        "canonical_value": value, "canonical_unit": "rial",
        "fiscal_year": fy, "fiscal_month": fm,
        "period_end_date": dt.date(2025, 3, 20)}
    eng._stmt.append(row)
    # compute() already materialized a copy of _stmt: keep the live view in
    # sync so detection sees the row either way
    if getattr(eng, "stmt", None) is not None and eng.stmt is not eng._stmt:
        eng.stmt.append(row)
    eng._rep_index[cid].setdefault((fy, fm), {})[metric] = {order: value}


def test_quarantine_removes_only_consumed_legacy_tag_and_never_mutates_input():
    import copy
    eng = pilot_engine()
    add_legacy_sentinel(eng, "G00", 1403, 12)
    bases, _ = PILOT.resolve_prev_bases(eng)
    assert bases["G00"]["operating_profit_prev"] == 1_000_000.0  # poisoned
    snapshot = copy.deepcopy(bases)
    clean, info = PILOT.quarantine_prev_bases(eng, bases)
    assert bases == snapshot                 # input dict is never mutated
    # op out, net and (sentinel-free) revenue kept
    assert clean["G00"] == {"net_profit_prev": 40.0, "revenue_prev": 1000.0}
    assert clean["G01"]["operating_profit_prev"] == 70.0  # healthy untouched
    assert info["n_quarantined_tags"] == 1
    row = info["quarantined"][0]
    assert (row["company_id"], row["tag"]) == ("G00", "operating_profit_prev")
    assert row["prov_code"] == RC.PROV_DIRECT
    assert "prev_cell_o1" in row["flags"]
    assert "base_exact_sentinel_value" in row["flags"]
    assert info["cell_census"]["consumed_cells"] == 1
    assert info["cell_census"]["inert_cells"] == 0


def test_quarantine_paths_annual_and_chain():
    # ANNUAL path: an explicit 12-month title makes prev resolve as
    # ANNUAL_REPORT; the sentinel sits on that same order-1 cell
    eng = pilot_engine()
    eng.codal_titles = [{
        "company_id": "G02",
        "title": "اطلاعات و صورت‌های مالی ۱۲ ماهه منتهی به 1403/12/29",
        "period_end_date": dt.date(2025, 3, 20)}]
    # the real engine sees the SAME titles, so its recorded tags match the
    # replication (the frozen fixture tags would drop the base as a mismatch)
    eng.metrics["G02"]["_ttm_prov"]["operating_profit_prev"] = \
        RC.PROV_ANNUAL_REPORT
    eng.metrics["G02"]["_ttm_prov"]["net_profit_prev"] = RC.PROV_ANNUAL_REPORT
    eng.metrics["G02"]["_ttm_prov"]["revenue_prev"] = RC.PROV_ANNUAL_REPORT
    add_legacy_sentinel(eng, "G02", 1403, 12)
    bases, _ = PILOT.resolve_prev_bases(eng)
    clean, info = PILOT.quarantine_prev_bases(eng, bases)
    row = next(r for r in info["quarantined"] if r["company_id"] == "G02")
    assert row["prov_code"] == RC.PROV_ANNUAL_REPORT
    assert "prev_cell_o1" in row["flags"]
    assert "operating_profit_prev" not in clean["G02"]
    assert clean["G02"]["net_profit_prev"] == 40.0
    assert clean["G02"]["revenue_prev"] == 1000.0   # healthy, sentinel-free

    # CHAIN path: the sentinel poisons the prior comparable YTD leg while the
    # resolved base stays IN the anomaly band — no magnitude warning would
    # ever catch it; leg-based consumption does
    eng2 = pilot_engine()
    eng2._rep_index["G01"] = {
        (1404, 3): {"operating_profit": {1: 30.0}},
        (1403, 3): {"operating_profit": {1: 20.0}},
        (1402, 12): {"operating_profit": {1: 70.0}},
        (1402, 3): {"operating_profit": {1: 1_000_000.0}},
    }
    chain_row = {
        "company_id": "G01", "report_id": "r-legacy-chain",
        "collected_at": COLLECTED, "statement_type": "income_statement",
        "metric_code": "operating_profit", "period_order": 1,
        "canonical_value": 1_000_000.0, "canonical_unit": "rial",
        "fiscal_year": 1402, "fiscal_month": 3,
        "period_end_date": dt.date(2023, 6, 22)}
    eng2._stmt.append(chain_row)
    if getattr(eng2, "stmt", None) is not None and eng2.stmt is not eng2._stmt:
        eng2.stmt.append(chain_row)
    eng2.codal_titles = [{
        "company_id": "G01",
        "title": "اطلاعات و صورت‌های مالی ۱۲ ماهه منتهی به 1402/12/29",
        "period_end_date": dt.date(2024, 3, 19)}]
    bases2 = {"G01": {"operating_profit_prev": 70.0 + 20.0 - 1_000_000.0,
                      "net_profit_prev": 40.0}}
    clean2, info2 = PILOT.quarantine_prev_bases(eng2, bases2)
    row2 = info2["quarantined"][0]
    assert row2["tag"] == "operating_profit_prev"
    assert row2["prov_code"] == RC.PROV_CHAIN
    assert "prior_comparable_ytd_o1" in row2["flags"]
    assert clean2["G01"] == {"net_profit_prev": 40.0}  # healthy net survives


def test_real_value_winning_the_cell_is_never_quarantined():
    eng = pilot_engine()
    bases, _ = PILOT.resolve_prev_bases(eng)
    # a legacy sentinel fact row exists but LOST its cell to the real value:
    # the engine consumed real data, so nothing may be removed — the inert
    # cell is reported as uncertainty, never auto-declared clean
    loser = {
        "company_id": "G00", "report_id": "r-legacy-loser",
        "collected_at": COLLECTED, "statement_type": "income_statement",
        "metric_code": "operating_profit", "period_order": 1,
        "canonical_value": 1_000_000.0, "canonical_unit": "rial",
        "fiscal_year": 1403, "fiscal_month": 12,
        "period_end_date": dt.date(2025, 3, 19)}
    eng._stmt.append(loser)
    if getattr(eng, "stmt", None) is not None and eng.stmt is not eng._stmt:
        eng.stmt.append(loser)
    clean, info = PILOT.quarantine_prev_bases(eng, bases)
    assert clean == bases
    assert info["quarantined"] == []
    assert info["cell_census"]["inert_cells"] == 1
    assert info["cell_census"]["consumed_cells"] == 0


def test_quarantined_base_yields_no_partial_blend_and_keeps_net_ranked():
    eng = pilot_engine()
    add_legacy_sentinel(eng, "G00", 1403, 12)
    meta, _detail = PILOT.build_company_meta(eng, dict(make_world()[4]))
    bases, _ = PILOT.resolve_prev_bases(eng)
    clean, _info = PILOT.quarantine_prev_bases(eng, bases)
    raw = PILOT.RAW.build_q_raw(eng.metrics, prev_bases=clean,
                                provenance={}, as_of=CUTOFF)
    eg = raw["G00"]["earnings_growth"]["components"]
    assert eg["operating_profit_growth_pct"]["status"] == \
        PILOT.RAW.STATUS_MISSING
    assert eg["net_profit_growth_pct"]["status"] == PILOT.RAW.STATUS_VALID
    out = PILOT.SN.normalize_q_cross_section(
        raw, meta, as_of=CUTOFF, pit_policy=PILOT.SN.PIT_CURRENT_EXPLORATORY)
    f = out["factors"]["G00"]["earnings_growth"]
    assert f["normalization_status"] == PILOT.SN.FS_PENDING_DATA
    assert f.get("factor_blend_score") is None     # no partial blend invented
    net = next(r for r in out["records"]
               if r["company_id"] == "G00"
               and r["factor_id"] == "earnings_growth"
               and r["component_id"] == "net_profit_growth_pct")
    assert net.get("percentile_market_family") is not None  # net still ranked


def test_quarantine_is_empty_on_clean_population_and_invariants_hold(
        pilot_report):
    q = pilot_report["growth_quarantine"]
    qi = q["quarantine"]
    assert qi["n_quarantined_tags"] == 0 and qi["quarantined"] == []
    assert q["earnings_growth_blended"] == {"before": 13, "after": 13}
    for s in q["percentile_shift_healthy_companies"].values():
        assert s["n_percentile_changed"] == 0
    assert all(v["normalization_identical"]
               for v in q["invariant_factors"].values())
    # without quarantine, runs A and B are the same computation
    assert pilot_report["coverage"] == \
        pilot_report["baseline_unquarantined"]["coverage"]


def test_run_pilot_quarantine_recomputes_population_and_shifts_percentiles():
    eng = FakeEngine()
    add_legacy_sentinel(eng, "G00", 1403, 12)
    r = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25, engine=eng,
                        sector_map=dict(make_world()[4]))
    q = r["growth_quarantine"]
    assert q["quarantine"]["n_quarantined_tags"] == 1
    # run B drives the report: G00's earnings_growth is refused pending data
    assert r["coverage"]["earnings_growth"]["composite_blended"] == 12
    # run A keeps it — comparison only
    assert r["baseline_unquarantined"]["coverage"]["earnings_growth"][
        "composite_blended"] == 13
    # healthy percentiles were recomputed on the cleaned population: the
    # 14 ranked general op components minus quarantined G00 leave 13 common
    # comparisons (11 healthy + BROKE + INT9)
    op = q["percentile_shift_healthy_companies"]["operating_profit_growth_pct"]
    assert op["n_healthy_compared"] == 13
    assert op["n_percentile_changed"] > 0
    # margins / leverage / cash conversion are provably untouched
    for v in q["invariant_factors"].values():
        assert v["raw_identical"] and v["normalization_identical"]
    # the cross-table reconciles contamination vs magnitude warnings — here
    # the consumed sentinel base stays INSIDE the anomaly band, i.e. a
    # contaminated base WITHOUT any magnitude warning
    ct = q["cross_table_baseline"]["operating_profit_growth_pct"]
    assert ct.get("contaminated_without_anomaly") == 1
    assert ct.get("clean_without_anomaly") == 14
    assert q["component_population"]["operating_profit_growth_pct"] == \
        {"before": 15, "after": 14}
    assert {"before", "after", "changed"} <= \
        set(q["winsor_bounds"]["operating_profit_growth_pct"])


def test_next_factor_readiness_table_shape_and_honesty(pilot_report):
    rd = pilot_report["next_factor_readiness"]
    assert set(rd["factors"]) == {"roe_level", "interest_coverage",
                                  "earnings_quality", "margin_trend",
                                  "revenue_growth"}
    assert "excluded" in rd["roe_stability"]
    for row in rd["factors"].values():
        assert row["n_population"] == 15
        assert row["uses_prev_year_ttm_base"] is False
        assert row["contamination_signs"]["prev_base_channel_involved"] is False
        assert row["contamination_signs"][
            "current_ttm_sentinel_valued_companies"] == 0
    # the fixture's engine metrics carry only the keys the pilot exercises
    # (INT9 adds a revenue_growth): availability here is ~0 — the REAL run
    # reports true coverage (structure pinned, not magnitudes)
    assert rd["factors"]["roe_level"]["n_metrics_available"] == 0
    assert rd["factors"]["interest_coverage"]["n_metrics_available"] == 0
    assert rd["factors"]["earnings_quality"]["n_metrics_available"] == 0
    assert rd["factors"]["margin_trend"]["n_metrics_available"] == 0
    assert rd["factors"]["revenue_growth"]["n_metrics_available"] == 1


# ---------------------------------------------------------------------------
# 2-B-5: batch implementation — three implemented, two blocked, Q diagnostic
# ---------------------------------------------------------------------------
def test_factor_batch_2b5_section_implementation_decisions(pilot_report):
    b = pilot_report["factor_batch_2b5"]
    assert set(b["implemented"]) == {"roe_level", "margin_trend",
                                     "revenue_growth"}
    assert set(b["blocked"]) == {"interest_coverage", "earnings_quality"}
    for fid, blk in b["blocked"].items():
        assert "blocked" in blk["decision"]
        assert "TTM" in blk["problem"] and "YTD" in blk["problem"]
        assert blk["n_metrics_available"] == 0  # fixture engine metrics lack
        # the derived keys — structure pinned here, real coverage in the run
        # 2-B-7 supersession is recorded on the historical decision itself
        assert "superseded_by" in blk
        assert "2-B-7" in blk["superseded_by"]
    wa = b["window_audit"]
    # every fixture company's latest report is the annual (1404, 12) cell
    # except INT9's interim (1404, 9) report
    assert wa["n_annual_latest_report"] == 14
    assert wa["latest_period_fiscal_month_split"] == {9: 1, 12: 14}
    assert wa["revenue_order2_negative_companies"] == []
    assert b["n_sentinel_winners_in_latest_report_cells"] == 0
    assert set(b["excluded"]) == {"roe_stability", "roic"}


def test_expense_pair_channel_gated_not_engine_metric_gated():
    # the engine's window-mismatched derived metrics may exist: the raw
    # layer still refuses them WITHOUT the same-window channel (records
    # exist, status missing — never the 2-B-5 order-1 YTD substitution),
    # and WITH the channel the honest same-window value comes through
    eng = pilot_engine()
    for m in eng.metrics.values():
        m["interest_coverage"] = 4.0
        m["earnings_quality"] = 10.0
    raw = PILOT.RAW.build_q_raw(eng.metrics)
    assert raw["G00"]["interest_coverage"]["status"] == "missing"
    assert "channel not supplied" in \
        raw["G00"]["interest_coverage"]["validation_reason"]
    assert raw["G00"]["earnings_quality"]["status"] == "missing"
    channels, census = PILOT.resolve_expense_ttm_channels(eng)
    raw2 = PILOT.RAW.build_q_raw(eng.metrics, expense_ttm=channels)
    ic = raw2["G00"]["interest_coverage"]
    assert ic["status"] == "valid"
    assert ic["raw_value"] == pytest.approx(80.0 / 25.0)  # op_ttm / |−25 o1|
    assert ic["ttm_evidence"]["prov_code"] == RC.PROV_DIRECT
    eq = raw2["G00"]["earnings_quality"]
    assert eq["status"] == "valid"
    assert eq["raw_value"] == pytest.approx(6.0 / 80.0 * 100.0)
    # INT9's fm=9 report: finance_cost carries all three legs (within-report
    # assembly), other_non_operating misses its order-2 comparative
    assert census["finance_cost_ttm"]["resolved_fiscal_month_12"] == 14
    assert census["finance_cost_ttm"]["resolved_within_report"] == 1
    assert census["other_nonop_ttm"]["resolved_fiscal_month_12"] == 14
    assert census["other_nonop_ttm"]["unresolved_missing_order2"] == 1
    ic9 = raw2["INT9"]["interest_coverage"]
    assert ic9["status"] == "valid"
    assert ic9["raw_value"] == pytest.approx(90.0 / 120.0)  # |−30−100+10|
    assert ic9["ttm_evidence"]["prov_code"] == RC.PROV_DIRECT
    assert raw2["INT9"]["earnings_quality"]["status"] == "missing"
    assert "order2" in raw2["INT9"]["earnings_quality"]["validation_reason"]


def test_q_readiness_diagnostic_is_weight_coverage_not_a_score(pilot_report):
    qr = pilot_report["q_readiness"]
    assert qr["family"] == "general"
    assert qr["q_axis_total_weight"] == 40
    # parked since 2-B-7: only roe_stability (3) — the expense pair joined
    # the raw scope, so max coverable is 40 - 3 (roe_stability) = 37; this
    # 2-B-5 diagnostic counts all in-scope weights and does not apply the
    # q_observed earnings_growth policy exclusion
    assert qr["parked_q_factors_with_weights"] == {"roe_stability": 3}
    assert qr["parked_weight_sum"] == 3
    assert qr["max_currently_coverable_weight"] == 37
    assert qr["essential_q_factors"] == ["margins", "roe_level"]
    # the fixture never has roe_level (engine metrics carry no 'roe' key),
    # so the essential gate stays closed everywhere. 14 general companies
    # rank margin_trend: the 12 healthy ones plus BROKE and INT9.
    assert qr["n_ranked_by_factor"]["margin_trend"] == 14
    assert qr["n_all_essentials_ranked"] == 0
    # BROKE loses margins (missing net margin) and cash_conversion (no ocf):
    # its covered weight is 10/40 (margin_trend 3 + leverage 4 + ic 3) —
    # below the 0.5 policy floor. INT9 reaches 24/40 (margins 6 +
    # margin_trend 3 + cash 4 + leverage 4 + revenue 4 + ic 3), so exactly
    # the 12 healthy general companies plus INT9 clear the coverage bar.
    assert qr["n_coverage_at_or_above_min"] == 13
    assert qr["n_potentially_q_eligible"] == 0
    for k, _v in _walk(qr):
        assert k not in FORBIDDEN_SCORE_KEYS


def test_run_pilot_q_observed_section_is_the_first_observed_q(pilot_report):
    # step 2-B-6 wiring, extended by 2-B-7: the pilot report carries the
    # observed-Q section and its contracts hold on the real pipeline fixture
    qo = pilot_report["q_observed"]
    assert qo["stage"] == "q_observed_pilot"
    assert qo["family"] == "general"
    wt = qo["weight_table"]
    assert wt["target_weight"] == wt["total_weight"] == 40
    assert {f for f, r in wt["rows"].items()
            if r["in_aggregation_scope"]} == {
        "roe_level", "margins", "margin_trend", "cash_conversion",
        "leverage", "revenue_growth", "interest_coverage", "earnings_quality"}
    assert wt["rows"]["earnings_growth"]["scope_category"] == "policy_excluded"
    assert wt["rows"]["roe_stability"]["implementation"] == "not_implemented"
    s = qo["summary"]
    assert s["n_companies_total"] == 15
    assert s["n_general"] == 14
    assert s["n_family_out_of_scope"] == 1
    # the fixture has no 'roe' engine metric: the essential gate closes
    # everywhere, even where coverage clears the 0.5 bar
    assert s["n_pilot_eligible"] == 0
    assert s["n_essentials_satisfied"] == 0
    g00 = qo["companies"]["G00"]
    assert g00["covered_weight"] == pytest.approx(
        23.0)  # margins 6 + cash 4 + leverage 4 + margin_trend 3 + ic 3 + eq 3
    assert g00["q_observed_points"] is not None
    assert g00["q_observed_points"] <= g00["covered_weight"] + 1e-9
    assert g00["risk_gate"]["status"] == "not_evaluated"
    assert g00["data_confidence"]["status"] == "not_evaluated"
    for fid in ("interest_coverage", "earnings_quality"):
        f = g00["factors"][fid]
        assert f["included"] is True
        assert f["weight"] == 3          # untouched by the activation
        assert f["score"] is not None    # ranked with the general peers
        assert f["contribution_points"] == pytest.approx(3 * f["score"])
    int9 = qo["companies"]["INT9"]
    # margins 6 + margin_trend 3 + cash 4 + leverage 4 + ic 3 = 20; its
    # revenue_growth is the family's only valid value, so normalization's
    # own insufficient_peers contract refuses to rank it (3,3 stay unused)
    assert int9["covered_weight"] == pytest.approx(20.0)
    assert int9["factors"]["revenue_growth"]["not_included_reason"] \
        .startswith("insufficient_peers")
    assert int9["factors"]["earnings_quality"]["included"] is False
    assert int9["factors"]["earnings_quality"]["not_included_reason"] \
        .startswith("raw_missing")
    eg = g00["factors"]["earnings_growth"]
    assert eg["included"] is False
    assert eg["contribution_points"] is None
    assert eg["score"] is not None          # the diagnostic survives
    bank = qo["companies"]["BANK"]
    assert bank["aggregation_status"] == "family_out_of_scope"
    assert "q_observed_points" not in bank
    assert len(qo["display_sample"]) == 15
    for k, _v in _walk(qo):
        assert k not in FORBIDDEN_SCORE_KEYS, k


def test_factor_batch_2b7_section_activates_the_expense_pair(pilot_report):
    # 2-B-7 wiring end-to-end on the pipeline fixture: the same-window
    # channels flow into coverage, the q_observed scope and the display
    b7 = pilot_report["factor_batch_2b7"]
    after = b7["coverage_after_this_run"]
    assert after["interest_coverage"]["raw_valid"] == 15
    assert after["interest_coverage"]["scored"] == 14   # 14 general ranked;
    # BANK's family of one is refused by normalization's own peer minimum
    assert after["interest_coverage"]["insufficient_peers"] == 1
    assert after["earnings_quality"]["raw_valid"] == 14  # INT9's o2 leg absent
    assert after["earnings_quality"]["scored"] == 13
    cap = b7["cap_bridge"]
    # 2-B-8 correction: the two weight-3 factors add at most +6 (25 -> 31);
    # 34 is the all-implemented aggregable ceiling, not this step's potential
    assert cap["observed_max_covered_before_2b7"] == 25
    assert cap["potential_from_the_two_weight3_factors"] == 31
    assert cap["aggregable_ceiling_all_implemented"] == 34
    assert "NOT 25 -> 34" in cap["note"]
    assert b7["coverage_before_reference"]["n_pilot_eligible"] == 98
    ic9 = next(r for r in b7["display_companies"]
               if r["company_id"] == "INT9")
    # one valid factor beats the bucket order: INT9 sits in one_raw_valid
    # while its earnings_quality leg evidence names the absent comparative
    assert ic9["bucket"] == "one_raw_valid"
    assert ic9["earnings_quality"]["raw_status"] == "missing"
    assert "comparative leg" in ic9["earnings_quality"]["raw_validation_reason"]
    assert ic9["interest_coverage"]["raw_value"] == pytest.approx(0.75)
    # the display is a deterministic variety sample, never a ranking: every
    # aggregated fixture company appears (the real run shows 18), each row
    # with raw value, score, covered weight and reason
    assert len(b7["display_companies"]) == 14
    for r in b7["display_companies"]:
        assert "covered_weight" in r and "pilot_eligible" in r
        assert "raw_validation_reason" in r["interest_coverage"]
    ex = b7["resolved_examples_with_legs"]
    assert ex, "at least one resolved TTM must carry its leg evidence"
    first = next(e for e in ex if e["channel"] == "finance_cost_ttm"
                 and e["state"] == "resolved_within_report")
    assert first["company_id"] == "INT9"
    assert first["legs"]["prior_fiscal_year_order3"]["value"] == -100.0
    # the run-level census mirrors the section
    assert pilot_report["expense_ttm"]["resolution_census"][
        "other_nonop_ttm"]["unresolved_missing_order2"] == 1


def test_margin_trend_valid_and_quarantined_alongside_op_prev():
    # the implemented TTM trend consumes operating_profit_prev: valid on the
    # clean population, missing when the base is quarantined — never the
    # span-mismatched engine field
    eng = pilot_engine()
    bases, _ = PILOT.resolve_prev_bases(eng)
    raw = PILOT.RAW.build_q_raw(eng.metrics, prev_bases=bases)
    mt = raw["G00"]["margin_trend"]
    assert mt["status"] == PILOT.RAW.STATUS_VALID
    assert mt["raw_value"] == pytest.approx(8.0 - 7.0)   # 80/1000 - 70/1000
    eng2 = pilot_engine()
    add_legacy_sentinel(eng2, "G00", 1403, 12)
    bases2, _ = PILOT.resolve_prev_bases(eng2)
    clean, _ = PILOT.quarantine_prev_bases(eng2, bases2)
    raw2 = PILOT.RAW.build_q_raw(eng2.metrics, prev_bases=clean)
    mt2 = raw2["G00"]["margin_trend"]
    assert mt2["status"] == PILOT.RAW.STATUS_MISSING
    assert "operating_profit_prev" in mt2["validation_reason"]


def test_run_pilot_margin_trend_population_moves_between_runs():
    eng = FakeEngine()
    add_legacy_sentinel(eng, "G00", 1403, 12)
    r = PILOT.run_pilot(AS_OF, CUTOFF, sample_limit=25, engine=eng,
                        sector_map=dict(make_world()[4]))
    q = r["growth_quarantine"]
    assert q["margin_trend_population"]["before"] == 15
    assert q["margin_trend_population"]["after"] == 14
    assert "EXPECTED" in q["margin_trend_population"]["role"]
    # the 2-B-5 singles that consume no bases are proven invariant
    assert set(q["invariant_factors"]) == {"margins", "leverage",
                                           "cash_conversion", "roe_level",
                                           "revenue_growth"}
    assert all(v["normalization_identical"]
               for v in q["invariant_factors"].values())
    # and the factors appear in the run-B coverage table (2-B-7's expense
    # pair included: every fixture company resolves finance_cost; INT9's
    # other_nonop order-2 leg is absent)
    cov = r["coverage"]
    assert cov["margin_trend"]["raw_valid"] == 14   # quarantined G00 out
    assert cov["roe_level"]["raw_missing"] == 15    # fixture has no 'roe'
    assert cov["revenue_growth"]["raw_missing"] == 14  # INT9 carries the key
    assert cov["interest_coverage"]["raw_valid"] == 15
    assert cov["earnings_quality"]["raw_valid"] == 14



def test_pilot_module_never_executes_sql_or_store_path():
    src = (PKG / "pilot_v2_qvt.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            assert name not in ("store_run", "execute", "executemany",
                                "cursor", "commit"), \
                f"pilot must stay strictly read-only: found {name!r}()"
