"""Expense-TTM channel tests (step 2-B-7) — pure, no database.

Covers the same-window finance_cost_ttm / other_nonop_ttm channel (resolved
by the pilot over the engine's own report index) and the two raw factors it
feeds — interest_coverage and earnings_quality:

  * within-report assembly: order1 + order3 - order2 of the LATEST report,
    for fm = 3 / 6 / 9; order 1 for fm = 12 or an explicitly 12-month
    titled report — every leg a real report value, audit-preserved
  * a missing leg (order 1 / 2 / 3) leaves the channel unresolved with the
    leg named — NEVER a YTD*12/fm scaling and NEVER a cross-report chain,
    even when the (t-1,12) and (t-1,fm) reports exist (the registry
    classifies both metrics DIRECT_ONLY; mixing reports mixes restatement
    bases — the fiscal-window-mismatch guard of 2-B-5 stays intact)
  * a consumed leg equal to a legacy-migration sentinel constant
    quarantines the channel (2-B-4.2 discipline extended)
  * the financial contracts: zero / positive (income-convention) finance
    cost -> not_applicable (never zero or infinite coverage, never an
    abs()-fabricated expense); negative operating profit stays a valid
    negative coverage with a warning but is a conservative not_applicable
    for the lower-is-better non-operating share; a real zero numerator is a
    valid zero; NaN/Infinity are invalid, never data
  * provenance flows per contract (verified requires timestamp AND
    source_ref with one shared source period); warnings survive ranking
  * percentile direction comes from config: coverage higher-is-better, the
    non-operating share lower-is-better; a 3-company family (the real
    2026-10-08 shape) is correctly refused as insufficient_peers
  * no mutation of metrics/channels; the seven previous factors' records
    are byte-identical with and without the channels; weights stay 3 + 3
    and a missing channel's weight is never redistributed

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_score_v2_expense_ttm.py -q
"""

from __future__ import annotations

import copy
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import report_chain_ttm as RC  # noqa: E402
import score_v2_config as CFG  # noqa: E402
import score_v2_normalize as SN  # noqa: E402
import score_v2_q_observed as QO  # noqa: E402
import score_v2_raw as SR  # noqa: E402
import pilot_v2_qvt as PILOT  # noqa: E402

AS_OF = dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc)
COLLECTED = dt.datetime(2026, 10, 1, 8, 0, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# 1. the pure channel resolver (pilot side)
# ---------------------------------------------------------------------------
def fin_cell(o1=None, o2=None, o3=None):
    d = {}
    if o1 is not None:
        d["finance_cost"] = {1: o1}
        if o2 is not None or o3 is not None:
            d["finance_cost"] = {1: o1, 2: o2, 3: o3}
    return {(1405, 3): d}


@pytest.mark.parametrize("fm", [3, 6, 9])
def test_ttm_assembles_the_three_real_report_legs(fm):
    # TTM = YTD(t,fm) + annual(t-1) - YTD(t-1,fm) — here all three legs are
    # the latest report's own comparative columns (order 1/2/3)
    rep = {(1405, fm): {"finance_cost": {1: -30.0, 2: -10.0, 3: -100.0}}}
    ch = PILOT._expense_ttm_channel(rep, (1405, fm), "finance_cost", None)
    assert ch["state"] == "resolved_within_report"
    assert ch["value"] == pytest.approx(-30.0 + -100.0 - -10.0)
    assert ch["prov_code"] == RC.PROV_DIRECT
    assert sorted(ch["consumed_legs"]) == [
        "latest_ytd_order1", "prior_fiscal_year_order3",
        "prior_year_same_period_order2"]
    assert ch["legs"]["prior_year_same_period_order2"]["value"] == -10.0
    assert ch["legs"]["prior_fiscal_year_order3"]["cell"] == [1405, fm]


def test_annual_latest_report_ttm_is_order1():
    # fm=12 by fiscal month, or an explicit 12-month Codal title at any fm:
    # the annual order-1 value IS the TTM, no comparative legs consumed
    rep = {(1404, 12): {"finance_cost": {1: -90.0}}}
    ch = PILOT._expense_ttm_channel(rep, (1404, 12), "finance_cost", None)
    assert ch["state"] == "resolved_fiscal_month_12"
    assert ch["value"] == pytest.approx(-90.0)
    rep2 = {(1405, 3): {"finance_cost": {1: -90.0}}}
    ch2 = PILOT._expense_ttm_channel(rep2, (1405, 3), "finance_cost",
                                     is_annual=True)
    assert ch2["state"] == "resolved_annual_title"
    assert ch2["prov_code"] == RC.PROV_ANNUAL_REPORT
    assert ch2["consumed_legs"] == ["latest_ytd_order1"]


@pytest.mark.parametrize("legs, state", [
    ({}, "unresolved_no_order1_value"),
    ({1: -30.0}, "unresolved_missing_order2_and_order3"),
    ({1: -30.0, 2: -10.0}, "unresolved_missing_order3"),
    ({1: -30.0, 3: -100.0}, "unresolved_missing_order2"),
])
def test_missing_leg_stays_unresolved_and_names_it(legs, state):
    rep = {(1405, 3): {"finance_cost": legs}}
    ch = PILOT._expense_ttm_channel(rep, (1405, 3), "finance_cost", None)
    assert ch["state"] == state
    assert ch["value"] is None
    assert ch["prov_code"] == RC.PROV_INSUFFICIENT


def test_never_scales_ytd_by_four_and_never_chains_across_reports():
    # a Q3 report with ONLY the current YTD: the ×4 guess is forbidden and
    # the chain legs (the prior annual + prior comparable reports) exist but
    # must NOT be used — the registry classifies finance_cost DIRECT_ONLY
    rep = {(1405, 3): {"finance_cost": {1: -30.0}},
           (1404, 12): {"finance_cost": {1: -100.0}},
           (1404, 3): {"finance_cost": {1: -8.0}}}
    ch = PILOT._expense_ttm_channel(rep, (1405, 3), "finance_cost", None)
    assert ch["value"] is None
    assert ch["state"] == "unresolved_missing_order2_and_order3"
    # an fm=3 report with only o1 is exactly -122.5% NOT -120.0 (=4*-30):
    # no scaling ever produces a value here
    assert "12/fm" not in ch["reason"] and "scale" not in ch["reason"]


def test_quarter_values_are_never_multiplied_in_the_record():
    rep = {(1405, 6): {"finance_cost": {1: -30.0}}}
    ch = PILOT._expense_ttm_channel(rep, (1405, 6), "finance_cost", None)
    assert ch["value"] is None  # a half-year YTD is never 2x, an fm=3 never 4x


def test_legacy_sentinel_leg_quarantines_the_channel():
    rep = {(1405, 3): {"finance_cost": {1: -30.0, 2: -1_000_000.0,
                                        3: -100.0}}}
    ch = PILOT._expense_ttm_channel(rep, (1405, 3), "finance_cost", None)
    assert ch["state"] == "quarantined_legacy_sentinel_leg"
    assert ch["value"] is None  # the poisoned assembly is never kept
    assert ch["warnings"] and ch["warnings"][0].startswith(
        "ttm_quarantined_legacy_sentinel_leg")


def test_non_finite_assembly_refused():
    rep = {(1405, 3): {"finance_cost": {1: -1e308, 2: -1e308, 3: -1e308}}}
    ch = PILOT._expense_ttm_channel(rep, (1405, 3), "finance_cost", None)
    assert ch["state"] == "non_finite_result"
    assert ch["value"] is None


# ---------------------------------------------------------------------------
# 2. the raw-layer contracts
# ---------------------------------------------------------------------------
def base_metrics(**over) -> dict:
    m = {
        "revenue_ttm": 1000.0, "net_profit_ttm": 100.0,
        "operating_profit_ttm": 150.0, "ocf_ttm": 90.0, "debt_ratio": 0.4,
    }
    m.update(over)
    return {"C1": m}


def channel(value, reason="within-report same-window assembly", **kw):
    return {"state": "resolved_within_report", "value": value,
            "prov_code": RC.PROV_DIRECT, "reason": reason,
            "legs": {"latest_ytd_order1": {"cell": [1405, 3],
                                           "metric": "finance_cost",
                                           "order": 1, "value": value}},
            "consumed_legs": ["latest_ytd_order1"],
            "warnings": list(kw.get("warnings", []))}


def build(metrics=None, expense=None, **kw):
    return SR.build_q_raw(metrics if metrics is not None else base_metrics(),
                          expense_ttm=expense, **kw)


def test_interest_coverage_arithmetic_and_audit_evidence():
    ch = channel(-50.0)
    rec = build(expense={"C1": {"finance_cost_ttm": ch}})["C1"][
        "interest_coverage"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(150.0 / 50.0)
    ev = rec["ttm_evidence"]
    assert ev["value"] == pytest.approx(-50.0)
    assert ev["prov_code"] == RC.PROV_DIRECT
    assert ev["legs"]["latest_ytd_order1"]["value"] == pytest.approx(-50.0)
    assert "PROXY" in rec["definition"]          # honest proxy naming
    assert "|finance_cost_ttm|" in rec["unit"]


def test_interest_coverage_negative_operating_profit_stays_valid_data():
    rec = build(base_metrics(operating_profit_ttm=-60.0),
                expense={"C1": {"finance_cost_ttm": channel(-50.0)}})["C1"][
        "interest_coverage"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(-60.0 / 50.0)  # never auto-zeroed
    assert any(w.startswith("negative_operating_profit")
               for w in rec["warnings"])


def test_zero_finance_cost_is_coverage_undefined_never_zero_or_infinite():
    rec = build(expense={"C1": {"finance_cost_ttm": channel(0.0)}})["C1"][
        "interest_coverage"]
    assert rec["status"] == "not_applicable"
    assert rec["raw_value"] is None
    assert "not mapped to a zero or infinite coverage" in \
        rec["validation_reason"]


def test_positive_finance_cost_is_income_convention_never_fake_expense():
    # the store's finance_cost rows are negative for expense (957/1040) — a
    # positive TTM reads as net finance income; abs() must NOT fabricate a
    # real expense out of it
    rec = build(expense={"C1": {"finance_cost_ttm": channel(50.0)}})["C1"][
        "interest_coverage"]
    assert rec["status"] == "not_applicable"
    assert "net finance income" in rec["validation_reason"]
    assert "abs() substitution" in rec["validation_reason"]


def test_unresolved_channel_leaves_missing_with_channel_reason_and_warnings():
    ch = channel(None, reason="within-report comparative leg(s) absent: "
                              "prior_year_same_period_order2",
                 warnings=["ttm_quarantined_legacy_sentinel_leg: x"])
    rec = build(expense={"C1": {"finance_cost_ttm": ch}})["C1"][
        "interest_coverage"]
    assert rec["status"] == "missing"
    assert "comparative leg(s) absent" in rec["validation_reason"]
    assert rec["warnings"] == ["ttm_quarantined_legacy_sentinel_leg: x"]
    assert rec["ttm_evidence"]["legs"]["latest_ytd_order1"]["value"] is None


def test_earnings_quality_arithmetic_abs_magnitude_sign_in_evidence():
    rec = build(expense={"C1": {"other_nonop_ttm": channel(-25.0)}})["C1"][
        "earnings_quality"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == pytest.approx(25.0 / 150.0 * 100.0)
    assert "net expense" in rec["validation_reason"]
    assert rec["ttm_evidence"]["value"] == pytest.approx(-25.0)  # sign kept
    assert "DEPENDENCE" in rec["definition"]  # not "complete earnings quality"


def test_earnings_quality_real_zero_numerator_is_valid_zero():
    rec = build(expense={"C1": {"other_nonop_ttm": channel(0.0)}})["C1"][
        "earnings_quality"]
    assert rec["status"] == "valid"
    assert rec["raw_value"] == 0.0
    assert "real zero" in rec["validation_reason"]


def test_earnings_quality_non_positive_operating_base_conservative_na():
    for op in (0.0, -80.0):
        rec = build(base_metrics(operating_profit_ttm=op),
                    expense={"C1": {"other_nonop_ttm": channel(30.0)}})["C1"][
            "earnings_quality"]
        assert rec["status"] == "not_applicable", op
        assert rec["raw_value"] is None
        if op < 0:
            assert "operating loss" in rec["validation_reason"]
    # and the coverage proxy beside it still computes from the loss
    ic = build(base_metrics(operating_profit_ttm=-80.0),
               expense={"C1": {"finance_cost_ttm": channel(-40.0),
                               "other_nonop_ttm": channel(30.0)}})["C1"][
        "interest_coverage"]
    assert ic["status"] == "valid"


def test_non_finite_inputs_and_results_are_invalid_never_data():
    rec = build(base_metrics(operating_profit_ttm=float("nan")),
                expense={"C1": {"finance_cost_ttm": channel(-50.0),
                                "other_nonop_ttm": channel(30.0)}})["C1"]
    assert rec["interest_coverage"]["status"] == "invalid"
    assert rec["earnings_quality"]["status"] == "invalid"
    rec2 = build(expense={"C1": {"finance_cost_ttm": channel(float("inf")),
                                 "other_nonop_ttm": channel(float("nan"))}})["C1"]
    assert rec2["interest_coverage"]["status"] == "invalid"
    assert rec2["earnings_quality"]["status"] == "invalid"


def test_overflowing_ratio_is_invalid_non_finite_result():
    # finite inputs, overflowing ratio: 1e308 / 0.5 overflows to +inf
    rec = build(base_metrics(operating_profit_ttm=1e308),
                expense={"C1": {"finance_cost_ttm": channel(-0.5)}})["C1"][
        "interest_coverage"]
    assert rec["status"] == "invalid"
    assert "non_finite_result" in rec["validation_reason"]


def test_magnitude_anomalies_warn_but_stay_valid():
    rec = build(expense={"C1": {"finance_cost_ttm": channel(-0.5),
                                "other_nonop_ttm": channel(1e6)}})["C1"]
    ic, eq = rec["interest_coverage"], rec["earnings_quality"]
    assert ic["status"] == "valid" and ic["raw_value"] == pytest.approx(300.0)
    assert any(w.startswith("magnitude_anomaly") for w in ic["warnings"])
    assert eq["status"] == "valid" and eq["raw_value"] > 1000.0
    assert any(w.startswith("magnitude_anomaly") for w in eq["warnings"])


def test_no_channel_never_the_window_mismatched_engine_value():
    # the engine's derived order-1 YTD values (2-B-5 audit: TTM numerator /
    # YTD denominator) are NEVER substituted, even when present in metrics
    m = base_metrics(interest_coverage=999.0, earnings_quality=0.5)
    rec = build(m)["C1"]
    for fid in ("interest_coverage", "earnings_quality"):
        assert rec[fid]["status"] == "missing"
        assert "channel not supplied" in rec[fid]["validation_reason"]
        assert "never substituted" in rec[fid]["validation_reason"]


# ---------------------------------------------------------------------------
# 3. PIT / provenance contract
# ---------------------------------------------------------------------------
def test_pit_verified_requires_timestamp_ref_and_one_shared_period():
    prov = {"C1": {"available_at": COLLECTED, "source_ref": "codal:letter-1",
                   "source_period": "1405Q3-fs"}}
    rec = build(expense={"C1": {"finance_cost_ttm": channel(-50.0),
                                "other_nonop_ttm": channel(30.0)}},
                provenance=prov, as_of=AS_OF)["C1"]
    for fid in ("interest_coverage", "earnings_quality"):
        assert rec[fid]["pit_status"] == SR.PIT_VERIFIED, fid
        assert rec[fid]["available_at"] == COLLECTED
        assert rec[fid]["source_period"] == "1405Q3-fs"


def test_pit_bare_timestamp_or_missing_ref_stays_unverified():
    for prov in ({"C1": {"available_at": COLLECTED}},
                 {"C1": {"source_ref": "codal:letter-1"}}):
        rec = build(expense={"C1": {"finance_cost_ttm": channel(-50.0)}},
                    provenance=prov, as_of=AS_OF)["C1"]
        assert rec["interest_coverage"]["pit_status"] == \
            SR.PIT_UNVERIFIED


def test_pit_after_as_of_invalidates_for_historical_use():
    late = AS_OF + dt.timedelta(days=1)
    rec = build(expense={"C1": {"finance_cost_ttm": channel(-50.0)}},
                provenance={"C1": {"available_at": late,
                                   "source_ref": "codal:late",
                                   "source_period": "1405Q3"}},
                as_of=AS_OF)["C1"]
    assert rec["interest_coverage"]["pit_status"] == SR.PIT_AFTER_AS_OF
    assert rec["interest_coverage"]["status"] == "invalid"


# ---------------------------------------------------------------------------
# 4. normalize: direction control, peers, no mutation, previous-factor
#    regression
# ---------------------------------------------------------------------------
def _world(n=12, eq_base=5.0, ic_base=2.0):
    metrics, expense = {}, {}
    for i in range(n):
        cid = f"K{i:02d}"
        metrics[cid] = {
            "revenue_ttm": 1000.0, "net_profit_ttm": 100.0,
            "operating_profit_ttm": 150.0 + i, "ocf_ttm": 90.0,
            "debt_ratio": 0.4,
        }
        expense[cid] = {
            "finance_cost_ttm": channel(-(150.0 + i) / (ic_base + i)),
            "other_nonop_ttm": channel(eq_base + i),
        }
    return metrics, expense


def test_percentile_direction_from_config_ic_higher_eq_lower():
    metrics, expense = _world()
    raw = SR.build_q_raw(metrics, expense_ttm=expense)
    meta = {c: {"model_family": "general", "industry": "Metals"}
            for c in metrics}
    out = SN.normalize_q_cross_section(raw, meta, as_of=AS_OF,
                                       pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    ic = {c: out["factors"][c]["interest_coverage"]["percentile_combined"]
          for c in metrics}
    eq = {c: out["factors"][c]["earnings_quality"]["percentile_combined"]
          for c in metrics}
    assert all(0.0 <= v <= 1.0 for v in list(ic.values()) + list(eq.values()))
    # coverage: higher raw value -> higher percentile (K11 has the top ratio)
    assert ic["K11"] > ic["K00"]
    # dependence share: lower-is-better — the SMALLest share ranks highest,
    # the largest share ranks lowest (direction read from config, not assumed)
    assert eq["K00"] > eq["K11"]
    assert CFG.V2_QVT_FACTORS["interest_coverage"]["direction"] == "higher"
    assert CFG.V2_QVT_FACTORS["earnings_quality"]["direction"] == "lower"


def test_three_company_family_is_insufficient_peers_the_real_run_shape():
    # the 2026-10-08 real store resolves the expense TTM for only 3
    # companies — normalization must refuse to rank a peer group of 3
    metrics, expense = _world(n=3)
    raw = SR.build_q_raw(metrics, expense_ttm=expense)
    meta = {c: {"model_family": "general", "industry": "Metals"}
            for c in metrics}
    out = SN.normalize_q_cross_section(raw, meta, as_of=AS_OF,
                                       pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    for c in metrics:
        for fid in ("interest_coverage", "earnings_quality"):
            assert out["factors"][c][fid]["normalization_status"] == \
                SN.NR_INSUFFICIENT_PEERS


def test_ranked_records_carry_the_unverified_exploratory_warning():
    metrics, expense = _world()
    # one huge (but real) dependence share: valid, anomaly-warned, ranked
    expense["K11"]["other_nonop_ttm"] = channel(1e6)
    raw = SR.build_q_raw(metrics, expense_ttm=expense)
    meta = {c: {"model_family": "general", "industry": "Metals"}
            for c in metrics}
    out = SN.normalize_q_cross_section(raw, meta, as_of=AS_OF,
                                       pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    recs = [r for r in out["records"] if r["factor_id"] == "earnings_quality"
            and r.get("percentile_combined") is not None]
    assert recs
    assert all(any(w.startswith("pit_unverified_exploratory")
                   for w in r["warnings"]) for r in recs)
    # anomaly warnings survive ranking untouched
    warned = [r for r in recs
              if any(w.startswith("magnitude_anomaly") for w in r["warnings"])]
    assert warned, "at least one ranked record keeps its anomaly warning"


def test_channels_and_metrics_are_never_mutated():
    metrics, expense = _world(n=2)
    m_snap = copy.deepcopy(metrics)
    e_snap = copy.deepcopy(expense)
    SR.build_q_raw(metrics, expense_ttm=expense)
    assert metrics == m_snap and expense == e_snap


def test_previous_seven_factors_byte_identical_with_and_without_channels():
    metrics, expense = _world(n=3)
    without = SR.build_q_raw(copy.deepcopy(metrics))
    with_ch = SR.build_q_raw(copy.deepcopy(metrics), expense_ttm=expense)
    previous = ("margins", "cash_conversion", "leverage", "earnings_growth",
                "roe_level", "margin_trend", "revenue_growth")
    for cid in metrics:
        for fid in previous:
            assert without[cid][fid] == with_ch[cid][fid], (cid, fid)


# ---------------------------------------------------------------------------
# 5. q_observed integration: weights 3 + 3 untouched, missing never
#    redistributed
# ---------------------------------------------------------------------------
def test_q_observed_consumes_only_ranked_expense_scores():
    metrics, expense = _world()
    raw = SR.build_q_raw(metrics, expense_ttm=expense)
    meta = {c: {"model_family": "general", "industry": "Metals"}
            for c in metrics}
    out = SN.normalize_q_cross_section(raw, meta, as_of=AS_OF,
                                       pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    rep = QO.build_q_observed_report(out, raw, meta)
    row = rep["weight_table"]["rows"]
    assert row["interest_coverage"]["weight"] == 3
    assert row["earnings_quality"]["weight"] == 3
    assert row["interest_coverage"]["in_aggregation_scope"] is True
    covered = rep["companies"]["K00"]["covered_weight"]
    # margins 6 + cash 4 + leverage 4 + ic 3 + eq 3 = 20 (no roe / revenue /
    # margin_trend inputs in this world) — the pair really contributes 3+3
    assert covered == pytest.approx(20.0)
    f = rep["companies"]["K00"]["factors"]
    assert f["interest_coverage"]["contribution_points"] == pytest.approx(
        3 * f["interest_coverage"]["score"])
    # a company whose channel is unresolved keeps its weight unused — the
    # sum never grows to fake full coverage
    metrics2, _ = _world(n=12)
    expense2 = {cid: {} for cid in metrics2}   # channels absent entirely
    raw2 = SR.build_q_raw(metrics2, expense_ttm=expense2)
    out2 = SN.normalize_q_cross_section(raw2, meta, as_of=AS_OF,
                                        pit_policy=SN.PIT_CURRENT_EXPLORATORY)
    rep2 = QO.build_q_observed_report(out2, raw2, meta)
    e2 = rep2["companies"]["K00"]
    assert e2["covered_weight"] == pytest.approx(14.0)  # 6+4+4, the pair out
    for fid in ("interest_coverage", "earnings_quality"):
        fe = e2["factors"][fid]
        assert fe["included"] is False
        assert fe["not_included_reason"].startswith("raw_missing")
        assert fe["contribution_points"] is None
