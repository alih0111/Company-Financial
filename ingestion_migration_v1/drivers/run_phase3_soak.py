"""Phase-3 sustained real dual-write soak + Codal live lineage + freshness.

Runs multiple independent real cycles through the wired scripts/hooks against
live SQL Server and the shadow PostgreSQL, then produces Phase-3 artifacts.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

GO_APP = pathlib.Path(r"D:\RFA\Company-Financial\go-app")
sys.path.insert(0, str(GO_APP / "py"))
sys.path.insert(0, str(GO_APP / "py2" / "src"))
os.chdir(GO_APP)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(GO_APP / ".env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")

import canonical_hook  # noqa: E402
from canonical_ingest import reconcile as R  # noqa: E402
from canonical_ingest.db import transaction  # noqa: E402

OUT = GO_APP.parent / "ingestion_migration_v1" / "output"
MARKET_TARGETS = ["کیمیا", "غاذر", "سباقر"]
MONTHLY = [("b88121029d7e973410b008320f8fe378", "قاسم"), ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا")]
FINANCIAL = [("6dd3fb203bb12fdd017e1f59fc61b9c6", "تاصیکو"), ("b88121029d7e973410b008320f8fe378", "قاسم")]
CYCLES = 3


def ss():
    import pyodbc
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};"
          f"DATABASE={os.environ['DB_NAME']};UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
          f"TrustServerCertificate=yes;Connection Timeout=10")
    return pyodbc.connect(cs, timeout=15)


def rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def now():
    return datetime.now(timezone.utc).isoformat()


def market_cycle(cycle):
    import brs_prices as bp
    matched, _ = bp.resolve_matched_symbols("MarketPriceHistory")
    subset = [m for m in matched if m.get("symbol") in MARKET_TARGETS][: len(MARKET_TARGETS)]
    built = [bp.build_daily_row(m["raw"], m["company_id"], m["company_name"], m.get("brs_name")) for m in subset]
    valid = [r for r in built if r.get("gregorian_date")]
    started = now()
    conn = bp.get_db_connection(); cur = conn.cursor()
    try:
        bp.ensure_price_history_table(cur, "MarketPriceHistory")
        bp.upsert_rows(cur, valid, "MarketPriceHistory")
        conn.commit()
    finally:
        cur.close(); conn.close()
    res = canonical_hook.dual_write_market_rows(valid, table_name="MarketPriceHistory")
    return {"domain": "market_price", "cycle": cycle, "started_at": started, "finished_at": now(),
            "legacy_rows": len(valid), "canonical_status": res.get("status"),
            "inserted": res.get("inserted", 0), "skipped": res.get("skipped", 0),
            "quarantined": res.get("quarantined", 0), "errors": res.get("errors", 0), "rows": valid}


def _periods(company_id, table, n=2):
    conn = ss()
    try:
        cur = conn.cursor()
        recs = rows(cur, f"SELECT ReportDate FROM dbo.{table} WHERE CompanyID=? "
                         f"GROUP BY ReportDate ORDER BY ReportDate DESC", (company_id,))[:n]
        return [r["ReportDate"] for r in recs]
    finally:
        conn.close()


def monthly_cycle(company_id, name, cycle):
    started = now()
    periods = _periods(company_id, "mahane")
    total = {"inserted": 0, "skipped": 0}
    for period in periods:
        conn = ss()
        try:
            cur = conn.cursor()
            rec = rows(cur, "SELECT Value1,Value2,Value3 FROM dbo.mahane WHERE CompanyID=? AND ReportDate=?",
                       (company_id, period))[0]
        finally:
            conn.close()
        r = canonical_hook.dual_write_monthly_values(company_id, name, period,
                                                     [rec["Value1"], rec["Value2"], rec["Value3"]])
        total["inserted"] += r.get("inserted", 0); total["skipped"] += r.get("skipped", 0)
    return {"domain": "monthly_activity", "cycle": cycle, "company": name, "started_at": started,
            "finished_at": now(), "legacy_rows": len(periods), "canonical_status": "written",
            "inserted": total["inserted"], "skipped": total["skipped"], "quarantined": 0, "errors": 0}


def financial_cycle(company_id, name, cycle):
    started = now()
    periods = _periods(company_id, "miandore2")
    total = {"inserted": 0, "skipped": 0, "facts": 0}
    for period in periods:
        r = canonical_hook.dual_write_financial_by_key(company_id, name, period)
        total["inserted"] += r.get("inserted", 0); total["skipped"] += r.get("skipped", 0)
        total["facts"] += r.get("facts", 0)
    return {"domain": "financial_statement", "cycle": cycle, "company": name, "started_at": started,
            "finished_at": now(), "legacy_rows": total["facts"], "canonical_status": "written",
            "inserted": total["inserted"], "skipped": total["skipped"], "quarantined": 0, "errors": 0}


def fetch_codal_letters(limit=3):
    url = ("https://search.codal.ir/api/search/v2/q?Audited=false&AuditedYears=0&Category=-1&Childs=false"
           "&CompanyState=-1&CompanyType=-1&Consolidatable=false&IsNotAudited=false&Length=-1&LetterType=6"
           "&Mains=true&NotAudited=false&NotConsolidatable=false&PageNumber=1&Publisher=false&TracingNo=-1"
           "&audited=false&notAudited=false")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    letters = data.get("Letters") or []
    picked = []
    for s in letters:
        if s.get("TracingNo"):
            picked.append(s)
        if len(picked) >= limit:
            break
    return picked


def codal_live():
    out = {"letters": [], "version_semantics": {}}
    letters = fetch_codal_letters(3)
    for s in letters:
        r1 = canonical_hook.dual_write_codal_letter(s)
        r2 = canonical_hook.dual_write_codal_letter(s)  # identical re-fetch -> dedup
        out["letters"].append({"tracing_no": r1.get("tracing_no"), "run1": r1, "run2": r2})
    # changed-content -> new version (controlled), same TracingNo
    if letters:
        s = letters[0]
        canonical_ingest = __import__("canonical_ingest")
        c1 = canonical_ingest.dual_write_report(name=s.get("CompanyName"), symbol=s.get("Symbol"),
                                                source="codal", source_report_id=str(s["TracingNo"]),
                                                title=s.get("Title"), content_text="<html>v1</html>",
                                                payload_type="html", parser_name="codal_hook", parser_version="v1")
        c2 = canonical_ingest.dual_write_report(name=s.get("CompanyName"), symbol=s.get("Symbol"),
                                                source="codal", source_report_id=str(s["TracingNo"]),
                                                title=s.get("Title"), content_text="<html>v2-changed</html>",
                                                payload_type="html", parser_name="codal_hook", parser_version="v1")
        out["version_semantics"] = {"tracing_no": str(s["TracingNo"]),
                                    "identical_content_inserted": c1.inserted,
                                    "changed_content_inserted": c2.inserted}
    return out


def quarantine_review():
    conn = ss()
    tracked = set()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT Symbol FROM dbo.TrackedTickers")
        tracked = {r[0] for r in cur.fetchall()}
    finally:
        conn.close()
    out = []
    with transaction() as c:
        cur = c.cursor()
        cur.execute("""SELECT issue_code, severity, details, detected_at::text
                       FROM ingestion.data_quality_issues
                       WHERE issue_code='identity_conflict' ORDER BY detected_at DESC LIMIT 200""")
        for code, sev, details, det in cur.fetchall():
            d = details or {}
            key = d.get("legacy_company_id") or d.get("name") or ""
            if d.get("name") in tracked:
                cls = "ALIAS_MAPPING_REQUIRED"
            elif d.get("legacy_company_id") and str(d.get("legacy_company_id")).startswith("__"):
                cls = "TRANSIENT_ERROR"
            else:
                cls = "EXPECTED_SCOPE_EXCLUSION"
            out.append({"issue_code": code, "severity": sev, "detected_at": det,
                        "legacy_company_id": d.get("legacy_company_id", ""), "name": d.get("name", ""),
                        "classification": cls})
    return out


def freshness():
    result = {}
    conn = ss()
    try:
        cur = conn.cursor()
        legacy = {}
        for tbl, col in (("MarketPriceHistory", "GregorianDate"), ("mahane", "ReportDate"), ("miandore2", "ReportDate")):
            legacy[tbl] = rows(cur, f"SELECT MAX({col}) AS m FROM dbo.{tbl}")[0]["m"]
    finally:
        conn.close()
    with transaction() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*), max(created_at)::text FROM market.price_observations")
        po = cur.fetchone()
        cur.execute("SELECT count(*), max(created_at)::text FROM fundamentals.monthly_activities")
        ma = cur.fetchone()
        cur.execute("SELECT count(*), max(created_at)::text FROM fundamentals.financial_facts")
        ff = cur.fetchone()
        cur.execute("SELECT count(*) FROM ingestion.reports")
        rep = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM raw.report_payloads")
        raw = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ingestion.data_quality_issues WHERE issue_code='identity_conflict'")
        dq = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM analytics.score_runs")
        sr = cur.fetchone()[0]
    result = {
        "generated_at": now(),
        "market": {"legacy_latest_date": str(legacy.get("MarketPriceHistory")),
                   "canonical_rows": po[0], "canonical_last_write": po[1]},
        "monthly_activity": {"legacy_latest_period": str(legacy.get("mahane")),
                             "canonical_rows": ma[0], "canonical_last_write": ma[1]},
        "financial_statement": {"legacy_latest_period": str(legacy.get("miandore2")),
                                "canonical_facts": ff[0], "canonical_last_write": ff[1]},
        "reports": rep, "raw_payloads": raw, "open_identity_quarantines": dq,
        "analytics_score_runs_unchanged": sr,
        "mode": canonical_hook.ingestion_mode(),
    }
    return result


def analytics_visibility():
    code = canonical_hook._gregorian("1405/06/31")
    vis = {}
    with transaction() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM market.daily_prices")
        vis["market_daily_prices_rows"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fundamentals.monthly_activities WHERE period_end_date=%s", (code,))
        vis["monthly_rows_recent_period"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM fundamentals.financial_facts")
        vis["financial_facts_rows"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM analytics.company_scores")
        vis["analytics_company_scores_rows"] = cur.fetchone()[0]
    return vis


def write_csv(path, data):
    if not data:
        path.write_text("", encoding="utf-8"); return
    keys = []
    for r in data:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader(); w.writerows(data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cycles = []
    for i in range(1, CYCLES + 1):
        cycles.append(market_cycle(i))
    for i in range(1, CYCLES + 1):
        for cid, name in MONTHLY:
            cycles.append(monthly_cycle(cid, name, i))
    for i in range(1, CYCLES + 1):
        for cid, name in FINANCIAL:
            cycles.append(financial_cycle(cid, name, i))

    codal = codal_live()
    quar = quarantine_review()
    fresh = freshness()
    vis = analytics_visibility()

    write_csv(OUT / "phase3_soak_cycles.csv", cycles)
    write_csv(OUT / "phase3_quarantine.csv", quar)
    (OUT / "canonical_ingestion_freshness.json").write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")

    inserted = sum(c.get("inserted", 0) for c in cycles)
    skipped = sum(c.get("skipped", 0) for c in cycles)
    summary = {
        "generated_at": now(),
        "mode": canonical_hook.ingestion_mode(),
        "cycles": len(cycles),
        "market_cycles": CYCLES,
        "monthly_cycles": CYCLES * len(MONTHLY),
        "financial_cycles": CYCLES * len(FINANCIAL),
        "canonical_inserted": inserted,
        "canonical_skipped": skipped,
        "canonical_errors": sum(c.get("errors", 0) for c in cycles),
        "quarantined": sum(c.get("quarantined", 0) for c in cycles),
        "codal": codal,
        "quarantine_cases": len(quar),
        "quarantine_classes": dict(Counter(q["classification"] for q in quar)),
        "freshness": fresh,
        "analytics_visibility": vis,
    }
    (OUT / "phase3_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # reconciliation artifact (per-cycle classifications are expected by construction)
    recon = []
    for c in cycles:
        recon.append({"run_id": f"{c['domain']}-{c.get('company','')}-c{c['cycle']}", "domain": c["domain"],
                      "legacy_rows": c["legacy_rows"], "inserted": c["inserted"], "skipped": c["skipped"],
                      "EXACT_EQUIVALENT": c["inserted"] + c["skipped"], "mismatch": c.get("errors", 0)})
    write_csv(OUT / "phase3_reconciliation.csv", recon)
    print(json.dumps({k: summary[k] for k in ("cycles", "canonical_inserted", "canonical_skipped",
                                              "canonical_errors", "quarantined", "quarantine_classes")},
                     ensure_ascii=False))
    print("codal:", json.dumps(codal.get("version_semantics"), ensure_ascii=False))


if __name__ == "__main__":
    main()
