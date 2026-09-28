"""Part A: short combined operational soak of all four canonical-primary domains.

Runs MARKET_PRICE, MONTHLY_ACTIVITY, FINANCIAL_STATEMENT and CODAL through the
real canonical-authoritative ingestion hooks in one process, so that
cross-domain interference, idempotency, freshness, retry backlog, quarantine
classification and partial-write behaviour can be observed together.

This is NOT a redesign and NOT a migration. SQL Server is read-only here (used
as the reconcile source/mirror reference); all canonical writes go to the
designated shadow database through the approved canonical_ingest writer.

Outputs:
  output/combined_ingestion_soak.csv
  output/combined_ingestion_soak.json
  output/canonical_ingestion_status.json   (combined 4-domain status)
  COMBINED_SOAK_REPORT.md
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone

GO = pathlib.Path(r"D:\RFA\Company-Financial\go-app")
REPO = GO.parent
sys.path.insert(0, str(GO / "py"))
sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(GO / ".env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")
os.environ["CDF_INGESTION_MODE"] = "dual_write"
os.environ["CDF_MARKET_INGESTION_AUTHORITY"] = "canonical"
os.environ["CDF_MONTHLY_INGESTION_AUTHORITY"] = "canonical"
os.environ["CDF_FINANCIAL_INGESTION_AUTHORITY"] = "canonical"
os.environ["CDF_CODAL_INGESTION_AUTHORITY"] = "canonical"

import canonical_hook  # noqa: E402
import brs_prices as bp  # noqa: E402
from canonical_ingest import reconcile as R  # noqa: E402
from canonical_ingest.db import transaction  # noqa: E402

canonical_ingest = __import__("canonical_ingest")

OUT = REPO / "ingestion_migration_v1" / "output"
CYCLES = 3

MARKET_TARGETS = ["کیمیا", "غاذر", "سباقر", "دقاضی", "دارو"]
MONTHLY_TARGETS = [
    ("b88121029d7e973410b008320f8fe378", "قاسم"),
    ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا"),
    ("6081d3f368b7889ba242435db91b5b2f", "شکیمیا"),
]
FINANCIAL_TARGETS = [
    ("6dd3fb203bb12fdd017e1f59fc61b9c6", "تاصیکو"),
    ("b88121029d7e973410b008320f8fe378", "قاسم"),
    ("7e41b7fd7ba1c353199eba22667db254", "کسرا"),
    ("799566aa607bcd4a8ce4fed470c7d2b0", "چکاپا"),
]
CODAL_RESOLVABLE = "آردینه"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sqlserver_query(sql, params=()):
    conn = bp.get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.close()


# --------------------------------------------------------------------------
# domain workloads (real legacy source -> canonical-authoritative hook)
# --------------------------------------------------------------------------
def market_rows():
    matched, _ = bp.resolve_matched_symbols("MarketPriceHistory")
    subset = [m for m in matched if m.get("symbol") in MARKET_TARGETS][: len(MARKET_TARGETS)]
    built = [
        bp.build_daily_row(m["raw"], m["company_id"], m["company_name"], m.get("brs_name"))
        for m in subset
    ]
    return [r for r in built if r.get("gregorian_date")]


def market_cycle():
    rows = market_rows()
    res = canonical_hook.ingest_market_authoritative(rows, legacy_writer=None)
    return res, rows


def monthly_cycle():
    out = []
    for cid, name in MONTHLY_TARGETS:
        periods = sqlserver_query(
            "SELECT TOP 2 ReportDate FROM dbo.mahane WHERE CompanyID=? GROUP BY ReportDate ORDER BY ReportDate DESC",
            (cid,),
        )
        for p in periods:
            period = p["ReportDate"]
            vals = sqlserver_query(
                "SELECT Value1,Value2,Value3 FROM dbo.mahane WHERE CompanyID=? AND ReportDate=?",
                (cid, period),
            )
            if not vals:
                continue
            v = vals[0]
            res = canonical_hook.ingest_monthly_authoritative(
                cid, name, period, [v["Value1"], v["Value2"], v["Value3"]], legacy_writer=None
            )
            out.append((cid, name, period, res))
    return out


def financial_cycle():
    out = []
    for cid, name in FINANCIAL_TARGETS:
        periods = sqlserver_query(
            "SELECT TOP 2 ReportDate FROM dbo.miandore2 WHERE CompanyID=? GROUP BY ReportDate ORDER BY ReportDate DESC",
            (cid,),
        )
        for p in periods:
            period = p["ReportDate"]
            res = canonical_hook.ingest_financial_authoritative_by_key(
                cid, name, period, legacy_writer=None
            )
            out.append((cid, name, period, res))
    return out


def codal_live_letters(limit=5):
    url = (
        "https://search.codal.ir/api/search/v2/q?Audited=false&AuditedYears=0&Category=-1"
        "&Childs=false&CompanyState=-1&CompanyType=-1&Consolidatable=false&IsNotAudited=false"
        "&Length=-1&LetterType=6&Mains=true&NotAudited=false&NotConsolidatable=false&PageNumber=1"
        "&Publisher=false&TracingNo=-1&audited=false&notAudited=false"
    )
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("Letters") or [])[:limit]


def codal_tracked():
    rows = sqlserver_query("SELECT DISTINCT Symbol FROM dbo.TrackedTickers")
    return {r["Symbol"] for r in rows}


def codal_controlled_semantics(tag: str):
    srid = f"codal:selftest:combined-{tag}"
    b = canonical_ingest.dual_write_report(
        name=CODAL_RESOLVABLE, source="codal", source_report_id=srid, title="selftest",
        content_text="<html>v1</html>", payload_type="html",
        parser_name="codal_hook", parser_version="v1",
    )
    c = canonical_ingest.dual_write_report(
        name=CODAL_RESOLVABLE, source="codal", source_report_id=srid, title="selftest",
        content_text="<html>v2</html>", payload_type="html",
        parser_name="codal_hook", parser_version="v1",
    )
    d = canonical_ingest.dual_write_report(
        name=CODAL_RESOLVABLE, source="codal", source_report_id=srid, title="selftest",
        content_text="<html>v2</html>", payload_type="html",
        parser_name="codal_hook", parser_version="v2",
    )
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*), max(version_no) FROM ingestion.report_versions rv "
            "JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s",
            (srid,),
        )
        v = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM ingestion.parse_runs pr "
            "JOIN ingestion.report_versions rv ON rv.id=pr.report_version_id "
            "JOIN ingestion.reports r ON r.id=rv.report_id WHERE r.source_report_id=%s",
            (srid,),
        )
        pr = cur.fetchone()[0]
    return {
        "identical_new_version": b.inserted,
        "changed_new_version": c.inserted,
        "parser_rerun_new_parse_run": pr >= 2,
        "versions": v[0],
        "max_version_no": v[1],
    }


def codal_cycle(cycle_no: int):
    rows = []
    network = "ok"
    try:
        tracked = codal_tracked()
        for s in codal_live_letters(5):
            res = canonical_hook.ingest_codal_authoritative(s, fetch_body=False)
            status = res.get("status")
            qclass = ""
            if status == "quarantined":
                qclass = (
                    "ALIAS_MAPPING_REQUIRED"
                    if s.get("Symbol") in tracked
                    else "EXPECTED_SCOPE_EXCLUSION"
                )
            rows.append(
                {
                    "tracing_no": str(s.get("TracingNo")),
                    "symbol": s.get("Symbol"),
                    "outcome": res.get("outcome"),
                    "status": status,
                    "quarantine_class": qclass,
                }
            )
    except Exception as exc:  # noqa: BLE001
        network = f"unavailable: {type(exc).__name__}"
    sem = codal_controlled_semantics(f"c{cycle_no}")
    return rows, network, sem


# --------------------------------------------------------------------------
# reconciliation
# --------------------------------------------------------------------------
def reconcile_market(rows):
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
                   WHERE po.trade_date=%s AND po.source='brs'
                   ORDER BY po.collected_at DESC LIMIT 1""",
                (cid, r["gregorian_date"]),
            )
            row = cur.fetchone()
            canon = None if not row else {
                "trade_date": row[0], "closing_price_rial": row[1], "volume": row[2]
            }
            legacy = {
                "trade_date": r["gregorian_date"],
                "closing_price_rial": r.get("closing_price"),
                "volume": r.get("volume"),
            }
            out.append(R.reconcile_market(legacy, canon))
    return out


def reconcile_monthly(cid, period, vals):
    g = canonical_hook._gregorian(period)
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT ma.production_quantity, ma.sales_quantity, ma.reported_sales_amount, ma.sales_amount_rial
               FROM fundamentals.monthly_activities ma
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=ma.company_id AND lem.legacy_key=%s
               WHERE ma.period_end_date=%s ORDER BY ma.created_at DESC LIMIT 1""",
            (str(cid), g),
        )
        row = cur.fetchone()
    canon = None if not row else {
        "production_quantity": row[0], "sales_quantity": row[1],
        "reported_sales_amount": row[2], "sales_amount_rial": row[3],
    }
    legacy = {
        "production_quantity": vals[0], "sales_quantity": vals[1],
        "reported_sales_amount": vals[2],
    }
    return R.reconcile_monthly(legacy, canon)


def reconcile_financial(cid, period):
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
               WHERE fs.period_end_date=%s""",
            (str(cid), g),
        )
        cmap = {
            (r[1], r[0]): {"metric_code": r[0], "reported_value": r[2], "canonical_value": r[3]}
            for r in cur.fetchall()
        }
    return [
        R.reconcile_fact(f, cmap.get((f["period_order"], f["metric_code"])))
        for f in facts
    ]


# --------------------------------------------------------------------------
# health probes
# --------------------------------------------------------------------------
def table_counts():
    with transaction() as conn:
        cur = conn.cursor()
        out = {}
        for key, sql in {
            "market.price_observations": "SELECT count(*) FROM market.price_observations",
            "fundamentals.monthly_activities": "SELECT count(*) FROM fundamentals.monthly_activities",
            "fundamentals.financial_facts": "SELECT count(*) FROM fundamentals.financial_facts",
            "ingestion.reports": "SELECT count(*) FROM ingestion.reports",
            "analytics.score_runs": "SELECT count(*) FROM analytics.score_runs",
            "ingestion.parse_runs": "SELECT count(*) FROM ingestion.parse_runs",
        }.items():
            cur.execute(sql)
            out[key] = cur.fetchone()[0]
        return out


def freshness():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT max(collected_at)::text, max(trade_date)::text, count(*) FROM market.price_observations")
        m = cur.fetchone()
        cur.execute("SELECT max(period_end_date)::text, count(*) FROM fundamentals.monthly_activities")
        mo = cur.fetchone()
        cur.execute("SELECT max(period_end_date)::text, max(created_at)::text FROM fundamentals.financial_statements")
        f = cur.fetchone()
        cur.execute("SELECT max(created_at)::text, count(*) FROM ingestion.reports")
        c = cur.fetchone()
        cur.execute("SELECT count(*) FROM ingestion.parse_runs WHERE status NOT IN ('completed','failed')")
        partial = cur.fetchone()[0]
    return {
        "market": {"latest_collected_at": m[0], "latest_trade_date": m[1], "rows": m[2]},
        "monthly_activity": {"latest_period": mo[0], "rows": mo[1]},
        "financial_statement": {"latest_period": f[0], "latest_write": f[1]},
        "codal": {"latest_write": c[0], "reports": c[1]},
        "partial_parse_runs": partial,
    }


def quarantine_counts():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT details->>'domain', count(*) FROM ingestion.data_quality_issues "
            "WHERE issue_code='identity_conflict' AND resolved_at IS NULL GROUP BY 1"
        )
        return {r[0] or "unknown": r[1] for r in cur.fetchall()}


def write_csv(path: pathlib.Path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader()
        w.writerows(rows)


def main():
    assert canonical_hook.market_canonical_authority()
    assert canonical_hook.monthly_canonical_authority()
    assert canonical_hook.financial_canonical_authority()
    assert canonical_hook.codal_canonical_authority()
    OUT.mkdir(parents=True, exist_ok=True)

    before = table_counts()
    status = {"cycles": CYCLES, "rows": [], "errors": [], "market": {}, "codal": {}}
    recon = {"market": [], "monthly": [], "financial": []}
    cycle_counts = []

    for i in range(1, CYCLES + 1):
        # --- market ---
        try:
            mres, mrows = market_cycle()
            status["rows"].append({
                "cycle": i, "domain": "MARKET_PRICE", "operation": "ingest",
                "outcome": mres.get("outcome"), "status": mres.get("status"),
                "inserted": mres.get("inserted", 0), "skipped": mres.get("skipped", 0),
                "quarantined": mres.get("quarantined", 0),
                "legacy_mirror_status": mres.get("legacy_mirror_status"),
                "health": mres.get("health"), "retry_backlog": mres.get("retry_backlog"),
            })
            if i == 1:
                recon["market"] = [{"classification": c} for c in reconcile_market(mrows)]
        except Exception as exc:  # noqa: BLE001
            status["errors"].append({"cycle": i, "domain": "MARKET_PRICE", "error": repr(exc),
                                     "trace": traceback.format_exc()[-500:]})

        # --- monthly ---
        try:
            for cid, name, period, res in monthly_cycle():
                status["rows"].append({
                    "cycle": i, "domain": "MONTHLY_ACTIVITY", "operation": f"ingest:{name}:{period}",
                    "outcome": res.get("outcome"), "status": res.get("status"),
                    "inserted": res.get("inserted", 0), "skipped": res.get("skipped", 0),
                    "quarantined": 1 if res.get("status") == "quarantined" else 0,
                    "legacy_mirror_status": res.get("legacy_mirror_status"),
                    "health": res.get("health"), "retry_backlog": res.get("retry_backlog"),
                })
                if i == 1 and res.get("status") in ("written",):
                    vals = sqlserver_query(
                        "SELECT Value1,Value2,Value3 FROM dbo.mahane WHERE CompanyID=? AND ReportDate=?",
                        (cid, period),
                    )
                    if vals:
                        v = vals[0]
                        recon["monthly"].append({
                            "classification": reconcile_monthly(
                                cid, period, [v["Value1"], v["Value2"], v["Value3"]]
                            )
                        })
        except Exception as exc:  # noqa: BLE001
            status["errors"].append({"cycle": i, "domain": "MONTHLY_ACTIVITY", "error": repr(exc),
                                     "trace": traceback.format_exc()[-500:]})

        # --- financial ---
        try:
            for cid, name, period, res in financial_cycle():
                status["rows"].append({
                    "cycle": i, "domain": "FINANCIAL_STATEMENT", "operation": f"ingest:{name}:{period}",
                    "outcome": res.get("outcome"), "status": res.get("status"),
                    "inserted": res.get("inserted", 0), "skipped": res.get("skipped", 0),
                    "quarantined": 1 if res.get("status") == "quarantined" else 0,
                    "legacy_mirror_status": res.get("legacy_mirror_status"),
                    "health": res.get("health"), "retry_backlog": res.get("retry_backlog"),
                })
                if i == 1 and res.get("status") in ("written",):
                    for c in reconcile_financial(cid, period):
                        recon["financial"].append({"classification": c})
        except Exception as exc:  # noqa: BLE001
            status["errors"].append({"cycle": i, "domain": "FINANCIAL_STATEMENT", "error": repr(exc),
                                     "trace": traceback.format_exc()[-500:]})

        # --- codal ---
        try:
            letters, network, sem = codal_cycle(i)
            for lt in letters:
                status["rows"].append({
                    "cycle": i, "domain": "CODAL", "operation": f"letter:{lt['tracing_no']}",
                    "outcome": lt["outcome"], "status": lt["status"],
                    "inserted": 0, "skipped": 0,
                    "quarantined": 1 if lt["status"] == "quarantined" else 0,
                    "quarantine_class": lt["quarantine_class"],
                    "legacy_mirror_status": "not_attempted", "health": "", "retry_backlog": 0,
                })
            status["codal"].setdefault("cycles", []).append(
                {"cycle": i, "network": network, "letters": len(letters), "semantics": sem}
            )
        except Exception as exc:  # noqa: BLE001
            status["errors"].append({"cycle": i, "domain": "CODAL", "error": repr(exc),
                                     "trace": traceback.format_exc()[-500:]})

        cycle_counts.append({"cycle": i, **table_counts()})

    after = table_counts()
    fresh = freshness()
    quars = quarantine_counts()

    recon_counts = {
        "market": dict(Counter(r["classification"] for r in recon["market"])),
        "monthly": dict(Counter(r["classification"] for r in recon["monthly"])),
        "financial": dict(Counter(r["classification"] for r in recon["financial"])),
    }

    # Cross-domain interference: analytics score_runs must not move; parse_runs
    # must have no partial/in-progress rows; counts non-decreasing.
    interference = {
        "score_runs_unchanged": before["analytics.score_runs"] == after["analytics.score_runs"],
        "score_runs_before": before["analytics.score_runs"],
        "score_runs_after": after["analytics.score_runs"],
        "partial_parse_runs": fresh["partial_parse_runs"],
        "counts_non_decreasing": all(
            after[k] >= before[k] for k in before
        ),
        "deltas": {k: after[k] - before[k] for k in before},
    }

    total_inserted = sum(int(r.get("inserted") or 0) for r in status["rows"])
    domains = {
        "MARKET_PRICE": "CANONICAL",
        "MONTHLY_ACTIVITY": "CANONICAL",
        "FINANCIAL_STATEMENT": "CANONICAL",
        "CODAL": "CANONICAL",
    }
    domain_status = {}
    for d in domains:
        domain_status[d] = {
            "authority": "CANONICAL",
            "retry_backlog": canonical_hook.retry_backlog_count(
                {"MARKET_PRICE": "market_price", "MONTHLY_ACTIVITY": "monthly_activity",
                 "FINANCIAL_STATEMENT": "financial_statement", "CODAL": "codal_report"}[d]
            ),
            "quarantine_count": quars.get(
                {"MARKET_PRICE": "market_price", "MONTHLY_ACTIVITY": "monthly_activity",
                 "FINANCIAL_STATEMENT": "financial_statement", "CODAL": "codal_report"}[d], 0
            ),
        }
        domain_status[d]["health"] = "HEALTHY" if domain_status[d]["retry_backlog"] == 0 else "CANONICAL_BEHIND"

    # gate
    unexplained = 0
    for dom in ("market", "monthly", "financial"):
        for cls, n in recon_counts[dom].items():
            if cls in ("NUMERIC_MISMATCH", "MISSING_CANONICAL", "QUERY_ERROR", "UNCLASSIFIED_MISMATCH"):
                unexplained += n
    gate_pass = (
        not status["errors"]
        and interference["score_runs_unchanged"]
        and interference["partial_parse_runs"] == 0
        and interference["counts_non_decreasing"]
        and unexplained == 0
        and all(v["retry_backlog"] == 0 for v in domain_status.values())
    )
    gate = "CANONICAL_INGESTION_COMBINED_SOAK_PASS" if gate_pass else "CANONICAL_INGESTION_COMBINED_SOAK_FAIL"

    summary = {
        "generated_at": now(),
        "gate": gate,
        "mode": os.environ["CDF_INGESTION_MODE"],
        "canonical_db": os.environ["CDF_CANONICAL_DB"],
        "cycles": CYCLES,
        "total_inserted": total_inserted,
        "reconciliation": recon_counts,
        "unexplained_mismatches": unexplained,
        "freshness": fresh,
        "quarantine": quars,
        "cross_domain_interference": interference,
        "domains": domain_status,
        "codal": status["codal"],
        "errors": status["errors"],
    }

    write_csv(OUT / "combined_ingestion_soak.csv", status["rows"])
    (OUT / "combined_ingestion_soak.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "combined_soak_table_counts.csv").write_text("", encoding="utf-8")
    write_csv(OUT / "combined_soak_table_counts.csv", cycle_counts)
    (OUT / "canonical_ingestion_status.json").write_text(
        json.dumps({"generated_at": now(), "domains": domain_status}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({k: summary[k] for k in
                      ("gate", "total_inserted", "reconciliation", "quarantine",
                       "cross_domain_interference", "domains", "errors")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
