"""Part B: CODAL canonical-authoritative completion + combined status."""

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
from canonical_ingest.db import transaction  # noqa: E402
from canonical_ingest.identity import resolve_company  # noqa: E402
import brs_prices as bp  # noqa: E402
canonical_ingest = __import__("canonical_ingest")

OUT = GO.parent / "ingestion_migration_v1" / "output"
RESOLVABLE = "آردینه"


def now():
    return datetime.now(timezone.utc).isoformat()


def fetch_letters(limit=5):
    url = ("https://search.codal.ir/api/search/v2/q?Audited=false&AuditedYears=0&Category=-1&Childs=false"
           "&CompanyState=-1&CompanyType=-1&Consolidatable=false&IsNotAudited=false&Length=-1&LetterType=6"
           "&Mains=true&NotAudited=false&NotConsolidatable=false&PageNumber=1&Publisher=false&TracingNo=-1"
           "&audited=false&notAudited=false")
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("Letters") or [])[:limit]


def tracked():
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT Symbol FROM dbo.TrackedTickers")
        return {r[0] for r in cur.fetchall()}
    finally:
        cur.close(); conn.close()


def live_letters():
    rows = []
    tr = tracked()
    for s in fetch_letters(5):
        res = canonical_hook.ingest_codal_authoritative(s, fetch_body=False)
        reason = res.get("status")
        if res.get("status") == "quarantined":
            reason = "ALIAS_MAPPING_REQUIRED" if (s.get("Symbol") in tr) else "EXPECTED_SCOPE_EXCLUSION"
        rows.append({"tracing_no": str(s.get("TracingNo")), "symbol": s.get("Symbol"),
                     "company": s.get("CompanyName"), "outcome": res.get("outcome"),
                     "status": res.get("status"), "quarantine_class": reason if res.get("status") == "quarantined" else "",
                     "has_raw": res.get("has_raw", False)})
    return rows


def controlled_semantics():
    srid1 = "codal:selftest:authority-1"
    srid2 = "codal:selftest:authority-2"
    a = canonical_ingest.dual_write_report(name=RESOLVABLE, source="codal", source_report_id=srid1,
                                           title="selftest", content_text="<html>v1</html>", payload_type="html",
                                           parser_name="codal_hook", parser_version="v1")
    b = canonical_ingest.dual_write_report(name=RESOLVABLE, source="codal", source_report_id=srid1,
                                           title="selftest", content_text="<html>v1</html>", payload_type="html",
                                           parser_name="codal_hook", parser_version="v1")
    c = canonical_ingest.dual_write_report(name=RESOLVABLE, source="codal", source_report_id=srid1,
                                           title="selftest", content_text="<html>v2</html>", payload_type="html",
                                           parser_name="codal_hook", parser_version="v1")
    d = canonical_ingest.dual_write_report(name=RESOLVABLE, source="codal", source_report_id=srid1,
                                           title="selftest", content_text="<html>v2</html>", payload_type="html",
                                           parser_name="codal_hook", parser_version="v2")
    # supersession: srid2 supersedes srid1
    e = canonical_ingest.dual_write_report(name=RESOLVABLE, source="codal", source_report_id=srid2,
                                           title="corrected", content_text="<html>corrected</html>",
                                           payload_type="html", parser_name="codal_hook", parser_version="v1",
                                           supersedes_source_report_id=srid1)
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*), max(version_no) FROM ingestion.report_versions rv JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s", (srid1,))
        v = cur.fetchone()
        cur.execute("SELECT count(*) FROM ingestion.parse_runs pr JOIN ingestion.report_versions rv ON rv.id=pr.report_version_id JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s", (srid1,))
        pr = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM raw.report_payloads rp JOIN ingestion.report_versions rv ON rv.id=rp.report_version_id JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s", (srid1,))
        raw = cur.fetchone()[0]
        cur.execute("""SELECT (r2.supersedes_report_id = r1.id)
                       FROM ingestion.reports r1, ingestion.reports r2
                       WHERE r1.source_report_id=%s AND r2.source_report_id=%s""", (srid1, srid2))
        sup = cur.fetchone()
    return {"identical_inserted": b.inserted, "changed_inserted": c.inserted,
            "versions": v[0], "max_version_no": v[1], "parse_runs": pr, "raw_payloads": raw,
            "parser_rerun_new_parse_run_no_new_version": pr >= 2 and v[1] == 2,
            "supersession_linked": bool(sup and sup[0]), "superseding_inserted": e.inserted}


def freshness(domain, backlog_domain, canonical_query):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(canonical_query)
        c = cur.fetchone()
    backlog = canonical_hook.retry_backlog_count(backlog_domain)
    return {"authority": "CANONICAL", "latest_canonical": c[0], "count": c[1] if len(c) > 1 else None,
            "retry_backlog": backlog, "health": "HEALTHY" if backlog == 0 else "CANONICAL_BEHIND"}


def combined_status():
    status = {}
    status["MARKET_PRICE"] = {"authority": "CANONICAL", "retry_backlog": canonical_hook.retry_backlog_count("market_price"),
                              "quarantine_count": _quar("market_price")}
    status["MONTHLY_ACTIVITY"] = {"authority": "CANONICAL", "retry_backlog": canonical_hook.retry_backlog_count("monthly_activity"),
                                  "quarantine_count": _quar("monthly_activity")}
    status["FINANCIAL_STATEMENT"] = {"authority": "CANONICAL", "retry_backlog": canonical_hook.retry_backlog_count("financial_statement"),
                                     "quarantine_count": _quar("financial_statement")}
    status["CODAL"] = {"authority": "CANONICAL", "retry_backlog": canonical_hook.retry_backlog_count("codal_report"),
                       "quarantine_count": _quar("codal_report")}
    for d in status:
        status[d]["health"] = "HEALTHY" if status[d]["retry_backlog"] == 0 else "CANONICAL_BEHIND"
    return status


def _quar(domain):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM ingestion.data_quality_issues WHERE issue_code='identity_conflict' AND resolved_at IS NULL AND details->>'domain'=%s", (domain,))
        return cur.fetchone()[0]


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
    assert canonical_hook.codal_canonical_authority(), "set CDF_CODAL_INGESTION_AUTHORITY=canonical"
    OUT.mkdir(parents=True, exist_ok=True)
    letters = live_letters()
    sem = controlled_semantics()
    status = combined_status()

    quar = [l for l in letters if l["status"] == "quarantined"]
    recon = [{"tracing_no": l["tracing_no"], "status": l["status"], "classification": l["quarantine_class"] or "CANONICAL_OK"} for l in letters]
    write_csv(OUT / "codal_authority_cycles.csv", letters)
    write_csv(OUT / "codal_authority_reconciliation.csv", recon)
    (OUT / "codal_authority_freshness.json").write_text(json.dumps(
        {"generated_at": now(), "CODAL": {"authority": "CANONICAL", "retry_backlog": canonical_hook.retry_backlog_count("codal_report"),
                                          "quarantine_count": _quar("codal_report")}}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "canonical_ingestion_status.json").write_text(json.dumps(
        {"generated_at": now(), "domains": status}, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"generated_at": now(), "codal": {"letters": letters, "semantics": sem, "quarantines": len(quar)},
               "domains": status}
    (OUT / "final_ingestion_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"letters": len(letters), "quarantined": len(quar), "semantics": sem, "status": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
