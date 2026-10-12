"""READ-ONLY exploratory pilot for the V2 QVT raw + normalize layers (2-B-4,
quarantined re-run 2-B-4.2; expense-TTM activation 2-B-7).

Runs the EXISTING production layers — score_v2_raw.build_q_raw on top of the
canonical V1 metric engine (compute_metrics.Engine) and
score_v2_normalize.normalize_q_cross_section — over the FULL reachable
canonical population, and emits a reviewable coverage report. No final Q/V/T
score is produced anywhere: the in-scope Q factors (nine as of 2-B-7) are
NOT representative of overall fundamental quality, and no factor weight is
redistributed to fake an axis score. Since 2-B-7 interest_coverage and
earnings_quality receive a same-window expense TTM resolved INSIDE the
latest report (no cross-report chain, no YTD scaling, no guessed leg — see
resolve_expense_ttm_channels); where the comparative legs are absent the
factors honestly stay missing.

READ-ONLY GUARANTEES
  * compute_metrics.Engine only ever SELECTs (pg_pilot_conn, autocommit read).
  * score_v4.load_sector_map only SELECTs core.company_classification.
  * this module never imports or calls store_run / any INSERT/UPDATE/DDL.
  * the only files it writes are its own JSON artifact under output/.

DATA HONESTY CONTRACT
  * no financial value, industry, publication date or prior-year base is ever
    guessed or fabricated:
      - industry  : real TSETMC category from core.company_classification at
                    as_of (V4's own PIT query); companies without a mapping
                    are handled by the normalization contract (family-only
                    rank, explicit industry_unknown warning), never assigned
                    an invented group.
      - prev bases: earnings_growth needs the engine's OWN prior-year TTM
                    values. compute_metrics.Engine resolves them internally
                    but does not materialize them, so this pilot re-resolves
                    them with the engine's own building blocks (report_index,
                    fiscal calendar, report_chain_ttm.resolve_ttm) and keeps a
                    base only when the provenance code matches the tag the
                    engine itself recorded (_ttm_prov) — a diverging
                    replication is DROPPED, not trusted.
      - provenance: company-level available_at = the newest REAL collected_at
                    among the company's PIT-eligible statement facts. No
                    source_ref is invented (per-metric report attribution
                    does not exist yet), so the raw layer keeps every
                    component PIT-unverified — which is exactly what an
                    exploratory run must be. This output is NEVER
                    backtest-valid evidence.
  * pit_policy is pinned to current_exploratory; as_of doubles as the
    publication cutoff the engine itself used (no synthetic timestamps).

Usage:
  set CDF_PILOT_DB=company_financial_analytics_shadow_v121
  python pilot_v2_qvt.py [--as-of 2026-09-24]
                         [--cutoff 2026-09-24T20:41:02+00:00]
                         [--sample 25] [--out output/v2_qvt_pilot.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
for p in (str(HERE), str(BASE / "migration_tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import compute_metrics as CM  # noqa: E402  (read-only metric engine)
import expense_ttm_recovery as REC  # noqa: E402  (step 2-B-8, SELECT-only)
import fiscal_calendar as FC  # noqa: E402
import report_chain_ttm as RC  # noqa: E402
import score_v2 as S2  # noqa: E402  (family resolution via V4 mapping)
import score_v2_config as CFG2  # noqa: E402  (read-only weight registry)
import score_v2_normalize as SN  # noqa: E402
import score_v2_q_observed as QO  # noqa: E402  (step 2-B-6 aggregate)
import score_v2_raw as RAW  # noqa: E402
import score_v4 as S4  # noqa: E402  (PIT sector map, SELECT-only)

STAGE = "pilot_v2_qvt_exploratory"
COMPOSITE_FACTORS = ("margins", "earnings_growth")

DISCLAIMER = (
    "EXPLORATORY ONLY — pit_policy=current_exploratory; every ranked record "
    "carries an explicit pit_unverified_exploratory warning and this output is "
    "never backtest-verified evidence. The in-scope Q factors (nine as of "
    "step 2-B-7) do not represent overall fundamental quality: no Q/V/T or "
    "total score is computed here and no weight is redistributed across "
    "missing factors. interest_coverage and earnings_quality are served "
    "through a same-window expense-TTM channel resolved inside the latest "
    "report (factor_batch_2b7); where its comparative legs are absent they "
    "stay missing — never a guessed window. earnings_growth additionally "
    "carries a separate economic-validity diagnostic label (report key "
    "economic_validity) and a temporary quarantine of prior-year TTM bases "
    "that consume legacy sentinel cells (report key growth_quarantine); the "
    "baseline run without quarantine is kept for comparison only (report "
    "key baseline_unquarantined)."
)

# ---------------------------------------------------------------------------
# 2-B-4.1 diagnostic: legacy-migration sentinel constants
# ---------------------------------------------------------------------------
# The canonical store carries thousands of NON-superseded legacy synthetic
# rows (no report title, no published_at) whose canonical value is an exact
# ±1,000,000 / ±100,000,000 rial constant for operating_profit. A prior-year
# TTM chained over such cells collapses to the constant itself, and the
# resulting growth magnitudes (billions of percent) are data artifacts, not
# economics. This pilot cannot confirm the economic validity of
# earnings_growth from the store alone, so the report carries a SEPARATE
# diagnostic label — it never rewrites a base, a raw status or a score.
SENTINEL_VALUES = (1_000_000.0, -1_000_000.0, 100_000_000.0, -100_000_000.0)
SENTINEL_METRICS = ("net_profit", "operating_profit")
ECONOMIC_VALIDITY_LABEL = "economic_validity_unverified"

# ---------------------------------------------------------------------------
# 2-B-4.2 temporary quarantine of legacy-sentinel prior-year bases
# ---------------------------------------------------------------------------
# The 2-B-4.1 audit proved the anomaly root cause: prior-year TTM bases whose
# annual/direct/chain resolution consumes a legacy sentinel cell (exact
# ±1e6/±1e8 rial operating_profit rows with no report title and no
# published_at) collapse to the constant and poison the growth cross-section.
# This pilot cannot fix the store, so it QUARANTINES: before build_q_raw, a
# prev_base tag whose resolved path consumed such a cell is REMOVED from the
# exploratory input — the raw layer then applies its own missing-base
# contract (component missing -> no blend, never a guessed value, zero or
# conversion factor). The OTHER component's base is untouched, and the
# baseline run without quarantine is recomputed on the same companies and
# as_of so healthy-company percentiles can be compared honestly.
QUARANTINE_POLICY = "legacy_sentinel_base_quarantine_v1"
QUARANTINE_REASON = (
    "prior-year TTM base consumes at least one legacy sentinel cell (exact "
    "±1e6/±1e8 rial operating_profit/net_profit row with no report title and "
    "no published_at) — the base is treated as untrustworthy and removed "
    "from the exploratory input; no replacement value, zero or conversion "
    "factor is invented and the healthy component's base is kept"
)


# ---------------------------------------------------------------------------
# engine-adjacent inputs (all rebuilt from the engine's own data, no guessing)
# ---------------------------------------------------------------------------
def fiscal_calendar_for(eng):
    """Rebuild compute_metrics' fiscal calendar from the SAME codal titles,
    so prev-base replication uses identical fiscal evidence."""
    cal_rows = []
    for row in getattr(eng, "codal_titles", []):
        try:
            c_fy, c_fm = CM.fiscal_ym(row["period_end_date"])
        except Exception:
            continue
        cal_rows.append((row["company_id"], row["title"], c_fy, c_fm))
    durations_cell, fiscal_cal = FC.build_fiscal_calendar(cal_rows)
    durations_by_company: dict = {}
    for (c_id, cell_key), dur in durations_cell.items():
        durations_by_company.setdefault(c_id, {})[cell_key] = dur
    return durations_by_company, fiscal_cal


def resolve_prev_bases(eng) -> tuple[dict, dict]:
    """{cid: {"net_profit_prev": x, "operating_profit_prev": y,
    "revenue_prev": z}} — the engine's own prior-year TTM values.

    compute_metrics.Engine resolves these internally (its ``rtt`` closure) but
    does not materialize them, and its docstring contract for prev_bases
    forbids substituting the unverified derived percents. So the pilot
    re-resolves them with the engine's own tested building blocks and keeps a
    base ONLY when the resolved provenance code equals the code the engine
    itself recorded in metrics[cid]["_ttm_prov"] — any divergence between the
    replication and the engine's own resolution drops the base. revenue_prev
    (needed by margin_trend since 2-B-5) follows the identical
    engine-anchored contract; revenue carries no legacy-sentinel signature
    (SENTINEL_METRICS), so it needs no quarantine of its own.
    """
    rep_index = eng.report_index()
    durations_by_company, fiscal_cal = fiscal_calendar_for(eng)
    bases: dict = {}
    diag = {"n_companies": len(eng.metrics), "n_net_base": 0, "n_op_base": 0,
            "n_rev_base": 0,
            "n_no_report": 0, "n_unresolved": 0, "n_prov_mismatch": 0}
    for cid, m in eng.metrics.items():
        rep = rep_index.get(cid, {})
        if not rep:
            diag["n_no_report"] += 1
            continue
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        prev = (latest[0] - 1, latest[1])
        ann_month, ann_state, _src = FC.annual_month_of(fiscal_cal, cid)
        cell_durations = durations_by_company.get(cid, {})
        # exactly compute_metrics.Engine.rtt's resolution contract:
        is_annual = True if cell_durations.get(prev) == 12 else None
        anchor = FC.prev_annual_cell(cell_durations, *prev)
        eng_prov = m.get("_ttm_prov", {})
        for metric, tag in (("net_profit", "net_profit_prev"),
                            ("operating_profit", "operating_profit_prev"),
                            ("revenue", "revenue_prev")):
            v, p = RC.resolve_ttm(rep, metric, *prev, annual_month=ann_month,
                                  is_annual=is_annual,
                                  prev_annual_cell=anchor)
            if p == RC.PROV_CHAIN and anchor is None \
                    and ann_state != FC.STATE_EXPLICIT:
                # the engine blocks rather than guess a fiscal-year anchor
                v, p = None, RC.PROV_FISCAL_UNKNOWN
            if v is None:
                diag["n_unresolved"] += 1
                continue
            if eng_prov.get(tag) != p:
                # replication disagrees with the engine's own resolution —
                # drop the base instead of trusting either side
                diag["n_prov_mismatch"] += 1
                continue
            bases.setdefault(cid, {})[tag] = v
        if isinstance(bases.get(cid), dict):
            diag["n_net_base"] += int("net_profit_prev" in bases[cid])
            diag["n_op_base"] += int("operating_profit_prev" in bases[cid])
            diag["n_rev_base"] += int("revenue_prev" in bases[cid])
    diag["n_no_base_at_all"] = sum(
        1 for cid in eng.metrics if cid not in bases)
    return bases, diag


def build_provenance(eng) -> tuple[dict, dict]:
    """({cid: {"available_at": real ts}}, diag) — company-level publication
    evidence from REAL ingestion timestamps only: the newest collected_at
    among the company's PIT-eligible statement facts. No source_ref is
    fabricated (per-metric report attribution does not exist yet), so the raw
    layer keeps every component PIT-unverified — the honest exploratory state.
    """
    latest: dict = {}
    n_superseded = 0
    for st in eng.stmt:
        if st["report_id"] in eng.superseded:
            n_superseded += 1
            continue
        ts = st.get("collected_at")
        if ts is None:
            continue
        cid = st["company_id"]
        if latest.get(cid) is None or ts > latest[cid]:
            latest[cid] = ts
    prov = {cid: {"available_at": ts} for cid, ts in latest.items()}
    diag = {"n_with_real_available_at": len(prov),
            "n_without_any_timestamp": sum(1 for cid in eng.metrics
                                           if cid not in prov),
            "n_superseded_rows_skipped": n_superseded}
    return prov, diag


def detect_sentinel_fact_cells(eng) -> tuple[dict, Counter]:
    """({cid: {(fy, fm, metric, order)}}, {metric: n_rows}) of NON-superseded
    statement facts whose canonical value is an exact legacy-migration
    sentinel constant. Purely diagnostic: nothing is dropped or rewritten.
    """
    cells: dict = {}
    census: Counter = Counter()
    for st in getattr(eng, "stmt", []) or []:
        if st.get("report_id") in (getattr(eng, "superseded", None) or set()):
            continue
        v = st.get("canonical_value")
        if v is None or float(v) not in SENTINEL_VALUES:
            continue
        metric = st.get("metric_code")
        if metric not in SENTINEL_METRICS:
            continue
        fy, fm = st.get("fiscal_year"), st.get("fiscal_month")
        if fy is None or fm is None:
            try:
                fy, fm = CM.fiscal_ym(st["period_end_date"])
            except Exception:
                continue
        cells.setdefault(st["company_id"], set()).add(
            (fy, fm, metric, st.get("period_order")))
        census[metric] += 1
    return cells, census


def sentinel_base_flags(eng, bases: dict,
                        sentinel_cells: dict | None = None) -> dict:
    """{cid: {tag: [flag, ...]}} — which legs of each SUPPLIED prior-year
    base consumed sentinel cells, resolved under the exact same contract as
    resolve_prev_bases (annual/direct/chain legs selected by the resolved
    provenance code), plus the exact-constant base value itself. Diagnostic
    only: the bases are NOT modified.
    """
    flags: dict = {}
    if not bases:
        return flags
    if sentinel_cells is None:
        sentinel_cells, _census = detect_sentinel_fact_cells(eng)
    rep_index = eng.report_index()
    durations_by_company, fiscal_cal = fiscal_calendar_for(eng)
    for cid, bb in bases.items():
        rep = rep_index.get(cid, {})
        if not rep:
            continue
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        prev = (latest[0] - 1, latest[1])
        ann_month, ann_state, _src = FC.annual_month_of(fiscal_cal, cid)
        cell_durations = durations_by_company.get(cid, {})
        is_annual = True if cell_durations.get(prev) == 12 else None
        anchor = FC.prev_annual_cell(cell_durations, *prev)
        sc = sentinel_cells.get(cid, set())

        def _leg(key, metric, order):
            d = ((rep.get(key) or {}).get(metric)) or {}
            v = d.get(order)
            return ((key[0], key[1], metric, order) in sc
                    and v is not None and float(v) in SENTINEL_VALUES)

        for metric, tag in (("net_profit", "net_profit_prev"),
                            ("operating_profit", "operating_profit_prev")):
            if tag not in bb:
                continue
            fl: list = []
            bv = bb.get(tag)
            if bv is not None and float(bv) in SENTINEL_VALUES:
                fl.append("base_exact_sentinel_value")
            v, p = RC.resolve_ttm(rep, metric, *prev, annual_month=ann_month,
                                  is_annual=is_annual,
                                  prev_annual_cell=anchor)
            if p == RC.PROV_CHAIN and anchor is None \
                    and ann_state != FC.STATE_EXPLICIT:
                v, p = None, RC.PROV_FISCAL_UNKNOWN
            if v is not None and float(v) in SENTINEL_VALUES:
                if "base_exact_sentinel_value" not in fl:
                    fl.append("resolved_base_exact_sentinel_value")
            if p == RC.PROV_ANNUAL_REPORT:
                if _leg(prev, metric, 1):
                    fl.append("prev_cell_o1")
            elif p == RC.PROV_DIRECT:
                for order, name in ((1, "prev_cell_o1"), (2, "prev_cell_o2"),
                                    (3, "prev_cell_o3")):
                    if _leg(prev, metric, order):
                        fl.append(name)
            elif p == RC.PROV_CHAIN:
                if _leg(prev, metric, 1):
                    fl.append("prev_cell_o1")
                if anchor is not None and _leg(anchor, metric, 1):
                    fl.append("annual_anchor_o1")
                if _leg((prev[0] - 1, prev[1]), metric, 1):
                    fl.append("prior_comparable_ytd_o1")
            if fl:
                flags.setdefault(cid, {})[tag] = fl
    return flags


_GROWTH_COMPONENT_TO_BASE_TAG = {
    "net_profit_growth_pct": "net_profit_prev",
    "operating_profit_growth_pct": "operating_profit_prev",
}


def legacy_sentinel_cells(eng, sentinel_cells: dict) -> dict:
    """Subset of sentinel-valued cells whose rep-index WINNER is the sentinel
    constant — i.e. cells the engine's own resolution actually consumes. A
    sentinel fact row that lost its cell to a real value is inert for TTM
    bases and must never drive a quarantine."""
    rep_index = eng.report_index()
    consumed: dict = {}
    for cid, keys in (sentinel_cells or {}).items():
        rep = rep_index.get(cid, {})
        for key in keys:
            fy, fm, metric, order = key
            v = (((rep.get((fy, fm)) or {}).get(metric)) or {}).get(order)
            if v is not None and float(v) in SENTINEL_VALUES:
                consumed.setdefault(cid, set()).add(key)
    return consumed


def titled_period_coverage(eng) -> dict:
    """{cid: {(fy, fm)}} of periods covered by a titled PUBLISHED Codal
    report — the engine's only window into publication evidence (codal_titles
    is loaded with published_at IS NOT NULL AND title IS NOT NULL)."""
    covered: dict = {}
    for row in getattr(eng, "codal_titles", []) or []:
        try:
            fy, fm = CM.fiscal_ym(row["period_end_date"])
        except Exception:
            continue
        covered.setdefault(row["company_id"], set()).add((fy, fm))
    return covered


def classify_legacy_cells(eng, sentinel_cells: dict, consumed: dict) -> dict:
    """Origin classification of the sentinel-VALUED cells (2-B-4.2).

    Consumption (rep-index winner == the constant) is the quarantine trigger;
    codal-title coverage of the period only refines the reason: a consumed
    cell in a period with NO titled published report is pure legacy evidence,
    while a consumed cell inside a titled-covered period is a legacy row
    shadowing titled coverage (with the residual caveat that the engine
    cannot exclude a report genuinely printing the constant — the store-wide
    audit found none). Sentinel-valued cells that lost their cell to a real
    value are counted as INERT uncertainty: never quarantined, never
    declared clean.
    """
    covered = titled_period_coverage(eng)
    classes: dict = {}
    counts = {"value_cells": 0, "consumed_cells": 0, "inert_cells": 0,
              "no_published_period_cells": 0, "shadowing_titled_period_cells": 0}
    for cid, keys in (sentinel_cells or {}).items():
        cov = covered.get(cid, set())
        cons = consumed.get(cid, set())
        for key in keys:
            counts["value_cells"] += 1
            if key not in cons:
                counts["inert_cells"] += 1
                continue
            counts["consumed_cells"] += 1
            if (key[0], key[1]) in cov:
                counts["shadowing_titled_period_cells"] += 1
                classes.setdefault(cid, {})[key] = "legacy_row_shadowing_titled_period"
            else:
                counts["no_published_period_cells"] += 1
                classes.setdefault(cid, {})[key] = "legacy_no_published_period_evidence"
    return {"classes": classes, "counts": counts}


def _prev_prov_codes(eng, rep_index, durations_by_company, fiscal_cal, cid):
    """The engine's own provenance codes for the prior-year TTM tags (same
    resolution and fiscal guard as resolve_prev_bases)."""
    rep = rep_index.get(cid, {})
    if not rep:
        return {}
    latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
    prev = (latest[0] - 1, latest[1])
    ann_month, ann_state, _src = FC.annual_month_of(fiscal_cal, cid)
    cell_durations = durations_by_company.get(cid, {})
    is_annual = True if cell_durations.get(prev) == 12 else None
    anchor = FC.prev_annual_cell(cell_durations, *prev)
    out = {}
    for metric, tag in (("net_profit", "net_profit_prev"),
                        ("operating_profit", "operating_profit_prev")):
        _v, p = RC.resolve_ttm(rep, metric, *prev, annual_month=ann_month,
                               is_annual=is_annual, prev_annual_cell=anchor)
        if p == RC.PROV_CHAIN and anchor is None \
                and ann_state != FC.STATE_EXPLICIT:
            p = RC.PROV_FISCAL_UNKNOWN
        out[tag] = p
    return out


def quarantine_prev_bases(eng, bases: dict, sentinel_cells: dict | None = None,
                          census: Counter | None = None) -> tuple[dict, dict]:
    """(clean_bases, info) — the 2-B-4.2 temporary quarantine.

    Removes ONLY the prev_base tag whose resolved prior-year path (annual /
    direct / chain legs selected by the engine's own provenance code) consumed
    a legacy sentinel cell, or whose resolved value is itself the constant.
    The other component's base is NEVER dropped for it (healthy net profit
    survives an operating-profit contamination and vice versa). Nothing is
    replaced with a guess, zero or conversion factor: the raw layer sees a
    missing base and applies its own missing contract (component missing ->
    no blend). The input dict is never mutated; consumption — not mere value
    equality — is the trigger, and inert sentinel cells are reported as
    uncertainty instead of being auto-declared clean.
    """
    if sentinel_cells is None:
        sentinel_cells, census = detect_sentinel_fact_cells(eng)
    consumed = legacy_sentinel_cells(eng, sentinel_cells)
    classified = classify_legacy_cells(eng, sentinel_cells, consumed)
    classes, cell_counts = classified["classes"], classified["counts"]
    flags = sentinel_base_flags(eng, bases, sentinel_cells=sentinel_cells)
    rep_index = eng.report_index()
    durations_by_company, fiscal_cal = fiscal_calendar_for(eng)

    clean: dict = {}
    rows: list = []
    by_tag: Counter = Counter()
    for cid in sorted(bases):
        kept = {}
        prov_codes = None
        for tag, value in bases[cid].items():
            fl = flags.get(cid, {}).get(tag)
            if not fl:
                kept[tag] = value
                continue
            if prov_codes is None:
                prov_codes = _prev_prov_codes(
                    eng, rep_index, durations_by_company, fiscal_cal, cid)
            metric = "net_profit" if tag == "net_profit_prev" else "operating_profit"
            origins = sorted({c for key, c in classes.get(cid, {}).items()
                              if key[2] == metric}) or ["value_signature_only"]
            by_tag[tag] += 1
            subj = (getattr(eng, "subjects", {}) or {}).get(cid, {})
            rows.append({
                "company_id": cid,
                "symbol": subj.get("symbol"),
                "tag": tag,
                "base_value": value,
                "prov_code": prov_codes.get(tag),
                "flags": fl,
                "origin_classes": origins,
                "reason": QUARANTINE_REASON,
            })
        if kept:
            clean[cid] = kept
    inert = cell_counts["inert_cells"]
    shadow = cell_counts["shadowing_titled_period_cells"]
    info = {
        "policy": QUARANTINE_POLICY,
        "reason": QUARANTINE_REASON,
        "signature": {"values_rial": list(SENTINEL_VALUES),
                      "metrics": list(SENTINEL_METRICS)},
        "n_companies_with_quarantined_base": len({r["company_id"] for r in rows}),
        "n_quarantined_tags": len(rows),
        "n_quarantined_tags_by_tag": dict(sorted(by_tag.items())),
        "quarantined": rows,
        "cell_census": {
            "value_rows_by_metric": dict(sorted((census or Counter()).items())),
            **cell_counts,
        },
        "uncertain": {
            "inert_sentinel_cells_not_consumed_by_any_base": inert,
            "consumed_cells_shadowing_titled_period": shadow,
            "note": ("inert sentinel cells are reported, never auto-declared "
                     "clean; a consumed cell inside a titled-covered period "
                     "is still quarantined because the engine cannot "
                     "separate a shadowing legacy row from a report genuinely "
                     "printing the constant (store audit: zero titled "
                     "sentinel rows exist today) — the residual separation "
                     "belongs to the upstream data purge"),
        },
        "not_modified": ("no base replaced with a guess or zero; healthy "
                         "component bases untouched; raw/normalize/engine "
                         "contracts unchanged; input dict not mutated"),
    }
    return clean, info


# ---------------------------------------------------------------------------
# 2-B-7: same-window expense TTM channels for interest_coverage /
# earnings_quality (within-report assembly over the engine's own report index)
# ---------------------------------------------------------------------------
EXPENSE_TTM_SPEC = (("finance_cost", "finance_cost_ttm"),
                    ("other_non_operating", "other_nonop_ttm"))

EXPENSE_TTM_CONTRACT = (
    "within-report same-window assembly ONLY (the report_chain_ttm direct "
    "contract): expense_ttm = latest-report period_order 1 + 3 - 2, or "
    "order 1 when the latest report is explicitly 12-month (Codal title "
    "evidence) or covers fiscal month 12. The metric registry classifies "
    "finance_cost / other_non_operating DIRECT_ONLY, so there is NO "
    "cross-report chain (that would mix restatement bases across reports), "
    "no YTD*12/fm scaling and no guessed leg — a missing comparative leg "
    "honestly leaves the TTM unresolved and the factor missing. A consumed "
    "leg equal to an exact legacy-migration sentinel constant quarantines "
    "the channel (2-B-4.2 discipline extended to the expense legs).")

EXPENSE_TTM_STATES = (
    "resolved_annual_title", "resolved_fiscal_month_12",
    "resolved_within_report", "resolved_within_report_recovered_order3",
    "unresolved_no_order1_value",
    "unresolved_missing_order2", "unresolved_missing_order3",
    "unresolved_missing_order2_and_order3",
    "quarantined_legacy_sentinel_leg", "non_finite_result", "no_report")

# step 2-B-8: the order-3 leg recovered from the project's own raw Codal
# letter archive (raw.report_payloads) under the recovery module's identity
# gates. The channel keeps PROV_DIRECT (one letter, one restated basis) and
# carries the full recovery evidence for audit.
RECOVERED_STATE = "resolved_within_report_recovered_order3"

RECOVERY_CONTRACT = (
    "order-3 recovery from raw.report_payloads (SELECT-only): the raw Codal "
    "letter of the SAME company + SAME Jalali period as the engine's latest "
    "cell, PIT-eligible and not superseded; value columns chosen by the "
    "letter cells' own periodEndToDate (current == statement period, "
    "prior-same == year-1 same month/day, prior-annual == yearEndToDate-1y); "
    "a row (or a split sub-row subset) is accepted only when it reproduces "
    "the stored reported_value of orders 1 AND 2 EXACTLY; current vs "
    "prior-same columns differ by exactly one year, so o1 + o3 - o2 stays a "
    "same-window TTM on one restated basis. Everything else is refused with "
    "a named state — no guessing, no scaling, no fabricated source_ref.")


def _apply_recovered_order3(ch: dict, metric: str, rec: dict | None) -> dict:
    """Merge a recovery outcome into an unresolved_missing_order3 channel —
    pure, never mutates ``ch``; sentinel and non-finite discipline extend to
    the recovered leg."""
    if ch["state"] != "unresolved_missing_order3" or not rec \
            or rec.get("state") != REC.STATE_RECOVERED:
        return ch
    legs = ch["legs"]
    o1 = legs["latest_ytd_order1"]["value"]
    o2 = legs["prior_year_same_period_order2"]["value"]
    o3 = rec.get("value")
    consumed = {"latest_ytd_order1": o1,
                "prior_year_same_period_order2": o2,
                "prior_fiscal_year_order3": o3}
    value = o1 + o3 - o2
    for name, v in consumed.items():
        if v is not None and float(v) in SENTINEL_VALUES:
            return {**ch, "state": "quarantined_legacy_sentinel_leg",
                    "prov_code": RC.PROV_INSUFFICIENT, "value": None,
                    "consumed_legs": sorted(consumed),
                    "reason": ("ttm_quarantined_legacy_sentinel_leg: the "
                               f"{name} leg equals an exact legacy-migration "
                               "sentinel constant (±1e6/±1e8 rial) — the "
                               "recovered channel is treated as "
                               "untrustworthy; no replacement value"),
                    "warnings": [
                        f"ttm_quarantined_legacy_sentinel_leg: {metric} "
                        f"{name} == {v!r}"]}
    if not math.isfinite(value):
        return {**ch, "state": "non_finite_result",
                "prov_code": "NON_FINITE_RESULT", "value": None,
                "consumed_legs": sorted(consumed),
                "reason": ("the three real legs computed to a non-finite "
                           "TTM — refused, never kept as data"),
                "warnings": []}
    ev_leg = dict(legs["prior_fiscal_year_order3"])
    ev_leg["value"] = o3
    ev_leg["recovered_from"] = rec.get("evidence")
    new_legs = dict(legs)
    new_legs["prior_fiscal_year_order3"] = ev_leg
    return {**ch, "state": RECOVERED_STATE, "value": value,
            "prov_code": RC.PROV_DIRECT,
            "legs": new_legs,
            "consumed_legs": sorted(consumed),
            "reason": ("within-report same-window assembly with the order-3 "
                       "leg recovered from the letter's own raw payload: "
                       "identity proven by exact order-1/order-2 anchor "
                       "match, window dates recorded in the leg evidence"),
            "warnings": [
                "order3_recovered_from_raw_letter: "
                + str((rec.get("evidence") or {}).get("report_id"))]}


def _expense_ttm_channel(rep: dict, latest: tuple, metric: str,
                         is_annual) -> dict:
    """Pure: one expense-TTM channel for one company/metric, built from the
    real report index only. Never mutates ``rep``; never guesses."""
    fy, fm = latest
    d = (rep.get(latest) or {}).get(metric) or {}
    o1, o2, o3 = d.get(1), d.get(2), d.get(3)
    legs = {
        "latest_ytd_order1": {"cell": [fy, fm], "metric": metric,
                              "order": 1, "value": o1},
        "prior_year_same_period_order2": {"cell": [fy, fm], "metric": metric,
                                          "order": 2, "value": o2},
        "prior_fiscal_year_order3": {"cell": [fy, fm], "metric": metric,
                                     "order": 3, "value": o3},
    }

    def _channel(state: str, value, prov_code: str, reason: str,
                 consumed: dict, warnings: list | None = None) -> dict:
        return {"state": state, "value": value, "prov_code": prov_code,
                "reason": reason, "legs": legs,
                "consumed_legs": sorted(consumed),
                "warnings": list(warnings or ())}

    if is_annual or fm == 12:
        if o1 is None:
            return _channel(
                "unresolved_no_order1_value", None, RC.PROV_INSUFFICIENT,
                f"no {metric} order-1 value in the latest report cell",
                {"latest_ytd_order1": o1})
        if is_annual:
            return _channel(
                "resolved_annual_title", o1, RC.PROV_ANNUAL_REPORT,
                "the latest report is explicitly 12-month (Codal title "
                "evidence) — its annual order-1 value IS the TTM",
                {"latest_ytd_order1": o1})
        return _channel(
            "resolved_fiscal_month_12", o1, RC.PROV_DIRECT,
            "the latest report covers fiscal month 12 — its annual order-1 "
            "value IS the TTM",
            {"latest_ytd_order1": o1})

    if o1 is None:
        return _channel(
            "unresolved_no_order1_value", None, RC.PROV_INSUFFICIENT,
            f"no {metric} order-1 value in the latest report cell",
            {"latest_ytd_order1": o1})
    missing = [name for name, v in (
        ("prior_year_same_period_order2", o2),
        ("prior_fiscal_year_order3", o3)) if v is None]
    if missing:
        return _channel(
            "unresolved_missing_order2" if missing == [
                "prior_year_same_period_order2"] else
            "unresolved_missing_order3" if missing == [
                "prior_fiscal_year_order3"] else
            "unresolved_missing_order2_and_order3",
            None, RC.PROV_INSUFFICIENT,
            "within-report comparative leg(s) absent from the latest "
            "report: " + ", ".join(missing) + " — no cross-report chain "
            "(DIRECT_ONLY registry), no YTD scaling, no guessed leg",
            {"latest_ytd_order1": o1, "prior_year_same_period_order2": o2,
             "prior_fiscal_year_order3": o3})
    consumed = {"latest_ytd_order1": o1, "prior_year_same_period_order2": o2,
                "prior_fiscal_year_order3": o3}
    value = o1 + o3 - o2
    for name, v in consumed.items():
        if v is not None and float(v) in SENTINEL_VALUES:
            return _channel(
                "quarantined_legacy_sentinel_leg", None,
                RC.PROV_INSUFFICIENT,
                "ttm_quarantined_legacy_sentinel_leg: the "
                f"{name} leg equals an exact legacy-migration sentinel "
                "constant (±1e6/±1e8 rial) — the channel is treated as "
                "untrustworthy and left unresolved (2-B-4.2 discipline "
                "extended to the expense TTM legs); no replacement value",
                consumed,
                [f"ttm_quarantined_legacy_sentinel_leg: {metric} {name} "
                 f"== {v!r}"])
    if not math.isfinite(value):
        return _channel(
            "non_finite_result", None, "NON_FINITE_RESULT",
            "the three real legs computed to a non-finite TTM — refused, "
            "never kept as data", consumed)
    return _channel(
        "resolved_within_report", value, RC.PROV_DIRECT,
        "within-report same-window assembly: order1 + order3 - order2 of "
        "the latest report", consumed)


def resolve_expense_ttm_channels(eng, recovery: dict | None = None,
                                 rep_index: dict | None = None,
                                 durations_by_company: dict | None = None
                                 ) -> tuple[dict, dict]:
    """({cid: {"finance_cost_ttm": channel, "other_nonop_ttm": channel}},
    {tag: census}) — the 2-B-7 same-window expense TTMs, replicated from the
    engine's own report index with the pilot's read-only building blocks.
    ``recovery`` (step 2-B-8) optionally supplies proven order-3 legs for the
    unresolved_missing_order3 channels.
    Read-only: no SQL here, no mutation of the engine's structures.
    """
    rep_index = rep_index if rep_index is not None else eng.report_index()
    if durations_by_company is None:
        durations_by_company, _f = fiscal_calendar_for(eng)
    channels: dict = {}
    census: dict = {tag: Counter() for _m, tag in EXPENSE_TTM_SPEC}
    for cid in eng.metrics:
        rep = rep_index.get(cid, {})
        if not rep:
            for _m, tag in EXPENSE_TTM_SPEC:
                census[tag]["no_report"] += 1
            continue
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        is_annual = True if durations_by_company.get(cid, {}).get(latest) \
            == 12 else None
        rec_by_metric = (recovery or {}).get(cid) or {}
        for metric, tag in EXPENSE_TTM_SPEC:
            ch = _expense_ttm_channel(rep, latest, metric, is_annual)
            ch = _apply_recovered_order3(ch, metric,
                                         rec_by_metric.get(metric))
            channels.setdefault(cid, {})[tag] = ch
            census[tag][ch["state"]] += 1
            v = ch["value"]
            if v is not None:
                census[tag]["sign_" + ("negative" if v < 0 else "positive"
                                       if v > 0 else "zero")] += 1
    return channels, {tag: dict(sorted(c.items()))
                      for tag, c in census.items()}


def economic_validity_section(raw_by_company: dict, bases: dict,
                              base_flags: dict, detail: dict,
                              sentinel_census: Counter) -> dict:
    """The separate 2-B-4.1 diagnostic label for earnings_growth: the raw
    layer kept every value and warning exactly per its own contract, but the
    ECONOMIC validity of the growth magnitudes could not be confirmed from
    the store alone. Counts only — no status, base or score is changed."""
    components: dict = {}
    for comp, tag in _GROWTH_COMPONENT_TO_BASE_TAG.items():
        affected: list = []
        n_valid = 0
        for cid, bb in bases.items():
            if tag not in bb:
                continue
            part = (((raw_by_company.get(cid, {})
                      .get("earnings_growth", {}) or {})
                     .get("components", {}) or {}).get(comp)) or {}
            if part.get("status") != RAW.STATUS_VALID:
                continue
            n_valid += 1
            if base_flags.get(cid, {}).get(tag):
                affected.append(detail[cid]["symbol"] or cid)
        components[comp] = {
            "n_valid_growth_values": n_valid,
            "n_sentinel_affected": len(affected),
            "affected_symbols": sorted(affected),
        }
    return {
        "factor_id": "earnings_growth",
        "label": ECONOMIC_VALIDITY_LABEL,
        "label_fa": "اعتبار اقتصادی بررسی‌نشده",
        "reason": ("the raw layer kept every value and warning per its own "
                   "contract, but the economic validity of the growth "
                   "magnitudes could NOT be confirmed from the canonical "
                   "store alone: prior-year bases chained over "
                   "legacy-migration sentinel constants (exact ±1e6/±1e8 "
                   "rial operating_profit rows with no report title and no "
                   "published_at) and the remaining magnitudes are not "
                   "externally verified — treat every earnings_growth value "
                   "as diagnostically unverified"),
        "sentinel_signature": {"values_rial": list(SENTINEL_VALUES),
                               "metrics": list(SENTINEL_METRICS)},
        "sentinel_census_rows_by_metric":
            dict(sorted(sentinel_census.items())),
        "components": components,
        "note": ("diagnostic only — the label itself changes no raw status, "
                 "base or score; quarantine of flagged bases (where applied) "
                 "is reported separately under growth_quarantine and does "
                 "NOT by itself verify the economics of the remaining "
                 "growth values"),
    }


# ---------------------------------------------------------------------------
# 2-B-4.2 before/after comparison (baseline A vs quarantined exploratory B)
# ---------------------------------------------------------------------------
def growth_cross_table(raw_baseline: dict, bases: dict, base_flags: dict) -> dict:
    """{component: quadrant counts} over the BASELINE run's valid growth
    values: contaminated/clean base x with/without magnitude_anomaly. This
    reconciles the leg-based quarantine census with the magnitude-band
    warnings (in-band contaminated bases and out-of-band clean bases both
    exist by construction)."""
    table: dict = {}
    for comp, tag in _GROWTH_COMPONENT_TO_BASE_TAG.items():
        ct: Counter = Counter()
        for cid, bb in bases.items():
            if tag not in bb:
                continue
            part = (((raw_baseline.get(cid, {})
                      .get("earnings_growth", {}) or {})
                     .get("components", {}) or {}).get(comp)) or {}
            if part.get("status") != RAW.STATUS_VALID:
                continue
            contaminated = bool(base_flags.get(cid, {}).get(tag))
            warned = any(w.startswith("magnitude_anomaly")
                         for w in part.get("warnings", []))
            ct[("contaminated" if contaminated else "clean")
               + ("_with_anomaly" if warned else "_without_anomaly")] += 1
        table[comp] = dict(sorted(ct.items()))
    return table


def _component_valid_counts(raw_by_company: dict) -> dict:
    counts = {}
    for comp in _GROWTH_COMPONENT_TO_BASE_TAG:
        counts[comp] = sum(
            1 for rec in raw_by_company.values()
            if (((rec.get("earnings_growth", {}) or {})
                 .get("components", {}) or {}).get(comp) or {}
                ).get("status") == RAW.STATUS_VALID)
    return counts


def _component_percentiles(out: dict, comp: str) -> dict:
    return {r["company_id"]: r.get("percentile_market_family")
            for r in out["records"]
            if r["factor_id"] == "earnings_growth"
            and r.get("component_id") == comp}


def percentile_comparison(out_baseline: dict, out_clean: dict,
                          detail: dict) -> dict:
    """Healthy-company growth percentiles recomputed on the cleaned
    population: a quarantined extreme value previously dragged every healthy
    percentile and the winsor bounds — this quantifies the shift instead of
    hiding it. Only companies whose component is valid in BOTH runs are
    compared; quarantined companies simply leave the population."""
    res: dict = {}
    for comp in _GROWTH_COMPONENT_TO_BASE_TAG:
        pb = _component_percentiles(out_baseline, comp)
        pc = _component_percentiles(out_clean, comp)
        common = [c for c in sorted(set(pb) & set(pc))
                  if pb.get(c) is not None and pc.get(c) is not None]
        moved = [(c, pc[c] - pb[c]) for c in common]
        moved = [(c, d) for c, d in moved if abs(d) > 1e-12]
        movers = sorted(moved, key=lambda x: (-abs(x[1]), x[0]))[:5]
        res[comp] = {
            "n_healthy_compared": len(common),
            "n_percentile_changed": len(moved),
            "max_abs_change": max((abs(d) for _, d in moved), default=0.0),
            "mean_abs_change": (sum(abs(d) for _, d in moved) / len(moved))
                               if moved else 0.0,
            "top_movers": [{"symbol": detail[c]["symbol"], "before": pb[c],
                            "after": pc[c], "delta": round(d, 6)}
                           for c, d in movers],
        }
    return res


def winsor_bounds_comparison(out_baseline: dict, out_clean: dict) -> dict:
    """Growth winsor bounds (P1/P99 per family) before vs after quarantine —
    contaminated extremes previously stretched the bounds for everyone."""

    def bounds(out: dict, key: str) -> dict:
        fams = (((out.get("populations") or {}).get(key) or {})
                .get("families")) or {}
        res = {}
        for fam, v in fams.items():
            w = v.get("winsor") or {}
            res[fam] = {"applied": w.get("applied"), "low": w.get("low"),
                        "high": w.get("high"), "n_valid": v.get("n_valid")}
        return res

    res = {}
    for comp in _GROWTH_COMPONENT_TO_BASE_TAG:
        key = f"earnings_growth.{comp}"
        b, c = bounds(out_baseline, key), bounds(out_clean, key)
        res[comp] = {"before": b, "after": c, "changed": b != c}
    return res


INVARIANT_FACTORS = ("margins", "leverage", "cash_conversion",
                     "roe_level", "revenue_growth")


def invariance_check(out_baseline: dict, out_clean: dict,
                     raw_baseline: dict, raw_clean: dict) -> dict:
    """Factors that consume no prev-year bases (margins, leverage,
    cash_conversion, roe_level, revenue_growth) must be untouched by the
    earnings_growth quarantine — verified, not assumed. margin_trend is
    deliberately ABSENT: since 2-B-5 it consumes operating_profit_prev /
    revenue_prev and is legitimately quarantined alongside them."""
    res = {}
    for fid in INVARIANT_FACTORS:
        n_raw = sum(1 for cid in raw_baseline
                    if raw_baseline[cid][fid] != raw_clean[cid][fid])
        n_norm = sum(1 for cid in out_baseline["factors"]
                     if out_baseline["factors"][cid][fid]
                     != out_clean["factors"][cid][fid])
        res[fid] = {"raw_identical": n_raw == 0,
                    "normalization_identical": n_norm == 0,
                    "n_differences": n_norm}
    return res


# ---------------------------------------------------------------------------
# 2-B-4.2 readiness of the NEXT five general Q factors (prioritization only)
# ---------------------------------------------------------------------------
_READINESS_FACTORS = (
    ("roe_level", ("roe",),
     ("net_profit", "total_equity"),
     "net_ttm / total_equity(order-1, latest report) — current level",
     "yes — the engine metric is already materialized; uses only the "
     "CURRENT TTM (audited 2-B-4.1: zero sentinel hits) and a balance-sheet "
     "cell, never a prior-year base"),
    ("interest_coverage", ("interest_coverage",),
     ("operating_profit", "finance_cost"),
     "operating_profit_ttm / |finance_cost(order-1, latest report)|",
     "yes — engine metric exists; CURRENT TTM side only (audited: zero "
     "sentinel hits), no prior-year base channel"),
    ("earnings_quality", ("earnings_quality",),
     ("other_non_operating", "operating_profit"),
     "|other_non_operating(order-1, latest report)| / |operating_profit_ttm|",
     "yes — engine metric exists; same inputs as interest_coverage "
     "(current side only)"),
    ("margin_trend", ("margin_trend",),
     ("operating_profit", "revenue"),
     "operating_margin(now, TTM-based) − operating_margin(same-report "
     "order-2 comparative) — no prior-year chain",
     "yes — the comparative legs live inside the SAME report cell, so the "
     "legacy sentinel prev-base channel is not involved"),
    ("revenue_growth", ("revenue_growth",),
     ("revenue",),
     "(revenue order-1 − order-2) / |order-2| within the latest report",
     "yes — same-report comparatives only, no TTM chain and no prev-year "
     "base"),
)
ROE_STABILITY_NOTE = (
    "excluded from this batch by mission: roe_stability needs a verified "
    "multi-year ROE series, which the canonical store cannot yet provide "
    "without the legacy-corpus cleanup — keep it separate"
)


def next_factor_readiness_section(eng) -> dict:
    """Availability / coverage / contamination-sign table for the five
    remaining general Q raw factors, computed from Engine.compute output and
    the PIT statement rows. Prioritization evidence only — NO factor is
    implemented or scored in this step."""
    metrics = eng.metrics
    n_pop = len(metrics)
    superseded = getattr(eng, "superseded", None) or set()

    def sentinel_rows_for(input_metrics):
        hits: Counter = Counter()
        for st in getattr(eng, "stmt", []) or []:
            if st.get("report_id") in superseded:
                continue
            v = st.get("canonical_value")
            if v is None or float(v) not in SENTINEL_VALUES:
                continue
            if st.get("metric_code") in input_metrics:
                hits[st["metric_code"]] += 1
        return dict(sorted(hits.items()))

    n_cur_ttm_sentinel = sum(
        1 for m in metrics.values()
        for k in ("net_profit_ttm", "operating_profit_ttm")
        if m.get(k) is not None and float(m[k]) in SENTINEL_VALUES)
    factors = {}
    for fid, metric_keys, input_metrics, definition, contract_note in _READINESS_FACTORS:
        cov = sum(1 for m in metrics.values()
                  if all(m.get(k) is not None for k in metric_keys))
        hits = sentinel_rows_for(input_metrics)
        factors[fid] = {
            "engine_metrics": list(metric_keys),
            "input_statement_metrics": list(input_metrics),
            "definition": definition,
            "n_population": n_pop,
            "n_metrics_available": cov,
            "coverage_pct": round(100.0 * cov / n_pop, 1) if n_pop else 0.0,
            "uses_current_ttm_resolution": fid in (
                "roe_level", "interest_coverage", "earnings_quality",
                "margin_trend"),
            "uses_prev_year_ttm_base": False,
            "uses_same_report_comparative_only": fid in (
                "margin_trend", "revenue_growth"),
            "contamination_signs": {
                "current_ttm_sentinel_valued_companies": n_cur_ttm_sentinel,
                "sentinel_valued_rows_in_input_metrics": hits,
                "prev_base_channel_involved": False,
            },
            "implementable_under_current_contract": (
                "yes" if not hits and n_cur_ttm_sentinel == 0
                else "yes — with the residual signs above disclosed"),
            "contract_note": contract_note,
        }
    return {
        "purpose": ("prioritization evidence for the next batch only — no "
                    "factor is implemented, weighted or scored in this step"),
        "roe_stability": ROE_STABILITY_NOTE,
        "current_ttm_sentinel_audit_reference": (
            "2-B-4.1: zero current-TTM sentinel hits store-wide; re-verified "
            "per run in contamination_signs"),
        "factors": factors,
    }


# ---------------------------------------------------------------------------
# 2-B-5: batch implementation decisions for the five readiness factors
# ---------------------------------------------------------------------------
_WINDOW_AUDIT_NOTE = (
    "Engine window semantics (compute_metrics.Engine): roe = net_profit_ttm "
    "/ total_equity (TTM over point-in-time equity — consistent). "
    "revenue_growth = same-report order-1 vs order-2 — both legs share one "
    "window by construction. interest_coverage = operating_profit_ttm / "
    "|finance_cost order-1 of the latest report| and earnings_quality = "
    "|other_nonop order-1| / |operating_profit_ttm| — a TTM numerator over a "
    "same-report YTD denominator; unless the latest report is annual the "
    "denominator window is shorter (12/fm bias, varying per company). The "
    "engine's derived margin_trend compares the TTM operating margin against "
    "the same-report prior-year YTD margin — the same span mismatch, which "
    "is why the implemented margin_trend uses provenance-matched prior-year "
    "TTM bases (op_prev/rev_prev) instead and inherits the 2-B-4.2 "
    "quarantine."
)


def window_audit(eng) -> dict:
    """Latest-report window split + same-report leg facts for the 2-B-5
    decisions. Real rep-index evidence, no assumptions."""
    rep_index = eng.report_index()
    fm_split: Counter = Counter()
    annual = 0
    rev_o2_negative, rev_o2_zero = [], []
    for cid in eng.metrics:
        rep = rep_index.get(cid, {})
        if not rep:
            continue
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        fm_split[latest[1]] += 1
        annual += int(latest[1] == 12)
        rev2 = ((rep.get(latest) or {}).get("revenue") or {}).get(2)
        if rev2 is not None:
            if rev2 < 0:
                rev_o2_negative.append(cid)
            elif rev2 == 0:
                rev_o2_zero.append(cid)
    n_reports = sum(fm_split.values())
    return {
        "n_companies_with_report": n_reports,
        "latest_period_fiscal_month_split": dict(sorted(fm_split.items())),
        "n_annual_latest_report": annual,
        "n_non_annual_latest_report": n_reports - annual,
        "revenue_order2_negative_companies": rev_o2_negative,
        "revenue_order2_zero_companies": rev_o2_zero,
        "note": _WINDOW_AUDIT_NOTE,
    }


_BLOCKED_FACTOR_EVIDENCE = {
    "interest_coverage": {
        "engine_formula": "operating_profit_ttm / |finance_cost order-1 of "
                          "the latest report|",
        "problem": "TTM numerator over a same-report YTD denominator — for "
                   "non-annual latest reports the coverage is inflated by "
                   "roughly 12/fm with fm varying per company, so values "
                   "are not cross-sectionally comparable and are not the "
                   "standard interest-coverage measure",
        "decision": "blocked (needs_development at the raw layer): the "
                    "economically correct metric needs finance_cost_ttm, "
                    "which the engine does not materialize and no "
                    "provenance anchor exists for a replication — no "
                    "guessed same-window surrogate",
        "superseded_by": ("step 2-B-7: the same-window finance_cost_ttm is "
                          "now resolved inside the latest report's own "
                          "comparative legs and the factor is implemented "
                          "in the raw layer (see factor_batch_2b7); this "
                          "entry is kept as the historical 2-B-5 decision "
                          "record"),
    },
    "earnings_quality": {
        "engine_formula": "|other_nonop order-1 of the latest report| / "
                          "|operating_profit_ttm| * 100",
        "problem": "the same TTM/YTD span mismatch deflates the "
                   "non-operating share by roughly fm/12 for non-annual "
                   "latest reports; also, on a negative operating base the "
                   "lower-is-better ratio would falsely favor deep "
                   "operating losses",
        "decision": "blocked (needs_development at the raw layer): correct "
                    "computation needs other_nonop_ttm (no engine anchor) "
                    "and an explicit loss-base contract; it is NOT the same "
                    "concept as cash_conversion (ocf/net), so no "
                    "re-scoring shortcut is taken",
        "superseded_by": ("step 2-B-7: the same-window other_nonop_ttm "
                          "channel plus the explicit non-positive-base "
                          "not_applicable contract implement this factor "
                          "(see factor_batch_2b7); this entry is kept as "
                          "the historical 2-B-5 decision record"),
    },
}


def factor_batch_2b5_section(eng) -> dict:
    """Implementation decisions + live evidence for the five 2-B-4.2
    readiness factors: three implemented, two blocked with the window-audit
    reason; roe_stability/roic stay excluded by mission/design."""
    audit = window_audit(eng)
    metrics = eng.metrics
    superseded = getattr(eng, "superseded", None) or set()

    # sentinel rows that WIN a latest-report cell (order 1 or 2) — the only
    # store cells the five factors' same-report inputs can consume
    sentinel_cells, _census = detect_sentinel_fact_cells(eng)
    latest_winners: list = []
    for cid, keys in sentinel_cells.items():
        rep = eng.report_index().get(cid, {})
        if not rep:
            continue
        latest = max(rep.keys(), key=lambda k: k[0] * 12 + k[1])
        cell = rep.get(latest) or {}
        for fy, fm, metric, order in keys:
            if (fy, fm) != latest:
                continue
            v = ((cell.get(metric) or {}).get(order))
            if v is not None and float(v) in SENTINEL_VALUES:
                latest_winners.append({"company_id": cid, "metric": metric,
                                       "order": order})

    def avail(*keys):
        return sum(1 for m in metrics.values()
                   if all(m.get(k) is not None for k in keys))

    implemented = {
        "roe_level": {
            "engine_formula": "net_profit_ttm / total_equity * 100 "
                              "(emitted only for equity > 0)",
            "implemented_definition": "the engine metric as-is; negative "
                                      "ROE stays a valid loss signal; "
                                      "equity missing/zero/negative is "
                                      "missing, never a fabricated level",
            "n_metrics_available": avail("roe"),
        },
        "margin_trend": {
            "engine_formula": "op_margin(TTM) − op_margin(same-report "
                              "order-2 YTD) — span-mismatched, NOT reused",
            "implemented_definition": "op_margin_ttm(now) − "
                                      "op_margin_ttm(prior year) from the "
                                      "provenance-matched prev_bases "
                                      "(operating_profit_prev, "
                                      "revenue_prev); like-for-like "
                                      "12-month windows; a quarantined "
                                      "op_prev honestly leaves it missing",
            "n_metrics_available": avail("operating_profit_ttm",
                                         "revenue_ttm"),
        },
        "revenue_growth": {
            "engine_formula": "(revenue order-1 − order-2) / |order-2| "
                              "inside the latest report",
            "implemented_definition": "the engine metric as-is — same-report "
                                      "comparatives share one window by "
                                      "construction; very large growth "
                                      "stays valid with a data warning",
            "n_metrics_available": avail("revenue_growth"),
        },
    }
    blocked = {}
    for fid, ev in _BLOCKED_FACTOR_EVIDENCE.items():
        blocked[fid] = {**ev,
                        "n_metrics_available": (
                            avail("interest_coverage")
                            if fid == "interest_coverage"
                            else avail("earnings_quality"))}
    return {
        "purpose": ("batch implementation record for the five 2-B-4.2 "
                    "readiness factors — three implemented on the raw "
                    "layer, two blocked with evidence; no final Q/V/T "
                    "score is produced anywhere"),
        "window_audit": audit,
        "sentinel_winners_in_latest_report_cells": latest_winners,
        "n_sentinel_winners_in_latest_report_cells": len(latest_winners),
        "implemented": implemented,
        "blocked": blocked,
        "excluded": {
            "roe_stability": ROE_STABILITY_NOTE,
            "roic": "no NOPAT / operating invested capital data path "
                    "(config availability needs_development; never a "
                    "surrogate)",
        },
    }


# ---------------------------------------------------------------------------
# 2-B-7: activation record for interest_coverage / earnings_quality
# ---------------------------------------------------------------------------
_STEP_2B6_COVERAGE_REFERENCE = {
    "artifact": "output/v2_q_observed_report.json (step 2-B-6, same "
                "as_of=2026-10-08 / cutoff=2026-10-08T23:59:00+00:00)",
    "interest_coverage": "blocked_at_raw_layer — scored 0 of 260 general",
    "earnings_quality": "blocked_at_raw_layer — scored 0 of 260 general",
    "n_pilot_eligible": 98,
    "max_covered_weight_observed": 25.0,
    "note": ("documented 2-B-6 reference state, restated here as the fixed "
             "before-picture; this run re-measures the after-state live"),
}


def _expense_sign_census(eng) -> dict:
    """Store-wide sign convention of the two expense metrics (all
    non-superseded PIT-eligible fact rows) — the evidence behind the raw
    layer's finance-cost sign contract."""
    counts: dict = {}
    superseded = getattr(eng, "superseded", None) or set()
    for st in getattr(eng, "stmt", []) or []:
        if st.get("report_id") in superseded:
            continue
        metric = st.get("metric_code")
        if metric not in ("finance_cost", "other_non_operating"):
            continue
        v = st.get("canonical_value")
        state = "null" if v is None else \
            ("negative" if float(v) < 0 else "positive" if float(v) > 0
             else "zero")
        counts.setdefault(metric, Counter())[state] += 1
    return {m: dict(sorted(c.items())) for m, c in sorted(counts.items())}


def expense_ttm_display_companies(detail: dict, raw_by_company: dict,
                                  out: dict, qo: dict, limit: int = 18) -> list:
    """Deterministic display rows across channel states — an illustrative
    sample for the report, NEVER a ranking. Buckets (both factors raw-valid /
    one valid / not_applicable / unresolved legs / no order-1 value) are
    round-robined in company-id order."""
    buckets: dict = {k: [] for k in (
        "both_raw_valid", "one_raw_valid", "not_applicable",
        "unresolved_legs", "no_order1_value", "other_state")}
    for cid in sorted(qo.get("companies", {})):
        e = qo["companies"][cid]
        if e.get("aggregation_status") != "aggregated":
            continue
        raw = raw_by_company.get(cid, {})
        st_ic = raw.get("interest_coverage", {}).get("status")
        st_eq = raw.get("earnings_quality", {}).get("status")
        valid = [s for s in (st_ic, st_eq) if s == RAW.STATUS_VALID]
        if len(valid) == 2:
            k = "both_raw_valid"
        elif len(valid) == 1:
            k = "one_raw_valid"
        elif RAW.STATUS_NOT_APPLICABLE in (st_ic, st_eq):
            k = "not_applicable"
        elif any("comparative leg" in (raw.get(f, {}).get(
                "validation_reason") or "") for f in
                ("interest_coverage", "earnings_quality")):
            k = "unresolved_legs"
        elif any("order-1" in (raw.get(f, {}).get(
                "validation_reason") or "") for f in
                ("interest_coverage", "earnings_quality")):
            k = "no_order1_value"
        else:
            k = "other_state"
        buckets[k].append(cid)
    order = list(buckets)
    idx = {k: 0 for k in order}
    picks: list = []
    while len(picks) < limit:
        progressed = False
        for k in order:
            if idx[k] < len(buckets[k]):
                picks.append(buckets[k][idx[k]])
                idx[k] += 1
                progressed = True
                if len(picks) >= limit:
                    break
        if not progressed:
            break

    def factor_row(cid: str, fid: str) -> dict:
        rec = raw_by_company.get(cid, {}).get(fid, {})
        f = out["factors"].get(cid, {}).get(fid, {})
        qf = (qo["companies"].get(cid, {}).get("factors", {}) or {}).get(fid, {})
        return {
            "raw_status": rec.get("status"),
            "raw_value": rec.get("raw_value"),
            "raw_validation_reason": rec.get("validation_reason"),
            "score": (f.get("percentile_combined")
                      if f.get("percentile_combined") is not None else None),
            "normalization_status": f.get("normalization_status"),
            "weight": qf.get("weight"),
            "included_in_q_observed": qf.get("included"),
            "not_included_reason": qf.get("not_included_reason"),
        }

    rows: list = []
    for cid in picks:
        e = qo["companies"][cid]
        rows.append({
            "company_id": cid,
            "symbol": detail.get(cid, {}).get("symbol"),
            "industry": detail.get(cid, {}).get("industry"),
            "model_family": e.get("model_family"),
            "interest_coverage": factor_row(cid, "interest_coverage"),
            "earnings_quality": factor_row(cid, "earnings_quality"),
            "covered_weight": e.get("covered_weight"),
            "coverage_ratio": e.get("coverage_ratio"),
            "pilot_eligible": e.get("pilot_eligible"),
            "bucket": next(k for k in order if cid in buckets[k]),
        })
    return rows


def factor_batch_2b7_section(eng, channels: dict, census: dict,
                             coverage: dict, qo: dict, detail: dict,
                             raw_by_company: dict, normalize_out: dict) -> dict:
    """The 2-B-7 activation record: same-window expense-TTM evidence, the
    two implemented contracts, the live after-state, and the fixed 2-B-6
    before-reference. Evidence and honesty only — no weight moves."""
    after = {}
    for fid in ("interest_coverage", "earnings_quality"):
        c = coverage.get(fid, {})
        after[fid] = {k: c.get(k) for k in (
            "n_population", "raw_valid", "raw_missing", "raw_invalid",
            "raw_not_applicable", "scored", "single_ranked",
            "insufficient_peers")}
    per_state: dict = {}
    quarantined: list = []
    for cid in sorted(channels):
        for tag, ch in channels[cid].items():
            subj_cid = cid
            if ch["value"] is not None:
                per_state.setdefault(ch["state"], []).append((subj_cid, tag,
                                                              ch))
            elif ch["state"] in ("quarantined_legacy_sentinel_leg",
                                 "non_finite_result"):
                quarantined.append((subj_cid, tag, ch))
    resolved_examples: list = []
    subjects = getattr(eng, "subjects", {}) or {}
    for state in sorted(per_state):
        for cid, tag, ch in per_state[state][:4]:
            resolved_examples.append({
                "company_id": cid,
                "symbol": (subjects.get(cid) or {}).get("symbol"),
                "channel": tag, "state": state, "value": ch["value"],
                "prov_code": ch["prov_code"], "legs": ch["legs"]})
    for cid, tag, ch in quarantined[:8]:
        resolved_examples.append({
            "company_id": cid,
            "symbol": (subjects.get(cid) or {}).get("symbol"),
            "channel": tag, "state": ch["state"], "value": None,
            "prov_code": ch["prov_code"], "reason": ch["reason"],
            "legs": ch["legs"]})
    return {
        "purpose": ("activation record for interest_coverage and "
                    "earnings_quality: the 2-B-5 window-mismatch block is "
                    "superseded by a same-window expense-TTM channel — the "
                    "weights stay 3 + 3, nothing is redistributed, and no "
                    "final Q/V/T/total score is produced anywhere"),
        "contract": EXPENSE_TTM_CONTRACT,
        "formula": ("finance_cost_ttm / other_nonop_ttm = latest-report "
                    "period_order 1 + 3 - 2 (or order 1 for an explicitly "
                    "12-month latest report); interest_coverage = "
                    "operating_profit_ttm / |finance_cost_ttm| (PROXY, not "
                    "standardized EBIT); earnings_quality = "
                    "|other_nonop_ttm| / operating_profit_ttm * 100 over a "
                    "strictly positive operating base only"),
        "sign_convention_census": _expense_sign_census(eng),
        "resolution_census": census,
        "resolved_examples_with_legs": resolved_examples,
        "implemented": {
            "interest_coverage": {
                "definition": "operating-profit-based finance-cost coverage "
                              "PROXY over one trailing-12-month window — "
                              "deliberately not presented as standardized "
                              "EBIT-based coverage",
                "zero_or_income_denominator": "not_applicable (never zero "
                                              "or infinite coverage, never "
                                              "an abs()-fabricated expense)",
                "negative_operating_profit": "valid negative value with an "
                                             "explicit warning — ranks at "
                                             "the bottom, never auto-zeroed",
            },
            "earnings_quality": {
                "definition": "non-operating DEPENDENCE share "
                              "(|other_nonop_ttm| / positive operating "
                              "profit) — not complete earnings quality and "
                              "not a cash-quality measure",
                "non_positive_operating_base": "not_applicable (a "
                                               "lower-is-better share would "
                                               "falsely rank a deep loss as "
                                               "excellent quality)",
                "real_zero_numerator": "valid 0.0 — no non-operating "
                                       "dependence",
            },
        },
        "coverage_after_this_run": after,
        "coverage_before_reference": _STEP_2B6_COVERAGE_REFERENCE,
        "cap_bridge": {
            "observed_max_covered_before_2b7": 25,
            "potential_from_the_two_weight3_factors": 31,
            "aggregable_ceiling_all_implemented": 34,
            "note": ("CORRECTION of this section's earlier wording: the two "
                     "newly activated factors weigh 3 + 3, so from the "
                     "observed 25 they can add at most +6 — a potential of "
                     "25 -> 31, NOT 25 -> 34. The 34 previously shown here "
                     "is the sum of all eight implementable non-diagnostic "
                     "quality weights (roe_level 7 + margins 6 + "
                     "cash_conversion 4 + leverage 4 + revenue_growth 4 + "
                     "margin_trend 3 + interest_coverage 3 + "
                     "earnings_quality 3); it is the aggregable ceiling, "
                     "not the potential this step unlocks, and it is only "
                     "reached where every one of the eight actually ranks "
                     "(normalization's family_min_n still refuses tiny "
                     "peer groups). The diagnostic-only earnings_growth "
                     "(weight 3) is excluded from all of these numbers."),
            "observed_max_covered_weight_this_run":
                qo.get("summary", {}).get("max_covered_weight_observed"),
        },
        "display_companies": expense_ttm_display_companies(
            detail, raw_by_company, normalize_out, qo),
        "not_modified": ("previous factors' raw records, weights, the "
                         "2-B-4.2 quarantine, the earnings_growth policy "
                         "exclusion, PIT honesty, Data Confidence and the "
                         "Risk Gate are untouched; V1/V4 and score_v2.py "
                         "unmodified; the run stays read-only"),
    }


def factor_batch_2b8_section(rec_results: dict, rec_census: dict,
                             channels: dict, coverage: dict, qo: dict,
                             detail: dict, raw_by_company: dict,
                             normalize_out: dict) -> dict:
    """The 2-B-8 recovery record: which order-3 legs were recovered from the
    project's own raw letter archive under the identity gates, and what the
    two factors' coverage did with them. Evidence and honesty only — the
    formulas, weights and refusals are untouched."""
    after = {}
    for fid in ("interest_coverage", "earnings_quality"):
        c = coverage.get(fid, {})
        after[fid] = {k: c.get(k) for k in (
            "n_population", "raw_valid", "raw_missing", "raw_invalid",
            "raw_not_applicable", "scored", "single_ranked",
            "insufficient_peers")}
    # per-factor ranked counts across companies (the honest "ranked, not
    # merely raw-valid" number — q_observed marks included units)
    n_ranked_companies: dict = {}
    for fid in ("interest_coverage", "earnings_quality"):
        n = 0
        for cid, e in (qo.get("companies", {}) or {}).items():
            f = (e.get("factors", {}) or {}).get(fid) or {}
            if f.get("included"):
                n += 1
        n_ranked_companies[fid] = n
    examples: list = []
    for cid in sorted(rec_results):
        for metric, rec in rec_results[cid].items():
            if rec.get("state") != REC.STATE_RECOVERED:
                continue
            ch = (channels.get(cid) or {}).get(
                "finance_cost_ttm" if metric == "finance_cost"
                else "other_nonop_ttm") or {}
            examples.append({
                "company_id": cid,
                "symbol": (detail.get(cid) or {}).get("symbol"),
                "metric": metric,
                "recovered_value_rial": rec.get("value"),
                "window_dates": rec.get("window_dates"),
                "evidence": rec.get("evidence"),
                "channel_state": ch.get("state"),
                "ttm_value": ch.get("value"),
            })
            if len(examples) >= 8:
                break
        if len(examples) >= 8:
            break
    refusals: dict = {}
    for cid in sorted(rec_results):
        for metric, rec in rec_results[cid].items():
            st = rec.get("state")
            if st == REC.STATE_RECOVERED:
                continue
            refusals.setdefault(st, []).append(
                (detail.get(cid, {}) or {}).get("symbol") or cid)
    both_recovered = sorted(
        cid for cid, per in rec_results.items()
        if all(r.get("state") == REC.STATE_RECOVERED
               for r in per.values()))
    return {
        "purpose": ("read-only recovery of the missing order-3 legs from "
                    "the project's own raw Codal letter archive "
                    "(raw.report_payloads) under exact identity gates — "
                    "no new factor, no formula change, no weight move, no "
                    "ingestion/database modification"),
        "recovery_contract": RECOVERY_CONTRACT,
        "identity_gates": [
            "same company + same Jalali (fy, fm) as the engine's latest "
            "cell; PIT-eligible; not superseded; exactly one letter may "
            "pass the value gate",
            "value columns selected only by the cells' periodEndToDate: "
            "current == statement period, prior-same == (y-1, same "
            "month/day), prior-annual == yearEndToDate - 1y",
            "row (or split sub-row subset) must reproduce the stored "
            "reported_value of orders 1 AND 2 EXACTLY (Decimal)",
            "current vs prior-same windows differ by exactly one year — "
            "o1 + o3 - o2 stays a same-window TTM on one restated basis",
        ],
        "unit_convention": ("million_rial -> rial x 1e6 (the store's own "
                            "uniform normalization; ratio exactly 1e6 over "
                            "all 1040 finance_cost facts)"),
        "recovery_census": rec_census,
        "n_companies_both_factors_recovered": len(both_recovered),
        "recovered_examples": examples,
        "refusal_states": {k: sorted(v) for k, v in
                           sorted(refusals.items())},
        "coverage_after_this_run": after,
        "ranked_status": {
            "n_companies_included_by_factor": n_ranked_companies,
            "note": ("included = the factor actually contributes to that "
                     "company's q_observed_points (ranked, not merely "
                     "raw-valid)"),
        },
        "coverage_before_reference_2b7": (
            "interest_coverage / earnings_quality raw_valid 3 each, scored "
            "0, insufficient_peers 3 (2-B-7 run on the same snapshot); "
            "observed max covered weight stayed 25/40"),
        "cap_bridge_correction": (
            "the two factors weigh 3 + 3 each: from the observed 25 they "
            "can add at most +6 (potential 25 -> 31, not 25 -> 34 as the "
            "previous report's bridge wrongly implied; 34 is the sum of "
            "all eight implementable non-diagnostic quality weights)"),
        "display_companies": expense_ttm_display_companies(
            detail, raw_by_company, normalize_out, qo),
        "not_modified": ("raw/normalize/config/q_observed layers, the "
                         "factor formulas, weights, refusals, the 2-B-4.2 "
                         "quarantine, PIT honesty, Risk Gate and Data "
                         "Confidence untouched; the recovery module does "
                         "SELECT-only access"),
    }


def q_readiness_diagnostic(out: dict, meta: dict) -> dict:
    """Diagnostic ONLY (mission §7): which general-family Q weights the
    current raw+normalize output could cover, per FAMILY_WEIGHTS — no final
    Q is computed, no missing weight is redistributed, V/T stay out."""
    q_weights = {fid: w for fid, w
                 in CFG2.FAMILY_WEIGHTS["general"].items()
                 if CFG2.V2_QVT_FACTORS[fid]["axis"] == "quality"}
    total_q = CFG2.AXIS_WEIGHTS["quality"]
    essentials = sorted(fid for fid in q_weights
                        if CFG2.V2_QVT_FACTORS[fid]["essential"])
    implemented = sorted(fid for fid in q_weights
                         if fid in RAW.IN_SCOPE_FACTORS)
    per_factor_ranked: Counter = Counter()
    n_general = 0
    n_essentials_ok = 0
    n_coverage_ok = 0
    n_eligible = 0
    min_cov = CFG2.SCORING_POLICY["min_axis_coverage"]
    for cid, m in meta.items():
        if m["model_family"] != "general":
            continue
        n_general += 1
        covered = 0.0
        ess_ok = True
        for fid, w in q_weights.items():
            f = out["factors"].get(cid, {}).get(fid) or {}
            if _is_scored(f):
                per_factor_ranked[fid] += 1
                covered += w
            elif CFG2.V2_QVT_FACTORS[fid]["essential"]:
                ess_ok = False
        if ess_ok:
            n_essentials_ok += 1
        if covered / total_q >= min_cov:
            n_coverage_ok += 1
        if ess_ok and covered / total_q >= min_cov:
            n_eligible += 1
    parked = {fid: w for fid, w in q_weights.items()
              if fid not in RAW.IN_SCOPE_FACTORS}
    return {
        "purpose": ("weight-coverage diagnostic only — NOT a Q score; the "
                    "missing/parked weights are never redistributed and no "
                    "quality_score key exists in this report"),
        "family": "general",
        "q_axis_total_weight": total_q,
        "q_factor_weights": dict(sorted(q_weights.items())),
        "essential_q_factors": essentials,
        "implemented_q_factors": implemented,
        "parked_q_factors_with_weights": dict(sorted(parked.items())),
        "parked_weight_sum": sum(parked.values()),
        "max_currently_coverable_weight": total_q - sum(parked.values()),
        "min_axis_coverage_policy": min_cov,
        "n_general_companies": n_general,
        "n_ranked_by_factor": dict(sorted(per_factor_ranked.items())),
        "n_all_essentials_ranked": n_essentials_ok,
        "n_coverage_at_or_above_min": n_coverage_ok,
        "n_potentially_q_eligible": n_eligible,
        "not_computed_here": ("quality_score, weight redistribution, V and "
                              "T axes and any total score — next step "
                              "designs the Q aggregation contract on this "
                              "evidence"),
    }


def build_company_meta(eng, sector_map: dict) -> tuple[dict, dict]:
    """(normalize company_meta, human-readable detail) — real industry from
    core.company_classification at as_of via V4's own PIT query; companies
    without a mapping stay model_family=general with family_status
    unclassified and industry=None (the normalization contract ranks them
    family-wide with an explicit industry_unknown warning)."""
    meta: dict = {}
    detail: dict = {}
    for cid in eng.metrics:
        category = sector_map.get(cid)
        family, fam_status = S2.resolve_family(category)
        subj = (getattr(eng, "subjects", {}) or {}).get(cid, {})
        meta[cid] = {"model_family": family, "industry": category}
        detail[cid] = {
            "symbol": subj.get("symbol"),
            "display_name": subj.get("display_name"),
            "model_family": family,
            "family_status": fam_status,
            "industry": category,
        }
    return meta, detail


# ---------------------------------------------------------------------------
# coverage aggregation
# ---------------------------------------------------------------------------
def _is_scored(f: dict) -> bool:
    if f.get("normalization_status") == SN.FS_BLENDED:
        return f.get("factor_blend_score") is not None
    return f.get("normalization_status") == SN.NR_RANKED \
        and f.get("percentile_combined") is not None


def reason_bucket(fid: str, f: dict) -> str | None:
    """Categorized refusal reason; None when the factor actually scored."""
    st = f.get("normalization_status")
    if _is_scored(f):
        return None
    if st == SN.NR_PENDING_BLEND:
        if "does not match" in (f.get("reason") or ""):
            return "pending_blend: weight-config mismatch refusal"
        return "pending_blend: no component blend contract for this family"
    if st in (SN.FS_INSUFFICIENT_PEERS, SN.NR_INSUFFICIENT_PEERS):
        return "insufficient_peers"
    if st == SN.FS_PENDING_DATA:
        sts = {cd.get("normalization_status")
               for cd in (f.get("components") or {}).values()}
        if "not_ranked_raw_not_applicable" in sts:
            return "pending_data: a component is not_applicable"
        return "pending_data: a component is missing"
    if st == SN.FS_UNAVAILABLE:
        return "unavailable: invalid / non-finite / PIT-corrupt component"
    if st in (SN.NR_NON_FINITE, SN.NR_PIT_STRICT, SN.NR_AFTER_AS_OF):
        return f"single factor refused: {st}"
    if isinstance(st, str) and st.startswith("not_ranked_raw_"):
        return f"single factor raw status: {st[len('not_ranked_raw_'):]}"
    return f"other: {st!r}"


def aggregate_coverage(out: dict, raw_by_company: dict,
                       meta: dict) -> tuple[dict, dict]:
    """Per-factor coverage counts over the FULL population + refusal-reason
    buckets. Counts what the data actually produced — no imputation."""
    factors_out = out["factors"]
    # scored units ranked on an unverified publication date (exploratory): the
    # warning lives on the normalize record of the ranked unit
    pit_unverified: set = {
        (r["company_id"], r["factor_id"])
        for r in out["records"]
        if any(w.startswith("pit_unverified_exploratory")
               for w in r.get("warnings", []))}
    families = {fid: Counter() for fid in RAW.IN_SCOPE_FACTORS}
    coverage: dict = {}
    for fid in RAW.IN_SCOPE_FACTORS:
        is_comp = fid in COMPOSITE_FACTORS
        c = {k: 0 for k in (
            "n_population", "raw_valid", "raw_missing", "raw_invalid",
            "raw_not_applicable", "scored", "composite_blended",
            "single_ranked", "insufficient_peers", "pending_data",
            "unavailable", "pending_blend", "one_component_only",
            "pit_unverified_ranked")}
        status_counts: Counter = Counter()
        warning_kinds: Counter = Counter()
        for cid, by_fid in raw_by_company.items():
            rec = by_fid[fid]
            c["n_population"] += 1
            c[f"raw_{rec['status']}"] += 1
            for w in rec.get("warnings", ()):
                warning_kinds[w.split(":", 1)[0]] += 1
            f = factors_out[cid][fid]
            st = f["normalization_status"]
            status_counts[st] += 1
            if _is_scored(f):
                c["scored"] += 1
                families[fid][meta[cid]["model_family"]] += 1
                if st == SN.FS_BLENDED:
                    c["composite_blended"] += 1
                else:
                    c["single_ranked"] += 1
                if (cid, fid) in pit_unverified:
                    c["pit_unverified_ranked"] += 1
            elif st in (SN.FS_INSUFFICIENT_PEERS, SN.NR_INSUFFICIENT_PEERS):
                c["insufficient_peers"] += 1
            elif st == SN.FS_PENDING_DATA:
                c["pending_data"] += 1
            elif st == SN.FS_UNAVAILABLE:
                c["unavailable"] += 1
            elif st == SN.NR_PENDING_BLEND:
                c["pending_blend"] += 1
            if is_comp:
                valid = [p for p in rec.get("components", {}).values()
                         if p["status"] == RAW.STATUS_VALID]
                if len(valid) == 1:
                    c["one_component_only"] += 1
        c["normalization_status_counts"] = dict(sorted(status_counts.items()))
        c["warning_kinds"] = dict(sorted(warning_kinds.items()))
        c["scored_by_family"] = dict(sorted(families[fid].items()))
        coverage[fid] = c

    reasons: dict = {fid: Counter() for fid in RAW.IN_SCOPE_FACTORS}
    for cid, by_fid in raw_by_company.items():
        for fid in RAW.IN_SCOPE_FACTORS:
            b = reason_bucket(fid, factors_out[cid][fid])
            if b:
                reasons[fid][b] += 1
    return coverage, {fid: dict(sorted(cnt.items()))
                      for fid, cnt in reasons.items()}


# ---------------------------------------------------------------------------
# company samples
# ---------------------------------------------------------------------------
def build_rec_index(out: dict) -> dict:
    return {(r["company_id"], r["factor_id"], r["component_id"]): r
            for r in out["records"]}


def factor_entry(cid: str, fid: str, out: dict, raw_by_company: dict,
                 rec_by_unit: dict) -> dict:
    f = out["factors"][cid][fid]
    rr = raw_by_company[cid][fid]
    e: dict = {"raw_status": rr["status"]}
    if "components" in rr:
        e["raw_components"] = {
            comp: {"value": p.get("value"), "status": p["status"]}
            for comp, p in rr["components"].items()}
    else:
        e["raw_value"] = rr.get("raw_value")
    e["normalization_status"] = f["normalization_status"]
    if f.get("reason"):
        e["reason"] = f["reason"]
    score = (f["factor_blend_score"] if "factor_blend_score" in f
             else f.get("percentile_combined"))
    if score is not None:
        e["score"] = score
    if isinstance(f.get("blend"), dict):
        e["blend"] = {k: f["blend"][k] for k in sorted(f["blend"])
                      if k != "contributions"}
    comps = f.get("components")
    if comps:
        e["components"] = {}
        for comp, cd in comps.items():
            ce = dict(cd)
            raw_part = (rr.get("components") or {}).get(comp) or {}
            for k in ("pit_status", "available_at"):
                ce.setdefault(k, raw_part.get(k))
            r = rec_by_unit.get((cid, fid, comp))
            if r is not None:
                for k in ("raw_value", "n_valid_market_family",
                          "n_valid_sector", "warnings"):
                    ce.setdefault(k, r.get(k))
            e["components"][comp] = ce
    else:
        for k in ("pit_status", "available_at"):
            if rr.get(k) is not None:
                e[k] = rr[k]
        if rr.get("ttm_evidence") is not None:
            e["ttm_evidence"] = rr["ttm_evidence"]   # 2-B-7 audit trail
        r = rec_by_unit.get((cid, fid, None))
        if r is not None:
            for k in ("percentile_market_family", "percentile_sector",
                      "n_valid_market_family", "n_valid_sector",
                      "warnings", "null_reasons", "peer_group"):
                if r.get(k) is not None:
                    e[k] = r[k]
    return e


def select_sample(detail: dict, out: dict, limit: int) -> list:
    """Deterministic mix: companies WITH composite scores first (by score
    count, then symbol) and companies WITHOUT any score (by symbol), so the
    sample shows complete and incomplete data side by side."""
    factors_out = out["factors"]

    def n_scored(cid: str) -> int:
        return sum(1 for f in factors_out[cid].values() if _is_scored(f))

    ids = sorted(factors_out)
    scored = sorted((cid for cid in ids if n_scored(cid) > 0),
                    key=lambda c: (-n_scored(c), detail[c]["symbol"] or "", c))
    unscored = sorted((cid for cid in ids if n_scored(cid) == 0),
                      key=lambda c: (detail[c]["symbol"] or "", c))
    keep_scored = limit - limit // 2
    return scored[:keep_scored] + unscored[:limit // 2]


def build_samples(detail: dict, out: dict, raw_by_company: dict,
                  limit: int) -> list:
    factors_out = out["factors"]
    rec_by_unit = build_rec_index(out)

    def entry(cid: str) -> dict:
        d = detail[cid]
        return {
            "company_id": cid,
            "symbol": d["symbol"],
            "display_name": d["display_name"],
            "model_family": d["model_family"],
            "family_status": d["family_status"],
            "industry": d["industry"],
            "n_scored_factors": sum(1 for f in factors_out[cid].values()
                                    if _is_scored(f)),
            "factors": {fid: factor_entry(cid, fid, out, raw_by_company,
                                          rec_by_unit)
                        for fid in RAW.IN_SCOPE_FACTORS},
        }

    return [entry(cid) for cid in select_sample(detail, out, limit)]


def build_roster(detail: dict, out: dict) -> list:
    """One compact row per company in the FULL population — the sample above
    is illustrative, this roster is the complete audit list."""
    factors_out = out["factors"]
    rows = []
    for cid in sorted(factors_out):
        d = detail[cid]
        rows.append({
            "company_id": cid,
            "symbol": d["symbol"],
            "display_name": d["display_name"],
            "model_family": d["model_family"],
            "family_status": d["family_status"],
            "industry": d["industry"],
            "n_scored_factors": sum(1 for f in factors_out[cid].values()
                                    if _is_scored(f)),
            "factor_status": {fid: factors_out[cid][fid]["normalization_status"]
                              for fid in RAW.IN_SCOPE_FACTORS},
        })
    return rows


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def run_pilot(as_of: dt.date, cutoff: dt.datetime, sample_limit: int = 25,
              engine=None, sector_map: dict | None = None,
              expense_recovery: tuple | None = None) -> dict:
    """Full read-only pipeline over the reachable population; ``engine`` and
    ``sector_map`` are injectable for offline tests (the real run constructs
    compute_metrics.Engine and V4's PIT sector map). ``expense_recovery`` is
    the optional step 2-B-8 (results, census) from the read-only letter
    archive; the real run computes it, offline tests omit it."""
    if engine is None:
        engine = CM.Engine(as_of, cutoff)
    metrics = engine.compute()
    if sector_map is None:
        sector_map = S4.load_sector_map(as_of)

    meta, detail = build_company_meta(engine, sector_map)
    bases, base_diag = resolve_prev_bases(engine)
    prov, prov_diag = build_provenance(engine)
    sentinel_cells, sentinel_census = detect_sentinel_fact_cells(engine)
    base_flags = sentinel_base_flags(engine, bases,
                                     sentinel_cells=sentinel_cells)
    # 2-B-7: the same-window expense TTMs are resolved ONCE (identical
    # channels for runs A and B — the quarantine below concerns prev-year
    # bases only) and handed to the raw layer for both runs. Step 2-B-8
    # optionally merges proven order-3 legs recovered from raw letters.
    rec_results, rec_census = expense_recovery or ({}, None)
    expense_channels, expense_census = resolve_expense_ttm_channels(
        engine, recovery=rec_results or None)

    # A: baseline — the store as-is, NO quarantine. Comparison only; its
    # cross-section (percentiles, winsor bounds, blends) still carries the
    # legacy-sentinel contamination documented in 2-B-4.1.
    raw_baseline = RAW.build_q_raw(metrics, prev_bases=bases,
                                   provenance=prov, as_of=cutoff,
                                   expense_ttm=expense_channels)
    out_baseline = SN.normalize_q_cross_section(
        raw_baseline, meta, as_of=cutoff,
        pit_policy=SN.PIT_CURRENT_EXPLORATORY)

    # B: quarantined exploratory run — the deliverable. Contaminated
    # prev_base tags are removed BEFORE build_q_raw, so the raw layer's own
    # missing contract (no blend) applies; nothing else moves.
    clean_bases, quarantine_info = quarantine_prev_bases(
        engine, bases, sentinel_cells=sentinel_cells, census=sentinel_census)
    raw_by_company = RAW.build_q_raw(metrics, prev_bases=clean_bases,
                                     provenance=prov, as_of=cutoff,
                                     expense_ttm=expense_channels)
    out = SN.normalize_q_cross_section(
        raw_by_company, meta, as_of=cutoff,
        pit_policy=SN.PIT_CURRENT_EXPLORATORY)

    coverage, reasons = aggregate_coverage(out, raw_by_company, meta)
    coverage_baseline, _ = aggregate_coverage(out_baseline, raw_baseline, meta)

    # step 2-B-6: the first observed-Q pilot — plain weighted sum over the
    # factors that actually scored and the policy permits; never renormalized,
    # never ranked, never a final Q (the module enforces the weight table)
    q_observed = QO.build_q_observed_report(
        out, raw_by_company, meta,
        symbols={cid: detail[cid].get("symbol") for cid in detail})

    # step 2-B-7: the activation record for the two formerly blocked factors
    batch_2b7 = factor_batch_2b7_section(
        engine, expense_channels, expense_census, coverage, q_observed,
        detail, raw_by_company, out)

    # step 2-B-8: the recovery record (None census -> section omitted, the
    # offline tests stay deterministic)
    batch_2b8 = None
    if rec_census is not None:
        batch_2b8 = factor_batch_2b8_section(
            rec_results, rec_census, expense_channels, coverage, q_observed,
            detail, raw_by_company, out)

    eg_before = coverage_baseline["earnings_growth"]
    eg_after = coverage["earnings_growth"]
    valid_before = _component_valid_counts(raw_baseline)
    valid_after = _component_valid_counts(raw_by_company)
    mt_before = sum(1 for rec in raw_baseline.values()
                    if rec["margin_trend"]["status"] == RAW.STATUS_VALID)
    mt_after = sum(1 for rec in raw_by_company.values()
                   if rec["margin_trend"]["status"] == RAW.STATUS_VALID)
    quarantine_section = {
        "policy": quarantine_info["policy"],
        "runs": {
            "A_baseline_no_quarantine": "kept for comparison only",
            "B_quarantined_exploratory": ("drives coverage/companies/roster "
                                          "in this report"),
        },
        "quarantine": quarantine_info,
        "cross_table_baseline": growth_cross_table(raw_baseline, bases,
                                                   base_flags),
        "component_population": {comp: {"before": valid_before[comp],
                                        "after": valid_after[comp]}
                                 for comp in valid_before},
        "margin_trend_population": {
            "before": mt_before, "after": mt_after,
            "role": ("margin_trend (since 2-B-5) consumes "
                     "operating_profit_prev via the implemented like-for-like "
                     "TTM trend, so it is legitimately quarantined alongside "
                     "it — unlike the invariant factors it is EXPECTED to "
                     "move between runs A and B"),
        },
        "earnings_growth_blended": {"before": eg_before["composite_blended"],
                                    "after": eg_after["composite_blended"]},
        "percentile_shift_healthy_companies": percentile_comparison(
            out_baseline, out, detail),
        "winsor_bounds": winsor_bounds_comparison(out_baseline, out),
        "invariant_factors": invariance_check(out_baseline, out,
                                              raw_baseline, raw_by_company),
    }

    # named audit trail for the rarest and most alarming outcome: a factor
    # that carries data yet is refused outright (unavailable / raw invalid)
    issues: dict = {}
    for fid in RAW.IN_SCOPE_FACTORS:
        rows = []
        for cid, by_fid in raw_by_company.items():
            f = out["factors"][cid][fid]
            if f["normalization_status"] != SN.FS_UNAVAILABLE \
                    and by_fid[fid]["status"] != RAW.STATUS_INVALID:
                continue
            rows.append({
                "company_id": cid, "symbol": detail[cid]["symbol"],
                "raw_status": by_fid[fid]["status"],
                "normalization_status": f["normalization_status"],
                "reason": (f.get("reason")
                           or by_fid[fid].get("validation_reason")),
                "raw_validation_reason": by_fid[fid].get("validation_reason"),
            })
        if rows:
            issues[fid] = rows

    by_family = Counter(m["model_family"] for m in meta.values())
    known = sum(1 for m in meta.values() if m["industry"] is not None)
    report = {
        "stage": STAGE,
        "score_version": SN.SCORE_VERSION,
        "pit_policy": out["pit_policy"],
        "as_of": str(as_of),
        "cutoff": cutoff.isoformat(),
        "disclaimer": DISCLAIMER,
        "population": {
            "n_subjects": len(getattr(engine, "subjects", {}) or {}),
            "n_companies_in_metrics": len(metrics),
            "by_model_family": dict(sorted(by_family.items())),
            "n_industry_known": known,
            "n_industry_unknown": len(meta) - known,
            "n_normalize_records": len(out["records"]),
        },
        "prev_bases": base_diag,
        "provenance": prov_diag,
        "economic_validity": economic_validity_section(
            raw_baseline, bases, base_flags, detail, sentinel_census),
        "growth_quarantine": quarantine_section,
        "coverage": coverage,
        "baseline_unquarantined": {
            "note": ("run A — the pre-quarantine cross-section, kept for "
                     "comparison only; its growth percentiles and winsor "
                     "bounds still carry the legacy-sentinel contamination"),
            "coverage": coverage_baseline,
        },
        "next_factor_readiness": next_factor_readiness_section(engine),
        "factor_batch_2b5": factor_batch_2b5_section(engine),
        "q_readiness": q_readiness_diagnostic(out, meta),
        "q_observed": q_observed,
        "expense_ttm": {
            "contract": EXPENSE_TTM_CONTRACT,
            "resolution_census": expense_census,
        },
        "factor_batch_2b7": batch_2b7,
        "expense_recovery": (None if rec_census is None else
                             {"contract": RECOVERY_CONTRACT,
                              "census": rec_census}),
        "factor_batch_2b8": batch_2b8,
        "refusal_reasons": reasons,
        "issues": issues,
        "populations": out["populations"],
        "companies": build_samples(detail, out, raw_by_company, sample_limit),
        "roster": build_roster(detail, out),
    }
    return report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as-of", default="2026-09-24")
    ap.add_argument("--cutoff", default="2026-09-24T20:41:02+00:00")
    ap.add_argument("--sample", type=int, default=25)
    ap.add_argument("--out", default="output/v2_qvt_pilot.json")
    ap.add_argument("--q-out", default="output/v2_q_observed_report.json")
    args = ap.parse_args()
    as_of = dt.date.fromisoformat(args.as_of)
    cutoff = dt.datetime.fromisoformat(args.cutoff)

    # step 2-B-8: read-only order-3 recovery from the raw letter archive,
    # computed ONCE over the engine's report index (SELECT-only)
    engine = CM.Engine(as_of, cutoff)
    engine.compute()
    rep_index = engine.report_index()
    durations_by_company, _fc = fiscal_calendar_for(engine)
    expense_recovery = REC.recover_expense_order3(
        rep_index, durations_by_company, as_of, cutoff)

    report = run_pilot(as_of, cutoff, sample_limit=args.sample,
                       engine=engine, expense_recovery=expense_recovery)

    out_path = HERE / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, default=str),
                        encoding="utf-8")

    p = report["population"]
    print(f"population: {p['n_companies_in_metrics']} companies "
          f"(subjects {p['n_subjects']}), families {p['by_model_family']}, "
          f"industry unknown {p['n_industry_unknown']}")
    print(f"prev_bases: {report['prev_bases']}")
    print(f"provenance: {report['provenance']}")
    ev = report["economic_validity"]
    affected = ", ".join("{}: {}".format(k, v["n_sentinel_affected"])
                         for k, v in ev["components"].items())
    print(f"economic_validity: {ev['label']} ({ev['label_fa']}) "
          f"census={ev['sentinel_census_rows_by_metric']} "
          f"affected_base_tags {{{affected}}}")
    q = report["growth_quarantine"]
    qi = q["quarantine"]
    bt = qi["n_quarantined_tags_by_tag"]
    cc = qi["cell_census"]
    print(f"growth_quarantine [{qi['policy']}]: "
          f"companies={qi['n_companies_with_quarantined_base']} "
          f"tags_removed={qi['n_quarantined_tags']} "
          f"(net {bt.get('net_profit_prev', 0)}, "
          f"op {bt.get('operating_profit_prev', 0)}) | cells "
          f"value={cc['value_cells']} consumed={cc['consumed_cells']} "
          f"inert(uncertain)={cc['inert_cells']}")
    print(f"  earnings_growth blended: "
          f"{q['earnings_growth_blended']['before']} -> "
          f"{q['earnings_growth_blended']['after']}; valid components: "
          + ", ".join(f"{comp.split('_')[0]} "
                      f"{q['component_population'][comp]['before']} -> "
                      f"{q['component_population'][comp]['after']}"
                      for comp in sorted(q['component_population'])))
    for comp, s in q["percentile_shift_healthy_companies"].items():
        print(f"  healthy percentile shift [{comp}]: "
              f"{s['n_percentile_changed']}/{s['n_healthy_compared']} changed, "
              f"max|delta|={s['max_abs_change']:.4f}")
    inv = q["invariant_factors"]
    print(f"  invariants: "
          + ", ".join(f"{fid} {'OK' if v['normalization_identical'] else 'CHANGED'}"
                      for fid, v in inv.items()))
    mtp = q["margin_trend_population"]
    print(f"  margin_trend valid (quarantine-aware): {mtp['before']} -> {mtp['after']}")
    batch = report["factor_batch_2b5"]
    wa = batch["window_audit"]
    print(f"2-B-5 window audit: annual latest reports {wa['n_annual_latest_report']}"
          f"/{wa['n_companies_with_report']} | sentinel winners in latest "
          f"cells {batch['n_sentinel_winners_in_latest_report_cells']}")
    for fid, imp in batch["implemented"].items():
        print(f"  implemented {fid}: available {imp['n_metrics_available']}")
    for fid, blk in batch["blocked"].items():
        print(f"  BLOCKED {fid}: available {blk['n_metrics_available']} — "
              f"{blk['decision']}")
    qr = report["q_readiness"]
    print(f"q_readiness (diagnostic only): general {qr['n_general_companies']}, "
          f"max coverable Q weight {qr['max_currently_coverable_weight']}"
          f"/{qr['q_axis_total_weight']} (parked {qr['parked_weight_sum']}), "
          f"all-essentials {qr['n_all_essentials_ranked']}, "
          f"coverage>=min {qr['n_coverage_at_or_above_min']}, "
          f"potentially Q-eligible {qr['n_potentially_q_eligible']}")
    for fid, c in report["coverage"].items():
        print(f"{fid}: raw valid {c['raw_valid']} / missing {c['raw_missing']} "
              f"/ invalid {c['raw_invalid']} / n.a. {c['raw_not_applicable']} "
              f"-> scored {c['scored']} "
              f"(blended {c['composite_blended']}, single {c['single_ranked']}), "
              f"insufficient_peers {c['insufficient_peers']}, "
              f"pending_data {c['pending_data']}, unavailable {c['unavailable']}, "
              f"pending_blend {c['pending_blend']}, "
              f"one-comp-only {c['one_component_only']}")
    for fid, r in report["refusal_reasons"].items():
        print(f"{fid} refusals: {r}")

    qo = report["q_observed"]
    wt, s = qo["weight_table"], qo["summary"]
    scope = [f for f, r in wt["rows"].items() if r["in_aggregation_scope"]]
    print(f"q_observed [{qo['family']}]: Q target {wt['target_weight']}, "
          f"weight sum {wt['total_weight']}, aggregation scope {scope}")
    for fid, row in wt["rows"].items():
        if not row["in_aggregation_scope"]:
            print(f"  out of scope {fid} (weight {row['weight']}): "
                  f"{row['aggregation_note']}")
    eff = s["eligibility_policy_effect"]
    print(f"  general {s['n_general']} / total {s['n_companies_total']}, "
          f"any-score {s['n_any_score']}, zero-coverage {s['n_zero_coverage']}, "
          f"essentials-ok {s['n_essentials_satisfied']}, coverage>={qo['policy']['coverage_threshold']} "
          f"{s['n_coverage_threshold_met']}, pilot_eligible "
          f"{s['n_pilot_eligible']} (policy-exclusion counterfactual "
          f"{eff['n_eligible_if_policy_exclusions_lifted']}, delta {eff['delta']}), "
          f"max covered {s['max_covered_weight_observed']:g}/40")
    print("  display sample (variety across coverage classes, NOT a ranking):")
    for cid in qo["display_sample"]:
        e = qo["companies"][cid]
        if e["aggregation_status"] == "family_out_of_scope":
            print(f"    {e['symbol'] or cid}: out of scope ({e['reason']})")
            continue
        pts = ("—" if e["q_observed_points"] is None
               else f"{e['q_observed_points']:.2f}")
        missing = ",".join(e["essential_status"]["missing"]) or "-"
        print(f"    {e['symbol'] or cid} [{e['industry'] or 'industry?'}]: "
              f"points {pts}, covered {e['covered_weight']:g}/40 "
              f"(ratio {e['coverage_ratio']:.3f}), essential-missing {missing}, "
              f"eligible {e['pilot_eligible']}, warnings "
              f"{len(e['risk_gate']['financial_warnings'])}")

    b7 = report.get("factor_batch_2b7")
    if b7:
        print("2-B-7 expense TTM activation:")
        for m, c in report["expense_ttm"]["resolution_census"].items():
            print(f"  {m}: {c}")
        for fid, a in b7["coverage_after_this_run"].items():
            print(f"  {fid}: raw_valid {a['raw_valid']}, scored "
                  f"{a['scored']} (single_ranked {a['single_ranked']}), "
                  f"insufficient_peers {a['insufficient_peers']}")
        cap = b7["cap_bridge"]
        print(f"  cap bridge: observed max covered "
              f"{cap['observed_max_covered_weight_this_run']:g}/40; "
              f"potential from the two weight-3 factors "
              f"{cap['observed_max_covered_before_2b7']} -> "
              f"{cap['potential_from_the_two_weight3_factors']} "
              f"(CORRECTED; aggregable ceiling all-implemented "
              f"{cap['aggregable_ceiling_all_implemented']}/40)")
        rows = b7["display_companies"]
        print(f"  display companies ({len(rows)}, variety across channel "
              f"states, NOT a ranking):")
        for r in rows:
            ic, eq = r["interest_coverage"], r["earnings_quality"]
            print(f"    {r['symbol'] or r['company_id'][:8]} "
                  f"[{r['bucket']}]: ic={ic['raw_value']} "
                  f"(score {ic['score']}), eq={eq['raw_value']} "
                  f"(score {eq['score']}), covered "
                  f"{r['covered_weight']:g}/40, eligible "
                  f"{r['pilot_eligible']}")

    b8 = report.get("factor_batch_2b8")
    if b8:
        print("2-B-8 order-3 recovery from the raw letter archive:")
        print(f"  census: {json.dumps(b8['recovery_census'], default=str)}")
        print(f"  both-factors recovered: "
              f"{b8['n_companies_both_factors_recovered']} companies")
        for fid, a in b8["coverage_after_this_run"].items():
            print(f"  {fid}: raw_valid {a['raw_valid']}, scored "
                  f"{a['scored']} (single_ranked {a['single_ranked']}), "
                  f"insufficient_peers {a['insufficient_peers']}, included "
                  f"{b8['ranked_status']['n_companies_included_by_factor'].get(fid)}")
        print(f"  corrected cap bridge: {b8['cap_bridge_correction']}")
        rows = b8["display_companies"]
        print(f"  display companies ({len(rows)}, NOT a ranking):")
        for r in rows:
            ic, eq = r["interest_coverage"], r["earnings_quality"]
            print(f"    {r['symbol'] or r['company_id'][:8]} "
                  f"[{r['bucket']}]: ic={ic['raw_value']} "
                  f"(score {ic['score']}), eq={eq['raw_value']} "
                  f"(score {eq['score']}), covered "
                  f"{r['covered_weight']:g}/40, eligible "
                  f"{r['pilot_eligible']}")

    qo_path = HERE / args.q_out
    qo_path.parent.mkdir(parents=True, exist_ok=True)
    qo_path.write_text(json.dumps(qo, indent=1, default=str),
                       encoding="utf-8")
    print(f"artifact: {out_path}")
    print(f"artifact: {qo_path} (standalone observed-Q report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
