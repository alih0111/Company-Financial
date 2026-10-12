"""Order-3 recovery tests (step 2-B-8).

Covers the read-only recovery of the missing order-3 expense legs from the
project's own raw Codal letter archive (raw.report_payloads) and its merge
into the 2-B-7 expense-TTM channels:

  * the pure letter parser: FEPS cell grids embedded in the raw HTML,
    Arabic yeh/kaf + RTL-control normalization, thousand separators
  * the identity gates: exact anchor match on orders 1 AND 2 (a split
    non-operating sub-row subset may sum to the anchors), value columns
    chosen only by the cells' own periodEndToDate, prior-annual column ==
    yearEndToDate - 1y, percent columns never consumed
  * the refusals: anchor mismatch, blank annual cell (class B), ambiguous
    rows, unparsable/no-table letters, missing yearEndToDate — every
    refusal is a named state, never a guess, never a scaled value
  * the merge into the pilot channels: resolved_within_report_recovered_
    order3 with the recovery evidence on the leg; a recovered leg equal to
    a legacy sentinel constant quarantines the channel; a non-finite
    result refuses; other channel states pass through untouched
  * the 2-B-8 section: class rollup, per-company examples with evidence,
    refusal states, the corrected cap bridge (25 -> 31 from the two
    weight-3 factors, never 34)
  * one SELECT-only integration check against the shadow DB (skipped
    without CDF_PILOT_DB): فباهنر's letter recovers both legs with the
    full provenance chain

Run:
    set CDF_PILOT_DB=company_financial_analytics_shadow_v121
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests/test_expense_ttm_recovery.py -q
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG.parent / "migration_tools"))

import pytest  # noqa: E402

import expense_ttm_recovery as REC  # noqa: E402
import pilot_v2_qvt as PILOT  # noqa: E402
import report_chain_ttm as RC  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)
PERIOD_J = (1405, 3, 31)
YEND = "1405/12/29"
CUR, PREV, ANNUAL = "1405/03/31", "1404/03/31", "1404/12/29"
ANCHORS = {
    "finance_cost": {"o1": -5797765, "o2": -2258136},
    "other_non_operating": {"o1": 1478573, "o2": 705644},
}


def _dec_anchors(anchors=None):
    from decimal import Decimal
    return {m: {k: Decimal(str(v))
                for k, v in (anchors or ANCHORS)[m].items()}
            for m in REC.EXPENSE_METRICS}


def cell(tid: int, addr: str, row: int, col: int, value,
         period: str = "", yend: str = "", title: str | None = None):
    return {"metaTableId": tid, "metaTableCode": tid, "address": addr,
            "formula": "", "validations": "", "financialConcept": None,
            "cellGroupName": "Body", "rowSpan": 1, "rowCode": row,
            "rowSequence": row, "colSpan": 1, "columnCode": col,
            "columnSequence": col, "cssClass": "", "rowTypeName": "FixedRow",
            "category": 0, "isVisible": True, "value": value,
            "valueTypeName": "FormControl", "dataTypeName": "Integer",
            "decimalPlace": 0, "periodEndToDate": period,
            "yearEndToDate": yend, "conditionalIsUnique": False,
            "removableCustomRow": None, "isAudited": False,
            **({"financialConcept": title} if False else {})}


def letter_html(cells: list) -> str:
    return ("<html><body>"
            + "".join(json.dumps(c, ensure_ascii=False) for c in cells)
            + "</body></html>")


def standard_cells(tid: int = 900, onop_split: bool = False,
                   fc_annual: str | None = "-12817111",
                   onop_annual: str | None = "4872899",
                   fc_cur: str = "-5,797,765",   # thousand separators
                   arabic_labels: bool = False):
    fc_title = "هزینه هاى مالى" if arabic_labels else "هزینه های مالی"
    onop_title = "سایر درآمدها و هزینه های غیرعملیاتی"
    cells = [
        cell(tid, "B1", 1, 2, "دوره منتهي به 1405/03/31"),
        cell(tid, "C1", 1, 3, "تجديد ارائه شده دوره منتهي به 1404/03/31"),
        cell(tid, "D1", 1, 5, "تجديد ارائه شده دوره منتهي به 1404/12/29"),
        cell(tid, "E1", 1, 4, "درصد تغيير"),
        cell(tid, "A9", 9, 1, "سود (زیان) عملیاتی"),
        cell(tid, "A10", 10, 1, fc_title),
        cell(tid, "A52", 52, 1, onop_title),
    ]
    # operating row (col2 only, with yend on the current column cells)
    cells += [
        cell(tid, "B9", 9, 2, "12949186", CUR, YEND),
        cell(tid, "C9", 9, 3, "7493530", PREV, "1404/12/29"),
        cell(tid, "D9", 9, 5, "38153935", ANNUAL, ""),
        cell(tid, "E9", 9, 4, "72.8"),
    ]
    cells += [
        cell(tid, "B10", 10, 2, fc_cur, CUR, YEND),
        cell(tid, "C10", 10, 3, "-2258136", PREV, "1404/12/29"),
        cell(tid, "E10", 10, 4, "156.8"),
    ]
    if fc_annual is not None:
        cells.append(cell(tid, "D10", 10, 5, fc_annual, ANNUAL, ""))
    cells += [
        cell(tid, "B52", 52, 2, "1478573", CUR, YEND),
        cell(tid, "C52", 52, 3, "705644", PREV, "1404/12/29"),
        cell(tid, "E52", 52, 4, "109.5"),
    ]
    if onop_annual is not None:
        cells.append(cell(tid, "D52", 52, 5, onop_annual, ANNUAL, ""))
    if onop_split:
        # replace the single onop row by two labelled sub-rows
        cells = [c for c in cells if not c["address"].endswith("52")]
        cells += [
            cell(tid, "A61", 61, 1,
                 "سایر درآمدها و هزینه های غیرعملیاتی - درآمد سرمایه "
                 "گذاری ها"),
            cell(tid, "A62", 62, 1,
                 "سایر درآمدها و هزینه های غیرعملیاتی - اقلام متفرقه"),
            cell(tid, "B61", 61, 2, "1000000", CUR, YEND),
            cell(tid, "C61", 61, 3, "500000", PREV, "1404/12/29"),
            cell(tid, "D61", 61, 5, "2000000", ANNUAL, ""),
            cell(tid, "B62", 62, 2, "478573", CUR, YEND),
            cell(tid, "C62", 62, 3, "205644", PREV, "1404/12/29"),
            cell(tid, "D62", 62, 5, "2872899", ANNUAL, ""),
        ]
    return cells


# ---------------------------------------------------------------------------
# the pure extractor
# ---------------------------------------------------------------------------
def test_standard_letter_recovers_both_metrics_with_full_evidence():
    out, err = REC.extract_order3(letter_html(standard_cells()), PERIOD_J,
                                  _dec_anchors())
    assert err is None
    fc = out["finance_cost"]
    onop = out["other_non_operating"]
    assert fc["state"] == REC.STATE_RECOVERED
    assert onop["state"] == REC.STATE_RECOVERED
    # million_rial -> rial x 1e6 (the store's uniform convention)
    assert fc["value"] == -12817111 * 1_000_000
    assert onop["value"] == 4872899 * 1_000_000
    assert fc["window_dates"]["current"] == PERIOD_J
    assert fc["window_dates"]["prior_same"] == (1404, 3, 31)
    assert fc["window_dates"]["prior_annual"] == (1404, 12, 29)
    rows = fc["evidence"]["rows_used"]
    assert rows[0]["row"] == 10 and "مالی" in rows[0]["title"]
    assert rows[0]["prior_annual"] == "-12817111"
    assert fc["evidence"]["consumed_columns"] == {
        "current": 2, "prior_same": 3, "prior_annual": 5}


def test_arabic_yeh_kaf_and_thousand_separators_normalize():
    out, err = REC.extract_order3(
        letter_html(standard_cells(arabic_labels=True)), PERIOD_J,
        _dec_anchors())
    assert err is None
    assert out["finance_cost"]["state"] == REC.STATE_RECOVERED


def test_anchor_mismatch_refuses_that_metric_only():
    anchors = _dec_anchors()
    anchors["finance_cost"]["o1"] -= 1  # one rial off in the anchor
    out, err = REC.extract_order3(letter_html(standard_cells()), PERIOD_J,
                                  anchors)
    assert err is None
    assert out["finance_cost"]["state"] == REC.STATE_ROW_FAILED
    # the other metric still recovers — the gates are per metric
    assert out["other_non_operating"]["state"] == REC.STATE_RECOVERED


def test_blank_annual_cell_is_class_b_letter_blank():
    out, err = REC.extract_order3(
        letter_html(standard_cells(fc_annual=None)), PERIOD_J,
        _dec_anchors())
    assert err is None
    assert out["finance_cost"]["state"] == REC.STATE_BLANK_ANNUAL_CELL
    assert out["finance_cost"]["value"] is None
    assert out["other_non_operating"]["state"] == REC.STATE_RECOVERED


def test_percent_column_is_never_consumed_even_with_trap_values():
    cells = standard_cells()
    # a poisoned percent column with the anchors as values but NO period
    # date — it must never be picked as a value column
    cells += [cell(900, "F10", 10, 6, "-2258136", "", "")]
    out, err = REC.extract_order3(letter_html(cells), PERIOD_J,
                                  _dec_anchors())
    assert err is None
    assert out["finance_cost"]["state"] == REC.STATE_RECOVERED
    assert out["finance_cost"]["value"] == -12817111 * 1_000_000


def test_split_nonop_subrows_recover_by_exact_sum():
    out, err = REC.extract_order3(
        letter_html(standard_cells(onop_split=True)), PERIOD_J,
        _dec_anchors())
    assert err is None
    onop = out["other_non_operating"]
    assert onop["state"] == REC.STATE_RECOVERED
    assert onop["value"] == (2000000 + 2872899) * 1_000_000
    assert len(onop["evidence"]["rows_used"]) == 2


def test_split_subrows_that_do_not_sum_refuse():
    cells = standard_cells()
    cells = [c for c in cells if c["rowCode"] != 52]
    cells += [
        cell(900, "A61", 61, 1,
             "سایر درآمدها و هزینه های غیرعملیاتی - درآمد سرمایه گذاری ها"),
        cell(900, "A62", 62, 1,
             "سایر درآمدها و هزینه های غیرعملیاتی - اقلام متفرقه"),
        cell(900, "B61", 61, 2, "1000000", CUR, YEND),
        cell(900, "C61", 61, 3, "500000", PREV, "1404/12/29"),
        cell(900, "D61", 61, 5, "2000000", ANNUAL, ""),
        # sums to 1,477,573 / 705,144 — one step off the anchors
        cell(900, "B62", 62, 2, "477573", CUR, YEND),
        cell(900, "C62", 62, 3, "205144", PREV, "1404/12/29"),
        cell(900, "D62", 62, 5, "2872899", ANNUAL, ""),
    ]
    out, err = REC.extract_order3(letter_html(cells), PERIOD_J,
                                  _dec_anchors())
    assert err is None
    assert out["other_non_operating"]["state"] == REC.STATE_ROW_FAILED


def test_two_matching_rows_are_ambiguous_never_guessed():
    cells = standard_cells()
    cells += [
        cell(900, "A11", 11, 1, "هزینه های مالی"),
        cell(900, "B11", 11, 2, "-5797765", CUR, YEND),
        cell(900, "C11", 11, 3, "-2258136", PREV, "1404/12/29"),
        cell(900, "D11", 11, 5, "999999", ANNUAL, ""),
    ]
    out, err = REC.extract_order3(letter_html(cells), PERIOD_J,
                                  _dec_anchors())
    assert err is None
    assert out["finance_cost"]["state"] == REC.STATE_ROW_AMBIGUOUS


def test_missing_yearend_field_refuses_window():
    cells = standard_cells()
    for c in cells:
        if c["columnCode"] == 2:
            c["yearEndToDate"] = ""
    out, err = REC.extract_order3(letter_html(cells), PERIOD_J,
                                  _dec_anchors())
    assert out is None and err == REC.STATE_WINDOW_UNPROVABLE


def test_non_feps_letter_is_grid_unparsable():
    out, err = REC.extract_order3("<html>old-style page</html>", PERIOD_J,
                                  _dec_anchors())
    assert out is None and err == REC.STATE_GRID_UNPARSABLE


def test_letter_without_the_rows_is_no_statement_table():
    cells = [cell(900, "B1", 1, 2, "دوره منتهي به 1405/03/31")]
    out, err = REC.extract_order3(letter_html(cells), PERIOD_J,
                                  _dec_anchors())
    assert out is None and err == REC.STATE_NO_TABLE


def test_two_candidate_tables_refuse():
    cells = standard_cells() + [
        cell(901, "A10", 10, 1, "هزینه های مالی"),
        cell(901, "A52", 52, 1, "سایر درآمدها و هزینه های غیرعملیاتی"),
    ]
    out, err = REC.extract_order3(letter_html(cells), PERIOD_J,
                                  _dec_anchors())
    assert out is None and err == REC.STATE_NO_TABLE


def test_wrong_period_letter_refuses_window():
    out, err = REC.extract_order3(letter_html(standard_cells()),
                                  (1405, 6, 31), _dec_anchors())
    assert out is None and err == REC.STATE_WINDOW_UNPROVABLE


def test_states_map_to_the_census_classes():
    assert REC.CLASS_OF_STATE[REC.STATE_RECOVERED] == \
        "A_extracted_not_stored"
    assert REC.CLASS_OF_STATE[REC.STATE_BLANK_ANNUAL_CELL] == \
        "B_absent_from_letter"
    assert REC.CLASS_OF_STATE[REC.STATE_NO_PAYLOAD] == \
        "C_no_payload_in_project_archive"
    for st in (REC.STATE_ROW_FAILED, REC.STATE_ROW_AMBIGUOUS,
               REC.STATE_AMBIGUOUS_LETTERS, REC.STATE_GRID_UNPARSABLE,
               REC.STATE_NO_TABLE, REC.STATE_WINDOW_UNPROVABLE,
               REC.STATE_NO_ANCHOR):
        assert REC.CLASS_OF_STATE[st] == "D_identity_unprovable"


# ---------------------------------------------------------------------------
# the merge into the 2-B-7 channels
# ---------------------------------------------------------------------------
def _unresolved_channel(metric_value: float | None = -5797765000000.0):
    legs = {
        "latest_ytd_order1": {"cell": [1405, 3], "metric": "finance_cost",
                              "order": 1, "value": metric_value},
        "prior_year_same_period_order2": {
            "cell": [1405, 3], "metric": "finance_cost", "order": 2,
            "value": -2258136000000.0},
        "prior_fiscal_year_order3": {"cell": [1405, 3],
                                     "metric": "finance_cost", "order": 3,
                                     "value": None},
    }
    return {"state": "unresolved_missing_order3", "value": None,
            "prov_code": RC.PROV_INSUFFICIENT, "reason": "missing leg",
            "legs": legs,
            "consumed_legs": ["latest_ytd_order1",
                              "prior_year_same_period_order2"],
            "warnings": []}


_RECOVERED = {
    "state": REC.STATE_RECOVERED, "order": 3,
    "value": -12817111000000.0,
    "window_dates": {"current": PERIOD_J, "prior_same": (1404, 3, 31),
                     "prior_annual": (1404, 12, 29)},
    "evidence": {"report_id": "rep-1", "published_at": "2026-07-21 ...",
                 "source_url": "http://codal/..."},
}


def test_merge_builds_recovered_channel_with_leg_evidence():
    ch = PILOT._apply_recovered_order3(_unresolved_channel(),
                                       "finance_cost", _RECOVERED)
    assert ch["state"] == PILOT.RECOVERED_STATE
    assert ch["prov_code"] == RC.PROV_DIRECT
    # o1 + o3 - o2
    assert ch["value"] == pytest.approx(
        -5797765000000.0 + -12817111000000.0 - (-2258136000000.0))
    assert sorted(ch["consumed_legs"]) == [
        "latest_ytd_order1", "prior_fiscal_year_order3",
        "prior_year_same_period_order2"]
    leg = ch["legs"]["prior_fiscal_year_order3"]
    assert leg["value"] == -12817111000000.0
    assert leg["recovered_from"]["report_id"] == "rep-1"
    assert any("order3_recovered_from_raw_letter" in w
               for w in ch["warnings"])


def test_merge_keeps_other_states_untouched():
    ch = _unresolved_channel()
    ch["state"] = "resolved_within_report"
    assert PILOT._apply_recovered_order3(ch, "finance_cost",
                                         _RECOVERED) is ch
    ch2 = _unresolved_channel()
    assert PILOT._apply_recovered_order3(ch2, "finance_cost", None) is ch2
    bad = dict(_RECOVERED, state=REC.STATE_ROW_FAILED)
    ch3 = _unresolved_channel()
    assert PILOT._apply_recovered_order3(ch3, "finance_cost", bad) is ch3


def test_merge_quarantines_a_sentinel_recovered_leg():
    rec = dict(_RECOVERED, value=1_000_000.0)   # exact legacy sentinel
    ch = PILOT._apply_recovered_order3(_unresolved_channel(),
                                       "finance_cost", rec)
    assert ch["state"] == "quarantined_legacy_sentinel_leg"
    assert ch["value"] is None
    assert ch["prov_code"] == RC.PROV_INSUFFICIENT


def test_merge_refuses_non_finite_results():
    rec = dict(_RECOVERED, value=float("inf"))
    ch = PILOT._apply_recovered_order3(_unresolved_channel(),
                                       "finance_cost", rec)
    assert ch["state"] == "non_finite_result"
    assert ch["value"] is None


def test_resolved_state_listed_in_the_contract_tuple():
    assert PILOT.RECOVERED_STATE in PILOT.EXPENSE_TTM_STATES


# ---------------------------------------------------------------------------
# the 2-B-8 report section
# ---------------------------------------------------------------------------
def _mini_world():
    channels = {"C1": {"finance_cost_ttm": _unresolved_channel()}}
    channels["C1"]["finance_cost_ttm"] = PILOT._apply_recovered_order3(
        channels["C1"]["finance_cost_ttm"], "finance_cost", _RECOVERED)
    coverage = {
        "interest_coverage": {"n_population": 2, "raw_valid": 2,
                              "raw_missing": 0, "raw_invalid": 0,
                              "raw_not_applicable": 0, "scored": 2,
                              "single_ranked": 2, "insufficient_peers": 0},
        "earnings_quality": {"n_population": 2, "raw_valid": 1,
                             "raw_missing": 1, "raw_invalid": 0,
                             "raw_not_applicable": 0, "scored": 1,
                             "single_ranked": 1, "insufficient_peers": 0},
    }
    qo = {"companies": {"C1": {"factors": {
        "interest_coverage": {"included": True},
        "earnings_quality": {"included": True}}}},
        "weight_table": {"rows": {}}, "summary": {},
        "display_sample": []}
    detail = {"C1": {"symbol": "فباهنر", "industry": "فلزات اساسی"}}
    raw = {"C1": {"interest_coverage": {"status": "valid",
                                        "raw_value": 3.2},
                  "earnings_quality": {"status": "missing"}}}
    rec_results = {"C1": {
        "finance_cost": dict(_RECOVERED),
        "other_non_operating": {"state": REC.STATE_ROW_FAILED,
                                "reason": "x"}}}
    rec_census = {
        "finance_cost": {"targets": 125, "recovered": 103,
                         "row_identity_failed": 12},
        "other_non_operating": {"targets": 125, "recovered": 92,
                                "row_identity_failed": 23},
        "class_rollup": {"A_extracted_not_stored": 195,
                         "C_no_payload_in_project_archive": 8,
                         "D_identity_unprovable": 47},
    }
    return rec_results, rec_census, channels, coverage, qo, detail, raw


def test_2b8_section_reports_gates_census_and_corrected_cap():
    sec = PILOT.factor_batch_2b8_section(*_mini_world(), None)
    assert "raw.report_payloads" in sec["purpose"]
    assert len(sec["identity_gates"]) == 4
    assert "x 1e6" in sec["unit_convention"]
    assert sec["recovery_census"]["class_rollup"][
        "A_extracted_not_stored"] == 195
    assert sec["n_companies_both_factors_recovered"] == 0  # onop refused
    ex = sec["recovered_examples"]
    assert ex[0]["symbol"] == "فباهنر"
    assert ex[0]["channel_state"] == PILOT.RECOVERED_STATE
    assert sec["refusal_states"] == {"row_identity_failed": ["فباهنر"]}
    assert sec["ranked_status"]["n_companies_included_by_factor"] == {
        "interest_coverage": 1, "earnings_quality": 1}
    assert "25 -> 31" in sec["cap_bridge_correction"]
    assert "not 25 -> 34" in sec["cap_bridge_correction"]
    assert sec["display_companies"] == []  # qo has no aggregated universe


# ---------------------------------------------------------------------------
# SELECT-only integration check against the shadow DB
# ---------------------------------------------------------------------------
needs_db = pytest.mark.skipif(
    not os.environ.get("CDF_PILOT_DB"), reason="CDF_PILOT_DB not set")


@needs_db
def test_real_letter_recovery_for_fbahar_is_proven_and_pit_honest():
    from psycopg.rows import dict_row

    from common import pg_pilot_conn
    pg = pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    cur.execute("""SELECT company_id::text AS cid FROM core.securities
                   WHERE codal_symbol = 'فباهنر' LIMIT 1""")
    cid = cur.fetchone()[0]
    pg.close()

    rep_index = {cid: {(1405, 3): {
        "finance_cost": {1: -5797765000000.0, 2: -2258136000000.0},
        "other_non_operating": {1: 1478573000000.0, 2: 705644000000.0}}}}
    results, census = REC.recover_expense_order3(
        rep_index, {}, AS_OF, CUTOFF, company_ids={cid})
    assert census["finance_cost"]["targets"] == 1
    assert census["finance_cost"]["recovered"] == 1
    rec = results[cid]["finance_cost"]
    assert rec["state"] == REC.STATE_RECOVERED
    assert rec["order"] == 3
    assert rec["value"] == -12817111000000.0
    ev = rec["evidence"]
    for key in ("report_id", "rv_id", "published_at", "source_url",
                "rows_used", "window_dates"):
        assert key in ev
    assert ev["rows_used"][0]["prior_annual"] == "-12817111"
    # the recovered value is a REAL letter cell, never a fabricated number:
    # the window dates come from the letter itself
    assert ev["window_dates"]["prior_annual"] == "1404-12-29"


@needs_db
def test_recovery_covers_the_real_125_targets_without_writes():
    import compute_metrics as CM
    eng = CM.Engine(AS_OF, CUTOFF)
    eng.compute()
    rep_index = eng.report_index()
    durations, _ = PILOT.fiscal_calendar_for(eng)
    results, census = REC.recover_expense_order3(
        rep_index, durations, AS_OF, CUTOFF)
    fc, onop = census["finance_cost"], census["other_non_operating"]
    assert fc["targets"] == 125 and onop["targets"] == 125
    assert fc["recovered"] == 103 and onop["recovered"] == 92
    assert sum(v for k, v in census["class_rollup"].items()) == 250
    # every recovered value is finite and non-trivial
    for cid, per in results.items():
        for metric, rec in per.items():
            if rec.get("state") == REC.STATE_RECOVERED:
                assert math.isfinite(rec["value"])
