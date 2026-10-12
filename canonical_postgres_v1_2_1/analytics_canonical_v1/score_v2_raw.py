"""Raw Q factor extraction and validation for Score v2 (canonical-v2-qvt).

Steps 2-B-1 / 2-B-1.5 / 2-B-2.2 — extraction/validation layer ONLY for
margins, cash_conversion, leverage, earnings_growth. Step 2-B-5 adds
roe_level, margin_trend and revenue_growth on the same contracts. No
scoring, no weights, no percentiles, no ranking: those belong to later
steps.

Step 2-B-7 scope change (expense-TTM activation): interest_coverage and
earnings_quality JOIN the raw scope. Their 2-B-5 block was a window
mismatch (TTM numerator / same-report YTD denominator). The honest fix is a
same-window denominator, so the CALLER (the V2 pilot path — read-only
replication over the engine's own report index) resolves within-report
expense TTMs — finance_cost_ttm / other_nonop_ttm via the report's own
comparative legs (period_order 1 + 3 - 2, or order 1 for an explicitly
annual report, the report_chain_ttm direct contract) and supplies them via
``expense_ttm``. This layer never recomputes them from statements, never
chains across reports (the metric registry classifies both metrics
DIRECT_ONLY: cross-report legs would mix restatement bases), never scales a
short YTD by 12/fm, and never guesses a missing leg. A channel whose value
is absent leaves the factor missing with the channel's own reason. The
store's sign convention is evidenced store-wide: finance_cost rows are
negative for expense (957/1040 negative, 83 zero, 0 positive in the
2026-10-08 census) — a POSITIVE finance_cost_ttm is not a real expense and
is not abs()-substituted into one; zero finance cost is coverage-undefined,
never zero or infinite coverage. interest_coverage is explicitly an
OPERATING-PROFIT-BASED coverage PROXY (the canonical operating_profit line,
not a standardized EBIT); earnings_quality here is the non-operating
DEPENDENCE share (|other_nonop_ttm| over a strictly positive operating
profit), not a complete earnings- or cash-quality measure, and a negative
operating base is conservatively not_applicable instead of falsely reading
as excellent quality.

Step 2-B-5 scope decision (window audit over Engine.compute, 2026-10-08
probe): interest_coverage and earnings_quality were held OUT of this layer
because the engine derived both as TTM-numerator / same-report-YTD-
denominator ratios (operating_profit_ttm / |finance_cost order-1| and
|other_nonop order-1| / |operating_profit_ttm|); on the real population
only 2 of 271 companies have an annual (12-month) latest report, so the
available values mixed a 12-month numerator with a shorter-window
denominator — a ~12/fm bias that varies per company and breaks
cross-sectional comparability. They remained declared config factors
(weights untouched — recalibration is a config decision) until 2-B-7
superseded the block with the same-window channel above. roe_stability
(needs a verified multi-year ROE series) and roic (needs NOPAT / operating
invested capital) stay unplanned here. The implemented margin_trend
deliberately does NOT reuse the engine's derived margin_trend field (TTM
margin minus a same-report prior-year YTD margin — the same window-span
mismatch): it is computed from the engine-resolved current TTM and the
provenance-matched prior-year TTM bases supplied via prev_bases (see
_build_margin_trend), so a quarantined prior base honestly leaves it
missing.

Input contract: the `metrics[cid]` dict produced by Engine.compute()
(compute_metrics.py). TTM primitives (revenue_ttm, net_profit_ttm,
operating_profit_ttm, ocf_ttm) are engine-resolved and are never recomputed
from statements here; only same-window ratios are formed, with explicit
state semantics the engine's derived fields collapse (e.g. the engine maps
"loss maker" and "cash statement absent" both to cash_conversion=None).

Per-company output: {factor_id: record} where record carries
    factor_id, raw_value, status, source_metric, source_period,
    available_at, pit_status, validation_reason, unit, definition, warnings
and, for composite factors, a "components" map with per-component
value/status/reason/warnings and an INDEPENDENT pit_status ("sign_change":
True where a profit-sign flip fired).

Three-tier validation doctrine (step 2-B-1.5) — real-but-unusual economic
data is never deleted here:
    invalid    definite data/computation errors only: non-finite or
               non-numeric inputs, non-finite COMPUTED results
               (non_finite_result — a ratio of finite inputs can still
               overflow to +/-inf, so status valid requires every computed
               value to be finite; step 2-B-2.2), negative revenue,
               negative debt_ratio, and look-ahead data attributable to a
               publication after `as_of`
    anomaly    valid but unusual magnitude — recorded in "warnings"
               (magnitude_anomaly / negative_equity /
               financial_distress_or_anomaly) with the raw value preserved;
               winsorization and the Risk Gate decide later, no scoring
               penalty is applied here
    ordinary   valid and unremarkable

Status vocabulary:
    valid           economically valid raw value — a real zero included;
                    anomaly warnings may still be attached
    missing         a needed input is absent or unverifiable (zero
                    denominator; engine-derived growth whose prior-year base
                    is not exposed)
    invalid         see the doctrine above
    not_applicable  the ratio is undefined or unmeaningful in this state by
                    design: cash conversion on zero/negative net profit,
                    percent growth on a zero base or across a profit-sign
                    flip
    not_implemented target-design factor with no computable path yet — none
                    of the nine in-scope factors; roe_stability and roic
                    live there (see not_implemented_record() and the 2-B-7
                    note above)

Composite factors (margins, earnings_growth): the factor is valid only when
EVERY component is valid. Otherwise: any invalid -> invalid; else any
not_applicable -> not_applicable; else missing. Per-component detail is
always in "components".

earnings_growth: a growth percent is valid ONLY against a caller-supplied
prior-year base (prev_bases), which makes zero-base and sign-change states
exactly classifiable. Engine-derived growth fields (net_profit_growth,
operating_profit_growth) are recorded as missing with an observed_engine_pct
diagnostic — never as a valid rankable value: their base is unverified, so a
misleading percent (e.g. a loss->profit flip reported as +300%) must not
enter ranking. A profit->loss flip against a positive base keeps the
standard-formula (negative) percent but records sign_change/current_loss and
a turned_to_loss warning; it is never surfaced as a desirable growth
outcome.

PIT contract: statement rows from the legacy snapshot carry no publication
timestamp (compute_metrics.py PIT filter: published_at-NULL rows fall back
to the period_end_date <= as_of visibility proxy). available_at is None and
pit_status is PIT_UNVERIFIED unless the caller supplies provenance:
    {cid: {"available_at": <publication timestamp>,
           "source_ref":    "<evidence attributing the timestamp to the
                             source report, e.g. a Codal letter id>",
           "source_period": <optional period label>,
           "metrics": {<metric>: {...same keys, per-metric override...}}}}
verified requires BOTH a timestamp and a non-empty source_ref — a bare
timestamp never verifies PIT. period_end is never promoted to a publication
date. With `as_of` supplied, an attributable timestamp after as_of yields
PIT_AFTER_AS_OF and invalidates the record for historical computation.
Every component's temporal validity is checked independently; conflicting
component source periods yield PIT_PERIOD_MISMATCH. cash_conversion is
verified only when CFO and net profit are provably same-window.

Known engine-coverage limits, made visible instead of hidden:
  - debt_ratio reaches this layer only as an engine-derived value; whether
    total_liabilities or total_assets was the absent input is not recoverable
    from metrics[cid] and the record says so.
  - prior-year TTM bases are not stored in metrics[cid]; callers holding the
    engine's own values (net_profit_prev / operating_profit_prev) pass them
    via `prev_bases` for exact growth classification.

Usage:
    raw = build_q_raw(engine.metrics)
    raw = build_q_raw(engine.metrics,
                      prev_bases={"c1": {"net_profit_prev": 80.0}},
                      provenance={"c1": {"available_at": dt.datetime(...),
                                         "source_ref": "codal:12345"}},
                      as_of=dt.datetime(...))
Pure and deterministic: no database, no engine instantiation, no clock.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Status / PIT vocabulary
# ---------------------------------------------------------------------------
STATUS_VALID = "valid"
STATUS_MISSING = "missing"
STATUS_INVALID = "invalid"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_NOT_IMPLEMENTED = "not_implemented"

PIT_VERIFIED = "verified"
PIT_UNVERIFIED = "unverified_no_publication_date"
PIT_AFTER_AS_OF = "after_as_of"
PIT_PERIOD_MISMATCH = "component_period_mismatch"

# Anomaly-warning thresholds (step 2-B-1.5). These are NOT validity bounds:
# a value beyond a band stays valid with a recorded warning so real (if
# unusual) economic data is never dropped at the raw layer — winsorization
# and the Risk Gate handle it later. They reuse the step 2-B-1 screening
# bands; no new arbitrary cutoffs are introduced. Definite data errors
# (invalid) are defined independently: non-finite/non-numeric inputs,
# non-finite computed results (overflow), negative revenue, negative
# debt_ratio, look-ahead after as_of.
MARGINS_PCT_ANOMALY_BAND = (-1000.0, 1000.0)          # percent of revenue_ttm
CASH_CONVERSION_ANOMALY_BAND = (-20.0, 20.0)          # ocf_ttm / net_profit_ttm
EARNINGS_GROWTH_PCT_ANOMALY_BAND = (-2000.0, 2000.0)  # percent vs prior base
REVENUE_GROWTH_PCT_ANOMALY_BAND = (-2000.0, 2000.0)   # percent vs same-report
                                                      # prior-year comparative
ROE_PCT_ANOMALY_BAND = (-1000.0, 1000.0)              # percent (np_ttm/equity)
MARGIN_TREND_PP_ANOMALY_BAND = (-200.0, 200.0)        # percentage-point diff
INTEREST_COVERAGE_ANOMALY_BAND = (-100.0, 100.0)      # op_ttm / |fin_cost_ttm|
EARNINGS_QUALITY_PCT_ANOMALY_BAND = (0.0, 1000.0)     # |nonop_ttm|/op_ttm*100
LEVERAGE_NEGATIVE_EQUITY = 1.0  # total_liabilities > total_assets <=> equity < 0
LEVERAGE_EXTREME = 2.0          # liabilities > 2x assets: deep distress or artifact

# Store-evidenced sign convention (2026-10-08 census over all non-superseded
# facts): canonical finance_cost rows are NEGATIVE for expense (957/1040) or
# zero (83) — never positive. A positive finance_cost_ttm therefore cannot
# read as a real expense; it is a net finance INCOME state under this
# convention and the coverage ratio is not computed from it.
FINANCE_COST_EXPENSE_SIGN_IS_NEGATIVE = True

IN_SCOPE_FACTORS = ("margins", "cash_conversion", "leverage", "earnings_growth",
                    "roe_level", "margin_trend", "revenue_growth",
                    "interest_coverage", "earnings_quality")

# Target-design Q factors this step deliberately does NOT extract. A raw
# record for them exists only through not_implemented_record(); build_q_raw
# never invents values or placeholder formulas for them. interest_coverage
# and earnings_quality were here from 2-B-5 (window audit) until 2-B-7 moved
# them INTO scope via the caller-supplied same-window expense-TTM channel;
# roe_stability and roic remain without any validated data path.
NOT_IMPLEMENTED_Q_FACTORS = ("roe_stability", "roic")

_ABSENT = object()  # sentinel: caller supplied no prior base at all


def _bad_number(x) -> bool:
    """True when x is not a finite real number (None aside): strings, bools,
    NaN and +/-inf are all definite data corruption, never usable values."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return True
    return not math.isfinite(x)


def _non_finite_result(what: str) -> dict:
    """Invalid part for a COMPUTED value that is not a finite real number.

    A ratio of finite inputs can still overflow to +/-inf (NaN is reachable
    only through non-finite inputs, which _bad_number already rejects, but
    the guard covers both). Contract (step 2-B-2.2): status == valid
    requires every computed numeric value to be finite — a non-finite
    result is a definite computation error: never valid data, never
    replaced by a number (value stays None; inputs and provenance are
    untouched).
    """
    return {"value": None, "status": STATUS_INVALID,
            "reason": f"non_finite_result: {what} computed to a non-finite "
                      "number — definite computation error, never kept as "
                      "valid data",
            "warnings": []}


# ---------------------------------------------------------------------------
# PIT machinery
# ---------------------------------------------------------------------------
def _ts_after(value, as_of):
    """True when value > as_of; False when the check does not apply; None
    when the two timestamps are not comparable (caller error -> unverified)."""
    if value is None or as_of is None:
        return False
    try:
        return value > as_of
    except TypeError:
        return None


def _metric_pit(prov_entry: dict | None, metric: str, as_of) -> dict:
    """PIT state of ONE source metric.

    verified    a publication timestamp AND a non-empty source_ref
                attributing it to the source report; a bare timestamp never
                verifies.
    after_as_of the timestamp is attributable but later than as_of — the
                metric must not count as valid for historical computation.
    unverified  no timestamp, or a timestamp without origin attribution.
    """
    entry = ((prov_entry or {}).get("metrics") or {}).get(metric) \
        or prov_entry or {}
    ts = entry.get("available_at")
    ref = entry.get("source_ref")
    sp = entry.get("source_period")
    if ts is None:
        return {"state": PIT_UNVERIFIED, "available_at": None,
                "source_period": sp, "reason": f"{metric}: no publication date"}
    if not isinstance(ref, str) or not ref.strip():
        return {"state": PIT_UNVERIFIED, "available_at": ts,
                "source_period": sp,
                "reason": f"{metric}: timestamp without origin attribution "
                          "(no source_ref for the source report)"}
    after = _ts_after(ts, as_of)
    if after is None:
        return {"state": PIT_UNVERIFIED, "available_at": ts,
                "source_period": sp,
                "reason": f"{metric}: available_at and as_of are not comparable"}
    if after:
        return {"state": PIT_AFTER_AS_OF, "available_at": ts,
                "source_period": sp,
                "reason": f"{metric}: published after as_of — must not be "
                          "treated as valid for historical computation"}
    return {"state": PIT_VERIFIED, "available_at": ts, "source_period": sp,
            "reason": f"{metric}: attributed publication evidence"}


def _component_pit(prov_entry: dict | None, metrics: tuple, as_of,
                   same_period_required: bool) -> dict:
    """Independent PIT check of every source metric of one ratio component.

    verified requires: every metric verified AND no conflict between the
    known source_periods. same_period_required additionally refuses
    verified unless EVERY metric's source_period is known and equal (e.g.
    cash_conversion: CFO and net profit must be provably same-window).
    """
    if not prov_entry:
        return {"state": PIT_UNVERIFIED, "available_at": None,
                "source_period": None,
                "reason": "no publication-date provenance supplied"}
    checks = [_metric_pit(prov_entry, name, as_of) for name in metrics]
    states = [c["state"] for c in checks]
    periods = [c["source_period"] for c in checks]
    known = {p for p in periods if p is not None}
    known_count = sum(1 for p in periods if p is not None)
    reason = "; ".join(c["reason"] for c in checks)

    if PIT_AFTER_AS_OF in states:
        state = PIT_AFTER_AS_OF
    elif all(s == PIT_VERIFIED for s in states):
        if len(known) > 1:
            state = PIT_PERIOD_MISMATCH
            reason = "component source periods are inconsistent: " + reason
        elif same_period_required and known_count < len(periods):
            state = PIT_UNVERIFIED
            reason = ("same-period alignment not provable from provenance "
                      "(missing source_period): " + reason)
        else:
            state = PIT_VERIFIED
    else:
        state = PIT_UNVERIFIED

    avail = [c["available_at"] for c in checks if c["available_at"] is not None]
    try:
        available_at = max(avail) if avail else None
    except TypeError:  # mixed timestamp types — do not guess
        available_at = None
    return {"state": state, "reason": reason, "available_at": available_at,
            "source_period": next(iter(known)) if len(known) == 1 else None}


def _factor_pit(parts: dict) -> dict:
    """Factor-level PIT from the independently checked components: any
    after_as_of wins; conflicting component periods yield
    PIT_PERIOD_MISMATCH; verified only when every component is verified."""
    states = [p["pit_status"] for p in parts.values()]
    periods = [p["source_period"] for p in parts.values()]
    known = {p for p in periods if p is not None}
    if PIT_AFTER_AS_OF in states:
        state = PIT_AFTER_AS_OF
    elif PIT_PERIOD_MISMATCH in states or len(known) > 1:
        state = PIT_PERIOD_MISMATCH
    elif all(s == PIT_VERIFIED for s in states):
        state = PIT_VERIFIED
    else:
        state = PIT_UNVERIFIED
    avail = [p["available_at"] for p in parts.values()
             if p["available_at"] is not None]
    try:
        available_at = max(avail) if avail else None
    except TypeError:
        available_at = None
    reasons: list = []
    for p in parts.values():
        if p["pit_status"] != PIT_VERIFIED:
            r = p.get("pit_reason")
            if r and r not in reasons:
                reasons.append(r)
    reason = "; ".join(reasons) if reasons else "all components PIT-verified"
    return {"state": state, "reason": reason, "available_at": available_at,
            "source_period": next(iter(known)) if len(known) == 1 else None}


# Which engine metrics back each component, and which factor must prove
# same-window alignment before PIT can be verified.
_PIT_SPEC = {
    "margins": (
        {"operating_margin_pct": ("revenue_ttm", "operating_profit_ttm"),
         "net_margin_pct": ("revenue_ttm", "net_profit_ttm")},
        False,
    ),
    "cash_conversion": (
        {"cash_conversion": ("ocf_ttm", "net_profit_ttm")},
        True,
    ),
    "leverage": ({"leverage": ("debt_ratio",)}, False),
    "earnings_growth": (
        {"net_profit_growth_pct": ("net_profit_ttm", "net_profit_prev"),
         "operating_profit_growth_pct": ("operating_profit_ttm",
                                         "operating_profit_prev")},
        False,
    ),
    "roe_level": ({"roe_level": ("net_profit_ttm", "total_equity")}, False),
    "margin_trend": (
        {"margin_trend_pp": ("operating_profit_ttm", "revenue_ttm",
                             "operating_profit_prev", "revenue_prev")},
        False,
    ),
    "revenue_growth": ({"revenue_growth_pct": ("revenue",)}, False),
    # 2-B-7: both legs of each ratio are the SAME trailing-12-month window by
    # construction (the expense TTM is assembled inside the latest report the
    # numerator's TTM comes from), so verification requires one provable
    # shared source period — same_period_required=True.
    "interest_coverage": (
        {"interest_coverage": ("operating_profit_ttm", "finance_cost_ttm")},
        True,
    ),
    "earnings_quality": (
        {"earnings_quality": ("other_nonop_ttm", "operating_profit_ttm")},
        True,
    ),
}


def _aggregate(statuses: list) -> str:
    """Composite rule (step 2-B-1.5): valid ONLY when every component is
    valid; otherwise the strongest blocking state wins (invalid, then
    not_applicable, then missing)."""
    if statuses and all(s == STATUS_VALID for s in statuses):
        return STATUS_VALID
    for s in (STATUS_INVALID, STATUS_NOT_APPLICABLE, STATUS_MISSING):
        if s in statuses:
            return s
    return STATUS_MISSING


def _assemble(factor_id: str, econ: dict, prov_entry: dict | None,
              as_of) -> dict:
    """Attach PIT to the economic result of one factor: per-component
    temporal validity, look-ahead invalidation, anomaly-warning rollup and
    the composite record itself."""
    metric_map, same_period_required = _PIT_SPEC[factor_id]
    parts: dict = econ["parts"]

    for pname, part in parts.items():
        cpit = _component_pit(prov_entry, metric_map[pname], as_of,
                              same_period_required)
        part["pit_status"] = cpit["state"]
        part["available_at"] = cpit["available_at"]
        part["source_period"] = cpit["source_period"]
        part["pit_reason"] = cpit["reason"]
        if cpit["state"] == PIT_AFTER_AS_OF and part["status"] == STATUS_VALID:
            part["status"] = STATUS_INVALID
            part["value"] = None
            part["reason"] = f"{part['reason']}; {cpit['reason']}"

    if econ["composite"]:
        raw_value = {name: (p["value"] if p["status"] == STATUS_VALID else None)
                     for name, p in parts.items()}
    else:
        only = next(iter(parts.values()))
        raw_value = only["value"] if only["status"] == STATUS_VALID else None

    status = _aggregate([p["status"] for p in parts.values()])
    fpit = _factor_pit(parts)

    warnings = list(econ.get("factor_warnings", ()))
    if fpit["state"] == PIT_PERIOD_MISMATCH:
        warnings.append("component_period_mismatch: component source periods "
                        "are inconsistent — PIT must stay unverified for "
                        "historical use")
    for p in parts.values():
        warnings.extend(p.get("warnings", ()))

    rec = {
        "factor_id": factor_id,
        "raw_value": raw_value,
        "status": status,
        "source_metric": econ["source_metric"],
        "source_period": fpit["source_period"],
        "available_at": fpit["available_at"],
        "pit_status": fpit["state"],
        "validation_reason": econ["reason"] + "; PIT: " + fpit["reason"],
        "unit": econ["unit"],
        "definition": econ["definition"],
        "warnings": warnings,
    }
    if econ["composite"]:
        rec["components"] = parts
    # 2-B-7 audit contract: every TTM built from real report legs carries the
    # leg values, their cells and the resolution provenance in the record.
    if econ.get("ttm_evidence") is not None:
        rec["ttm_evidence"] = econ["ttm_evidence"]
    return rec


def not_implemented_record(factor_id: str, reason: str = "") -> dict:
    """Explicit placeholder for a target-design factor with no computable
    path yet (e.g. roic: needs NOPAT and operating invested capital; no
    automatic substitute is allowed). raw_value stays None."""
    return {
        "factor_id": factor_id,
        "raw_value": None,
        "status": STATUS_NOT_IMPLEMENTED,
        "source_metric": "none — no agreed data path yet",
        "source_period": None,
        "available_at": None,
        "pit_status": PIT_UNVERIFIED,
        "validation_reason": reason or
        "not implemented: no validated data path for this factor yet",
        "unit": "n/a",
        "definition": "target-design factor; see score_v2_config.V2_QVT_FACTORS",
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# margins — operating_margin_pct / net_margin_pct (percent of revenue_ttm)
# ---------------------------------------------------------------------------
_MARGINS_SRC = ("revenue_ttm, operating_profit_ttm, net_profit_ttm "
                "(Engine.compute metrics; TTM resolved by the engine)")
_MARGINS_UNIT = "percent of revenue_ttm (per component)"
_MARGINS_DEF = ("operating_margin_pct = operating_profit_ttm / revenue_ttm * 100; "
                "net_margin_pct = net_profit_ttm / revenue_ttm * 100 — same "
                "engine-resolved TTM window. Recomputed here (not passed through "
                "the engine's abs()-denominator margins) so that revenue <= 0 is "
                "rejected explicitly instead of yielding a sign-flipped ratio. "
                "Magnitudes beyond the anomaly band stay valid with a warning. "
                "A computed margin that is not finite (overflow over an extreme "
                "denominator) is invalid (non_finite_result), never kept as data.")


def _build_margins(m: dict) -> dict:
    rev = m.get("revenue_ttm")
    parts: dict = {}
    lo, hi = MARGINS_PCT_ANOMALY_BAND

    if rev is None:
        for name in ("operating_margin_pct", "net_margin_pct"):
            parts[name] = {"value": None, "status": STATUS_MISSING,
                           "reason": "revenue_ttm absent in engine metrics",
                           "warnings": []}
        return {"parts": parts, "composite": True, "source_metric": _MARGINS_SRC,
                "unit": _MARGINS_UNIT, "definition": _MARGINS_DEF,
                "reason": "revenue_ttm missing — no denominator for either margin"}
    if _bad_number(rev):
        for name in ("operating_margin_pct", "net_margin_pct"):
            parts[name] = {"value": None, "status": STATUS_INVALID,
                           "reason": "revenue_ttm is not a finite real number",
                           "warnings": []}
        return {"parts": parts, "composite": True, "source_metric": _MARGINS_SRC,
                "unit": _MARGINS_UNIT, "definition": _MARGINS_DEF,
                "reason": "revenue_ttm non-finite or non-numeric — data corruption"}
    if rev <= 0:
        status = STATUS_MISSING if rev == 0 else STATUS_INVALID
        reason = ("revenue_ttm is zero — denominator undefined"
                  if rev == 0 else
                  "revenue_ttm is negative — economically impossible for the "
                  "general family; margin deliberately not computed")
        for name in ("operating_margin_pct", "net_margin_pct"):
            parts[name] = {"value": None, "status": status, "reason": reason,
                           "warnings": []}
        return {"parts": parts, "composite": True, "source_metric": _MARGINS_SRC,
                "unit": _MARGINS_UNIT, "definition": _MARGINS_DEF,
                "reason": reason}

    reasons = []
    for name, key in (("operating_margin_pct", "operating_profit_ttm"),
                      ("net_margin_pct", "net_profit_ttm")):
        val = m.get(key)
        if val is None:
            parts[name] = {"value": None, "status": STATUS_MISSING,
                           "reason": f"{key} absent in engine metrics",
                           "warnings": []}
            reasons.append(f"{name} missing ({key} absent)")
            continue
        if _bad_number(val):
            parts[name] = {"value": None, "status": STATUS_INVALID,
                           "reason": f"{key} is not a finite real number",
                           "warnings": []}
            reasons.append(f"{name} invalid ({key} non-finite/non-numeric)")
            continue
        pct = val / rev * 100.0
        if not math.isfinite(pct):
            parts[name] = _non_finite_result(name)
            reasons.append(f"{name} invalid (non_finite_result)")
            continue
        if pct < lo or pct > hi:
            parts[name] = {"value": pct, "status": STATUS_VALID,
                           "reason": f"valid but unusual: {pct:.1f}% outside "
                                     f"the anomaly screening band "
                                     f"{MARGINS_PCT_ANOMALY_BAND}",
                           "warnings": [f"magnitude_anomaly: {name} {pct:.1f}% "
                                        f"beyond {MARGINS_PCT_ANOMALY_BAND} — "
                                        "kept as real data; winsorization / "
                                        "Risk Gate decide later"]}
            reasons.append(f"{name} valid with magnitude_anomaly ({pct:.1f}%)")
        else:
            parts[name] = {"value": pct, "status": STATUS_VALID,
                           "reason": "within ordinary range", "warnings": []}
            reasons.append(f"{name} valid ({pct:.2f}%)")
    return {"parts": parts, "composite": True, "source_metric": _MARGINS_SRC,
            "unit": _MARGINS_UNIT, "definition": _MARGINS_DEF,
            "reason": "; ".join(reasons)}


# ---------------------------------------------------------------------------
# cash_conversion — ocf_ttm / net_profit_ttm (net profit > 0 only)
# ---------------------------------------------------------------------------
_CASH_SRC = "ocf_ttm, net_profit_ttm (Engine.compute metrics)"
_CASH_UNIT = "dimensionless ratio (ocf_ttm / net_profit_ttm)"
_CASH_DEF = ("cash_conversion = ocf_ttm / net_profit_ttm over the same "
             "latest TTM window; economically defined only for net_profit_ttm > 0. "
             "Zero or negative net profit is a distinct not_applicable state, "
             "never a ratio. PIT verification additionally requires provable "
             "same-window alignment of CFO and net profit. Magnitudes beyond "
             "the anomaly band stay valid with a warning. A computed ratio "
             "that is not finite (overflow over a tiny positive denominator) "
             "is invalid (non_finite_result), never kept as data.")


def _build_cash_conversion(m: dict) -> dict:
    np_ = m.get("net_profit_ttm")
    ocf = m.get("ocf_ttm")

    if np_ is None:
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "net_profit_ttm absent — ratio base unavailable",
                "warnings": []}
    elif _bad_number(np_):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "net_profit_ttm is not a finite real number — "
                          "data corruption",
                "warnings": []}
    elif np_ == 0:
        part = {"value": None, "status": STATUS_NOT_APPLICABLE,
                "reason": "net_profit_ttm is zero — ocf/np has no denominator; "
                          "ratio deliberately not computed",
                "warnings": []}
    elif np_ < 0:
        part = {"value": None, "status": STATUS_NOT_APPLICABLE,
                "reason": "net_profit_ttm is negative (loss maker) — ocf/np has "
                          "no agreed economic definition; ratio deliberately "
                          "not computed",
                "warnings": []}
    elif ocf is None:
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "ocf_ttm absent — operating cash-flow statement not "
                          "available for this company in the engine window",
                "warnings": []}
    elif _bad_number(ocf):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "ocf_ttm is not a finite real number — data corruption",
                "warnings": []}
    else:
        val = ocf / np_
        if not math.isfinite(val):
            # finite inputs, overflowing ratio (tiny positive np_): the
            # 2-B-2.2 contract forbids a valid non-finite value here
            part = _non_finite_result(
                "cash_conversion = ocf_ttm / net_profit_ttm")
        else:
            lo, hi = CASH_CONVERSION_ANOMALY_BAND
            warnings = []
            if val < lo or val > hi:
                warnings.append(f"magnitude_anomaly: ocf/np {val:.1f} outside "
                                f"{CASH_CONVERSION_ANOMALY_BAND} — kept as real "
                                "data; winsorization / Risk Gate decide later")
            if val == 0:
                reason = "real zero: no operating cash despite positive net profit"
            elif val < 0:
                reason = ("negative: positive net profit with operating cash "
                          "outflow — real data")
            else:
                reason = "positive: operating cash backs the reported profit"
            if warnings:
                reason += "; magnitude anomaly recorded, kept as real data"
            part = {"value": val, "status": STATUS_VALID, "reason": reason,
                    "warnings": warnings}
    return {"parts": {"cash_conversion": part}, "composite": False,
            "source_metric": _CASH_SRC, "unit": _CASH_UNIT,
            "definition": _CASH_DEF, "reason": part["reason"]}


# ---------------------------------------------------------------------------
# leverage — debt_ratio = total_liabilities / total_assets (lower is better)
# ---------------------------------------------------------------------------
_LEV_SRC = "debt_ratio (Engine.compute derived: total_liabilities / total_assets)"
_LEV_UNIT = "dimensionless ratio (total_liabilities / total_assets)"
_LEV_DEF = ("debt_ratio as computed by Engine.compute (only produced when "
            "total_assets > 0). Values in (0, 1] are ordinary; (1, inf) is "
            "real negative-equity territory, never auto-invalidated — the "
            "raw value is preserved for later winsorization and the Risk "
            "Gate. Invalid is reserved for definite data errors (non-finite, "
            "non-numeric, negative ratio). Lower is better; 0.0 is a real "
            "zero (no liabilities), not a missing value.")


def _build_leverage(m: dict) -> dict:
    dr = m.get("debt_ratio")
    if dr is None:
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "debt_ratio absent — engine had total_liabilities "
                          "or total_assets missing/zero; which input was "
                          "absent is not recoverable from the derived metric",
                "warnings": []}
    elif _bad_number(dr):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "debt_ratio is not a finite real number — data "
                          "corruption",
                "warnings": []}
    elif dr < 0:
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "negative debt_ratio — inconsistent with the "
                          "accounting definition total_liabilities / "
                          "total_assets when total_assets > 0",
                "warnings": []}
    else:
        warnings = []
        if dr == 0:
            reason = "real zero: no liabilities over positive assets"
        elif dr <= LEVERAGE_NEGATIVE_EQUITY:
            reason = "ordinary leverage band (<= 1)"
        else:
            reason = ("liabilities exceed assets — negative-equity state, "
                      "kept as real data")
            warnings.append(
                "negative_equity: total_liabilities exceed total_assets "
                "(equity < 0) — a real financial-distress state, not a data "
                "error")
        if dr > LEVERAGE_EXTREME:
            warnings.append(
                "financial_distress_or_anomaly: debt_ratio > 2 — either deep "
                "distress or a data artifact; left to winsorization / Risk "
                "Gate, no scoring penalty applied here")
        if warnings and dr > LEVERAGE_EXTREME:
            reason += "; anomaly warning recorded, value kept"
        part = {"value": dr, "status": STATUS_VALID, "reason": reason,
                "warnings": warnings}
    return {"parts": {"leverage": part}, "composite": False,
            "source_metric": _LEV_SRC, "unit": _LEV_UNIT,
            "definition": _LEV_DEF, "reason": part["reason"]}


# ---------------------------------------------------------------------------
# earnings_growth — net/operating profit growth vs prior-year base (percent)
# ---------------------------------------------------------------------------
_GROWTH_SRC = ("net_profit_ttm + net_profit_growth, operating_profit_ttm + "
               "operating_profit_growth (Engine.compute); prior-year bases "
               "only via prev_bases — without a supplied base the derived "
               "percent is recorded as missing, never as a valid value")
_GROWTH_UNIT = "percent vs prior-year same-window base (per component)"
_GROWTH_DEF = ("growth_pct = (current_ttm - prior_ttm) / prior_ttm * 100, "
               "defined only for prior_ttm > 0. Zero base, negative base and "
               "profit-sign flips are distinct non-valid states, never "
               "percentages. A profit->loss flip keeps the standard-formula "
               "negative percent but records the loss and sign change "
               "independently; it is never a desirable growth outcome.")


def _growth_component(name: str, cur_key: str, g_key: str, base_key: str,
                      m: dict, bases: dict) -> dict:
    cur = m.get(cur_key)
    g = m.get(g_key)
    base = bases.get(base_key, _ABSENT)

    if base is _ABSENT:
        # The prior-year base is not exposed by Engine.compute() metrics and
        # the caller did not supply it: the base is unverified, so the growth
        # can never be a valid, rankable input (zero-base vs sign-change
        # states are indistinguishable). This is MISSING (the required input
        # is not available here), kept distinct from INVALID (corruption).
        if cur is not None and _bad_number(cur):
            return {"value": None, "status": STATUS_INVALID,
                    "reason": f"{cur_key} is not a finite real number — "
                              "data corruption (distinct from a missing base)",
                    "warnings": []}
        if g is None:
            return {"value": None, "status": STATUS_MISSING,
                    "reason": f"{g_key} absent and prior-year base unverifiable "
                              "— growth not computable",
                    "warnings": []}
        if _bad_number(g):
            return {"value": None, "status": STATUS_INVALID,
                    "reason": f"{g_key} is not a finite real number — data "
                              "corruption (distinct from a missing base)",
                    "warnings": []}
        return {"value": None, "status": STATUS_MISSING,
                "observed_engine_pct": g,
                "reason": f"{g_key} = {g:g}% is engine-derived but its "
                          "prior-year base is not exposed by Engine.compute() "
                          "metrics and was not supplied via prev_bases — the "
                          "base cannot be verified, so this growth is NOT "
                          "usable for scoring; zero-base vs sign-change states "
                          "cannot be distinguished here — supply prev_bases "
                          "for exact classification",
                "warnings": []}

    # Exact classification from a caller-supplied prior base value.
    if base is None:
        return {"value": None, "status": STATUS_MISSING,
                "reason": "supplied prior base is None — no comparable period",
                "warnings": []}
    if _bad_number(base):
        return {"value": None, "status": STATUS_INVALID,
                "reason": "supplied prior base is not a finite real number — "
                          "data corruption",
                "warnings": []}
    if cur is None:
        return {"value": None, "status": STATUS_MISSING,
                "reason": f"{cur_key} absent — no current value against the "
                          "supplied prior base",
                "warnings": []}
    if _bad_number(cur):
        return {"value": None, "status": STATUS_INVALID,
                "reason": f"{cur_key} is not a finite real number — data "
                          "corruption",
                "warnings": []}
    if base == 0:
        return {"value": None, "status": STATUS_NOT_APPLICABLE,
                "reason": "prior-year base is zero — standard percent growth "
                          "is not definable",
                "warnings": []}
    if base < 0:
        if cur > 0:
            return {"value": None, "status": STATUS_NOT_APPLICABLE,
                    "reason": "sign change (loss -> profit) — percent growth "
                              "would be misleading; not computed, and no "
                              "automatic positive credit is given",
                    "sign_change": True, "warnings": []}
        return {"value": None, "status": STATUS_NOT_APPLICABLE,
                "reason": "prior profit is negative and current is non-positive "
                          "— percent change over a negative base is not a "
                          "rankable earnings-growth measure",
                "warnings": []}

    val = (cur - base) / base * 100.0
    if not math.isfinite(val):
        return {"value": None, "status": STATUS_INVALID,
                "reason": "non_finite_result: computed growth non-finite — "
                          "data corruption",
                "warnings": []}
    lo, hi = EARNINGS_GROWTH_PCT_ANOMALY_BAND
    warnings = []
    reason = "computed from caller-supplied positive prior base"
    if cur < 0:
        # Positive base turned into a loss: the standard-formula percent is
        # meaningful (and negative, so a higher-is-better ranking punishes
        # it), but the loss and the sign flip are recorded independently —
        # this is never surfaced as a desirable growth outcome.
        reason += "; profit turned to loss (sign change recorded)"
        warnings.append(
            "turned_to_loss: positive prior-year base turned into a loss — "
            "the negative percent is the standard-formula change, not a "
            "desirable growth outcome; loss state recorded independently")
    if val < lo or val > hi:
        warnings.append(
            f"magnitude_anomaly: growth {val:.1f}% beyond "
            f"{EARNINGS_GROWTH_PCT_ANOMALY_BAND} — kept as real data; "
            "winsorization / Risk Gate decide later")
        reason += f"; magnitude anomaly ({val:.1f}%)"
    return {"value": val, "status": STATUS_VALID, "reason": reason,
            "warnings": warnings,
            **({"sign_change": True, "current_loss": True} if cur < 0 else {})}


def _build_earnings_growth(m: dict, bases: dict | None) -> dict:
    bases = bases or {}
    parts = {}
    for name, cur_key, g_key, base_key in (
            ("net_profit_growth_pct", "net_profit_ttm", "net_profit_growth",
             "net_profit_prev"),
            ("operating_profit_growth_pct", "operating_profit_ttm",
             "operating_profit_growth", "operating_profit_prev")):
        parts[name] = _growth_component(name, cur_key, g_key, base_key,
                                        m, bases)
    reason = "; ".join(f"{n}: {p['reason']}" for n, p in parts.items())
    return {"parts": parts, "composite": True, "source_metric": _GROWTH_SRC,
            "unit": _GROWTH_UNIT, "definition": _GROWTH_DEF, "reason": reason}


# ---------------------------------------------------------------------------
# roe_level — engine ROE: net_profit_ttm / total_equity * 100 (percent)
# ---------------------------------------------------------------------------
_ROE_SRC = ("roe (Engine.compute derived: net_profit_ttm / total_equity, "
            "emitted only for total_equity > 0)")
_ROE_UNIT = "percent (net_profit_ttm / total_equity * 100)"
_ROE_DEF = ("Engine ROE: the engine-resolved TTM net profit over the latest "
            "report's order-1 total_equity, emitted ONLY for equity > 0. A "
            "negative ROE is a valid loss signal (never invalidated for its "
            "sign, and never a desirable outcome under higher-is-better); a "
            "real zero is a value. roe absent WITH net_profit_ttm present "
            "means the equity denominator is missing, zero or negative (the "
            "three states are not separable from the derived metric) — "
            "missing, never a fabricated level; equity <= 0 can never read "
            "as great performance because nothing is invented here. "
            "Magnitudes beyond the band stay valid with a warning (a tiny "
            "positive equity inflates ROE — real data; winsorization / Risk "
            "Gate decide later).")


def _build_roe_level(m: dict) -> dict:
    roe = m.get("roe")
    np_ = m.get("net_profit_ttm")
    if roe is None:
        if np_ is None:
            part = {"value": None, "status": STATUS_MISSING,
                    "reason": "roe absent and net_profit_ttm absent — no "
                              "numerator, denominator state unknown",
                    "warnings": []}
        elif _bad_number(np_):
            part = {"value": None, "status": STATUS_INVALID,
                    "reason": "net_profit_ttm is not a finite real number — "
                              "data corruption",
                    "warnings": []}
        else:
            part = {"value": None, "status": STATUS_MISSING,
                    "reason": "roe absent although net_profit_ttm is present "
                              "— the engine emits roe only for total_equity "
                              "> 0, so total_equity is missing, zero or "
                              "negative (not separable from the derived "
                              "metric); ROE is not computed rather than "
                              "guessed",
                    "warnings": []}
    elif _bad_number(roe):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "roe is not a finite real number — data corruption",
                "warnings": []}
    else:
        lo, hi = ROE_PCT_ANOMALY_BAND
        warnings = []
        if roe < lo or roe > hi:
            warnings.append(
                f"magnitude_anomaly: roe {roe:.1f}% beyond "
                f"{ROE_PCT_ANOMALY_BAND} — kept as real data; winsorization "
                "/ Risk Gate decide later")
        if roe == 0:
            reason = ("real zero: TTM net profit of exactly zero over "
                      "positive equity")
        elif roe < 0:
            reason = "negative ROE — a real loss over positive equity, kept as data"
        else:
            reason = "positive ROE over positive equity"
        if warnings:
            reason += "; magnitude anomaly recorded, value kept"
        part = {"value": roe, "status": STATUS_VALID, "reason": reason,
                "warnings": warnings}
    return {"parts": {"roe_level": part}, "composite": False,
            "source_metric": _ROE_SRC, "unit": _ROE_UNIT,
            "definition": _ROE_DEF, "reason": part["reason"]}


# ---------------------------------------------------------------------------
# margin_trend — TTM operating-margin change vs the provenance-matched
# prior-year TTM (percentage points), from caller-supplied prev_bases
# ---------------------------------------------------------------------------
_MT_SRC = ("operating_profit_ttm, revenue_ttm (Engine TTM) + "
           "operating_profit_prev, revenue_prev (prev_bases, "
           "provenance-matched replication of the engine's own resolution)")
_MT_UNIT = ("percentage points (operating margin now minus operating margin "
            "one year earlier, both over the same 12-month window)")
_MT_DEF = ("margin_trend_pp = operating_margin_ttm_now - "
           "operating_margin_ttm_prior_year, both margins recomputed over "
           "strictly POSITIVE revenue (the engine's abs()-denominator "
           "margins are not reused) from the engine-resolved current TTM and "
           "the prior-year TTM bases supplied via prev_bases. Like-for-like "
           "12-month windows — deliberately NOT the engine's derived "
           "margin_trend field, which compares the TTM margin against a "
           "same-report prior-year YTD margin (a shorter window span unless "
           "the latest report is annual; 2-B-5 probe: only 2 of 271 latest "
           "reports are annual); that derived field is recorded as an "
           "observed_engine_pp diagnostic only and is never the value. A "
           "missing prior base (unresolved, or removed by the 2-B-4.2 "
           "legacy-sentinel quarantine of operating_profit_prev) leaves the "
           "factor missing — no engine-field substitution, no guessed "
           "window. A negative prior-year margin (loss year) is a valid "
           "base: the trend then measures loss-to-profit improvement on "
           "ratio scales, which has no sign-flip pathology. Negative trends "
           "are valid negative data; diffs beyond the band stay valid with "
           "a warning. Zero prior revenue is not_applicable; negative prior "
           "revenue is invalid (economically impossible for the general "
           "family).")


def _margin_pct(numerator, denominator, label: str) -> tuple:
    """(margin or None, part) — margin in percent over strictly positive
    revenue; real data states stay distinct (missing/invalid/n.a.)."""
    if numerator is None:
        return None, {"value": None, "status": STATUS_MISSING,
                      "reason": f"{label}: profit numerator absent",
                      "warnings": []}
    if _bad_number(numerator):
        return None, {"value": None, "status": STATUS_INVALID,
                      "reason": f"{label}: profit numerator is not a finite "
                                "real number — data corruption",
                      "warnings": []}
    if denominator is None:
        return None, {"value": None, "status": STATUS_MISSING,
                      "reason": f"{label}: revenue denominator absent",
                      "warnings": []}
    if _bad_number(denominator):
        return None, {"value": None, "status": STATUS_INVALID,
                      "reason": f"{label}: revenue denominator is not a "
                                "finite real number — data corruption",
                      "warnings": []}
    if denominator == 0:
        return None, {"value": None, "status": STATUS_NOT_APPLICABLE,
                      "reason": f"{label}: revenue is zero — margin undefined",
                      "warnings": []}
    if denominator < 0:
        return None, {"value": None, "status": STATUS_INVALID,
                      "reason": f"{label}: negative revenue — economically "
                                "impossible for the general family",
                      "warnings": []}
    pct = numerator / denominator * 100.0
    if not math.isfinite(pct):
        return None, _non_finite_result(f"{label} margin")
    return pct, {"value": pct, "status": STATUS_VALID,
                 "reason": f"{label} margin {pct:.2f}%", "warnings": []}


def _build_margin_trend(m: dict, bases: dict | None) -> dict:
    bases = bases or {}
    cur_margin, cur_part = _margin_pct(m.get("operating_profit_ttm"),
                                       m.get("revenue_ttm"), "current TTM")

    def _with_diag(part: dict) -> dict:
        # the engine's derived field is a DIFFERENT measure (TTM vs YTD
        # span); echoed only as a diagnostic, never substituted for a value
        eng = m.get("margin_trend")
        if eng is not None and not _bad_number(eng):
            part["observed_engine_pp"] = eng
        return part

    if cur_part["status"] != STATUS_VALID:
        return {"parts": {"margin_trend_pp": _with_diag(cur_part)},
                "composite": False, "source_metric": _MT_SRC,
                "unit": _MT_UNIT, "definition": _MT_DEF,
                "reason": cur_part["reason"]}
    op_prev = bases.get("operating_profit_prev", _ABSENT)
    rev_prev = bases.get("revenue_prev", _ABSENT)
    if op_prev is _ABSENT or rev_prev is _ABSENT:
        which = [t for t, b in (("operating_profit_prev", op_prev),
                                ("revenue_prev", rev_prev)) if b is _ABSENT]
        missing_tags = ", ".join(which)
        return {"parts": {"margin_trend_pp": _with_diag({
                    "value": None, "status": STATUS_MISSING,
                    "reason": "prior-year TTM base(s) not supplied ("
                              + missing_tags + ") — the engine's derived "
                              "margin_trend compares TTM against a "
                              "same-report YTD margin (different window "
                              "span) and is recorded as a diagnostic only, "
                              "never as the value",
                    "warnings": []})},
                "composite": False, "source_metric": _MT_SRC,
                "unit": _MT_UNIT, "definition": _MT_DEF,
                "reason": "prior-year TTM base not supplied: " + missing_tags}
    if op_prev is None or rev_prev is None:
        prev_part = {"value": None, "status": STATUS_MISSING,
                     "reason": "prior-year TTM base absent — no comparable "
                               "prior window (unresolved or removed by the "
                               "legacy-sentinel quarantine)",
                     "warnings": []}
        return {"parts": {"margin_trend_pp": _with_diag(prev_part)},
                "composite": False, "source_metric": _MT_SRC,
                "unit": _MT_UNIT, "definition": _MT_DEF,
                "reason": prev_part["reason"]}
    prev_margin, prev_part = _margin_pct(op_prev, rev_prev, "prior-year TTM")
    if prev_part["status"] != STATUS_VALID:
        return {"parts": {"margin_trend_pp": _with_diag(prev_part)},
                "composite": False, "source_metric": _MT_SRC,
                "unit": _MT_UNIT, "definition": _MT_DEF,
                "reason": prev_part["reason"]}

    trend = cur_margin - prev_margin
    if not math.isfinite(trend):
        part = _non_finite_result("margin_trend_pp")
    else:
        lo, hi = MARGIN_TREND_PP_ANOMALY_BAND
        warnings = []
        if trend < lo or trend > hi:
            warnings.append(
                f"magnitude_anomaly: margin_trend {trend:.1f}pp beyond "
                f"{MARGIN_TREND_PP_ANOMALY_BAND} — kept as real data; "
                "winsorization / Risk Gate decide later")
        if trend == 0:
            reason = "real zero: operating margin unchanged year over year"
        elif trend < 0:
            reason = f"margin declined {trend:.2f}pp — real data"
        else:
            reason = f"margin improved {trend:.2f}pp"
        if warnings:
            reason += "; magnitude anomaly recorded, value kept"
        part = {"value": trend, "status": STATUS_VALID, "reason": reason,
                "warnings": warnings}
    return {"parts": {"margin_trend_pp": part}, "composite": False,
            "source_metric": _MT_SRC, "unit": _MT_UNIT,
            "definition": _MT_DEF, "reason": part["reason"]}


# ---------------------------------------------------------------------------
# revenue_growth — engine same-report YoY revenue growth (percent)
# ---------------------------------------------------------------------------
_REV_SRC = ("revenue_growth (Engine.compute derived: revenue order-1 vs "
            "order-2 inside the latest report)")
_REV_UNIT = "percent vs the same report's prior-year comparative revenue"
_REV_DEF = ("Engine revenue_growth: (revenue order-1 - revenue order-2) / "
            "|revenue order-2| * 100 inside the LATEST report — numerator "
            "and comparative come from the same report, so they share one "
            "window by construction (no TTM chain, no prior-year base "
            "channel, no legacy-sentinel exposure on this path). The engine "
            "guards an absent/zero comparative (None); a NEGATIVE "
            "comparative revenue would still produce a percent over the "
            "abs() base and is not separable from the derived metric — the "
            "2-B-5 store probe found zero such cells among latest reports "
            "and the pilot re-audits per run. Very large growth is never "
            "auto-invalidated: beyond the band it stays valid with an "
            "independent data warning; winsorization / Risk Gate decide "
            "later. A real zero is a value.")


def _build_revenue_growth(m: dict) -> dict:
    g = m.get("revenue_growth")
    if g is None:
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "engine revenue_growth absent — revenue order-1 "
                          "or the order-2 comparative is missing or zero in "
                          "the latest report (zero vs absent not separable "
                          "from the derived metric)",
                "warnings": []}
    elif _bad_number(g):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "revenue_growth is not a finite real number — "
                          "data corruption",
                "warnings": []}
    else:
        lo, hi = REVENUE_GROWTH_PCT_ANOMALY_BAND
        warnings = []
        if g < lo or g > hi:
            warnings.append(
                f"magnitude_anomaly: revenue growth {g:.1f}% beyond "
                f"{REVENUE_GROWTH_PCT_ANOMALY_BAND} — kept as real data; "
                "winsorization / Risk Gate decide later")
        if g == 0:
            reason = "real zero: revenue unchanged vs the same-report comparative"
        elif g < 0:
            reason = "revenue declined vs the same-report comparative — real data"
        else:
            reason = "revenue grew vs the same-report comparative"
        if warnings:
            reason += "; magnitude anomaly recorded, value kept"
        part = {"value": g, "status": STATUS_VALID, "reason": reason,
                "warnings": warnings}
    return {"parts": {"revenue_growth_pct": part}, "composite": False,
            "source_metric": _REV_SRC, "unit": _REV_UNIT,
            "definition": _REV_DEF, "reason": part["reason"]}


# ---------------------------------------------------------------------------
# interest_coverage — operating-profit coverage PROXY over a same-window
# finance_cost_ttm (caller-supplied expense-TTM channel, step 2-B-7)
# ---------------------------------------------------------------------------
_IC_SRC = ("operating_profit_ttm (Engine TTM) + finance_cost_ttm "
           "(caller-supplied same-window channel; within-report assembly "
           "from the latest report's own comparative legs)")
_IC_UNIT = "ratio (operating_profit_ttm / |finance_cost_ttm|)"
_IC_DEF = (
    "interest_coverage = operating_profit_ttm / |finance_cost_ttm| over ONE "
    "trailing-12-month window — an OPERATING-PROFIT-BASED finance-cost "
    "coverage PROXY, deliberately not presented as standardized EBIT-based "
    "interest coverage: the canonical operating_profit line excludes finance "
    "costs and non-operating items but is not a ratified EBIT definition. "
    "The denominator is the caller-resolved finance_cost_ttm (period_order "
    "1 + 3 - 2 inside the latest report, or order 1 for an explicitly annual "
    "report); no cross-report chain (the metric registry classifies "
    "finance_cost DIRECT_ONLY), no YTD-to-TTM scaling by 12/fm, no guessed "
    "leg. Sign contract (store-evidenced): finance_cost rows are negative "
    "for expense; a zero finance cost leaves the ratio undefined and is "
    "NEVER mapped to zero or infinite coverage, and a positive value reads "
    "as net finance income under the convention — both are not_applicable, "
    "never fabricated expenses via abs(). A negative operating profit is "
    "REAL data: the negative coverage stays valid and ranks at the bottom "
    "under the higher-is-better contract with an explicit warning; it is "
    "never auto-zeroed. A non-finite ratio is invalid; unusual magnitudes "
    "stay valid with a warning.")


def _expense_channel_evidence(channel: dict | None) -> dict | None:
    """Defensive copy of the caller's channel evidence for the record (the
    input dict is never mutated and never aliased into the output)."""
    if not isinstance(channel, dict):
        return None
    ev: dict = {}
    for key in ("value", "prov_code", "reason", "state"):
        if key in channel:
            ev[key] = channel[key]
    legs = channel.get("legs")
    if isinstance(legs, dict):
        ev["legs"] = {k: dict(v) if isinstance(v, dict) else v
                      for k, v in sorted(legs.items())}
    if channel.get("warnings"):
        ev["warnings"] = list(channel["warnings"])
    return ev


def _build_interest_coverage(m: dict, channel: dict | None) -> dict:
    num = m.get("operating_profit_ttm")
    evidence = _expense_channel_evidence(channel)
    if num is None:
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "operating_profit_ttm absent — no coverage numerator",
                "warnings": []}
    elif _bad_number(num):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "operating_profit_ttm is not a finite real number — "
                          "data corruption",
                "warnings": []}
    elif not isinstance(channel, dict):
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "finance_cost_ttm channel not supplied — the "
                          "same-window denominator needs the caller-resolved "
                          "within-report TTM; the engine's order-1 YTD "
                          "finance_cost (window mismatch, 2-B-5 audit) is "
                          "never substituted",
                "warnings": []}
    else:
        val = channel.get("value")
        if val is None:
            part = {"value": None, "status": STATUS_MISSING,
                    "reason": f"finance_cost_ttm unresolved: "
                              f"{channel.get('reason') or 'no reason given'}",
                    "warnings": list(channel.get("warnings") or ())}
        elif _bad_number(val):
            part = {"value": None, "status": STATUS_INVALID,
                    "reason": "finance_cost_ttm is not a finite real number — "
                              "data corruption",
                    "warnings": list(channel.get("warnings") or ())}
        elif val == 0:
            part = {"value": None, "status": STATUS_NOT_APPLICABLE,
                    "reason": "finance_cost_ttm is zero — coverage is "
                              "undefined and is deliberately not mapped to a "
                              "zero or infinite coverage",
                    "warnings": list(channel.get("warnings") or ())}
        elif val > 0:
            part = {"value": None, "status": STATUS_NOT_APPLICABLE,
                    "reason": "finance_cost_ttm is positive — under the "
                              "store's evidenced negative-expense convention "
                              "this reads as net finance income, not a real "
                              "expense; no abs() substitution into a fake "
                              "expense, coverage not computed",
                    "warnings": list(channel.get("warnings") or ())}
        else:
            den = -val  # negative-expense convention: the expense magnitude
            ratio = num / den
            if not math.isfinite(ratio):
                part = _non_finite_result(
                    "interest_coverage = operating_profit_ttm / "
                    "|finance_cost_ttm|")
            else:
                lo, hi = INTEREST_COVERAGE_ANOMALY_BAND
                warnings = list(channel.get("warnings") or ())
                if ratio < lo or ratio > hi:
                    warnings.append(
                        f"magnitude_anomaly: interest_coverage {ratio:.1f} "
                        f"beyond {INTEREST_COVERAGE_ANOMALY_BAND} — kept as "
                        "real data; winsorization / Risk Gate decide later")
                if num < 0:
                    warnings.append(
                        "negative_operating_profit: coverage computed from a "
                        "real operating loss — kept as data; it ranks at the "
                        "bottom under the higher-is-better contract and is "
                        "never auto-zeroed")
                if ratio == 0:
                    reason = "real zero: operating profit of exactly zero cannot cover any expense"
                elif num < 0:
                    reason = ("negative: operating loss over the same-window "
                              "finance-cost expense — real data")
                else:
                    reason = ("positive: operating profit covers the "
                              "same-window finance-cost expense")
                if warnings:
                    reason += "; warning recorded, value kept"
                part = {"value": ratio, "status": STATUS_VALID,
                        "reason": reason, "warnings": warnings}
    return {"parts": {"interest_coverage": part}, "composite": False,
            "source_metric": _IC_SRC, "unit": _IC_UNIT,
            "definition": _IC_DEF, "reason": part["reason"],
            "ttm_evidence": evidence}


# ---------------------------------------------------------------------------
# earnings_quality — non-operating DEPENDENCE share over a same-window
# other_nonop_ttm (caller-supplied expense-TTM channel, step 2-B-7)
# ---------------------------------------------------------------------------
_EQ_SRC = ("other_nonop_ttm (caller-supplied same-window channel; "
           "within-report assembly) + operating_profit_ttm (Engine TTM)")
_EQ_UNIT = "percent (|other_nonop_ttm| / operating_profit_ttm * 100)"
_EQ_DEF = (
    "earnings_quality = |other_nonop_ttm| / operating_profit_ttm * 100 over "
    "ONE trailing-12-month window, lower is better — the share of the "
    "operating result matched by non-operating items, i.e. an indicator of "
    "DEPENDENCE on non-operating results. It is deliberately NOT presented "
    "as complete earnings quality and it is NOT a cash-quality measure (the "
    "cash dimension is cash_conversion's alone — no factor is re-counted "
    "under this name). abs() on the numerator measures the magnitude of "
    "dependence regardless of the non-operating result's sign (both signs "
    "occur in the store); its sign is preserved in the channel evidence. "
    "The ratio is computed ONLY over a strictly positive operating profit: "
    "zero operating profit is undefined, and an operating loss is "
    "conservatively not_applicable because a lower-is-better share would "
    "falsely read a deep loss as excellent quality — the loss state is "
    "recorded, never scored. A real zero numerator is a valid value (no "
    "non-operating dependence); a non-finite ratio is invalid; unusual "
    "magnitudes stay valid with a warning.")


def _build_earnings_quality(m: dict, channel: dict | None) -> dict:
    den = m.get("operating_profit_ttm")
    evidence = _expense_channel_evidence(channel)
    if den is None:
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "operating_profit_ttm absent — no denominator for "
                          "the non-operating share",
                "warnings": []}
    elif _bad_number(den):
        part = {"value": None, "status": STATUS_INVALID,
                "reason": "operating_profit_ttm is not a finite real number — "
                          "data corruption",
                "warnings": []}
    elif den == 0:
        part = {"value": None, "status": STATUS_NOT_APPLICABLE,
                "reason": "operating_profit_ttm is zero — the non-operating "
                          "share is undefined and must never read as "
                          "excellent quality",
                "warnings": []}
    elif den < 0:
        part = {"value": None, "status": STATUS_NOT_APPLICABLE,
                "reason": "operating_profit_ttm is negative (operating loss) "
                          "— the conservative policy refuses a lower-is-"
                          "better share that would falsely rank a deep loss "
                          "as excellent quality; the loss state is recorded "
                          "in the channel evidence, not scored",
                "warnings": []}
    elif not isinstance(channel, dict):
        part = {"value": None, "status": STATUS_MISSING,
                "reason": "other_nonop_ttm channel not supplied — the "
                          "same-window numerator needs the caller-resolved "
                          "within-report TTM; the engine's order-1 YTD "
                          "other_nonop (window mismatch, 2-B-5 audit) is "
                          "never substituted",
                "warnings": []}
    else:
        val = channel.get("value")
        if val is None:
            part = {"value": None, "status": STATUS_MISSING,
                    "reason": f"other_nonop_ttm unresolved: "
                              f"{channel.get('reason') or 'no reason given'}",
                    "warnings": list(channel.get("warnings") or ())}
        elif _bad_number(val):
            part = {"value": None, "status": STATUS_INVALID,
                    "reason": "other_nonop_ttm is not a finite real number — "
                              "data corruption",
                    "warnings": list(channel.get("warnings") or ())}
        else:
            pct = abs(val) / den * 100.0
            if not math.isfinite(pct):
                part = _non_finite_result(
                    "earnings_quality = |other_nonop_ttm| / "
                    "operating_profit_ttm * 100")
            else:
                lo, hi = EARNINGS_QUALITY_PCT_ANOMALY_BAND
                warnings = list(channel.get("warnings") or ())
                if pct < lo or pct > hi:
                    warnings.append(
                        f"magnitude_anomaly: earnings_quality {pct:.1f}% "
                        f"beyond {EARNINGS_QUALITY_PCT_ANOMALY_BAND} — kept "
                        "as real data; winsorization / Risk Gate decide "
                        "later")
                if val == 0:
                    reason = ("real zero: no non-operating dependence over a "
                              "positive operating base")
                elif val < 0:
                    reason = ("non-operating result is a net expense (sign "
                              "preserved in the channel evidence); magnitude "
                              f"{pct:.2f}% of operating profit")
                else:
                    reason = ("non-operating result is net income; magnitude "
                              f"{pct:.2f}% of operating profit")
                if warnings:
                    reason += "; warning recorded, value kept"
                part = {"value": pct, "status": STATUS_VALID,
                        "reason": reason, "warnings": warnings}
    return {"parts": {"earnings_quality": part}, "composite": False,
            "source_metric": _EQ_SRC, "unit": _EQ_UNIT,
            "definition": _EQ_DEF, "reason": part["reason"],
            "ttm_evidence": evidence}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def build_q_raw(metrics_by_company: dict,
                prev_bases: dict | None = None,
                provenance: dict | None = None,
                as_of=None,
                expense_ttm: dict | None = None) -> dict:
    """company_id -> {factor_id: raw factor record} for IN_SCOPE_FACTORS.

    metrics_by_company : Engine.compute() output (metrics[cid] dicts)
    prev_bases         : optional {cid: {"net_profit_prev": x,
                                         "operating_profit_prev": y,
                                         "revenue_prev": z}} — the engine's
                         own prior-year TTM values; without them
                         earnings_growth components and margin_trend stay
                         missing (never the unverified derived percents /
                         the span-mismatched engine margin_trend field)
    provenance         : optional {cid: {"available_at": ts, "source_ref":
                         "<origin evidence>", "source_period": ...,
                         "metrics": {<metric>: {...}}}} — verified requires
                         BOTH the timestamp and a non-empty source_ref
    as_of              : optional historical cutoff; an attributable
                         publication timestamp after as_of invalidates the
                         record for historical computation (PIT_AFTER_AS_OF)
    expense_ttm        : optional {cid: {"finance_cost_ttm": channel,
                                         "other_nonop_ttm": channel}} — the
                         caller-resolved SAME-WINDOW expense TTMs (2-B-7),
                         each channel {"value": x, "prov_code": ...,
                         "reason": ..., "legs": {...}, "warnings": [...]}
                         as assembled inside the latest report; without a
                         channel the factor stays missing (never the
                         window-mismatched engine order-1 YTD value). The
                         channel dicts are never mutated; their evidence is
                         copied into the record's "ttm_evidence".
    """
    prev_bases = prev_bases or {}
    provenance = provenance or {}
    expense_ttm = expense_ttm or {}
    out: dict = {}
    for cid, m in metrics_by_company.items():
        prov = provenance.get(cid)
        bases = prev_bases.get(cid)
        channels = expense_ttm.get(cid) or {}
        econ = {
            "margins": _build_margins(m),
            "cash_conversion": _build_cash_conversion(m),
            "leverage": _build_leverage(m),
            "earnings_growth": _build_earnings_growth(m, bases),
            "roe_level": _build_roe_level(m),
            "margin_trend": _build_margin_trend(m, bases),
            "revenue_growth": _build_revenue_growth(m),
            "interest_coverage": _build_interest_coverage(
                m, channels.get("finance_cost_ttm")),
            "earnings_quality": _build_earnings_quality(
                m, channels.get("other_nonop_ttm")),
        }
        out[cid] = {fid: _assemble(fid, econ[fid], prov, as_of)
                    for fid in IN_SCOPE_FACTORS}
    return out
