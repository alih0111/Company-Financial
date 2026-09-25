"""Phase-2 real-script dual-write driver.

Exercises the *actual* legacy script functions (brs_prices.resolve_matched_symbols,
build_daily_row, upsert_rows) plus the post-commit canonical hook, against the
live SQL Server and the designated shadow PostgreSQL. Monthly/financial scraper
bodies require a browser, so their wired hook functions are invoked with real
legacy keys (the same functions the scripts call after commit).

Set CDF_INGESTION_MODE=dual_write and CDF_CANONICAL_DB=<shadow db>.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
import time
from decimal import Decimal
from datetime import datetime, timedelta, timezone

GO_APP = pathlib.Path(r"D:\RFA\Company-Financial\go-app")
PY = GO_APP / "py"
PY2_SRC = GO_APP / "py2" / "src"
OUT = GO_APP.parent / "ingestion_migration_v1" / "output"
sys.path.insert(0, str(PY))
sys.path.insert(0, str(PY2_SRC))
os.chdir(GO_APP)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(GO_APP / ".env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")

import canonical_hook  # noqa: E402
from canonical_ingest import reconcile as R  # noqa: E402
from canonical_ingest.db import transaction  # noqa: E402

MARKET_TARGETS = ["کیمیا", "غاذر", "سباقر", "دقاضی"]
MONTHLY_TARGETS = [("b88121029d7e973410b008320f8fe378", "قاسم")]
FINANCIAL_TARGETS = [("6dd3fb203bb12fdd017e1f59fc61b9c6", "تاصیکو"), ("7e41b7fd7ba1c353199eba22667db254", "کسرا")]


def _ss():
    import pyodbc
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};"
          f"DATABASE={os.environ['DB_NAME']};UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
          f"TrustServerCertificate=yes;Connection Timeout=10")
    return pyodbc.connect(cs, timeout=15)


def _rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def market_batch(label: str):
    import brs_prices as bp
    matched, _unmatched = bp.resolve_matched_symbols("MarketPriceHistory")
    subset = [m for m in matched if m.get("symbol") in MARKET_TARGETS][: len(MARKET_TARGETS)]
    rows = [bp.build_daily_row(m["raw"], m["company_id"], m["company_name"], m.get("brs_name")) for m in subset]
    valid = [r for r in rows if r.get("gregorian_date")]
    conn = bp.get_db_connection()
    cur = conn.cursor()
    try:
        bp.ensure_price_history_table(cur, "MarketPriceHistory")
        bp.upsert_rows(cur, valid, "MarketPriceHistory")
        conn.commit()
    finally:
        cur.close()
        conn.close()
    result = canonical_hook.dual_write_market_rows(valid, table_name="MarketPriceHistory")
    return {"label": label, "symbols": [m.get("symbol") for m in subset], "legacy_rows": len(valid),
            "result": result, "rows": valid}


def _latest_period(company_id, table):
    conn = _ss()
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT MAX(ReportDate) FROM dbo.{table} WHERE CompanyID=?", (company_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def monthly_batch(company_id, name):
    period = _latest_period(company_id, "mahane")
    if not period:
        return {"status": "no_legacy_row"}
    conn = _ss()
    try:
        cur = conn.cursor()
        rec = _rows(cur, "SELECT Value1, Value2, Value3 FROM dbo.mahane WHERE CompanyID=? AND ReportDate=?",
                    (company_id, period))[0]
    finally:
        conn.close()
    res = canonical_hook.dual_write_monthly_values(company_id, name, period,
                                                   [rec["Value1"], rec["Value2"], rec["Value3"]])
    return {"status": res.get("status"), "period": period, "legacy": rec, "result": res}


def financial_batch(company_id, name):
    period = _latest_period(company_id, "miandore2")
    if not period:
        return {"status": "no_legacy_row"}
    res = canonical_hook.dual_write_financial_by_key(company_id, name, period)
    return {"status": res.get("status"), "period": period, "result": res}


def reconcile_market(rows):
    from canonical_hook import _gregorian  # jalali->greg
    out = []
    with transaction() as conn:
        cur = conn.cursor()
        for r in rows:
            cid = r.get("company_id")
            cur.execute(
                """SELECT po.trade_date::text, po.closing_price_rial, po.volume
                   FROM market.price_observations po
                   JOIN core.legacy_entity_map lem
                     ON lem.entity_type='security' AND lem.target_uuid=po.security_id AND lem.legacy_key=%s
                   WHERE po.trade_date=%s AND po.source='brs'
                   ORDER BY po.collected_at DESC LIMIT 1""",
                (str(cid), r["gregorian_date"]))
            row = cur.fetchone()
            canon = None if not row else {"trade_date": row[0], "closing_price_rial": row[1], "volume": row[2]}
            legacy = {"trade_date": r["gregorian_date"], "closing_price_rial": r.get("closing_price"),
                      "volume": r.get("volume")}
            out.append({"domain": "market_price", "company_id": cid, "trade_date": r["gregorian_date"],
                        "classification": R.reconcile_market(legacy, canon)})
    return out


def reconcile_monthly(company_id, period, legacy):
    g = canonical_hook._gregorian(period)
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT ma.production_quantity, ma.sales_quantity, ma.reported_sales_amount, ma.sales_amount_rial
               FROM fundamentals.monthly_activities ma
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=ma.company_id AND lem.legacy_key=%s
               WHERE ma.period_end_date=%s ORDER BY ma.created_at DESC LIMIT 1""", (str(company_id), g))
        row = cur.fetchone()
    canon = None if not row else {"production_quantity": row[0], "sales_quantity": row[1],
                                  "reported_sales_amount": row[2], "sales_amount_rial": row[3]}
    lg = {"production_quantity": legacy.get("Value1"), "sales_quantity": legacy.get("Value2"),
          "reported_sales_amount": legacy.get("Value3")}
    return R.reconcile_monthly(lg, canon)


def reconcile_financial(company_id, period):
    g = canonical_hook._gregorian(period)
    conn = _ss()
    try:
        cur = conn.cursor()
        rows = _rows(cur, "SELECT * FROM dbo.miandore2 WHERE CompanyID=? AND ReportDate=?", (company_id, period))
    finally:
        conn.close()
    if not rows:
        return []
    data = rows[0]
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT f.metric_code, f.period_order, f.reported_value, f.canonical_value
               FROM fundamentals.financial_facts f
               JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=fs.company_id AND lem.legacy_key=%s
               WHERE fs.period_end_date=%s""", (str(company_id), g))
        cmap = {(r[1], r[0]): {"metric_code": r[0], "reported_value": r[2], "canonical_value": r[3]}
                for r in cur.fetchall()}
    out = []
    for stype, mcode, order, col, kind, comp in canonical_hook._FACT_MAP:
        if col not in data or data[col] is None:
            continue
        reported = Decimal(str(data[col]))
        legacy = {"metric_code": mcode, "reported_value": reported, "kind": kind}
        out.append({"domain": "financial_fact", "company_id": company_id, "period": period,
                    "metric": f"{mcode}:{order}",
                    "classification": R.reconcile_fact(legacy, cmap.get((order, mcode)))})
    return out


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader()
        w.writerows(rows)


def main():
    started = datetime.now(timezone.utc).isoformat()
    print("mode=", canonical_hook.ingestion_mode())
    OUT.mkdir(parents=True, exist_ok=True)

    batches = []
    recon = []
    idem = {}

    # ---- market (real BRS) ----
    m1 = market_batch("market_run1")
    m2 = market_batch("market_run2")
    idem["market"] = {"run1": m1["result"], "run2": m2["result"]}
    batches.append({"domain": "market_price", "batch": "run1",
                    "legacy_rows": m1["legacy_rows"], "canonical": m1["result"]})
    batches.append({"domain": "market_price", "batch": "run2",
                    "legacy_rows": m2["legacy_rows"], "canonical": m2["result"]})
    recon.extend(reconcile_market(m1["rows"]))

    # ---- monthly (real hook function with real legacy keys) ----
    for cid, name in MONTHLY_TARGETS:
        r1 = monthly_batch(cid, name)
        r2 = monthly_batch(cid, name)
        idem[f"monthly:{name}"] = {"run1": r1["result"], "run2": r2["result"]}
        batches.append({"domain": "monthly_activity", "batch": f"{name}:run1",
                        "legacy_rows": 1, "canonical": r1["result"]})
        batches.append({"domain": "monthly_activity", "batch": f"{name}:run2",
                        "legacy_rows": 1, "canonical": r2["result"]})
        if r1.get("status") == "written":
            recon.append({"domain": "monthly_activity", "company_id": cid, "period": r1["period"],
                          "classification": reconcile_monthly(cid, r1["period"], r1["legacy"])})

    # ---- financial (real hook function with real legacy keys) ----
    for cid, name in FINANCIAL_TARGETS:
        r1 = financial_batch(cid, name)
        r2 = financial_batch(cid, name)
        idem[f"financial:{name}"] = {"run1": r1["result"], "run2": r2["result"]}
        batches.append({"domain": "financial_statement", "batch": f"{name}:run1",
                        "legacy_rows": r1.get("result", {}).get("facts", 0), "canonical": r1["result"]})
        batches.append({"domain": "financial_statement", "batch": f"{name}:run2",
                        "legacy_rows": r2.get("result", {}).get("facts", 0), "canonical": r2["result"]})
        if r1.get("status") == "written":
            recon.extend(reconcile_financial(cid, r1["period"]))

    write_csv(OUT / "phase2_real_batches.csv", [
        {"domain": b["domain"], "batch": b["batch"], "legacy_rows": b["legacy_rows"],
         "canonical_status": b["canonical"].get("status"),
         "inserted": b["canonical"].get("inserted"), "skipped": b["canonical"].get("skipped"),
         "error": b["canonical"].get("error", "")} for b in batches])
    write_csv(OUT / "phase2_reconciliation.csv", recon)

    from collections import Counter
    recon_counts = dict(Counter(r["classification"] for r in recon))
    summary = {
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "mode": canonical_hook.ingestion_mode(),
        "market": m1["result"],
        "monthly": {f"{n}": {k: v for k, v in idem[f"monthly:{n}"].items()} for _, n in MONTHLY_TARGETS},
        "financial": {f"{n}": {k: v for k, v in idem[f"financial:{n}"].items()} for _, n in FINANCIAL_TARGETS},
        "reconciliation": recon_counts,
    }
    (OUT / "phase2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "phase2_idempotency.json").write_text(json.dumps(idem, ensure_ascii=False, indent=2), encoding="utf-8")
    print("summary:", json.dumps(recon_counts, ensure_ascii=False))
    print("market:", json.dumps(m1["result"], ensure_ascii=False))


if __name__ == "__main__":
    main()
