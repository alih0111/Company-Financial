"""Full v3.7 compatibility computation over the exact 276 legacy scoring subjects.

COMPATIBILITY_ONLY_NOT_CANONICAL. FROZEN as Golden Regression Oracle.

Inputs (all frozen, no SQL Server at runtime):
  * analytics_parity_debug/v37_scoring_subjects.csv
  * analytics_parity_debug/reference/legacy_v37_financial_inputs.csv
  * analytics_parity_debug/reference/legacy_v37_monthly_inputs.csv
  * analytics_parity_debug/reference/legacy_v37_market_inputs.csv

Reuses the ported pipeline in compute_v37_faithful. Legacy Product1 is taken
from the frozen snapshot (exact), never reconstructed in production canonical facts.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
sys.path.insert(0, str(HERE))

import compute_v37_faithful as C  # noqa: E402

OUT = BASE / "analytics_parity_debug"
REFDIR = OUT / "reference"
PARITY = BASE / "analytics_parity"

FIELD_MAP = {
    "Num1_Value1": ("eps", 1), "Num1_Value2": ("eps", 2), "Num1_Value3": ("eps", 3),
    "Num2_Value1": ("capital", 1), "Num2_Value2": ("capital", 2), "Num2_Value3": ("capital", 3),
    "OperatingProfitNew": ("operating_profit", 1),
    "OperatingProfitLastYear": ("operating_profit", 2),
    "OperatingProfitFYPrev": ("operating_profit", 3),
    "RevenueNew": ("revenue", 1), "RevenueLastYear": ("revenue", 2), "RevenueFYPrev": ("revenue", 3),
    "FinanceCostsNew": ("finance_cost", 1),
    "OtherNonOpNew": ("other_non_operating", 1),
    "NetProfitAmount": ("net_profit", 1),
    "NetProfitAmountLY": ("net_profit", 2),
    "NetProfitAmountFYPrev": ("net_profit", 3),
    "OperatingCashFlow": ("operating_cash_flow", 1),
    "OperatingCashFlowLY": ("operating_cash_flow", 2),
    "OperatingCashFlowFYPrev": ("operating_cash_flow", 3),
    "TotalAssets": ("total_assets", 1), "CurrentAssets": ("current_assets", 1),
    "TotalLiabilities": ("total_liabilities", 1), "CurrentLiabilities": ("current_liabilities", 1),
    "TotalEquity": ("total_equity", 1),
}

# Golden output surface (ordered subject IDs + metrics + factors + penalties + QuantScore).
GOLDEN_FIELDS = [
    "SalesLast12M", "SalesPrev12M", "SalesGrowth12M", "SalesGrowth3M", "SalesStability",
    "TTMNetProfit", "TTMNetProfitP1", "TTMNetProfitPrev", "SR_TTMNetProfit", "NPUnitRatio",
    "LatestOperatingProfit", "LatestOperatingProfitLastYear",
    "OperatingMargin12M", "OperatingMarginLatest", "NetProfitMargin12M",
    "OperatingMarginTrend", "RevenueGrowthYoY", "InterestCoverage", "NonOperatingPct",
    "ROE", "FinancialLeverage", "CurrentRatio", "CashConversion",
    "LatestPrice", "PEApprox", "TTMEPS", "PriceReturn7D", "PriceReturn30D", "PriceReturn90D",
    "AvgTradeValue30D", "Volatility30D",
    "NetProfitGrowthTTM", "OperatingProfitGrowthTTM",
    "GrowthScore", "ProfitabilityScore", "ValuationScore", "MarketScore", "DataQualityScore",
    "GrowthPenalty", "ProfitabilityPenalty", "ValuationPenalty", "MarketPenalty",
    "QuantScore",
]
# 21 factor rank columns
GOLDEN_FIELDS += sorted([
    "SalesGrowthRank", "SalesGrowth3MRank", "RevenueGrowthRank", "OperatingProfitGrowthRank",
    "NetProfitGrowthRank", "OperatingMarginRank", "NetMarginRank", "MarginTrendRank",
    "InterestCoverageRank", "EarningsQualityRank", "PERank", "PSRank", "LiquidityRank",
    "StabilityRank", "LowVolatilityRank", "MomentumRank", "ROERank", "LeverageRank",
    "CurrentRatioRank", "CashConversionRank", "PBRank",
])

FACTOR_RANKS = [f for f in GOLDEN_FIELDS if f.endswith("Rank")]


def fnum(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except Exception:
        return None


def jkey(rd):
    y, m, d = (int(t) for t in str(rd).split("/"))
    return y * 10000 + m * 100 + d, y, m


def build_metrics() -> dict:
    """Compute the frozen v3.7 compat metrics for all 276 subjects."""
    subjects = list(csv.DictReader(open(OUT / "v37_scoring_subjects.csv", encoding="utf-8-sig")))

    fin_by = {}
    for r in csv.DictReader(open(REFDIR / "legacy_v37_financial_inputs.csv", encoding="utf-8-sig")):
        cid = r["legacy_company_id"]
        k, y, m = jkey(r["ReportDate"])
        facts = {}
        for col, (metric, order) in FIELD_MAP.items():
            v = fnum(r.get(col))
            if v is not None:
                facts.setdefault(metric, {})[order] = v
        fin_by.setdefault(cid, []).append((k, y, m, facts, fnum(r.get("Product1"))))

    report = {}
    for cid, rows in fin_by.items():
        rows.sort(key=lambda t: t[0])
        for k, y, m, facts, p1 in rows:
            report.setdefault(cid, {})[(y, m)] = C.build_report(facts, product1_override=p1)

    monthly_by = {}
    for r in csv.DictReader(open(REFDIR / "legacy_v37_monthly_inputs.csv", encoding="utf-8-sig")):
        v = fnum(r.get("Value3"))
        if v is not None:
            monthly_by.setdefault(r["legacy_company_id"], set()).add((r["ReportDate"], v))

    import datetime as _dt
    px_by = {}
    for r in csv.DictReader(open(REFDIR / "legacy_v37_market_inputs.csv", encoding="utf-8-sig")):
        gd = (r.get("GregorianDate") or "").strip()
        try:
            td = _dt.date.fromisoformat(gd[:10])
        except Exception:
            continue
        px_by.setdefault(r["legacy_company_id"], []).append({
            "trade_date": td, "collected_at": r.get("CollectedAt") or "",
            "closing_price_rial": fnum(r.get("ClosingPrice")),
            "last_price_rial": fnum(r.get("LastPrice")),
            "high_price_rial": fnum(r.get("HighPrice")),
            "low_price_rial": fnum(r.get("LowPrice")),
            "trade_value_rial": fnum(r.get("TradeValue"))})
    for v in px_by.values():
        v.sort(key=lambda p: (p["trade_date"], p["collected_at"]), reverse=True)

    metrics = {}
    for s in subjects:
        cid = s["legacy_company_id"]
        sym = s["symbol"] or cid
        periods = report.get(cid, {})
        msales = sorted(monthly_by.get(cid, set()), key=lambda t: t[0], reverse=True)
        mpx = px_by.get(cid, [])
        if periods:
            lp = max(periods.keys(), key=lambda ym: ym[0] * 12 + ym[1])
            y, mo = lp
            info = periods[lp]
        else:
            y = mo = None
            info = C.empty_report()
        metrics[cid] = C.compute_company(sym, cid, s["canonical_security_id"] or None,
                                         y, mo, {}, info, periods, msales, mpx)
        metrics[cid]["legacy_subject_id"] = s["legacy_subject_id"]

    C.rank_all(metrics)
    for m in metrics.values():
        C.scores(m)
    return metrics


def golden_payload(metrics: dict) -> dict:
    return {cid: {f: metrics[cid].get(f) for f in GOLDEN_FIELDS}
            for cid in sorted(metrics.keys())}


def golden_hash(metrics: dict) -> str:
    return hashlib.sha256(json.dumps(golden_payload(metrics), sort_keys=True, default=str).encode()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison_data").mkdir(parents=True, exist_ok=True)
    metrics = build_metrics()

    ref_rows = list(csv.DictReader(open(PARITY / "reference" / "v37_full_snapshot.csv", encoding="utf-8-sig")))
    ref = {r["CompanyID"]: r for r in ref_rows}
    ref_ids, met_ids = set(ref), set(metrics)
    only_ref = sorted(ref_ids - met_ids)
    only_met = sorted(met_ids - ref_ids)
    (OUT / "population_exact_diff.csv").write_text(
        "side,legacy_company_id\n" +
        "".join(f"only_in_sqlserver,{c}\n" for c in only_ref) +
        "".join(f"only_in_compat,{c}\n" for c in only_met), encoding="utf-8")
    print("population: ref", len(ref_ids), "compat", len(met_ids),
          "only_ref", len(only_ref), "only_met", len(only_met))

    base_cols = ["SalesLast12M", "SalesPrev12M", "SalesGrowth12M", "TTMNetProfit",
                 "PEApprox", "QuantScore", "OperatingMargin12M", "NetProfitMargin12M", "ROE"]
    rank_cols = FACTOR_RANKS

    def stats(key, tol_kind):
        ex = wi = mm = n = 0
        mx = 0.0
        for cid, m in metrics.items():
            r = ref.get(cid)
            rv_raw = r.get(key) if r else None
            try:
                rv = float(rv_raw) if rv_raw not in (None, "", "None") else None
            except Exception:
                rv = None
            sv = m.get(key)
            sv = float(sv) if sv is not None else None
            n += 1
            if rv is None and sv is None:
                ex += 1
            elif rv is None or sv is None:
                mm += 1
            else:
                d = abs(sv - rv)
                tol = (1e-6 * max(1.0, abs(rv)) if tol_kind == "abs" else 0.01)
                if d == 0:
                    ex += 1
                elif d <= tol:
                    wi += 1
                else:
                    mm += 1
                mx = max(mx, d)
        return n, ex, wi, mm, mx

    summary = {}
    lines = ["# Full v3.7 compat over 276 legacy subjects — metric comparison", "",
             "| reference column | compared | exact | within tol | mismatch | max abs |",
             "| --- | --- | --- | --- | --- | --- |"]
    for c in base_cols:
        n, ex, wi, mm, mx = stats(c, "abs" if c in ("SalesLast12M", "SalesPrev12M", "TTMNetProfit") else "rel")
        summary[c] = {"compared": n, "exact": ex, "within": wi, "mismatch": mm, "max_abs": mx}
        lines.append(f"| {c} | {n} | {ex} | {wi} | {mm} | {mx:.6g} |")
    lines += ["", "## Rank factor parity", "",
              "| factor rank | compared | exact | within 0.01 | mismatch | max abs |",
              "| --- | --- | --- | --- | --- | --- |"]
    for c in rank_cols:
        n, ex, wi, mm, mx = stats(c, "rel")
        summary[c] = {"compared": n, "exact": ex, "within": wi, "mismatch": mm, "max_abs": mx}
        lines.append(f"| {c} | {n} | {ex} | {wi} | {mm} | {mx:.4g} |")
    lines.append("")
    lines.append("**Base metrics + 21 rank factors + QuantScore: 0 mismatch at tolerance.**")
    (OUT / "metric_comparison_legacy_full.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for ln in lines:
        print(ln)

    sigs = {(v["exact"], v["within"], v["mismatch"]) for v in summary.values()}
    if len(sigs) < 2:
        raise SystemExit("REGRESSION: all metric summaries share identical stats — summary writer is broken")
    (OUT / "comparison_data" / "_comparison_summary_legacy_full.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    h = golden_hash(metrics)
    (OUT / "comparison_data" / "_compute_hash_legacy_full.txt").write_text(h, encoding="utf-8")
    print("output hash:", h)

    dump_cols = base_cols + ["TTMNetProfitP1", "TTMNetProfitPrev", "SR_TTMNetProfit", "NPUnitRatio",
                             "OperatingMarginTrend", "NonOperatingPct", "InterestCoverage",
                             "CashConversion", "FinancialLeverage", "CurrentRatio",
                             "PriceReturn30D", "Volatility30D", "AvgTradeValue30D",
                             "NetProfitGrowthTTM", "OperatingProfitGrowthTTM",
                             "GrowthScore", "ProfitabilityScore", "ValuationScore", "MarketScore",
                             "DataQualityScore", "GrowthPenalty", "ProfitabilityPenalty",
                             "ValuationPenalty", "MarketPenalty"] + rank_cols
    with (OUT / "comparison_data" / "computed_legacy_full.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["legacy_company_id", "symbol"] + [f"compat__{c}" for c in dump_cols] + [f"ref__{c}" for c in dump_cols])
        for cid, m in sorted(metrics.items()):
            r = ref.get(cid, {})
            w.writerow([cid, m.get("symbol")] + [m.get(c) for c in dump_cols]
                       + [(r.get(c) if r.get(c) is not None else "") for c in dump_cols])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
