import sys
sys.path.insert(0, r"D:\RFA\Company-Financial\go-app\py2\src")
import os
from dotenv import load_dotenv
load_dotenv(r"D:\RFA\Company-Financial\go-app\.env")
os.environ.setdefault("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from canonical_ingest.db import transaction

NAME = "کاسپین"

with transaction() as c:
    cur = c.cursor()
    cur.execute("""SELECT c.id::text, c.display_name, c.legal_name
                   FROM core.companies c
                   WHERE c.display_name LIKE %s OR c.legal_name LIKE %s""", (f"%{NAME}%", f"%{NAME}%"))
    comps = cur.fetchall()
    print("companies:", comps)
    if not comps:
        sys.exit(0)
    cid = comps[0][0]
    cur.execute("SELECT legacy_key, source_system FROM core.legacy_entity_map WHERE entity_type='company' AND target_uuid=%s", (cid,))
    print("legacy map:", cur.fetchall())

    cur.execute("""SELECT fs.id::text, fs.statement_type, fs.period_end_date::text, fs.fiscal_year, fs.fiscal_month,
                          fs.duration_months, fs.is_cumulative, fs.report_id::text, fs.report_version_id::text, fs.parse_run_id::text,
                          r.source_report_id, r.jalali_period_text
                   FROM fundamentals.financial_statements fs
                   JOIN ingestion.reports r ON r.id=fs.report_id
                   WHERE fs.company_id=%s
                   ORDER BY fs.period_end_date DESC""", (cid,))
    stmts = cur.fetchall()
    print("\nstatements:", len(stmts))
    for s in stmts:
        print(s)

    cur.execute("""SELECT r.jalali_period_text, f.metric_code, f.period_order,
                          f.reported_value, f.canonical_value, f.reported_unit, f.canonical_unit
                   FROM fundamentals.financial_facts f
                   JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
                   JOIN ingestion.reports r ON r.id=fs.report_id
                   WHERE fs.company_id=%s AND f.metric_code IN ('eps','net_profit','revenue')
                   ORDER BY r.jalali_period_text DESC, f.metric_code, f.period_order""", (cid,))
    facts = cur.fetchall()
    print("\nfacts eps/net_profit/revenue:", len(facts))
    for f in facts:
        print(f)
