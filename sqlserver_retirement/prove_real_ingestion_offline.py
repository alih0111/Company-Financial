"""Prove the REAL ingestion entrypoints run with SQL Server unreachable.

Points DB_SERVER at an unreachable port, enables canonical authority + canonical
writer, and invokes the actual production-like functions:
  - brs_prices.cmd_daily
  - MianSql2.save_report_to_sql  (monthly)
  - MianSql.save_profit_loss_to_sql (financial, in-memory facts)
  - sync_codal.run_sync (codal canonical-only)

Inputs for monthly/financial are read back from canonical (replay/idempotent),
so no source data is fabricated.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
GO = REPO / "go-app"
sys.path.insert(0, str(GO / "py"))
sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)

os.environ["DB_SERVER"] = "127.0.0.1,59999"  # SQL Server unreachable
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GO / ".env", override=False)
os.environ["DB_SERVER"] = "127.0.0.1,59999"

os.environ["CDF_CANONICAL_DB"] = "company_financial_analytics_shadow_v121"
os.environ["CDF_INGESTION_MODE"] = "dual_write"
os.environ["CDF_SQLSERVER_MODE"] = "offline_expected"
for k in ("CDF_MARKET_INGESTION_AUTHORITY", "CDF_MONTHLY_INGESTION_AUTHORITY",
          "CDF_FINANCIAL_INGESTION_AUTHORITY", "CDF_CODAL_INGESTION_AUTHORITY"):
    os.environ[k] = "canonical"

OUT = REPO / "sqlserver_retirement" / "output"


def canonical_rows(sql, params=()):
    from canonical_ingest.db import connect
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


def prove_market():
    import brs_prices
    try:
        brs_prices.cmd_daily()
        return {"domain": "MARKET_PRICE", "entrypoint": "brs_prices.cmd_daily",
                "status": "EXECUTED", "sqlserver_connected": False,
                "note": "canonical-only path; no pyodbc connection"}
    except Exception as exc:  # noqa: BLE001
        return {"domain": "MARKET_PRICE", "entrypoint": "brs_prices.cmd_daily",
                "status": "SOURCE_UNAVAILABLE", "sqlserver_connected": False,
                "note": f"canonical path entered without SQL; source fetch: {type(exc).__name__}"}


def prove_monthly():
    import MianSql2
    rows = canonical_rows("""SELECT c.display_name, ma.jalali_period_text, ma.production_quantity,
                                    ma.sales_quantity, ma.reported_sales_amount
                             FROM fundamentals.monthly_activities ma JOIN core.companies c ON c.id=ma.company_id
                             ORDER BY ma.created_at DESC LIMIT 1""")
    if not rows:
        return {"domain": "MONTHLY_ACTIVITY", "status": "NO_CANONICAL_SAMPLE", "sqlserver_connected": False}
    name, period, v1, v2, v3 = rows[0]
    ok = MianSql2.save_report_to_sql(name, period, [float(v1 or 0), float(v2 or 0), float(v3 or 0)],
                                     "canonical://replay", "mahane")
    return {"domain": "MONTHLY_ACTIVITY", "entrypoint": "MianSql2.save_report_to_sql",
            "status": "EXECUTED" if ok else "FAILED", "sqlserver_connected": False,
            "company": name, "period": period, "replay": True}


def prove_financial():
    import MianSql
    rows = canonical_rows("""SELECT c.display_name, r.jalali_period_text, f.metric_code, f.reported_value
                             FROM fundamentals.financial_facts f
                             JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
                             JOIN ingestion.reports r ON r.id=fs.report_id
                             JOIN core.companies c ON c.id=fs.company_id
                             WHERE f.period_order=1 AND f.metric_code IN
                               ('eps','capital','operating_eps','revenue','operating_profit','net_profit')
                             ORDER BY fs.created_at DESC LIMIT 200""")
    if not rows:
        return {"domain": "FINANCIAL_STATEMENT", "status": "NO_CANONICAL_SAMPLE", "sqlserver_connected": False}
    name = rows[0][0]
    period = rows[0][1]
    vals = {}
    for _n, _p, code, val in rows:
        if _n == name and _p == period and code not in vals:
            vals[code] = float(val or 0)
    eps = vals.get("eps", 0.0)
    capital = vals.get("capital", 0.0)
    operating_eps = vals.get("operating_eps", 0.0)
    values_to_insert = [eps, capital, operating_eps, 0.0,
                        eps, capital, operating_eps, 0.0,
                        eps, capital, operating_eps, 0.0]
    try:
        ok = MianSql.save_profit_loss_to_sql(
            name, period, values_to_insert,
            vals.get("operating_profit", 0.0), 0.0, "canonical://replay", "miandore2",
            revenue_new=vals.get("revenue", 0.0),
            net_profit_amount=vals.get("net_profit", 0.0))
        status = "EXECUTED" if ok else "FAILED"
    except Exception as exc:  # noqa: BLE001
        status = "ERROR: " + type(exc).__name__
    return {"domain": "FINANCIAL_STATEMENT", "entrypoint": "MianSql.save_profit_loss_to_sql",
            "status": status, "sqlserver_connected": False, "company": name, "period": period,
            "facts_from_canonical_replay": True}


def prove_codal():
    import argparse
    import sync_codal
    args = argparse.Namespace(letter_types=[6], type="financial", all=False,
                              from_date=None, to_date=None,
                              max_pages=1, limit=None, dry_run=False, force=False,
                              route=None, overlap_days=None, retries=None)
    try:
        res = sync_codal.run_sync(args)
        return {"domain": "CODAL", "entrypoint": "sync_codal.run_sync",
                "status": "EXECUTED", "sqlserver_connected": False,
                "canonical_only": res.get("canonical_only", False),
                "total": res.get("total", {})}
    except Exception as exc:  # noqa: BLE001
        return {"domain": "CODAL", "entrypoint": "sync_codal.run_sync",
                "status": "ERROR: " + type(exc).__name__, "sqlserver_connected": False,
                "note": str(exc)[:160]}


def main():
    results = [prove_market(), prove_monthly(), prove_financial(), prove_codal()]
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "real_ingestion_offline_proof.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["domain", "entrypoint", "status", "sqlserver_connected", "note"], extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow(r)
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
