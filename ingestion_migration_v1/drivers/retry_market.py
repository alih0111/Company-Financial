"""Replay pending MARKET_PRICE canonical retries from the retry manifest.

Reads output/canonical_retry_manifest.jsonl, re-writes canonical-only for the
recorded companies (re-reading legacy rows), marks entries done, and refreshes
the market authority freshness artifact. Does not touch SQL Server writes.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from decimal import Decimal

GO = pathlib.Path(r"D:\RFA\Company-Financial\go-app")
sys.path.insert(0, str(GO / "py")); sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GO / ".env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")

import canonical_hook  # noqa: E402
from canonical_ingest.db import transaction  # noqa: E402

OUT = GO.parent / "ingestion_migration_v1" / "output"
MANIFEST = OUT / "canonical_retry_manifest.jsonl"


def ss():
    import pyodbc
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};"
          f"DATABASE={os.environ['DB_NAME']};UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
          f"TrustServerCertificate=yes;Connection Timeout=10")
    return pyodbc.connect(cs, timeout=15)


def market_rows_for(company_id):
    conn = ss(); cur = conn.cursor()
    try:
        cur.execute(
            "SELECT TOP 30 CompanyID, Symbol, CompanyName, CONVERT(NVARCHAR(20),GregorianDate,23) gd, JalaliDate, "
            "ISNULL(HighPrice,0) hp, ISNULL(LowPrice,0) lp, ISNULL(ClosingPrice,0) cp, ISNULL(LastPrice,0) lastp, "
            "ISNULL(FirstPrice,0) fp, ISNULL(YesterdayPrice,0) yp, ISNULL(ClosingChange,0) cc, "
            "ISNULL(ClosingChangePercent,0) ccp, ISNULL(Volume,0) vol, ISNULL(TradeValue,0) tv, ISNULL(TradeCount,0) tc "
            "FROM dbo.MarketPriceHistory WHERE CompanyID=? ORDER BY GregorianDate DESC", (company_id,))
        cols = [c[0] for c in cur.description]
        data = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close(); conn.close()
    return [{"company_id": r["CompanyID"], "symbol": r["Symbol"], "gregorian_date": r["gd"],
             "jalali_date": r["JalaliDate"], "high_price": r["hp"], "low_price": r["lp"],
             "closing_price": r["cp"], "last_price": r["lastp"], "first_price": r["fp"],
             "yesterday_price": r["yp"], "closing_change": r["cc"], "closing_change_percent": r["ccp"],
             "volume": r["vol"], "trade_value": r["tv"], "trade_count": r["tc"]} for r in data]


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(collected_at)::text, max(trade_date)::text, count(*) FROM market.price_observations")
        c = cur.fetchone()
    ss_ = ss(); cur = ss_.cursor()
    try:
        cur.execute("SELECT max(CollectedAt), max(GregorianDate) FROM dbo.MarketPriceHistory")
        l = cur.fetchone()
    finally:
        cur.close(); ss_.close()
    backlog = canonical_hook.retry_backlog_count("market_price")
    return {"domain": "MARKET_PRICE", "authority": "CANONICAL",
            "latest_source_collection_time": str(l[0]), "latest_source_trade_date": str(l[1]),
            "latest_canonical_observation_time": c[0], "latest_canonical_trade_date": c[1],
            "canonical_rows": c[2], "retry_backlog": backlog,
            "health": "HEALTHY" if backlog == 0 else "CANONICAL_BEHIND",
            "generated_at": datetime.now(timezone.utc).isoformat()}


def main():
    entries = []
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("domain") == "market_price" and e.get("status") == "pending":
                entries.append(e)
    replayed = inserted = 0
    with MANIFEST.open("a", encoding="utf-8") as fh:
        for e in entries:
            for cid in e.get("keys", {}).get("companies", []):
                rows = market_rows_for(cid)
                if rows:
                    res = canonical_hook._canonical_market_write(rows, "brs", "MarketPriceHistory")
                    inserted += res.get("inserted", 0)
            replayed += 1
            fh.write(json.dumps({"status": "done", "domain": "market_price", "keys": e.get("keys"),
                                 "replayed_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
    fresh = freshness()
    (OUT / "market_authority_freshness.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"replayed_entries": replayed, "canonical_inserted": inserted,
                      "retry_backlog": fresh["retry_backlog"], "health": fresh["health"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
