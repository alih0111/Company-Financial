"""Part A: short FINANCIAL_STATEMENT routine canonical-primary soak (clean state)."""

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
    ("6dd3fb203bb12fdd017e1f59fc61b9c6", "تاصیکو"),
    ("b88121029d7e973410b008320f8fe378", "قاسم"),
    ("7e41b7fd7ba1c353199eba22667db254", "کسرا"),
    ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا"),
]
CYCLES = 3


def now():
    return datetime.now(timezone.utc).isoformat()


def periods(cid, n=2):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT ReportDate FROM dbo.miandore2 WHERE CompanyID=? GROUP BY ReportDate ORDER BY ReportDate DESC", (cid,))
        return [r[0] for r in cur.fetchall()][:n]
    finally:
        cur.close(); conn.close()


def reconcile(cid, period):
    g = canonical_hook._gregorian(period)
    facts = canonical_hook._facts_from_db(cid, period) or []
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT f.metric_code, f.period_order, f.reported_value, f.canonical_value
               FROM fundamentals.financial_facts f
               JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
               JOIN core.legacy_entity_map lem ON lem.entity_type='company' AND lem.target_uuid=fs.company_id AND lem.legacy_key=%s
               WHERE fs.period_end_date=%s""", (str(cid), g))
        cmap = {(r[1], r[0]): {"metric_code": r[0], "reported_value": r[2], "canonical_value": r[3]}
                for r in cur.fetchall()}
    return [{"company_id": cid, "period": period, "metric": f"{f['metric_code']}:{f['period_order']}",
             "classification": R.reconcile_fact(f, cmap.get((f["period_order"], f["metric_code"])))} for f in facts]


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(period_end_date)::text, max(created_at)::text FROM fundamentals.financial_statements")
        c = cur.fetchone()
    backlog = canonical_hook.retry_backlog_count("financial_statement")
    return {"domain": "FINANCIAL_STATEMENT", "authority": "CANONICAL", "latest_canonical_period": c[0],
            "latest_canonical_write": c[1], "retry_backlog": backlog,
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
    assert canonical_hook.financial_canonical_authority()
    OUT.mkdir(parents=True, exist_ok=True)
    cycles, recon = [], []
    for i in range(1, CYCLES + 1):
        for cid, name in TARGETS:
            for period in periods(cid):
                outcome = canonical_hook.ingest_financial_authoritative_by_key(cid, name, period, legacy_writer=lambda: None)
                cycles.append({"cycle": i, "company": name, "period": period, "outcome": outcome.get("outcome"),
                               "canonical_status": outcome.get("status"), "facts": outcome.get("facts", 0),
                               "canonical_inserted": outcome.get("inserted", 0),
                               "canonical_skipped": outcome.get("skipped", 0),
                               "legacy_mirror_status": outcome.get("legacy_mirror_status"), "health": outcome.get("health")})
                if i == 1 and outcome.get("status") == "written":
                    recon.extend(reconcile(cid, period))
    fresh = freshness()
    recon_counts = dict(Counter(r["classification"] for r in recon))
    summary = {"generated_at": now(), "authority": "CANONICAL", "cycles": len(cycles),
               "canonical_inserted": sum(c["canonical_inserted"] for c in cycles),
               "canonical_skipped": sum(c["canonical_skipped"] for c in cycles),
               "reconciliation": recon_counts, "freshness": fresh}
    write_csv(OUT / "financial_routine_soak.csv", cycles)
    (OUT / "financial_routine_soak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cycles": len(cycles), "inserted": summary["canonical_inserted"],
                      "recon": recon_counts, "health": fresh["health"], "backlog": fresh["retry_backlog"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
