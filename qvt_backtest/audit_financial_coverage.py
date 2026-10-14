"""Classify actual archive gaps, without more downloads or financial guesses."""
from collections import Counter
import json
import urllib.parse
import pandas as pd
import collect_financial_history as H

CORE_METRICS = [("income_statement", "revenue"), ("income_statement", "net_profit"),
                ("income_statement", "operating_profit"), ("cash_flow", "operating_cash_flow"),
                ("balance_sheet", "total_equity"), ("balance_sheet", "total_assets"),
                ("balance_sheet", "total_liabilities")]


def missing_core(facts):
    present = {(f["statement_type"], f["metric_code"]) for f in facts}
    return [metric for statement, metric in CORE_METRICS if (statement, metric) not in present]

def main():
    catalog = H.C.read(H.OUT / "catalog_versions.json")
    missing, unusable, partial = [], [], []
    for row in catalog:
        tracing = str(row["letter"]["TracingNo"])
        path = H.OUT / "reports" / (row["company_id"] + "_" + tracing + ".json")
        summary = {"company_id": row["company_id"], "symbol": row["symbol"], "tracing_no": tracing,
                   "period_end": row["period"], "published_at": row["published_at"]}
        if path.exists():
            facts = H.load_archived_report(path)["facts"]
            if not facts:
                unusable.append({**summary, "reason": "no_parent_own_period_facts_with_proven_units_headers"})
            elif missing_core(facts):
                partial.append({**summary, "reason": "partial_parent_own_statement_coverage",
                                "missing_metrics": ",".join(missing_core(facts))})
        else:
            letter = row["letter"]
            serial = urllib.parse.parse_qs(urllib.parse.urlsplit(letter.get("Url", "")).query).get("LetterSerial")
            missing.append({**summary, "reason": "not_archived" if letter.get("ExcelUrl") or serial else "catalog_lacks_download_identity"})
    panel = pd.read_csv(H.OUT / "financial_panel.csv")
    age = (pd.to_datetime(panel.date) - pd.to_datetime(panel.financial_period_end)).dt.days
    raw_columns = ["roe_end_equity", "operating_margin", "net_margin", "cash_conversion", "debt_ratio"]
    ready = panel[raw_columns].notna().all(axis=1) & age.between(0, 365) & ~panel.used_older_income_report
    by_date = panel.loc[ready].groupby("date").company_id.nunique().to_dict()
    report = {"catalog_reports": len(catalog), "unarchived": len(missing), "unusable": len(unusable),
              "partial_reports": len(partial), "reports_with_all_seven_core_fields": len(catalog) - len(missing) - len(unusable) - len(partial),
              "missing_reasons": dict(Counter(r["reason"] for r in missing)),
              "financial_panel_rows": len(panel), "fresh_complete_financial_rows": int(ready.sum()),
              "fresh_complete_companies_by_date": by_date,
              "note": "Financial completeness only; share, price and timing gates may exclude further rows"}
    H.C.write(H.OUT / "coverage_audit.json", report)
    columns = ["company_id", "symbol", "tracing_no", "period_end", "published_at", "reason"]
    pd.DataFrame(missing, columns=columns).to_csv(H.OUT / "missing_reports.csv", index=False)
    pd.DataFrame(unusable, columns=columns).to_csv(H.OUT / "unusable_reports.csv", index=False)
    pd.DataFrame(partial, columns=columns + ["missing_metrics"]).to_csv(H.OUT / "partial_reports.csv", index=False)
    print(json.dumps({k: v for k, v in report.items() if k != "fresh_complete_companies_by_date"}, ensure_ascii=False))

if __name__ == "__main__":
    main()
