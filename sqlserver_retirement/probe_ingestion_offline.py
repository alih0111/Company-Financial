"""Probe canonical ingestion with SQL Server unreachable.

Points DB_SERVER at an unreachable port (process env) and exercises the real
canonical_hook authoritative entrypoints. Demonstrates which domains continue
canonically and which are runtime-coupled to SQL Server.

Read-only w.r.t. SQL Server (never connects successfully). Writes only to the
canonical shadow DB through the approved canonical writer.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
GO = REPO / "go-app"
sys.path.insert(0, str(GO / "py"))
sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)

# SQL Server unreachable (set before importing canonical_hook).
os.environ["DB_SERVER"] = "127.0.0.1,59999"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(GO / ".env", override=False)
os.environ["DB_SERVER"] = "127.0.0.1,59999"  # keep the override

os.environ["CDF_CANONICAL_DB"] = "company_financial_analytics_shadow_v121"
os.environ["CDF_INGESTION_MODE"] = "dual_write"
os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"
os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"

import canonical_hook  # noqa: E402

OUT = REPO / "sqlserver_retirement" / "output"

CID = "b88121029d7e973410b008320f8fe378"  # قاسم (mapped)
NAME = "قاسم"


def mirror_raises():
    raise RuntimeError("injected: SQL Server offline (mirror unavailable)")


def probe():
    results = {}

    # 1) Real script DB connection.
    try:
        canonical_hook._sqlserver_conn()
        results["script_sqlserver_conn"] = {"ok": True, "note": "connected (unexpected)"}
    except Exception as exc:  # noqa: BLE001
        results["script_sqlserver_conn"] = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)[:160]}

    # 2) MARKET canonical-authoritative with mirror failing.
    rows = [{
        "company_id": CID, "symbol": NAME, "company_name": NAME,
        "gregorian_date": "2026-09-25", "jalali_date": "1405/07/03",
        "closing_price": 1000, "last_price": 1000, "volume": 1, "trade_value": 1000,
    }]
    try:
        r = canonical_hook.ingest_market_authoritative(rows, legacy_writer=mirror_raises)
        results["market"] = {"outcome": r.get("outcome"), "canonical_status": r.get("status"),
                             "inserted": r.get("inserted"), "skipped": r.get("skipped"),
                             "mirror": r.get("legacy_mirror_status")}
    except Exception as exc:  # noqa: BLE001
        results["market"] = {"error": str(exc)[:200]}

    # 3) MONTHLY canonical-authoritative with mirror failing.
    try:
        r = canonical_hook.ingest_monthly_authoritative(
            CID, NAME, "1405/06/31", [100, 90, 5000000], legacy_writer=mirror_raises)
        results["monthly"] = {"outcome": r.get("outcome"), "canonical_status": r.get("status"),
                              "inserted": r.get("inserted"), "skipped": r.get("skipped"),
                              "mirror": r.get("legacy_mirror_status")}
    except Exception as exc:  # noqa: BLE001
        results["monthly"] = {"error": str(exc)[:200]}

    # 4a) FINANCIAL legacy-fallback path (would read facts from SQL Server).
    try:
        r = canonical_hook.ingest_financial_authoritative_by_key(
            CID, NAME, "1405/05/31", legacy_writer=mirror_raises)
        results["financial_legacy_fallback"] = {"outcome": r.get("outcome"), "canonical_status": r.get("status"),
                                                "facts": r.get("facts"), "error": str(r.get("error", ""))[:160]}
    except Exception as exc:  # noqa: BLE001
        results["financial_legacy_fallback"] = {"error": str(exc)[:200]}

    # 4b) FINANCIAL canonical path with normalized in-memory facts (SQL-free).
    from decimal import Decimal
    facts = [
        {"statement_type": "income_statement", "metric_code": "net_profit", "period_order": 1,
         "comparison_type": "current", "reported_value": Decimal("1234567"), "reported_unit": "million_rial",
         "canonical_value": Decimal("1234567") * Decimal(1000000), "canonical_unit": "rial",
         "kind": "m", "source_row_key": "income_statement:net_profit:1"},
        {"statement_type": "income_statement", "metric_code": "eps", "period_order": 1,
         "comparison_type": "current", "reported_value": Decimal("255"), "reported_unit": "rial_per_share",
         "canonical_value": Decimal("255"), "canonical_unit": "rial_per_share",
         "kind": "ps", "source_row_key": "income_statement:eps:1"},
    ]
    try:
        r = canonical_hook.ingest_financial_authoritative_by_key(
            CID, NAME, "1405/05/31", legacy_writer=mirror_raises, facts=facts)
        results["financial_in_memory_facts"] = {"outcome": r.get("outcome"), "canonical_status": r.get("status"),
                                                "facts": r.get("facts"), "inserted": r.get("inserted"),
                                                "skipped": r.get("skipped"),
                                                "mirror": "failed (injected)" if r.get("outcome") == "CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED" else r.get("outcome")}
    except Exception as exc:  # noqa: BLE001
        results["financial_in_memory_facts"] = {"error": str(exc)[:200]}

    # 5) CODAL canonical-authoritative (identity resolution, no SQL read needed).
    try:
        letter = {"TracingNo": 999999999, "Symbol": "قاسم", "CompanyName": NAME}
        r = canonical_hook.ingest_codal_authoritative(letter, fetch_body=False)
        results["codal"] = {"outcome": r.get("outcome"), "status": r.get("status")}
    except Exception as exc:  # noqa: BLE001
        results["codal"] = {"error": str(exc)[:200]}

    return results


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    res = probe()
    (OUT / "ingestion_offline_probe.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
