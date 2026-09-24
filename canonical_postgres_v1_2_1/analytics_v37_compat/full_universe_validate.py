"""Full-universe canonical input validation (source vs shadow)."""

from __future__ import annotations

import sys
from pathlib import Path
from decimal import Decimal

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))

from common import pg_pilot_conn, sqlserver_conn  # noqa: E402
from pilot_migrate import FACT_MAP  # noqa: E402

PARITY = BASE / "analytics_parity"
MULT = Decimal(1000000)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ss = sqlserver_conn()
    sc = ss.cursor()
    pg = pg_pilot_conn(autocommit=True)
    pc = pg.cursor()

    def ssq(sql, p=()):
        sc.execute(sql, p)
        return sc.fetchall()

    def pgq(sql, p=()):
        pc.execute(sql, p)
        return pc.fetchall()

    import json as _json
    uc = _json.loads((PARITY / "universe_companies.json").read_text(encoding="utf-8"))
    included_cids = sorted({cid for comp in uc["companies"] for cid in comp["company_ids"]})
    ph = ",".join("?" for _ in included_cids)

    src_mahane = ssq(f"SELECT COUNT(*) FROM dbo.mahane WHERE CompanyID IN ({ph})", included_cids)[0][0]
    src_miandore2 = ssq(f"SELECT COUNT(*) FROM dbo.miandore2 WHERE CompanyID IN ({ph})", included_cids)[0][0]
    src_mph = ssq(f"SELECT COUNT(*) FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph})", included_cids)[0][0]
    src_codal = ssq("SELECT COUNT(*) FROM dbo.CodalReports")[0][0]

    cols = [m[4] for m in FACT_MAP]
    expr = " + ".join(f"SUM(CASE WHEN [{c}] IS NOT NULL THEN 1 ELSE 0 END)" for c in cols)
    exp_facts = ssq(f"SELECT {expr} FROM dbo.miandore2 WHERE CompanyID IN ({ph})", included_cids)[0][0]

    tgt_monthly = pgq("SELECT COUNT(*) FROM fundamentals.monthly_activities")[0][0]
    tgt_facts = pgq("SELECT COUNT(*) FROM fundamentals.financial_facts")[0][0]
    tgt_prices = pgq("SELECT COUNT(*) FROM market.price_observations")[0][0]
    tgt_reports = pgq("SELECT COUNT(*) FROM ingestion.reports")[0][0]
    tgt_companies = pgq("SELECT COUNT(*) FROM core.companies")[0][0]
    tgt_securities = pgq("SELECT COUNT(*) FROM core.securities")[0][0]

    orphan_sql = {
        "facts without statement": "SELECT count(*) FROM fundamentals.financial_facts f LEFT JOIN fundamentals.financial_statements s ON s.id=f.statement_id WHERE s.id IS NULL",
        "statements without parse_run": "SELECT count(*) FROM fundamentals.financial_statements st LEFT JOIN ingestion.parse_runs p ON p.id=st.parse_run_id WHERE p.id IS NULL",
        "monthly without parse_run": "SELECT count(*) FROM fundamentals.monthly_activities m LEFT JOIN ingestion.parse_runs p ON p.id=m.parse_run_id WHERE p.id IS NULL",
        "securities without company": "SELECT count(*) FROM core.securities s LEFT JOIN core.companies c ON c.id=s.company_id WHERE c.id IS NULL",
        "prices without security": "SELECT count(*) FROM market.price_observations p LEFT JOIN core.securities s ON s.id=p.security_id WHERE s.id IS NULL",
        "legacy map company target missing": "SELECT count(*) FROM core.legacy_entity_map l LEFT JOIN core.companies c ON c.id=l.target_uuid WHERE l.entity_type='company' AND c.id IS NULL",
    }
    dup_sql = {
        "duplicate tsetmc_ins_code": "SELECT count(*) FROM (SELECT tsetmc_ins_code FROM core.securities WHERE tsetmc_ins_code IS NOT NULL GROUP BY 1 HAVING count(*)>1) t",
        "duplicate price observation key": "SELECT count(*) FROM (SELECT security_id,trade_date,source,price_series,observation_hash FROM market.price_observations GROUP BY 1,2,3,4,5 HAVING count(*)>1) t",
        "duplicate report source id": "SELECT count(*) FROM (SELECT source,source_report_id FROM ingestion.reports GROUP BY 1,2 HAVING count(*)>1) t",
        "duplicate fact business key": "SELECT count(*) FROM (SELECT statement_id,metric_code,period_order FROM fundamentals.financial_facts GROUP BY 1,2,3 HAVING count(*)>1) t",
        "name-only securities": "SELECT count(*) FROM core.securities WHERE tsetmc_ins_code IS NULL",
    }

    orphans = {k: pgq(v)[0][0] for k, v in orphan_sql.items()}
    dups = {k: pgq(v)[0][0] for k, v in dup_sql.items()}

    # unit check
    unit_bad = pgq("SELECT count(*) FROM fundamentals.financial_facts WHERE canonical_unit NOT IN ('rial','rial_per_share')")[0][0]
    monetary_bad = pgq("SELECT count(*) FROM fundamentals.financial_facts WHERE canonical_unit='rial' AND reported_unit <> 'million_rial'")[0][0]
    qty_null = pgq("SELECT count(*) FROM fundamentals.monthly_activities WHERE quantity_unit IS NULL")[0][0]

    issues = []
    def chk(cond, area, detail, sev="HIGH"):
        if not cond:
            issues.append({"severity": sev, "area": area, "detail": detail})

    chk(tgt_monthly == src_mahane, "counts", f"monthly {tgt_monthly}!={src_mahane}")
    chk(tgt_facts == exp_facts, "counts", f"facts {tgt_facts}!={exp_facts}")
    chk(tgt_prices == src_mph, "counts", f"prices {tgt_prices}!={src_mph}")
    for k, v in orphans.items():
        chk(v == 0, "orphan", f"{k}={v}")
    for k, v in dups.items():
        chk(v == 0, "duplicate", f"{k}={v}")
    chk(unit_bad == 0, "unit", f"bad canonical_unit={unit_bad}")
    chk(monetary_bad == 0, "unit", f"monetary reported_unit<>{monetary_bad}")

    lines = ["# Full-Universe Canonical Migration Validation", ""]
    lines += ["## Counts", "", "| object | source | target | expected | equal |", "| --- | --- | --- | --- | --- |"]
    lines += [
        f"| monthly (mahane) | {src_mahane} | {tgt_monthly} | {src_mahane} | {tgt_monthly==src_mahane} |",
        f"| facts (miandore2 non-null mapped) | {src_miandore2} rows | {tgt_facts} | {exp_facts} | {tgt_facts==exp_facts} |",
        f"| prices (MPH) | {src_mph} | {tgt_prices} | {src_mph} | {tgt_prices==src_mph} |",
        f"| reports (incl synthetic legacy) | CodalReports {src_codal} | {tgt_reports} | legacy-driven | n/a |",
    ]
    lines += ["", f"- canonical companies: {tgt_companies}, securities: {tgt_securities}"]
    lines += ["", "## Orphans", ""] + [f"- {k}: **{v}**" for k, v in orphans.items()]
    lines += ["", "## Duplicates / identity", ""] + [f"- {k}: **{v}**" for k, v in dups.items()]
    lines += ["", "## Units", "", f"- bad canonical_unit: **{unit_bad}**", f"- monetary reported_unit mismatch: **{monetary_bad}**", f"- quantity_unit NULL (allowed): **{qty_null}**"]
    lines += ["", f"## Gate", "", f"**{'FULL_UNIVERSE_INPUTS_PASS' if not issues else 'FULL_UNIVERSE_INPUTS_FAIL'}**", ""]
    (PARITY / "full_universe_migration_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (PARITY / "_universe_validation_issues.json").write_text(__import__("json").dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")

    ss.close(); pg.close()
    print("gate:", "PASS" if not issues else "FAIL", "issues:", issues)
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
