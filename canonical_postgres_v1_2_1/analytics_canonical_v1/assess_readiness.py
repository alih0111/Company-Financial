"""Readiness assessment: quantify factor availability + missing-data handling.

Canonical-only artifacts under data_work/. No writes to canonical, no runtime deps.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
DW = HERE / "data_work"

FACTOR_SOURCE = {
    "SalesGrowthRank": "sales_growth_12m", "SalesGrowth3MRank": "sales_growth_3m",
    "RevenueGrowthRank": "revenue_growth", "OperatingProfitGrowthRank": "operating_profit_growth",
    "NetProfitGrowthRank": "net_profit_growth", "OperatingMarginRank": "operating_margin",
    "NetMarginRank": "net_margin", "MarginTrendRank": "margin_trend",
    "InterestCoverageRank": "interest_coverage", "EarningsQualityRank": "earnings_quality",
    "PERank": "pe", "PSRank": "ps", "PBRank": "pb", "LiquidityRank": "avg_trade_value_30d",
    "StabilityRank": "sales_stability", "LowVolatilityRank": "volatility_30d",
    "MomentumRank": "price_momentum_30d", "ROERank": "roe", "LeverageRank": "debt_ratio",
    "CurrentRatioRank": "current_ratio", "CashConversionRank": "cash_conversion",
}
CATEGORY = {
    "growth": ["SalesGrowthRank", "SalesGrowth3MRank", "RevenueGrowthRank",
               "OperatingProfitGrowthRank", "NetProfitGrowthRank"],
    "profitability": ["OperatingMarginRank", "NetMarginRank", "ROERank", "MarginTrendRank",
                      "InterestCoverageRank", "CashConversionRank", "EarningsQualityRank"],
    "valuation": ["PERank", "PSRank", "PBRank"],
    "market": ["LiquidityRank", "LeverageRank", "CurrentRatioRank", "StabilityRank",
               "LowVolatilityRank", "MomentumRank"],
}
SOURCES = ["revenue", "net_profit", "operating_profit", "eps", "capital",
           "total_assets", "current_assets", "total_liabilities", "current_liabilities",
           "total_equity", "operating_cash_flow", "finance_cost", "other_non_operating"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    A = json.loads((OUT / "canonical_v1_metrics.json").read_text(encoding="utf-8"))
    n = len(A)

    # factor availability: underlying metric present => factor is data-driven
    frows = []
    for factor, src in FACTOR_SOURCE.items():
        present = sum(1 for v in A.values() if v.get(src) is not None)
        frows.append({"factor_code": factor, "source_metric": src,
                      "companies_with_data": present,
                      "companies_neutral_missing": n - present,
                      "availability_pct": round(present / n * 100, 1)})
    with (DW / "factor_availability.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(frows[0].keys()))
        w.writeheader(); w.writerows(frows)

    # per-company available factor count
    avail = {cid: sum(1 for f, s in FACTOR_SOURCE.items() if v.get(s) is not None)
             for cid, v in A.items()}
    counts = sorted(avail.values())
    # category coverage
    cat_summary = {}
    for cat, factors in CATEGORY.items():
        complete = sum(1 for v in A.values() if all(v.get(FACTOR_SOURCE[f]) is not None for f in factors))
        partial = sum(1 for v in A.values() if any(v.get(FACTOR_SOURCE[f]) is not None for f in factors))
        cat_summary[cat] = {"complete": complete, "any": partial, "none": n - partial,
                            "factors": len(factors)}

    # SOURCE_ABSENT affected companies
    cov = list(csv.DictReader(open(DW / "company_fact_coverage.csv", encoding="utf-8-sig")))
    sa_companies = {r["company_id"] for r in cov if r["missing_reason"] == "SOURCE_ABSENT"}
    # QuantScore validity
    qs_valid = sum(1 for v in A.values() if v.get("quant_score") is not None)

    summary = {
        "canonical_scored_population": n,
        "companies_with_complete_factor_coverage": sum(1 for x in counts if x == len(FACTOR_SOURCE)),
        "companies_with_partial_factor_coverage": sum(1 for x in counts if 0 < x < len(FACTOR_SOURCE)),
        "companies_with_zero_factors": sum(1 for x in counts if x == 0),
        "median_available_factors": statistics.median(counts),
        "min_available_factors": min(counts),
        "max_available_factors": max(counts),
        "factor_count_total": len(FACTOR_SOURCE),
        "category_coverage": cat_summary,
        "companies_affected_by_source_absent": len(sa_companies),
        "source_absent_affected_pct": round(len(sa_companies) / n * 100, 1),
        "companies_with_valid_quant_score": qs_valid,
        "valid_quant_score_pct": round(qs_valid / n * 100, 1),
    }
    (DW / "readiness_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (DW / "readiness_metrics.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "value"])
        for k, v in summary.items():
            w.writerow([k, json.dumps(v) if isinstance(v, dict) else v])

    for k, v in summary.items():
        print(f"{k}: {v}")
    print("\nfactor availability:")
    for r in sorted(frows, key=lambda r: r["availability_pct"]):
        print(f"  {r['factor_code']:28s} {r['companies_with_data']:3d}/{n} ({r['availability_pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
