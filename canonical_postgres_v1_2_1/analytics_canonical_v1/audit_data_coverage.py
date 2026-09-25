"""READ-ONLY canonical data coverage audit.

Audit tooling only (not the analytics runtime). SQL Server is SELECT-only.
Writes artifacts under analytics_canonical_v1/data_work/.

Do NOT use Product1 as a substitute for missing financial facts.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn, sqlserver_conn  # noqa: E402

DW = HERE / "data_work"
DW.mkdir(parents=True, exist_ok=True)

# canonical metric -> legacy source column (audit provenance only)
SRC_COL = {
    "revenue": "RevenueNew", "net_profit": "NetProfitAmount",
    "operating_profit": "OperatingProfitNew", "eps": "Num1_Value1",
    "capital": "Num2_Value1", "total_assets": "TotalAssets",
    "current_assets": "CurrentAssets", "total_liabilities": "TotalLiabilities",
    "current_liabilities": "CurrentLiabilities", "total_equity": "TotalEquity",
    "operating_cash_flow": "OperatingCashFlow", "finance_cost": "FinanceCostsNew",
    "other_non_operating": "OtherNonOpNew",
}
REQUIRED = ["revenue", "net_profit", "operating_profit", "eps", "capital",
            "total_assets", "current_assets", "total_liabilities",
            "current_liabilities", "total_equity", "operating_cash_flow",
            "finance_cost", "other_non_operating"]
TTM_METRICS = {"revenue", "net_profit", "operating_profit", "eps", "operating_cash_flow"}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pg = pg_pilot_conn(autocommit=True)
    pc = pg.cursor()

    def pq(sql, p=()):
        pc.execute(sql, p)
        return pc.fetchall()

    oracle = json.loads((BASE / "analytics_v37_oracle/golden_output.json").read_text(encoding="utf-8"))
    subjects = {s["legacy_company_id"]: s for s in
                csv.DictReader(open(BASE / "analytics_parity_debug/v37_scoring_subjects.csv", encoding="utf-8-sig"))}
    canon_metrics = json.loads((HERE / "output/canonical_v1_metrics.json").read_text(encoding="utf-8"))
    oracle_ids = set(oracle.keys())

    c2l, l2c = {}, {}
    for t, k in pq("SELECT target_uuid::text, legacy_key FROM core.legacy_entity_map WHERE entity_type='company'"):
        c2l.setdefault(t, set()).add(k)
        l2c.setdefault(k, set()).add(t)

    # ---------- population reconciliation ----------
    matched = set()
    for cid in canon_metrics:
        matched |= (c2l.get(cid, set()) & oracle_ids)
    oracle_only = sorted(oracle_ids - matched)
    outside = sorted({k for cid in canon_metrics for k in c2l.get(cid, set())} - oracle_ids)

    company_info = {r[0]: r[1] for r in pq("SELECT id::text, display_name FROM core.companies")}
    monthly_counts = {r[0]: r[1] for r in pq(
        "SELECT company_id::text, count(*) FROM fundamentals.monthly_activities GROUP BY company_id")}
    income_companies = {r[0] for r in pq(
        "SELECT DISTINCT company_id::text FROM fundamentals.financial_statements WHERE statement_type='income_statement'")}

    pop_rows = []
    for oid in oracle_only:
        s = subjects.get(oid, {})
        ccid = s.get("canonical_company_id") or ""
        mc = monthly_counts.get(ccid, 0) if ccid else 0
        has_income = ccid in income_companies if ccid else False
        if not ccid:
            reason = ("legacy fundamentals but no canonical market-history coverage under the "
                      "current migration universe; remediation intentionally deferred")
            cls = "ACCEPTED_CANONICAL_SCOPE_EXCLUSION"
            verdict = "accepted out-of-scope (not required for canonical v1)"
            rem = "NONE"
        elif not has_income and mc < 6:
            reason = f"canonical company eligible-policy excluded (no income_statement, monthly={mc} < 6)"
            cls = "POLICY_EXCLUSION"
            verdict = "expected policy"
            rem = "E"
        else:
            reason = "unexplained"
            cls = "OTHER_EXPLAINED"
            verdict = "investigate"
            rem = "OTHER"
        pop_rows.append({
            "legacy_scoring_subject_id": f"legacy:{oid}",
            "legacy_company_id": oid,
            "symbol": s.get("symbol") or "",
            "company_name": s.get("company_name") or "",
            "canonical_company_id": ccid,
            "canonical_security_id": s.get("canonical_security_id") or "",
            "has_market_price": s.get("has_market_price"),
            "subject_origin": s.get("subject_origin"),
            "reason_excluded_missing": reason,
            "classification": cls,
            "expected_policy_or_defect": verdict,
            "remediation_class": rem,
        })
    with (DW / "population_reconciliation.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pop_rows[0].keys()))
        w.writeheader(); w.writerows(pop_rows)

    # ---------- canonical fact coverage per company/metric ----------
    facts = pq("""
        SELECT st.company_id::text, st.statement_type, st.period_end_date, f.metric_code,
               f.period_order, f.canonical_value, f.canonical_unit
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id""")
    by_company = {}
    rep_orders = {}  # company -> (fy,fm) -> metric -> set(orders)
    import jdatetime as _jd
    def ym(ped):
        j = _jd.date.fromgregorian(date=ped)
        return (j.year, j.month)
    for cid, stype, ped, mc, po, val, unit in facts:
        by_company.setdefault(cid, {}).setdefault(mc, []).append((ped, po, val, stype, unit))
        if stype == "income_statement":
            rep_orders.setdefault(cid, {}).setdefault(ym(ped), {}).setdefault(mc, set()).add(po)

    # source availability per company per metric (SQL Server SELECT-only)
    sc = sqlserver_conn().cursor()
    src_avail = {}  # metric -> set(company_id)
    src_rows = {}   # metric -> company -> count
    for mc, col in SRC_COL.items():
        sc.execute(f"SELECT DISTINCT CompanyID FROM dbo.miandore2 WHERE [{col}] IS NOT NULL")
        ids = {r[0] for r in sc.fetchall()}
        src_avail[mc] = ids
        for cid in ids:
            for cc in l2c.get(cid, ()):
                src_rows.setdefault(mc, {}).setdefault(cc, 0)
                src_rows[mc][cc] += 1
    ss_close = sc.connection
    ss_close.close()

    import jdatetime
    def jmonth(d):
        return jdatetime.date.fromgregorian(date=d).month

    coverage_rows = []
    metric_agg = {mc: {"eligible": len(canon_metrics), "source": 0, "insufficient": 0,
                       "no_fact": 0, "missing": 0, "latest": None} for mc in REQUIRED}
    reason_agg = {}
    for cid, m in canon_metrics.items():
        symbol = m.get("symbol") or ""
        for mc in REQUIRED:
            entries = by_company.get(cid, {}).get(mc, [])
            periods = sorted({e[0] for e in entries})
            n = len(periods)
            latest = periods[-1].isoformat() if periods else ""
            src = src_rows.get(mc, {}).get(cid, 0)
            # TTM eligibility from the latest report of this metric
            ttm_ok, required = None, 1
            if mc in TTM_METRICS:
                required = 3
                if entries:
                    latest_ped = periods[-1]
                    orders = {po for (ped, po, *_ ) in entries if ped == latest_ped}
                    if 1 in orders:
                        ttm_ok = (jmonth(latest_ped) == 12) or (2 in orders and 3 in orders)
                    else:
                        ttm_ok = False
                else:
                    ttm_ok = False
            # report-chain recoverability (legitimate canonical derivation)
            chain_ok = False
            if mc in TTM_METRICS and periods:
                rep = rep_orders.get(cid, {})
                ly, lm = ym(periods[-1])
                prev = rep.get((ly - 1, lm), {})
                prevfy = rep.get((ly - 1, 12), {})
                if mc in prev and 1 in prev[mc] and mc in prevfy and 1 in prevfy[mc]:
                    chain_ok = True
            # missing reason
            if not entries:
                if src == 0:
                    reason = "SOURCE_ABSENT"
                else:
                    reason = "MIGRATION_NOT_IMPORTED"
                metric_agg[mc]["no_fact"] += 1
            elif mc in TTM_METRICS and not ttm_ok:
                reason = "TTM_RECOVERABLE_REPORT_CHAIN" if chain_ok else "INSUFFICIENT_TTM_PERIODS"
                metric_agg[mc]["insufficient"] += 1
            else:
                reason = ""
            if reason:
                metric_agg[mc]["missing"] += 1
                reason_agg[reason] = reason_agg.get(reason, 0) + 1
            if src > 0:
                metric_agg[mc]["source"] += 1
            if latest and (metric_agg[mc]["latest"] is None or latest > metric_agg[mc]["latest"]):
                metric_agg[mc]["latest"] = latest
            if reason in ("SOURCE_ABSENT",):
                rem = "D"
            elif reason == "MIGRATION_NOT_IMPORTED":
                rem = "A"
            elif reason == "TTM_RECOVERABLE_REPORT_CHAIN":
                rem = "B"
            elif reason == "INSUFFICIENT_TTM_PERIODS":
                rem = "C"
            elif reason == "":
                rem = ""
            else:
                rem = "OTHER"
            coverage_rows.append({
                "company_id": cid, "symbol": symbol, "required_fact": mc,
                "period_count": n, "required_period_count": required,
                "latest_period": latest, "ttm_eligible": ttm_ok,
                "pit_eligible": True,
                "missing_reason": reason or "PRESENT",
                "source_availability": src,
                "source_column": SRC_COL.get(mc, ""),
                "remediation_class": rem,
            })
    with (DW / "company_fact_coverage.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(coverage_rows[0].keys()))
        w.writeheader(); w.writerows(coverage_rows)

    with (DW / "metric_coverage.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["metric_code", "eligible_companies", "companies_with_source_data",
                    "companies_insufficient_periods", "companies_no_canonical_fact",
                    "missing_pct", "latest_available_period", "source_column"])
        for mc in REQUIRED:
            a = metric_agg[mc]
            miss_pct = round(a["missing"] / a["eligible"] * 100, 1)
            w.writerow([mc, a["eligible"], a["source"], a["insufficient"], a["no_fact"],
                        miss_pct, a["latest"], SRC_COL.get(mc, "")])

    with (DW / "missing_reason_summary.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["missing_reason", "count"])
        for k in sorted(reason_agg):
            w.writerow([k, reason_agg[k]])

    # ---------- console summary ----------
    print("oracle", len(oracle_ids), "canonical", len(canon_metrics),
          "matched", len(matched), "oracle_only", len(oracle_only), "outside", len(outside))
    print("population_reconciliation classifications:")
    from collections import Counter
    print("  ", dict(Counter(r["classification"] for r in pop_rows)))
    print("metric coverage:")
    for mc in REQUIRED:
        a = metric_agg[mc]
        print(f"  {mc:22s} source={a['source']:3d} no_fact={a['no_fact']:3d} "
              f"insufficient_ttm={a['insufficient']:3d} missing={a['missing']:3d} "
              f"({round(a['missing']/a['eligible']*100,1)}%)")
    print("missing reasons:", dict(sorted(reason_agg.items())))
    pg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
