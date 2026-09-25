"""Before/after comparison for report-chain TTM recovery. Canonical-only artifacts."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
DW = HERE / "data_work"
DW.mkdir(parents=True, exist_ok=True)

BEFORE = json.loads((OUT / "canonical_v1_metrics_before_report_chain.json").read_text(encoding="utf-8"))
AFTER = json.loads((OUT / "canonical_v1_metrics.json").read_text(encoding="utf-8"))

TTM_METRICS = ["operating_profit_ttm", "revenue_ttm", "net_profit_ttm", "eps_ttm", "operating_cash_flow_ttm"]
DOWNSTREAM = ["operating_margin", "operating_profit_growth", "net_margin", "roe",
              "growth_score", "profitability_score", "valuation_score", "market_score",
              "data_quality_score", "quant_score"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = []
    recovered = []
    changed_nonnull = []
    for cid, after in AFTER.items():
        before = BEFORE.get(cid, {})
        symbol = after.get("symbol") or ""
        prov = after.get("_ttm_prov", {})
        for metric in TTM_METRICS + DOWNSTREAM:
            b = before.get(metric)
            a = after.get(metric)
            changed = (b is None) != (a is None) or (
                b is not None and a is not None and abs(float(b) - float(a)) > 1e-9)
            p = prov.get(metric if metric.endswith("_ttm") else f"{metric}_ttm", "")
            rows.append({"company_id": cid, "symbol": symbol, "metric": metric,
                         "before": b, "after": a, "changed": changed, "provenance": p})
            if b is None and a is not None:
                recovered.append({"company_id": cid, "symbol": symbol, "metric": metric,
                                  "after": a, "provenance": p})
            if b is not None and a is not None and abs(float(b) - float(a)) > 1e-9:
                changed_nonnull.append({"company_id": cid, "symbol": symbol, "metric": metric,
                                        "before": b, "after": a})

    with (DW / "report_chain_before_after.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    with (DW / "report_chain_recovered_cases.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(recovered[0].keys()) if recovered else
                           ["company_id", "symbol", "metric", "after", "provenance"])
        w.writeheader(); w.writerows(recovered)

    # coverage before/after for TTM metrics
    print("metric                    before_present  after_present  recovered")
    for metric in TTM_METRICS:
        bp = sum(1 for c in BEFORE.values() if c.get(metric) is not None)
        ap = sum(1 for c in AFTER.values() if c.get(metric) is not None)
        print(f"  {metric:24s} {bp:5d}          {ap:5d}         {ap - bp:4d}")
    print("\nrecovered rows by (metric, provenance):")
    from collections import Counter
    print("  ", dict(Counter((r["metric"], r["provenance"]) for r in recovered)))
    print("changed-while-non-NULL rows:", len(changed_nonnull))
    print("\nprovenance distribution (operating_profit_ttm):")
    pc = Counter(AFTER[c].get("_ttm_prov", {}).get("operating_profit_ttm", "")
                 for c in AFTER if AFTER[c].get("operating_profit_ttm") is not None)
    print("  ", dict(pc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
