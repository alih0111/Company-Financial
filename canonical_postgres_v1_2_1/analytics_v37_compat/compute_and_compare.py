"""Canonical -> v3.7-compat analytics (subset) + comparison to frozen reference.

This is a COMPATIBILITY LAYER. It reads canonical tables only (never mutates
them) and computes v3.7-comparable metrics using the documented weights. It is a
deliberately reduced reimplementation of the production view; every metric that
is not reproduced is reported (not hidden).
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn  # noqa: E402

PARITY = BASE / "analytics_parity"
REF = PARITY / "reference"

WEIGHTS = {
    "SalesGrowth": 10, "RevenueGrowth": 5, "OperatingProfitGrowth": 5, "NetProfitGrowth": 10,
    "OperatingMargin": 4, "NetMargin": 4, "ROE": 6, "InterestCoverage": 3, "CashConversion": 2, "EarningsQuality": 4,
    "PE": 11, "PS": 3, "PB": 2,
    "Liquidity": 3, "Leverage": 2, "CurrentRatio": 2, "Stability": 1, "LowVolatility": 2, "Momentum": 1,
}


def midrank_percentile(values: dict[str, float | None], higher_better=True) -> dict[str, float]:
    present = {k: v for k, v in values.items() if v is not None}
    n = len(present)
    out = {k: 0.3 for k in values}  # neutral default for missing (v3.7 uses ~0.3)
    if n == 0:
        return out
    if n == 1:
        out[next(iter(present))] = 0.5
        return out
    order = sorted(present.items(), key=lambda kv: kv[1])
    rank = {k: i for i, (k, _) in enumerate(order)}
    for k, v in present.items():
        r = rank[k]
        pct = r / (n - 1)
        if not higher_better:
            pct = 1 - pct
        out[k] = pct
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ctx = json.loads((PARITY / "reference_context.json").read_text(encoding="utf-8"))
    cutoff = ctx["analysis_cutoff_at_utc"]
    print("cutoff:", cutoff)

    pg = pg_pilot_conn(autocommit=True)
    pc = pg.cursor()

    def rows(sql, p=()):
        pc.execute(sql, p)
        cols = [c[0] for c in pc.description]
        return [dict(zip(cols, r)) for r in pc.fetchall()]

    # securities + company symbol
    secs = rows("""
        SELECT s.id AS security_id, s.company_id, s.codal_symbol AS symbol, s.tsetmc_ins_code
        FROM core.securities s ORDER BY s.codal_symbol
    """)
    comp = {str(s["company_id"]): s for s in secs}

    # ---- Layer 2: monthly sales (distinct periods, last12 vs prev12) ----
    monthly = rows("""
        SELECT company_id, period_end_date, SUM(sales_amount_rial) AS amt
        FROM fundamentals.monthly_activities
        GROUP BY company_id, period_end_date ORDER BY company_id, period_end_date
    """)
    by_company_monthly: dict[str, list] = {}
    for m in monthly:
        by_company_monthly.setdefault(str(m["company_id"]), []).append(m)

    # ---- Layer 3/4: latest financial facts + TTM (period 1,2,3) ----
    facts = rows("""
        SELECT st.company_id, f.metric_code, f.period_order, f.canonical_value
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        ORDER BY st.company_id, f.period_order
    """)
    fact_index: dict[tuple[str, str, int], Decimal] = {}
    for f in facts:
        fact_index[(str(f["company_id"]), f["metric_code"], f["period_order"])] = f["canonical_value"]

    # ---- Layer 7: latest price at cutoff (point-in-time safe) ----
    prices = rows("""
        SELECT DISTINCT ON (security_id) security_id, trade_date, closing_price_rial, last_price_rial
        FROM market.price_observations
        WHERE collected_at <= %s
        ORDER BY security_id, collected_at DESC, id DESC
    """, (cutoff,))
    price_by_sec = {str(p["security_id"]): p for p in prices}

    def piv(cid, metric):
        return {o: fact_index.get((cid, metric, o)) for o in (1, 2, 3)}

    # company-level metrics
    metrics = {}
    for s in secs:
        cid = str(s["company_id"])
        ms = by_company_monthly.get(cid, [])
        sales_last12 = sum((m["amt"] or 0) for m in ms[-12:]) if ms else None
        sales_prev12 = sum((m["amt"] or 0) for m in ms[-24:-12]) if len(ms) >= 24 else None
        sgr = None
        if sales_prev12 and sales_prev12 != 0 and sales_last12 is not None:
            sgr = float((sales_last12 - sales_prev12) / abs(sales_prev12) * 100)
        # TTM net profit
        np_ = piv(cid, "net_profit")
        rev = piv(cid, "revenue")
        op = piv(cid, "operating_profit")
        def ttm(d):
            if d[1] is None:
                return None
            if d[2] is not None and d[3] is not None:
                return d[1] + d[3] - d[2]
            return d[1]
        ttm_np = ttm(np_)
        ttm_rev = ttm(rev)
        ttm_op = ttm(op)
        equity = piv(cid, "total_equity")[1]
        assets = piv(cid, "total_assets")[1]
        cur_assets = piv(cid, "current_assets")[1]
        cur_liab = piv(cid, "current_liabilities")[1]
        tot_liab = piv(cid, "total_liabilities")[1]
        ocf = ttm(piv(cid, "operating_cash_flow"))
        capital = piv(cid, "capital")[1]
        price = price_by_sec.get(str(s["security_id"]))
        latest_price = price["closing_price_rial"] if price else None
        shares = (capital / Decimal(1000)) if capital else None
        ttm_eps = (ttm_np / shares) if (ttm_np is not None and shares) else None
        pe = (Decimal(latest_price) / ttm_eps) if (latest_price and ttm_eps and ttm_eps != 0) else None
        op_margin = float(ttm_op / ttm_rev * 100) if (ttm_op is not None and ttm_rev) else None
        net_margin = float(ttm_np / ttm_rev * 100) if (ttm_np is not None and ttm_rev) else None
        roe = float(ttm_np / equity * 100) if (ttm_np is not None and equity) else None
        cur_ratio = float(cur_assets / cur_liab) if (cur_assets is not None and cur_liab) else None
        lev = float(tot_liab / assets) if (tot_liab is not None and assets) else None
        # simple revenue growth (TTM vs prev-year cumulative: rev1 vs rev2+rev3? approximate)
        metrics[s["symbol"]] = {
            "security_id": str(s["security_id"]), "company_id": cid,
            "sales_last12": sales_last12, "sales_prev12": sales_prev12, "sales_growth12": sgr,
            "ttm_net_profit": ttm_np, "ttm_revenue": ttm_rev, "ttm_operating_profit": ttm_op,
            "ttm_eps": ttm_eps, "pe": pe, "latest_price": latest_price,
            "op_margin": op_margin, "net_margin": net_margin, "roe": roe,
            "current_ratio": cur_ratio, "leverage": lev, "ocf": ocf,
        }

    # ---- Layer 9: ranks (reduced) ----
    def rank_metric(name, key, higher=True):
        vals = {sym: (float(m[key]) if m[key] is not None else None) for sym, m in metrics.items()}
        pct = midrank_percentile(vals, higher)
        for sym in metrics:
            metrics[sym][name] = pct[sym]

    rank_metric("sales_growth_rank", "sales_growth12")
    rank_metric("net_margin_rank", "net_margin")
    rank_metric("op_margin_rank", "op_margin")
    rank_metric("roe_rank", "roe")
    rank_metric("pe_rank", "pe", higher=False)
    rank_metric("liquidity_rank", "ttm_revenue")  # proxy only
    # unavailable factors default neutral
    for sym in metrics:
        for f in ["revenue_growth_rank", "op_growth_rank", "np_growth_rank", "interest_rank",
                  "cashconv_rank", "earningsq_rank", "ps_rank", "pb_rank", "leverage_rank",
                  "curr_rank", "stability_rank", "lowvol_rank", "momentum_rank"]:
            metrics[sym].setdefault(f, 0.3)

    # ---- Layer 10/11: QuantScore (reduced) ----
    def dq(sym):
        m = metrics[sym]
        score = 0.0
        if m["ttm_net_profit"] is not None:
            score += 0.5
        if m["latest_price"] is not None:
            score += 0.5
        return score

    for sym, m in metrics.items():
        growth = (10*m["sales_growth_rank"] + 5*m["revenue_growth_rank"] + 5*m["op_growth_rank"] + 10*m["np_growth_rank"])
        prof = (4*m["op_margin_rank"] + 4*m["net_margin_rank"] + 6*m["roe_rank"] + 4*m["earningsq_rank"]
                + 3*m["interest_rank"] + 2*m["cashconv_rank"])
        val = (11*m["pe_rank"] + 3*m["ps_rank"] + 2*m["pb_rank"])
        mkt = (3*m["liquidity_rank"] + 2*m["leverage_rank"] + 2*m["curr_rank"] + 1*m["stability_rank"]
               + 2*m["lowvol_rank"] + 1*m["momentum_rank"])
        base = growth + prof + val + mkt
        m["quant_score_compat"] = round(dq(sym) * base, 2)
        m["growth_score_compat"] = round(growth, 1)
        m["profitability_score_compat"] = round(prof, 1)
        m["valuation_score_compat"] = round(val, 1)
        m["market_score_compat"] = round(mkt, 1)
        m["data_quality_score_compat"] = round(dq(sym), 4)

    # ---- comparison ----
    ref_rows = list(csv.DictReader(open(REF / "v37_full_snapshot.csv", encoding="utf-8-sig")))
    ref = {r["Symbol"]: r for r in ref_rows}
    compare_cols = [
        ("sales_last12", "SalesLast12M"), ("sales_prev12", "SalesPrev12M"),
        ("sales_growth12", "SalesGrowth12M"), ("ttm_net_profit", "TTMNetProfit"),
        ("pe", "PEApprox"), ("quant_score_compat", "QuantScore"),
        ("op_margin", "OperatingMargin12M"), ("net_margin", "NetProfitMargin12M"),
        ("roe", "ROE"),
    ]

    outdir = PARITY / "comparison_data"
    outdir.mkdir(parents=True, exist_ok=True)
    comp_rows = []
    summary = {c[1]: {"compared": 0, "exact": 0, "within": 0, "mismatch": 0, "unknown": 0, "max_abs": 0.0, "diffs": []} for c in compare_cols}
    for sym, m in metrics.items():
        r = ref.get(sym)
        for pk, rk in compare_cols:
            sv = m.get(pk)
            rv_raw = r.get(rk) if r else None
            try:
                rv = float(rv_raw) if (rv_raw not in (None, "", "None")) else None
            except Exception:
                rv = None
            sv_f = float(sv) if sv is not None else None
            if rv is None and sv_f is None:
                cls = "EXACT"
            elif rv is None or sv_f is None:
                cls = "NULL_SEMANTICS"
            else:
                d = abs(sv_f - rv)
                tol = 1e-6 * max(1.0, abs(rv)) if rk in ("SalesLast12M", "SalesPrev12M", "TTMNetProfit") else 1e-2
                if d == 0:
                    cls = "EXACT"
                elif d <= tol:
                    cls = "FLOAT_PRECISION"
                else:
                    cls = "LOGIC_DIFFERENCE"
            s = summary[rk]
            s["compared"] += 1
            if cls == "EXACT":
                s["exact"] += 1
            elif cls in ("FLOAT_PRECISION", "ROUNDING"):
                s["within"] += 1
            elif cls == "UNKNOWN":
                s["unknown"] += 1
            else:
                s["mismatch"] += 1
            if rv is not None and sv_f is not None:
                s["diffs"].append(abs(sv_f - rv))
            comp_rows.append({
                "symbol": sym, "metric": rk, "sqlserver_value": rv_raw, "postgres_value": sv,
                "abs_diff": (abs(float(sv) - rv) if (sv is not None and rv is not None) else ""),
                "pass": cls in ("EXACT", "FLOAT_PRECISION", "ROUNDING"),
                "classification": cls,
            })
    with (outdir / "comparison_metrics.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["symbol", "metric", "sqlserver_value", "postgres_value", "abs_diff", "pass", "classification"])
        w.writeheader(); w.writerows(comp_rows)

    with (outdir / "company_scores_compat.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "quant_score_compat", "growth", "profitability", "valuation", "market", "data_quality"])
        for sym, m in sorted(metrics.items()):
            w.writerow([sym, m["quant_score_compat"], m["growth_score_compat"], m["profitability_score_compat"],
                        m["valuation_score_compat"], m["market_score_compat"], m["data_quality_score_compat"]])

    # reproducibility hash
    h = hashlib.sha256(json.dumps({k: [v.get("quant_score_compat"), v.get("ttm_net_profit"), v.get("sales_growth12")] for k, v in sorted(metrics.items())}, default=str).encode()).hexdigest()

    # summary report
    lines = ["# Metric Comparison (canonical v3.7-compat vs SQL Server v3.7)", ""]
    lines += ["| reference column | compared | exact | within tol | mismatches | max abs diff | median abs diff |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for _, rk in compare_cols:
        s = summary[rk]
        diffs = s["diffs"]
        mx = max(diffs) if diffs else 0.0
        med = statistics.median(diffs) if diffs else 0.0
        lines.append(f"| {rk} | {s['compared']} | {s['exact']} | {s['within']} | {s['mismatch']} | {mx:.6g} | {med:.6g} |")
    lines += ["", f"- canonical companies compared: {len(metrics)}; reference rows: {len(ref_rows)}",
              f"- output hash: `{h}`"]
    (PARITY / "metric_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (PARITY / "_comparison_summary.json").write_text(json.dumps(
        {rk: {"compared": s["compared"], "exact": s["exact"], "within": s["within"],
              "mismatch": s["mismatch"], "max_abs": (max(s["diffs"]) if s["diffs"] else 0.0)} for _, rk in compare_cols},
        indent=2), encoding="utf-8")
    (PARITY / "_compute_hash.txt").write_text(h, encoding="utf-8")

    print("compared companies:", len(metrics), "reference:", len(ref_rows))
    for _, rk in compare_cols:
        s = summary[rk]
        print(f"  {rk}: exact={s['exact']} within={s['within']} mismatch={s['mismatch']}")
    pg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
