"""Diagnostic historical financial inputs with per-cutoff report lineage.

Does not score, optimize or invent historical shares. Valuation remains blocked
until share/capital event history has been independently reconstructed.
"""
import datetime as dt
import json
from pathlib import Path
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect_financial_history as H


def duration(rec):
    text = rec["title"].translate(H.P.PERSIAN_DIGITS)
    m = re.search(r"(?:دوره\s*)?(3|6|9|12)\s*ماهه", text)
    return int(m.group(1)) if m else None


def values(rec):
    return {(f["statement_type"], f["metric_code"]): f["value"] for f in rec["facts"]}


def same_prior_year(current, old):
    # Jalali calendar and year-end leap day, never Gregorian 365-day guessing.
    import jdatetime
    a = jdatetime.date.fromgregorian(date=dt.date.fromisoformat(current["period_end"]))
    b = jdatetime.date.fromgregorian(date=dt.date.fromisoformat(old["period_end"]))
    return a.year == b.year + 1 and a.month == b.month and abs(a.day - b.day) <= 1


def reconstruct(reports):
    """Select a complete same-period cash/income TTM, otherwise retain gaps."""
    reports = sorted(reports, key=lambda r: r["period_end"], reverse=True)
    def proven_duration(rec):
        explicit = duration(rec)
        if explicit is not None:
            return explicit
        # Bare "financial year" does not prove twelve months when an issuer
        # changes its year-end. Require its preceding dated annual report.
        if H.F.classify_letter({"Title": rec["title"]}) in ("annual", "annual_audited"):
            if any(H.F.classify_letter({"Title": old["title"]}) in ("annual", "annual_audited")
                   and same_prior_year(rec, old) for old in reports):
                return 12
        return None
    for current in reports:
        months = proven_duration(current)
        if months not in (3, 6, 9, 12):
            continue
        v = values(current)
        sources = [current]
        components = [(v, 1)]
        if months != 12:
            same = next((r for r in reports if proven_duration(r) == months and same_prior_year(current, r)), None)
            annual = next((r for r in reports if proven_duration(r) == 12 and r["period_end"] < current["period_end"]
                           and same is not None and r["period_end"] > same["period_end"]), None)
            if same is None or annual is None:
                continue
            # The intervening fiscal year-end must be the preceding annual
            # window for this interim, not a later changed-year-end report.
            import jdatetime
            a = jdatetime.date.fromgregorian(date=dt.date.fromisoformat(annual["period_end"]))
            c = jdatetime.date.fromgregorian(date=dt.date.fromisoformat(current["period_end"]))
            delta = (c.year - a.year) * 12 + c.month - a.month
            if delta != months:
                continue
            components.extend([(values(annual), 1), (values(same), -1)])
            sources.extend([annual, same])
        metrics = {}
        for stype, metric in [("income_statement", "revenue"), ("income_statement", "net_profit"),
                              ("income_statement", "operating_profit"), ("cash_flow", "operating_cash_flow")]:
            key = stype, metric
            metrics[metric + "_ttm"] = (sum(vv[key] * sign for vv, sign in components)
                                         if all(key in vv for vv, _ in components) else None)
        if any(metrics[k] is None for k in ("revenue_ttm", "net_profit_ttm")):
            continue
        def ratio(n, d):
            return n / d if n is not None and d is not None and d > 0 else None
        revenue, profit = metrics["revenue_ttm"], metrics["net_profit_ttm"]
        metrics["net_margin"] = ratio(profit, revenue)
        metrics["operating_margin"] = ratio(metrics["operating_profit_ttm"], revenue)
        metrics["cash_conversion"] = ratio(metrics["operating_cash_flow_ttm"], profit)
        metrics["debt_ratio"] = ratio(v.get(("balance_sheet", "total_liabilities")), v.get(("balance_sheet", "total_assets")))
        prior = next((r for r in reports if same_prior_year(current, r)), None)
        equity = v.get(("balance_sheet", "total_equity"))
        prior_equity = values(prior).get(("balance_sheet", "total_equity")) if prior else None
        metrics["roe_average_equity"] = ratio(profit, (equity + prior_equity) / 2 if equity is not None and prior_equity is not None else None)
        metrics["total_equity"] = equity
        metrics["roe_end_equity"] = ratio(profit, equity)
        if prior is not None and prior_equity is not None:
            sources.append(prior)
        # Every input is a selected financial-report version. A newly published
        # empty/unarchived statement is not permission to reuse old earnings.
        latest_income = max((r["period_end"] for r in reports), default=current["period_end"])
        return {"financial_period_end": current["period_end"], "latest_income_period": latest_income,
                "used_older_income_report": current["period_end"] != latest_income, **metrics,
                "source_reports": sorted({r["tracing_no"] for r in sources}),
                "max_source_published_at": max((r["published_at"] for r in sources), key=dt.datetime.fromisoformat),
                "valuation_ready": False}
    return None


def main():
    reports = H.C.read(H.OUT / "reports.json")
    panel = pd.read_parquet(H.ROOT / "score_v2_research/pit_feature_panel.parquet")
    date_column = next(c for c in ("date", "signal_date", "asof", "as_of") if c in panel.columns)
    dates = sorted({str(v)[:10] for v in panel[date_column]})
    rows, coverage = [], []
    for date in dates:
        # Conservative opening-day cutoff: never include a report published
        # during the signal day. Full live cutoff semantics are not asserted.
        from codal_publish_resolver import TEHRAN
        cutoff = dt.datetime.fromisoformat(date).replace(tzinfo=TEHRAN).astimezone(dt.timezone.utc)
        selected = H.select_asof(reports, cutoff)
        by_company = {}
        for report in selected:
            by_company.setdefault(report["company_id"], []).append(report)
        available = 0
        for cid, group in by_company.items():
            result = reconstruct(group)
            if result is None:
                continue
            available += 1
            rows.append({"date": date, "company_id": cid, "symbol": group[0]["symbol"], **result,
                         "source_reports": json.dumps(result["source_reports"])})
        coverage.append({"date": date, "companies_with_ttm": available})
    pd.DataFrame(rows).to_csv(H.OUT / "financial_panel.csv", index=False)
    H.C.write(H.OUT / "panel_coverage.json", {"rows": len(rows), "dates": coverage,
        "history_basis": "reconstructed_publication_history", "full_qvt_ready": False,
        "limitations": ["Only archived catalogs and parsed own-period columns", "Conservative previous-day cutoff",
                        "No historical share count or value factors", "Diagnostic ratios, not full live QVT replay",
                        "Current universe has survivorship bias; no untouched historical holdout"]})
    print(json.dumps({"rows": len(rows), "dates": len(dates), "min_ttm_companies": min(x["companies_with_ttm"] for x in coverage),
                      "max_ttm_companies": max(x["companies_with_ttm"] for x in coverage)}))


if __name__ == "__main__":
    main()
