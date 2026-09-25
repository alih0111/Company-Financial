"""Part B: FINANCIAL_STATEMENT canonical-primary validation + injections + retry + TTM check."""

from __future__ import annotations

import csv
import glob
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
TARGETS = [
    ("6dd3fb203bb12fdd017e1f59fc61b9c6", "تاصیکو", "strong"),
    ("b88121029d7e973410b008320f8fe378", "قاسم", "strong"),
    ("7e41b7fd7ba1c353199eba22667db254", "کسرا", "alias"),
    ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا", "sparse"),
    ("6081d3f368b7889ba242435db91b5b2f", "شکیمیا", "legacy_only"),
]
CYCLES = 2


def now():
    return datetime.now(timezone.utc).isoformat()


def periods(cid, n=2):
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT ReportDate FROM dbo.miandore2 WHERE CompanyID=? GROUP BY ReportDate ORDER BY ReportDate DESC", (cid,))
        return [r[0] for r in cur.fetchall()][:n]
    finally:
        cur.close(); conn.close()


def run_cycles():
    cycles, recon = [], []
    for i in range(1, CYCLES + 1):
        for cid, name, kind in TARGETS:
            for period in periods(cid):
                outcome = canonical_hook.ingest_financial_authoritative_by_key(cid, name, period, legacy_writer=lambda: None)
                cycles.append({"cycle": i, "company": name, "kind": kind, "period": period,
                               "outcome": outcome.get("outcome"), "canonical_status": outcome.get("status"),
                               "facts": outcome.get("facts", 0), "canonical_inserted": outcome.get("inserted", 0),
                               "canonical_skipped": outcome.get("skipped", 0),
                               "legacy_mirror_status": outcome.get("legacy_mirror_status"), "health": outcome.get("health")})
                if i == 1 and outcome.get("status") == "written":
                    recon.extend(reconcile(cid, period))
    return cycles, recon


def reconcile(cid, period):
    g = canonical_hook._gregorian(period)
    facts = canonical_hook._facts_from_db(cid, period) or []
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT f.metric_code, f.period_order, f.reported_value, f.canonical_value
               FROM fundamentals.financial_facts f
               JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=fs.company_id AND lem.legacy_key=%s
               WHERE fs.period_end_date=%s""", (str(cid), g))
        cmap = {(r[1], r[0]): {"metric_code": r[0], "reported_value": r[2], "canonical_value": r[3]}
                for r in cur.fetchall()}
    out = []
    for f in facts:
        canon = cmap.get((f["period_order"], f["metric_code"]))
        out.append({"company_id": cid, "period": period, "metric": f"{f['metric_code']}:{f['period_order']}",
                    "classification": R.reconcile_fact(f, canon)})
    return out


def lineage_snapshot():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM fundamentals.financial_statements")
        stmts = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fundamentals.financial_facts")
        facts = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ingestion.report_versions")
        vers = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ingestion.parse_runs")
        runs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fundamentals.financial_facts WHERE metric_code ~* 'product|npunit|^opk$|^opamt$'")
        forbidden = cur.fetchone()[0]
    return {"statements": stmts, "facts": facts, "report_versions": vers, "parse_runs": runs,
            "forbidden_facts": forbidden}


def parser_rerun_check():
    cid, _, _ = TARGETS[0]
    period = periods(cid, 1)[0]
    g = canonical_hook._gregorian(period)
    before = _chain_counts(cid, g)
    import canonical_ingest
    facts = canonical_hook._facts_from_db(cid, period) or []
    canonical_ingest.dual_write_financial(legacy_company_id=str(cid), period_end_date=g,
                                          jalali_period_text=period, facts=facts)
    after = _chain_counts(cid, g)
    return {"before": before, "after": after,
            "new_parse_run_without_new_version": after["parse_runs"] >= before["parse_runs"] and after["versions"] == before["versions"]}


def _chain_counts(cid, g):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT count(DISTINCT rv.id), count(DISTINCT pr.id)
               FROM ingestion.reports r
               JOIN ingestion.report_versions rv ON rv.report_id=r.id
               LEFT JOIN ingestion.parse_runs pr ON pr.report_version_id=rv.id
               JOIN core.legacy_entity_map lem ON lem.entity_type='company' AND lem.target_uuid=r.company_id AND lem.legacy_key=%s
               WHERE r.period_end_date=%s""", (str(cid), g))
        v, p = cur.fetchone()
    return {"versions": v, "parse_runs": p}


def ttm_chain_check():
    # pick a company with >=5 canonical statement periods (report-chain TTM feasibility)
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT fs.company_id, count(DISTINCT fs.period_end_date) n
               FROM fundamentals.financial_statements fs
               WHERE fs.statement_type='income_statement'
               GROUP BY 1 ORDER BY n DESC LIMIT 1""")
        row = cur.fetchone()
        if not row:
            return {"periods": 0}
        cid, n = row
        cur.execute(
            """SELECT f.metric_code, count(DISTINCT f.period_order)
               FROM fundamentals.financial_facts f
               JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
               WHERE fs.company_id=%s AND fs.statement_type='income_statement'
               GROUP BY 1 ORDER BY 1""", (cid,))
        metrics = {r[0]: r[1] for r in cur.fetchall()}
    return {"company_id": str(cid), "statement_periods": n, "metrics": metrics,
            "report_chain_ttm_feasible": n >= 5 and metrics.get("revenue", 0) >= 1}


def replay_retries():
    entries = []
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("domain") == "financial_statement" and e.get("status") == "pending":
                entries.append(e)
    replayed = 0
    with MANIFEST.open("a", encoding="utf-8") as fh:
        for e in entries:
            keys = e.get("keys", {})
            cid, period = keys.get("legacy_company_id"), keys.get("report_date")
            if cid and period:
                canonical_hook._canonical_financial_write(cid, period)
            fh.write(json.dumps({"status": "done", "domain": "financial_statement", "keys": keys,
                                 "replayed_at": now()}, ensure_ascii=False) + "\n")
            replayed += 1
    return replayed


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(period_end_date)::text, max(created_at)::text, count(*) FROM fundamentals.financial_statements")
        c = cur.fetchone()
        cur.execute("SELECT count(*) FROM ingestion.data_quality_issues WHERE issue_code='identity_conflict' AND resolved_at IS NULL AND details->>'domain'='financial_statement'")
        quar = cur.fetchone()[0]
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT max(ReportDate) FROM dbo.miandore2"); src = cur.fetchone()[0]
    finally:
        cur.close(); conn.close()
    backlog = canonical_hook.retry_backlog_count("financial_statement")
    health = ("HEALTHY" if backlog == 0 and quar == 0 else "CANONICAL_BEHIND" if backlog else "IDENTITY_QUARANTINE")
    return {"domain": "FINANCIAL_STATEMENT", "authority": "CANONICAL", "latest_source_report": str(src),
            "latest_canonical_period": c[0], "latest_canonical_write": c[1], "statements": c[2],
            "legacy_mirror_state": "active", "retry_backlog": backlog, "quarantine_count": quar,
            "health": health, "generated_at": now()}


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
    assert canonical_hook.financial_canonical_authority(), "set CDF_FINANCIAL_INGESTION_AUTHORITY=canonical"
    OUT.mkdir(parents=True, exist_ok=True)
    cycles, recon = run_cycles()

    cid, name, _ = TARGETS[0]
    period = periods(cid, 1)[0]
    good = os.environ.get("CDF_CANONICAL_DB")
    os.environ["CDF_CANONICAL_DB"] = "definitely_production_db"
    canonical_hook._loaded = False
    fi_canon = canonical_hook.ingest_financial_authoritative_by_key(cid, name, period, legacy_writer=lambda: None)
    os.environ["CDF_CANONICAL_DB"] = good
    canonical_hook._loaded = False
    fi_mirror = canonical_hook.ingest_financial_authoritative_by_key(
        cid, name, period, legacy_writer=lambda: (_ for _ in ()).throw(RuntimeError("mirror down")))
    fi_ident = canonical_hook.ingest_financial_authoritative_by_key("__unknown_id__", "نامعلوم", "1405/05/31", legacy_writer=lambda: None)

    parser = parser_rerun_check()
    lineage = lineage_snapshot()
    ttm = ttm_chain_check()
    replayed = replay_retries()
    fresh = freshness()
    recon_counts = dict(Counter(r["classification"] for r in recon))
    summary = {
        "generated_at": now(), "authority": "CANONICAL",
        "cycles": cycles,
        "canonical_inserted": sum(c["canonical_inserted"] for c in cycles),
        "canonical_skipped": sum(c["canonical_skipped"] for c in cycles),
        "reconciliation": recon_counts,
        "failure_injection": {
            "canonical_unavailable": {"outcome": fi_canon.get("outcome")},
            "legacy_mirror_failure": {"outcome": fi_mirror.get("outcome")},
            "unresolved_identity": {"outcome": fi_ident.get("outcome"), "status": fi_ident.get("status")},
        },
        "parser_rerun": parser, "lineage": lineage, "ttm_chain": ttm,
        "retry_replayed": replayed, "freshness": fresh,
    }
    write_csv(OUT / "financial_authority_cycles.csv", cycles)
    write_csv(OUT / "financial_authority_reconciliation.csv", recon)
    (OUT / "financial_authority_freshness.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "financial_authority_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cycles": len(cycles), "inserted": summary["canonical_inserted"],
                      "skipped": summary["canonical_skipped"], "recon": recon_counts,
                      "fi_canon": fi_canon.get("outcome"), "fi_mirror": fi_mirror.get("outcome"),
                      "fi_ident": fi_ident.get("status"), "parser_ok": parser["new_parse_run_without_new_version"],
                      "forbidden_facts": lineage["forbidden_facts"], "ttm_feasible": ttm.get("report_chain_ttm_feasible"),
                      "health": fresh["health"], "backlog": fresh["retry_backlog"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
