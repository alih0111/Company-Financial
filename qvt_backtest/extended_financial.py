"""Historical remaining-Q diagnostics with dated, parent, same-window evidence.

No score activation: growth uses current-report comparative information only at
its publication cutoff; expense legs stay within one report and must reconcile
with the reconstructed operating-profit numerator. Gaps remain explicit.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
import pandas as pd
import jdatetime
import collect_financial_history as H
import build_financial_panel as F
from codal_publish_resolver import TEHRAN


def same_year(current, previous):
    return F.same_prior_year({"period_end": current}, {"period_end": previous})


def ttm(values, headers, months, group):
    if 1 not in values:
        return None
    if months == 12:
        return values[1] * 1e6
    if months not in (3, 6, 9) or len(headers) < 3 or not all(k in values for k in (1, 2, 3)):
        return None
    days = [H.F.jalali_to_gregorian(*h).isoformat() for h in headers[:3]]
    if not same_year(days[0], days[1]):
        return None
    c, a = (jdatetime.date.fromgregorian(date=dt.date.fromisoformat(d)) for d in (days[0], days[2]))
    if (c.year - a.year) * 12 + c.month - a.month != months:
        return None
    # An independent dated annual source must establish this fiscal year-end.
    annual = any(r["period_end"] == days[2] and F.duration(r) == 12 for r in group)
    if not annual:
        annual = any(r["period_end"] == days[2] and H.F.classify_letter({"Title": r["title"]}) in ("annual", "annual_audited")
                     and any(same_year(r["period_end"], old["period_end"]) and H.F.classify_letter({"Title": old["title"]}) in ("annual", "annual_audited") for old in group)
                     for r in group)
    return (values[1] + values[3] - values[2]) * 1e6 if annual else None


def derive(current, parsed, group, financial):
    result = {f: None for f in ("margin_trend", "revenue_growth", "interest_coverage", "earnings_quality")}
    reasons = {}
    income = parsed["statements"].get("income_statement", {})
    headers = parsed["period_headers"].get("income_statement", [])
    days = [H.F.jalali_to_gregorian(*h).isoformat() for h in headers]
    if not days or days[0] != current["period_end"]:
        return result, {f: "missing_parent_unit_proven_current_header" for f in result}, []
    months = F.duration(current)
    if months is None and H.F.classify_letter({"Title": current["title"]}) in ("annual", "annual_audited"):
        if any(same_year(current["period_end"], old["period_end"]) and H.F.classify_letter({"Title": old["title"]}) in ("annual", "annual_audited") for old in group):
            months = 12
    revenue = income.get("revenue", {})
    if len(days) >= 2 and same_year(days[0], days[1]) and 1 in revenue and revenue.get(2, 0) > 0:
        result["revenue_growth"] = (revenue[1] / revenue[2] - 1) * 100
    else:
        reasons["revenue_growth"] = "missing_or_nonpositive_same_report_yoy_revenue"
    own_op = ttm(income.get("operating_profit", {}), headers, months, group)
    expected_op = financial.get("operating_profit_ttm")
    reconciled = (own_op is not None and pd.notna(expected_op) and math.isclose(own_op, expected_op, rel_tol=1e-9, abs_tol=1))
    if reconciled:
        finance = ttm(income.get("finance_cost", {}), headers, months, group)
        other = ttm(income.get("other_non_operating", {}), headers, months, group)
        if finance is not None and finance < 0:
            result["interest_coverage"] = own_op / -finance
        else:
            reasons["interest_coverage"] = "missing_zero_or_income_finance_denominator"
        if other is not None and own_op > 0:
            result["earnings_quality"] = abs(other) / own_op * 100
        else:
            reasons["earnings_quality"] = "missing_nonop_or_nonpositive_operating_profit"
    else:
        reasons.update({f: "within_report_operating_ttm_missing_or_different_from_core_numerator" for f in ("interest_coverage", "earnings_quality")})
    prior_dates = [r["period_end"] for r in group if same_year(current["period_end"], r["period_end"])]
    # Bound the prior reconstruction to exactly the corresponding year/month/day.
    historical = [r for r in group if prior_dates and r["period_end"] <= max(prior_dates)]
    prior = F.reconstruct(historical) if historical else None
    lineage = [current["tracing_no"]]
    if (prior and same_year(current["period_end"], prior["financial_period_end"]) and pd.notna(financial.get("operating_margin"))
            and prior.get("operating_margin") is not None):
        result["margin_trend"] = (financial["operating_margin"] - prior["operating_margin"]) * 100
        lineage.extend(prior["source_reports"])
    else:
        reasons["margin_trend"] = "missing_same_period_prior_year_operating_ttm"
    return result, reasons, sorted(set(lineage))


def main():
    reports = H.C.read(H.OUT / "reports.json")
    panel = pd.read_csv(H.OUT / "financial_panel.csv")
    parsed_cache, rows = {}, []
    for date, cohort in panel.groupby("date", sort=True):
        cutoff = dt.datetime.fromisoformat(date).replace(tzinfo=TEHRAN).astimezone(dt.timezone.utc)
        groups = {}
        for rec in H.select_asof(reports, cutoff):
            groups.setdefault(rec["company_id"], []).append(rec)
        for financial in cohort.to_dict("records"):
            group = groups[financial["company_id"]]
            current = next(r for r in group if r["period_end"] == financial["financial_period_end"])
            key = current["company_id"], current["tracing_no"]
            if key not in parsed_cache:
                if current.get("parser_version") in ("codal-dynamic-source-v1", "codal-dynamic-source-v2", "codal-dynamic-source-v3", "codal-dynamic-source-v4", "codal-dynamic-source-v5", "codal-dynamic-source-v6"):
                    from dynamic_financial import verified_parsed
                    parsed_cache[key] = verified_parsed(current)
                else:
                    html, _ = H.C.report_html(current["symbol"], {"TracingNo": current["tracing_no"]}, False, 0)
                    parsed_cache[key] = H.P.parse_report(html, parent_only=True) if html else {"statements": {}, "period_headers": {}}
            values, reasons, sources = derive(current, parsed_cache[key], group, financial)
            rows.append({"date": date, "symbol": financial["symbol"], "company_id": current["company_id"],
                         "current_report": current["tracing_no"], "published_at": current["published_at"], **values,
                         "source_reports": json.dumps(sources), "reasons": json.dumps(reasons, ensure_ascii=False)})
        print(f"{date}: extended diagnostic rows={len(rows)}", flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(H.OUT / "extended_financial_panel.csv", index=False)
    summary = {"version": "historical-extended-q-diagnostics-v1", "rows": len(frame),
               "valid": {f: int(frame[f].notna().sum()) for f in ("margin_trend", "revenue_growth", "interest_coverage", "earnings_quality")},
               "full_model_certified": False, "weights_changed": False,
               "limitations": ["No historical industry", "ROE stability absent", "Only explicit unit/period parent tables", "Diagnostic panel not automatically scored or activated"]}
    H.C.write(H.OUT / "extended_financial_summary.json", summary)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
