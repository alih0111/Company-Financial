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
PROV_INSUFFICIENT = "INSUFFICIENT_TTM_PERIODS"
PROV_NO_ANNUAL = "MISSING_PRIOR_ANNUAL"
PROV_NO_COMPARABLE = "MISSING_PRIOR_COMPARABLE"
PROV_NONCOMPARABLE = "NON_COMPARABLE_PERIOD"
PROV_PIT = "PIT_UNAVAILABLE"


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
    if fm == 12:
        return cur, PROV_DIRECT
    prior_fy = d.get(3)
    prior_ytd = d.get(2)
    if prior_fy is None or prior_ytd is None:
        return None, PROV_INSUFFICIENT
    return cur + prior_fy - prior_ytd, PROV_DIRECT


def chain_ttm(report, metric, fy, fm):
    """B: FY(t-1,12) + YTD(t,m) - YTD(t-1,m)."""
    if metric not in FLOW_CUMULATIVE:
        return None, PROV_NONCOMPARABLE
    if fy is None or fm is None:
        return None, PROV_PIT
    cur = _cell_get(report, fy, fm, metric, 1)
    if cur is None:
        return None, PROV_INSUFFICIENT
    if fm == 12:
        return cur, PROV_CHAIN
    annual = _cell_get(report, fy - 1, 12, metric, 1)
    if annual is None:
        return None, PROV_NO_ANNUAL
    prior_ytd = _cell_get(report, fy - 1, fm, metric, 1)
    if prior_ytd is None:
        return None, PROV_NO_COMPARABLE
    return annual + cur - prior_ytd, PROV_CHAIN


def resolve_ttm(report, metric, fy, fm):
    """A direct -> B chain -> C. Returns (value, provenance). Deterministic."""
    v, prov = direct_ttm(report, metric, fy, fm)
    if v is not None:
        return v, prov
    if metric in FLOW_CUMULATIVE:
        cv, cprov = chain_ttm(report, metric, fy, fm)
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
