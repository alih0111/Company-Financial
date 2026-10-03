"""Canonical report-chain TTM (Class-B recovery). Pure functions, canonical-only.

TTM(t,m) = FY(t-1,12) + YTD(t,m) - YTD(t-1,m)   for m != 12
TTM(t,12) = YTD(t,12)

Resolution order: A direct canonical TTM -> B report-chain -> C NULL + provenance.
No SQL Server, no legacy fields, no scale inference, no balance-sheet chaining.
"""

from __future__ import annotations

# Machine-readable flow semantics. Runtime reads these sets, never metric names.
FLOW_CUMULATIVE = {"revenue", "net_profit", "operating_profit", "operating_cash_flow", "eps"}
STOCK_POINT_IN_TIME = {"total_assets", "current_assets", "total_liabilities",
                       "current_liabilities", "total_equity"}
DIRECT_ONLY = {"finance_cost", "other_non_operating"}

PROV_DIRECT = "DIRECT_CANONICAL"
PROV_CHAIN = "REPORT_CHAIN_TTM"
PROV_ANNUAL_REPORT = "ANNUAL_REPORT_12M"
PROV_FISCAL_UNKNOWN = "FISCAL_CALENDAR_UNKNOWN"
PROV_INSUFFICIENT = "INSUFFICIENT_TTM_PERIODS"
PROV_NO_ANNUAL = "MISSING_PRIOR_ANNUAL"
PROV_NO_COMPARABLE = "MISSING_PRIOR_COMPARABLE"
PROV_NONCOMPARABLE = "NON_COMPARABLE_PERIOD"
PROV_PIT = "PIT_UNAVAILABLE"

# Default fiscal-year-end month when a caller has no explicit evidence. Callers
# that DO have evidence (Codal report titles) must pass the real month; passing
# this default for a non-Esfand issuer is the defect this module now avoids.
DEFAULT_ANNUAL_MONTH = 12


def _cell_get(report, fy, fm, metric, order=1):
    cell = report.get((fy, fm))
    if not cell:
        return None
    d = cell.get(metric)
    if not d:
        return None
    return d.get(order)


def direct_ttm(report, metric, fy, fm):
    """A: within-report period_order 1 + 3 - 2 (or 1 when month==12)."""
    d = report.get((fy, fm), {}).get(metric)
    if not d:
        return None, PROV_INSUFFICIENT
    cur = d.get(1)
    if cur is None:
        return None, PROV_INSUFFICIENT
    if fm == DEFAULT_ANNUAL_MONTH:
        return cur, PROV_DIRECT
    prior_fy = d.get(3)
    prior_ytd = d.get(2)
    if prior_fy is None or prior_ytd is None:
        return None, PROV_INSUFFICIENT
    return cur + prior_fy - prior_ytd, PROV_DIRECT


def chain_ttm(report, metric, fy, fm, annual_month=None, prev_annual_cell=None):
    """B: annual_anchor + YTD(t,m) - YTD(t-1,m).

    The annual anchor is the previous **annual report cell**, supplied by the
    caller from explicit duration evidence (``prev_annual_cell``). It is never
    assumed to be "the same calendar month one year earlier": with a fiscal-year
    change the anchor moves, and a month-12 assumption is simply a special case.

    ``annual_month`` is the fallback for callers without cell-level evidence.
    """
    if metric not in FLOW_CUMULATIVE:
        return None, PROV_NONCOMPARABLE
    if fy is None or fm is None:
        return None, PROV_PIT
    cur = _cell_get(report, fy, fm, metric, 1)
    if cur is None:
        return None, PROV_INSUFFICIENT
    if prev_annual_cell is None:
        anchor = (fy - 1, annual_month if annual_month is not None else DEFAULT_ANNUAL_MONTH)
    else:
        anchor = prev_annual_cell
    if (fy, fm) == anchor:
        return cur, PROV_CHAIN
    annual = _cell_get(report, anchor[0], anchor[1], metric, 1)
    if annual is None:
        return None, PROV_NO_ANNUAL
    prior_ytd = _cell_get(report, fy - 1, fm, metric, 1)
    if prior_ytd is None:
        return None, PROV_NO_COMPARABLE
    return annual + cur - prior_ytd, PROV_CHAIN


def resolve_ttm(report, metric, fy, fm, annual_month=None, is_annual=None,
                prev_annual_cell=None):
    """Resolve a TTM value: explicit annual report -> A direct -> B chain -> C.

    ``is_annual`` and ``prev_annual_cell`` come from explicit duration evidence
    (Codal report titles). When ``is_annual`` is True the cell IS the annual
    report, so the TTM is its current-period value regardless of its month —
    this is what makes non-Esfand issuers correct instead of NULL.
    """
    if is_annual:
        cur = _cell_get(report, fy, fm, metric, 1)
        if cur is not None:
            return cur, PROV_ANNUAL_REPORT
    v, prov = direct_ttm(report, metric, fy, fm)
    if v is not None:
        return v, prov
    if metric in FLOW_CUMULATIVE:
        cv, cprov = chain_ttm(report, metric, fy, fm, annual_month=annual_month,
                              prev_annual_cell=prev_annual_cell)
        if cv is not None:
            return cv, cprov
        # prefer the more specific chain reason over the generic direct one
        if cprov in (PROV_NO_ANNUAL, PROV_NO_COMPARABLE, PROV_PIT, PROV_NONCOMPARABLE):
            return None, cprov
    return None, PROV_INSUFFICIENT


def chain_legs(report, metric, fy, fm):
    """Expose the three canonical cells used, for provenance/explainability."""
    return {
        "latest_ytd": (fy, fm, metric, 1, _cell_get(report, fy, fm, metric, 1)),
        "prior_annual": (fy - 1, 12, metric, 1, _cell_get(report, fy - 1, 12, metric, 1)),
        "prior_comparable_ytd": (fy - 1, fm, metric, 1, _cell_get(report, fy - 1, fm, metric, 1)),
    }
