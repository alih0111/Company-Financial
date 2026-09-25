"""Part B: MONTHLY_ACTIVITY canonical-primary validation + failure injection + retry."""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

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
MANIFEST = OUT / "canonical_retry_manifest.jsonl"
# (legacy_company_id, name, kind)  kind: repeated | sparse | alias/legacy-only
TARGETS = [
    ("b88121029d7e973410b008320f8fe378", "قاسم", "repeated"),
    ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا", "sparse"),
    ("6081d3f368b7889ba242435db91b5b2f", "شکیمیا", "legacy_only"),
]
CYCLES = 3


def now():
    return datetime.now(timezone.utc).isoformat()


def periods(company_id, n=2):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT ReportDate FROM dbo.mahane WHERE CompanyID=? GROUP BY ReportDate ORDER BY ReportDate DESC",
                    (company_id,))
        return [r[0] for r in cur.fetchall()][:n]
    finally:
        cur.close(); conn.close()


def legacy_values(company_id, period):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT Value1,Value2,Value3 FROM dbo.mahane WHERE CompanyID=? AND ReportDate=?",
                    (company_id, period))
        r = cur.fetchone()
        return None if not r else [r[0], r[1], r[2]]
    finally:
        cur.close(); conn.close()


def legacy_noop():
    return None


def run_cycles():
    cycles, recon = [], []
    for i in range(1, CYCLES + 1):
        for cid, name, kind in TARGETS:
            for period in periods(cid):
                vals = legacy_values(cid, period)
                if vals is None:
                    continue
                outcome = canonical_hook.ingest_monthly_authoritative(cid, name, period, vals, legacy_writer=legacy_noop)
                cycles.append({"cycle": i, "company": name, "kind": kind, "period": period,
                               "outcome": outcome.get("outcome"), "canonical_status": outcome.get("status"),
                               "canonical_inserted": outcome.get("inserted", 0),
                               "canonical_skipped": outcome.get("skipped", 0),
                               "legacy_mirror_status": outcome.get("legacy_mirror_status"),
                               "health": outcome.get("health")})
                if i == 1 and outcome.get("status") == "written":
                    recon.append(reconcile(cid, period, vals))
    return cycles, recon


def reconcile(company_id, period, vals):
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
    legacy = {"production_quantity": vals[0], "sales_quantity": vals[1], "reported_sales_amount": vals[2]}
    return {"company_id": company_id, "period": period, "classification": R.reconcile_monthly(legacy, canon),
            "unit_conversion": True}


def replay_retries():
    entries = []
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("domain") == "monthly_activity" and e.get("status") == "pending":
                entries.append(e)
    replayed = 0
    with MANIFEST.open("a", encoding="utf-8") as fh:
        for e in entries:
            keys = e.get("keys", {})
            cid, period = keys.get("legacy_company_id"), keys.get("report_date")
            vals = legacy_values(cid, period) if cid and period else None
            if vals is not None:
                canonical_hook._canonical_monthly_write(cid, "", period, vals)
            fh.write(json.dumps({"status": "done", "domain": "monthly_activity", "keys": keys,
                                 "replayed_at": now()}, ensure_ascii=False) + "\n")
            replayed += 1
    return replayed


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(period_end_date)::text, count(*) FROM fundamentals.monthly_activities")
        c = cur.fetchone()
        cur.execute("SELECT count(*) FROM ingestion.data_quality_issues WHERE issue_code='identity_conflict' AND resolved_at IS NULL AND details->>'domain'='monthly_activity'")
        quar = cur.fetchone()[0]
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT max(ReportDate) FROM dbo.mahane")
        src = cur.fetchone()[0]
    finally:
        cur.close(); conn.close()
    backlog = canonical_hook.retry_backlog_count("monthly_activity")
    health = ("HEALTHY" if backlog == 0 and quar == 0 else
              "CANONICAL_BEHIND" if backlog else "IDENTITY_QUARANTINE")
    return {"domain": "MONTHLY_ACTIVITY", "authority": "CANONICAL",
            "latest_source_period": str(src), "latest_canonical_period": c[0],
            "canonical_rows": c[1], "quarantine_count": quar, "legacy_mirror_state": "active",
            "retry_backlog": backlog, "health": health, "generated_at": now()}


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
    assert canonical_hook.monthly_canonical_authority(), "set CDF_MONTHLY_INGESTION_AUTHORITY=canonical"
    OUT.mkdir(parents=True, exist_ok=True)
    cycles, recon = run_cycles()

    # failure injection: canonical unavailable -> fallback + retry
    cid, name, _ = TARGETS[0]
    p = periods(cid, 1)[0]
    vals = legacy_values(cid, p)
    good = os.environ.get("CDF_CANONICAL_DB")
    os.environ["CDF_CANONICAL_DB"] = "definitely_production_db"
    canonical_hook._loaded = False
    fi_canon = canonical_hook.ingest_monthly_authoritative(cid, name, p, vals, legacy_writer=legacy_noop)
    os.environ["CDF_CANONICAL_DB"] = good
    canonical_hook._loaded = False

    # failure injection: legacy mirror failure -> canonical still authoritative
    fi_mirror = canonical_hook.ingest_monthly_authoritative(
        cid, name, p, vals, legacy_writer=lambda: (_ for _ in ()).throw(RuntimeError("mirror down")))

    # failure injection: unresolved identity -> quarantine
    fi_ident = canonical_hook.ingest_monthly_authoritative("__unknown_id__", "نامعلوم", "1405/06/31", [0, 0, 0],
                                                           legacy_writer=legacy_noop)

    replayed = replay_retries()
    fresh = freshness()
    recon_counts = dict(Counter(r["classification"] for r in recon))
    summary = {
        "generated_at": now(), "authority": "CANONICAL", "cycles": cycles,
        "canonical_inserted": sum(c["canonical_inserted"] for c in cycles),
        "canonical_skipped": sum(c["canonical_skipped"] for c in cycles),
        "reconciliation": recon_counts,
        "failure_injection": {
            "canonical_unavailable": {"outcome": fi_canon.get("outcome"), "mirror": fi_canon.get("legacy_mirror_status")},
            "legacy_mirror_failure": {"outcome": fi_mirror.get("outcome"), "mirror": fi_mirror.get("legacy_mirror_status")},
            "unresolved_identity": {"outcome": fi_ident.get("outcome"), "status": fi_ident.get("status"),
                                    "health": fi_ident.get("health")},
        },
        "retry_replayed": replayed, "freshness": fresh,
    }
    write_csv(OUT / "monthly_authority_cycles.csv", cycles)
    write_csv(OUT / "monthly_authority_reconciliation.csv", recon)
    (OUT / "monthly_authority_freshness.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "monthly_authority_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cycles": len(cycles), "inserted": summary["canonical_inserted"],
                      "skipped": summary["canonical_skipped"], "recon": recon_counts,
                      "fi_canon": fi_canon.get("outcome"), "fi_mirror": fi_mirror.get("outcome"),
                      "fi_ident": fi_ident.get("status"), "health": fresh["health"], "backlog": fresh["retry_backlog"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
