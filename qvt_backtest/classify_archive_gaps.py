"""Explain cached rejected reports without relaxing financial evidence rules."""
import json
from collections import Counter
import collect_financial_history as H
import pandas as pd


def classify(html, period):
    if not html:
        return {"reason": "missing_cached_html", "parent_tables": 0, "unit_proven_tables": 0}
    parent, units, dated = 0, 0, 0
    for caption, table in H.P._tables_with_captions(html):
        kind = H.P._caption_kind(caption)
        if not kind or kind[1]:
            continue
        parent += 1
        if "میلیونریال" not in H.P.norm_title(caption):
            continue
        units += 1
        for row in H.P._rows(table)[:4]:
            headers = [d for d in (H.P.jalali_in(c) for c in row) if d]
            if len(headers) >= 2 and H.F.jalali_to_gregorian(*headers[0]).isoformat() == period:
                dated += 1
                break
    reason = ("no_identifiable_parent_statement" if not parent else "no_statement_local_unit_evidence" if not units
              else "missing_own_period_header" if not dated else "unmatched_or_ambiguous_metrics_or_balance")
    return {"reason": reason, "parent_tables": parent, "unit_proven_tables": units, "own_period_tables": dated}


def main():
    catalog = {str(r["letter"]["TracingNo"]): r for r in H.C.read(H.OUT / "catalog_versions.json")}
    rows, missing = [], 0
    for report in H.C.read(H.OUT / "reports.json"):
        if report.get("archive_status") == "missing":
            # Catalog-only stubs block stale fallback but are not rejected
            # archived files. Coverage audit reports these separately.
            missing += 1
            continue
        if report["facts"]:
            continue
        letter = catalog[report["tracing_no"]]["letter"]
        html, path = H.C.report_html(report["symbol"], letter, False, 0)
        rows.append({"symbol": report["symbol"], "tracing_no": report["tracing_no"],
                     "period_end": report["period_end"], "source_sha256": report["sha256"],
                     **classify(html, report["period_end"])})
    pd.DataFrame(rows).to_csv(H.OUT / "unusable_classified.csv", index=False)
    summary = {"reports": len(rows), "catalog_only_missing": missing, "reasons": dict(Counter(r["reason"] for r in rows)),
               "facts_changed": False, "note": "Units in unrelated sales/production tables do not prove financial-statement units"}
    H.C.write(H.OUT / "unusable_classification.json", summary)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
