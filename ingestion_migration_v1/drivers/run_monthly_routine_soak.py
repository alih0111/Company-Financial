"""Part A: routine MONTHLY_ACTIVITY canonical-primary soak (clean state)."""

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
from canonical_ingest import reconcile as R  # noqa: E402
from canonical_ingest.db import transaction  # noqa: E402
import brs_prices as bp  # noqa: E402

OUT = GO.parent / "ingestion_migration_v1" / "output"
TARGETS = [
    ("b88121029d7e973410b008320f8fe378", "قاسم"),
    ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا"),
    ("6081d3f368b7889ba242435db91b5b2f", "شکیمیا"),
]
CYCLES = 4


def now():
    return datetime.now(timezone.utc).isoformat()


def periods(cid, n=2):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT ReportDate FROM dbo.mahane WHERE CompanyID=? GROUP BY ReportDate ORDER BY ReportDate DESC", (cid,))
        return [r[0] for r in cur.fetchall()][:n]
    finally:
        cur.close(); conn.close()


def values(cid, period):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT Value1,Value2,Value3 FROM dbo.mahane WHERE CompanyID=? AND ReportDate=?", (cid, period))
        r = cur.fetchone(); return None if not r else [r[0], r[1], r[2]]
    finally:
        cur.close(); conn.close()


def reconcile(cid, period, vals):
    g = canonical_hook._gregorian(period)
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT ma.production_quantity, ma.sales_quantity, ma.reported_sales_amount, ma.sales_amount_rial
               FROM fundamentals.monthly_activities ma
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=ma.company_id AND lem.legacy_key=%s
               WHERE ma.period_end_date=%s ORDER BY ma.created_at DESC LIMIT 1""", (str(cid), g))
        row = cur.fetchone()
    canon = None if not row else {"production_quantity": row[0], "sales_quantity": row[1],
                                  "reported_sales_amount": row[2], "sales_amount_rial": row[3]}
    legacy = {"production_quantity": vals[0], "sales_quantity": vals[1], "reported_sales_amount": vals[2]}
    return {"company_id": cid, "period": period, "classification": R.reconcile_monthly(legacy, canon)}


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(period_end_date)::text, count(*) FROM fundamentals.monthly_activities")
        c = cur.fetchone()
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT max(ReportDate) FROM dbo.mahane"); src = cur.fetchone()[0]
    finally:
        cur.close(); conn.close()
    backlog = canonical_hook.retry_backlog_count("monthly_activity")
    return {"domain": "MONTHLY_ACTIVITY", "authority": "CANONICAL", "latest_source_period": str(src),
            "latest_canonical_period": c[0], "canonical_rows": c[1], "retry_backlog": backlog,
            "health": "HEALTHY" if backlog == 0 else "CANONICAL_BEHIND", "generated_at": now()}


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8"); return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader(); w.writerows(rows)


def main():
    assert canonical_hook.monthly_canonical_authority()
    OUT.mkdir(parents=True, exist_ok=True)
    cycles, recon = [], []
    for i in range(1, CYCLES + 1):
        for cid, name in TARGETS:
            for period in periods(cid):
                vals = values(cid, period)
                if vals is None:
                    continue
                outcome = canonical_hook.ingest_monthly_authoritative(cid, name, period, vals, legacy_writer=lambda: None)
                cycles.append({"cycle": i, "company": name, "period": period, "outcome": outcome.get("outcome"),
                               "canonical_status": outcome.get("status"), "canonical_inserted": outcome.get("inserted", 0),
                               "canonical_skipped": outcome.get("skipped", 0),
                               "legacy_mirror_status": outcome.get("legacy_mirror_status"), "health": outcome.get("health")})
                if i == 1 and outcome.get("status") == "written":
                    recon.append(reconcile(cid, period, vals))
    fresh = freshness()
    recon_counts = dict(Counter(r["classification"] for r in recon))
    summary = {"generated_at": now(), "authority": "CANONICAL", "cycles": len(cycles),
               "canonical_inserted": sum(c["canonical_inserted"] for c in cycles),
               "canonical_skipped": sum(c["canonical_skipped"] for c in cycles),
               "reconciliation": recon_counts, "freshness": fresh}
    write_csv(OUT / "monthly_routine_soak.csv", cycles)
    (OUT / "monthly_routine_soak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cycles": len(cycles), "inserted": summary["canonical_inserted"],
                      "recon": recon_counts, "health": fresh["health"], "backlog": fresh["retry_backlog"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
