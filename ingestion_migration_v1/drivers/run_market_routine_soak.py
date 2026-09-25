"""Part A: routine MARKET_PRICE canonical-primary soak (real BRS, clean state)."""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone

GO = pathlib.Path(r"D:\RFA\Company-Financial\go-app")
sys.path.insert(0, str(GO / "py")); sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GO / ".env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")

import canonical_hook  # noqa: E402
import brs_prices as bp  # noqa: E402
from canonical_ingest import reconcile as R  # noqa: E402
from canonical_ingest.db import transaction  # noqa: E402

OUT = GO.parent / "ingestion_migration_v1" / "output"
TARGETS = ["کیمیا", "غاذر", "سباقر", "دقاضی", "دارو"]
CYCLES = 5


def now():
    return datetime.now(timezone.utc).isoformat()


def build_rows():
    matched, _ = bp.resolve_matched_symbols("MarketPriceHistory")
    subset = [m for m in matched if m.get("symbol") in TARGETS][: len(TARGETS)]
    built = [bp.build_daily_row(m["raw"], m["company_id"], m["company_name"], m.get("brs_name")) for m in subset]
    return [r for r in built if r.get("gregorian_date")]


def persist(rows):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        bp.ensure_price_history_table(cur, "MarketPriceHistory")
        return bp._persist_market(cur, conn, rows, "MarketPriceHistory")
    finally:
        cur.close(); conn.close()


def reconcile(rows):
    out = []
    with transaction() as conn:
        cur = conn.cursor()
        for r in rows:
            cid = str(r.get("company_id"))
            cur.execute(
                """SELECT po.trade_date::text, po.closing_price_rial, po.volume
                   FROM market.price_observations po
                   JOIN core.legacy_entity_map lem
                     ON lem.entity_type='security' AND lem.target_uuid=po.security_id AND lem.legacy_key=%s
                   WHERE po.trade_date=%s AND po.source='brs' ORDER BY po.collected_at DESC LIMIT 1""",
                (cid, r["gregorian_date"]))
            row = cur.fetchone()
            canon = None if not row else {"trade_date": row[0], "closing_price_rial": row[1], "volume": row[2]}
            legacy = {"trade_date": r["gregorian_date"], "closing_price_rial": r.get("closing_price"),
                      "volume": r.get("volume")}
            out.append({"company_id": cid, "trade_date": r["gregorian_date"],
                        "classification": R.reconcile_market(legacy, canon)})
    return out


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(collected_at)::text, max(trade_date)::text, count(*) FROM market.price_observations")
        c = cur.fetchone()
    backlog = canonical_hook.retry_backlog_count("market_price")
    return {"domain": "MARKET_PRICE", "authority": "CANONICAL",
            "latest_canonical_observation_time": c[0], "latest_canonical_trade_date": c[1],
            "canonical_rows": c[2], "retry_backlog": backlog,
            "health": "HEALTHY" if backlog == 0 else "CANONICAL_BEHIND", "generated_at": now()}


def write_csv(path, rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader(); w.writerows(rows)


def main():
    assert canonical_hook.market_canonical_authority(), "set CDF_MARKET_INGESTION_AUTHORITY=canonical"
    OUT.mkdir(parents=True, exist_ok=True)
    cycles = []
    recon = []
    for i in range(1, CYCLES + 1):
        rows = build_rows()
        outcome = persist(rows)
        cycles.append({"cycle": i, "started_at": now(), "finished_at": now(), "rows": len(rows),
                       "outcome": outcome.get("outcome"), "canonical_inserted": outcome.get("inserted", 0),
                       "canonical_skipped": outcome.get("skipped", 0),
                       "legacy_mirror_status": outcome.get("legacy_mirror_status"),
                       "health": outcome.get("health"), "retry_backlog": outcome.get("retry_backlog")})
        recon.extend(reconcile(rows))
    fresh = freshness()
    recon_counts = dict(Counter(r["classification"] for r in recon))
    summary = {"generated_at": now(), "authority": "CANONICAL", "cycles": cycles,
               "total_new_observations": sum(c["canonical_inserted"] for c in cycles),
               "reconciliation": recon_counts, "freshness": fresh}
    write_csv(OUT / "market_routine_soak.csv", cycles)
    (OUT / "market_routine_soak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cycles": CYCLES, "new_obs": summary["total_new_observations"],
                      "recon": recon_counts, "health": fresh["health"], "backlog": fresh["retry_backlog"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
