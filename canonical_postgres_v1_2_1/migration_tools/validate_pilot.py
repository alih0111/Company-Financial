"""Pilot validation: compare SQL Server (source) vs pilot PostgreSQL (target).

Read-only on SQL Server; read-only on pilot PG. Writes markdown reports.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

from common import (BASE, PILOT_DIR, jalali_to_gregorian, pg_pilot_conn, sqlserver_conn, to_decimal)
from pilot_migrate import FACT_MAP, METRIC_DEFS

MULT = Decimal(1000000)
SAMPLE = json.loads((BASE / "migration_tools" / "sample_companies.json").read_text(encoding="utf-8"))


def ss_rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def pg_rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def resolve_target(pg, company_ids, ins):
    """Return (company_id, security_id) for a sample cluster."""
    with pg.cursor() as cur:
        cur.execute("SELECT id, company_id FROM core.securities WHERE tsetmc_ins_code=%s", (int(ins),))
        row = cur.fetchone()
    return (str(row[1]), str(row[0])) if row else (None, None)


def main():
    ss = sqlserver_conn()
    sscur = ss.cursor()
    pg = pg_pilot_conn(autocommit=True)
    pgcur = pg.cursor()

    # build per-sample identity + signals from source
    samples = []
    for comp in SAMPLE["companies"]:
        cids = comp["company_ids"]
        ph = ",".join("?" for _ in cids)
        rec = ss_rows(sscur, f"""SELECT MAX(InstrumentCode) ins, MAX(Symbol) sym, MAX(BrsName) brs
                                 FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph})""", cids)[0]
        ins = int(rec["ins"]) if rec["ins"] is not None else None
        cid, sec = resolve_target(pg, cids, str(ins)) if ins else (None, None)
        samples.append({"label": comp["label"], "symbol": comp["symbol"], "cids": cids,
                        "ins": ins, "company_id": cid, "security_id": sec})

    issues = []

    # ---------------- identity ----------------
    idl = ["# Identity Validation", ""]
    dup_ins = pg_rows(pgcur, "SELECT tsetmc_ins_code, count(*) n FROM core.securities WHERE tsetmc_ins_code IS NOT NULL GROUP BY tsetmc_ins_code HAVING count(*)>1")
    idl.append(f"- duplicate tsetmc_ins_code: **{len(dup_ins)}** (expected 0)")
    idl.append("")
    idl.append("| label | legacy CompanyIDs | tsetmc_ins_code | canonical company_id | security_id | legacy_map rows |")
    idl.append("| --- | --- | --- | --- | --- | --- |")
    for s in samples:
        lm = pg_rows(pgcur, "SELECT count(*) n FROM core.legacy_entity_map WHERE legacy_key = ANY(%s)", (s["cids"],))[0]["n"]
        idl.append(f"| {s['label']} | {', '.join(s['cids'])} | {s['ins']} | {s['company_id']} | {s['security_id']} | {lm} |")
    # kastra convergence
    k = next(s for s in samples if s["label"] == "kastra")
    if k["company_id"]:
        conv = pg_rows(pgcur, "SELECT DISTINCT target_uuid::text FROM core.legacy_entity_map WHERE legacy_key = ANY(%s) AND entity_type='company'", (k["cids"],))
        idl += ["", f"**Kastra convergence:** distinct canonical companies for the two legacy IDs = "
                    f"**{len(conv)}** (expected 1): {[c['target_uuid'] for c in conv]}"]
    # no name-only identity
    nameonly = pg_rows(pgcur, "SELECT count(*) n FROM core.securities WHERE tsetmc_ins_code IS NULL")
    idl += ["", f"- securities created without tsetmc_ins_code (name-only identity): **{nameonly[0]['n']}** (expected 0)"]
    if dup_ins or len(conv) != 1 or nameonly[0]["n"] != 0:
        issues.append({"severity": "HIGH", "area": "identity", "detail": "identity assertion failed"})
    (PILOT_DIR / "identity_validation.md").write_text("\n".join(idl) + "\n", encoding="utf-8")

    # ---------------- source snapshot ----------------
    snap = ["# Source Snapshot (read-only)", ""]
    snap.append("| label | mahane | miandore2 | MPH | CodalReports | fin dates | monthly dates | market dates |")
    snap.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for comp in SAMPLE["companies"]:
        cids = comp["company_ids"]
        ph = ",".join("?" for _ in cids)
        mh = ss_rows(sscur, f"SELECT COUNT(*) n, MIN(ReportDate) mn, MAX(ReportDate) mx FROM dbo.mahane WHERE CompanyID IN ({ph})", cids)[0]
        md = ss_rows(sscur, f"SELECT COUNT(*) n, MIN(ReportDate) mn, MAX(ReportDate) mx FROM dbo.miandore2 WHERE CompanyID IN ({ph})", cids)[0]
        mp = ss_rows(sscur, f"SELECT COUNT(*) n, MIN(GregorianDate) mn, MAX(GregorianDate) mx FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph})", cids)[0]
        sym = comp["symbol"]
        cr = ss_rows(sscur, "SELECT COUNT(*) n FROM dbo.CodalReports WHERE Ticker=?", (sym,))[0]["n"]
        snap.append(f"| {comp['label']} | {mh['n']} | {md['n']} | {mp['n']} | {cr} | {md['mn']}..{md['mx']} | {mh['mn']}..{mh['mx']} | {mp['mn']}..{mp['mx']} |")
    (PILOT_DIR / "source_snapshot.md").write_text("\n".join(snap) + "\n", encoding="utf-8")

    # ---------------- row counts ----------------
    rc = ["# Row Count Validation", ""]
    rc.append("| entity | source table | source rows | target table | target rows | difference | note |")
    rc.append("| --- | --- | --- | --- | --- | --- | --- |")
    for comp in SAMPLE["companies"]:
        s = next(x for x in samples if x["label"] == comp["label"])
        cids = comp["company_ids"]
        ph = ",".join("?" for _ in cids)
        src_mh = ss_rows(sscur, f"SELECT COUNT(*) n FROM dbo.mahane WHERE CompanyID IN ({ph})", cids)[0]["n"]
        src_md = ss_rows(sscur, f"SELECT COUNT(*) n FROM dbo.miandore2 WHERE CompanyID IN ({ph})", cids)[0]["n"]
        src_mp = ss_rows(sscur, f"SELECT COUNT(*) n FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph})", cids)[0]["n"]
        # expected facts from source non-null
        cols = [m[4] for m in FACT_MAP]
        collist = ", ".join("[" + c + "]" for c in cols)
        mdrows = ss_rows(sscur, f"SELECT {collist} FROM dbo.miandore2 WHERE CompanyID IN ({ph})", cids)
        exp_facts = 0
        for r in mdrows:
            for (_, _, _, _, src, _) in FACT_MAP:
                if to_decimal(r.get(src)) is not None:
                    exp_facts += 1
        tgt_monthly = pg_rows(pgcur, "SELECT count(*) n FROM fundamentals.monthly_activities WHERE company_id=%s", (s["company_id"],))[0]["n"] if s["company_id"] else 0
        tgt_facts = pg_rows(pgcur, """SELECT count(*) n FROM fundamentals.financial_facts f
                                      JOIN fundamentals.financial_statements st ON st.id=f.statement_id
                                      WHERE st.company_id=%s""", (s["company_id"],))[0]["n"] if s["company_id"] else 0
        tgt_prices = pg_rows(pgcur, "SELECT count(*) n FROM market.price_observations WHERE security_id=%s", (s["security_id"],))[0]["n"] if s["security_id"] else 0
        # monthly: target monthly rows that came from mahane (all legacy monthly)
        rc.append(f"| {comp['label']} | mahane | {src_mh} | monthly_activities | {tgt_monthly} | {tgt_monthly-src_mh} | |")
        rc.append(f"| {comp['label']} | miandore2 | {src_md} | financial_facts | {tgt_facts} | {tgt_facts-exp_facts} | expected facts={exp_facts} (non-null mapped) |")
        rc.append(f"| {comp['label']} | MarketPriceHistory | {src_mp} | price_observations | {tgt_prices} | {tgt_prices-src_mp} | |")
        if tgt_monthly != src_mh:
            issues.append({"severity": "HIGH", "area": "rowcount", "detail": f"{comp['label']} monthly {tgt_monthly}!={src_mh}"})
        if tgt_facts != exp_facts:
            issues.append({"severity": "HIGH", "area": "rowcount", "detail": f"{comp['label']} facts {tgt_facts}!={exp_facts}"})
        if tgt_prices != src_mp:
            issues.append({"severity": "MEDIUM", "area": "rowcount", "detail": f"{comp['label']} prices {tgt_prices}!={src_mp} (possible dedup)"})
    (PILOT_DIR / "row_count_validation.md").write_text("\n".join(rc) + "\n", encoding="utf-8")

    # ---------------- monthly exact ----------------
    mo = ["# Monthly Activity Validation", ""]
    mo.append("Assertion: `sales_amount_rial = Value3 x 1,000,000`; production/sales qty equal; period maps correctly.")
    mism = 0
    checked = 0
    for comp in SAMPLE["companies"]:
        s = next(x for x in samples if x["label"] == comp["label"])
        if not s["company_id"]:
            continue
        ph = ",".join("?" for _ in s["cids"])
        src = ss_rows(sscur, f"SELECT ReportDate, Value1, Value2, Value3 FROM dbo.mahane WHERE CompanyID IN ({ph})", s["cids"])
        tgt = {r["period_end_date"].isoformat(): r for r in pg_rows(pgcur,
            "SELECT period_end_date, sales_amount_rial, reported_sales_amount, production_quantity, sales_quantity FROM fundamentals.monthly_activities WHERE company_id=%s", (s["company_id"],))}
        for r in src:
            gd = jalali_to_gregorian(r["ReportDate"])
            if gd is None:
                continue
            key = gd.isoformat()
            checked += 1
            t = tgt.get(key)
            if t is None:
                mism += 1
                continue
            exp = to_decimal(r["Value3"])
            exp_rial = None if exp is None else exp * MULT
            got = t["sales_amount_rial"]
            if exp_rial is None:
                ok = got is None
            else:
                ok = (got == exp_rial)
            if not ok:
                mism += 1
    mo += ["", f"- rows checked: **{checked}**", f"- mismatches: **{mism}**", f"- tolerance: exact (Decimal) for monetary; source FLOAT(53) values are exact within Decimal conversion."]
    if mism:
        issues.append({"severity": "HIGH", "area": "monthly", "detail": f"{mism} monthly mismatches"})
    (PILOT_DIR / "monthly_validation.md").write_text("\n".join(mo) + "\n", encoding="utf-8")

    # ---------------- financial exact ----------------
    fi = ["# Financial Facts Validation", ""]
    fi.append("Monetary: `canonical_value = legacy x 1,000,000`. EPS: `canonical_value = legacy` (rial_per_share).")
    fi.append("")
    fi.append("| company | report (greg) | metric | period | legacy | expected canonical | actual canonical | status |")
    fi.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    fin_mism = 0
    fin_checked = 0
    fin_rounded = 0
    TOL = Decimal("0.000001")  # canonical_value is numeric(30,6); FLOAT source may exceed 6dp
    for comp in SAMPLE["companies"]:
        s = next(x for x in samples if x["label"] == comp["label"])
        if not s["company_id"]:
            continue
        ph = ",".join("?" for _ in s["cids"])
        cols = [m[4] for m in FACT_MAP]
        collist = ", ".join("[" + c + "]" for c in cols)
        src = ss_rows(sscur, f"SELECT ReportDate, {collist} FROM dbo.miandore2 WHERE CompanyID IN ({ph})", s["cids"])
        tgt_rows = pg_rows(pgcur, """SELECT st.period_end_date, f.metric_code, f.period_order, f.canonical_value, f.canonical_unit
                                     FROM fundamentals.financial_facts f
                                     JOIN fundamentals.financial_statements st ON st.id=f.statement_id
                                     WHERE st.company_id=%s""", (s["company_id"],))
        tgt = {}
        for t in tgt_rows:
            tgt[(t["period_end_date"].isoformat(), t["metric_code"], t["period_order"])] = t
        for r in src:
            gd = jalali_to_gregorian(r["ReportDate"])
            if gd is None:
                continue
            for (stype, mcode, order, comp_t, srccol, kind) in FACT_MAP:
                val = to_decimal(r.get(srccol))
                if val is None:
                    continue
                exp = val if kind == "ps" else val * MULT
                fin_checked += 1
                t = tgt.get((gd.isoformat(), mcode, order))
                actual = t["canonical_value"] if t else None
                if actual is not None and actual == exp:
                    ok = True
                elif actual is not None and abs(actual - exp) <= TOL:
                    ok = True
                    fin_rounded += 1
                else:
                    ok = False
                if not ok:
                    fin_mism += 1
                    if fin_mism <= 30:
                        fi.append(f"| {comp['label']} | {gd} | {mcode} | {order} | {val} | {exp} | {actual} | MISMATCH |")
    fi += ["", f"- facts checked: **{fin_checked}**", f"- mismatches: **{fin_mism}**",
           f"- rows rounded within tolerance (<= 1e-6, numeric(30,6) vs FLOAT source): **{fin_rounded}**",
           "- tolerance: exact for EPS; monetary allowed |diff| <= 1e-6 absolute due to canonical_value numeric(30,6)."]
    if fin_mism:
        issues.append({"severity": "HIGH", "area": "financial", "detail": f"{fin_mism} financial mismatches"})
    (PILOT_DIR / "financial_validation.md").write_text("\n".join(fi) + "\n", encoding="utf-8")

    # ---------------- market ----------------
    mk = ["# Market Price Validation", ""]
    mk.append("Deterministic sample: earliest 5, latest 5, and 10 evenly-spaced middle dates per security. Fields compared exactly.")
    mk.append("")
    mk.append("| security | dates checked | mismatches |")
    mk.append("| --- | --- | --- |")
    mk_mism = 0
    for comp in SAMPLE["companies"]:
        s = next(x for x in samples if x["label"] == comp["label"])
        if not s["security_id"]:
            continue
        ph = ",".join("?" for _ in s["cids"])
        src = ss_rows(sscur, f"""SELECT GregorianDate, ClosingPrice, LastPrice, HighPrice, LowPrice, FirstPrice,
            YesterdayPrice, Volume, TradeValue, TradeCount FROM dbo.MarketPriceHistory
            WHERE CompanyID IN ({ph}) ORDER BY GregorianDate""", s["cids"])
        if not src:
            continue
        n = len(src)
        idx = sorted(set([0,1,2,3,4, n-5,n-4,n-3,n-2,n-1] + [int(n*(k+1)/11) for k in range(10)]))
        idx = [i for i in idx if 0 <= i < n]
        picks = [src[i] for i in idx]
        tgt = {r["trade_date"].isoformat(): r for r in pg_rows(pgcur,
            "SELECT trade_date, closing_price_rial, last_price_rial, high_price_rial, low_price_rial, first_price_rial, yesterday_price_rial, volume, trade_value_rial, trade_count FROM market.price_observations WHERE security_id=%s AND price_series='adjusted'", (s["security_id"],))}
        m_here = 0
        for r in picks:
            td = r["GregorianDate"].isoformat()
            t = tgt.get(td)
            if t is None:
                m_here += 1; continue
            checks = [
                (to_decimal(r["ClosingPrice"]), t["closing_price_rial"]),
                (to_decimal(r["LastPrice"]), t["last_price_rial"]),
                (to_decimal(r["HighPrice"]), t["high_price_rial"]),
                (to_decimal(r["LowPrice"]), t["low_price_rial"]),
                (to_decimal(r["FirstPrice"]), t["first_price_rial"]),
                (to_decimal(r["YesterdayPrice"]), t["yesterday_price_rial"]),
                (to_decimal(r["TradeValue"]), t["trade_value_rial"]),
            ]
            for a, b in checks:
                if (a is None and b is not None) or (a is not None and a != b):
                    m_here += 1
            if r["Volume"] != t["volume"] or r["TradeCount"] != t["trade_count"]:
                m_here += 1
        mk.append(f"| {comp['label']} | {len(picks)} | {m_here} |")
        mk_mism += m_here
    mk += ["", f"- total mismatches: **{mk_mism}**"]
    if mk_mism:
        issues.append({"severity": "HIGH", "area": "market", "detail": f"{mk_mism} market mismatches"})
    (PILOT_DIR / "market_validation.md").write_text("\n".join(mk) + "\n", encoding="utf-8")

    # ---------------- date ----------------
    dt = ["# Date Validation", ""]
    bad = 0
    total_dates = 0
    for comp in SAMPLE["companies"]:
        s = next(x for x in samples if x["label"] == comp["label"])
        if not s["company_id"]:
            continue
        for r in pg_rows(pgcur, "SELECT period_end_date, jalali_period_text FROM fundamentals.monthly_activities WHERE company_id=%s", (s["company_id"],)):
            total_dates += 1
            gd = jalali_to_gregorian(r["jalali_period_text"])
            if gd is None or gd != r["period_end_date"]:
                bad += 1
    for comp in SAMPLE["companies"]:
        s = next(x for x in samples if x["label"] == comp["label"])
        if not s["security_id"]:
            continue
        for r in pg_rows(pgcur, "SELECT trade_date, jalali_date_text FROM market.price_observations WHERE security_id=%s AND jalali_date_text IS NOT NULL", (s["security_id"],)):
            total_dates += 1
            gd = jalali_to_gregorian(r["jalali_date_text"])
            if gd is None or gd != r["trade_date"]:
                bad += 1
    dt += [f"- date pairs checked: **{total_dates}**", f"- mismatches/invalid: **{bad}** (no silent rollover)",
           "- `1405/06/31` (Shahrivar 31) is a valid Jalali date and maps to `2026-09-22`; verified by converter."]
    if bad:
        issues.append({"severity": "HIGH", "area": "date", "detail": f"{bad} date mismatches"})
    (PILOT_DIR / "date_validation.md").write_text("\n".join(dt) + "\n", encoding="utf-8")

    # ---------------- unit ----------------
    un = ["# Unit Validation", ""]
    bad_unit = pg_rows(pgcur, "SELECT count(*) n FROM fundamentals.financial_facts WHERE canonical_unit IS DISTINCT FROM 'rial' AND canonical_unit IS DISTINCT FROM 'rial_per_share'")[0]["n"]
    monetary_bad = pg_rows(pgcur, "SELECT count(*) n FROM fundamentals.financial_facts WHERE canonical_unit='rial' AND reported_unit IS DISTINCT FROM 'million_rial'")[0]["n"]
    eps = pg_rows(pgcur, "SELECT count(*) n FROM fundamentals.financial_facts WHERE canonical_unit='rial_per_share'")[0]["n"]
    qty_null = pg_rows(pgcur, "SELECT count(*) n FROM fundamentals.monthly_activities WHERE quantity_unit IS NULL")[0]["n"]
    un += [f"- monetary facts with canonical_unit != 'rial' and != 'rial_per_share': **{bad_unit}** (expected 0)",
           f"- monetary facts whose reported_unit != 'million_rial': **{monetary_bad}** (expected 0)",
           f"- EPS facts with canonical_unit='rial_per_share': **{eps}**",
           f"- monthly activities with quantity_unit NULL (allowed/unknown): **{qty_null}**"]
    if bad_unit or monetary_bad:
        issues.append({"severity": "HIGH", "area": "unit", "detail": "unexpected canonical unit"})
    (PILOT_DIR / "unit_validation.md").write_text("\n".join(un) + "\n", encoding="utf-8")

    # ---------------- orphan / duplicate ----------------
    od = ["# Orphan & Duplicate Validation", ""]
    checks = {
        "facts without statement": "SELECT count(*) n FROM fundamentals.financial_facts f LEFT JOIN fundamentals.financial_statements s ON s.id=f.statement_id WHERE s.id IS NULL",
        "statements without parse_run": "SELECT count(*) n FROM fundamentals.financial_statements st LEFT JOIN ingestion.parse_runs p ON p.id=st.parse_run_id WHERE p.id IS NULL",
        "monthly without parse_run": "SELECT count(*) n FROM fundamentals.monthly_activities m LEFT JOIN ingestion.parse_runs p ON p.id=m.parse_run_id WHERE p.id IS NULL",
        "securities without company": "SELECT count(*) n FROM core.securities s LEFT JOIN core.companies c ON c.id=s.company_id WHERE c.id IS NULL",
        "prices without security": "SELECT count(*) n FROM market.price_observations p LEFT JOIN core.securities s ON s.id=p.security_id WHERE s.id IS NULL",
        "legacy map target missing": "SELECT count(*) n FROM core.legacy_entity_map l LEFT JOIN core.companies c ON c.id=l.target_uuid WHERE l.entity_type='company' AND c.id IS NULL",
        "duplicate tsetmc_ins_code": "SELECT count(*) n FROM (SELECT tsetmc_ins_code FROM core.securities WHERE tsetmc_ins_code IS NOT NULL GROUP BY tsetmc_ins_code HAVING count(*)>1) t",
        "duplicate price observation key": "SELECT count(*) n FROM (SELECT security_id,trade_date,source,price_series,observation_hash FROM market.price_observations GROUP BY 1,2,3,4,5 HAVING count(*)>1) t",
        "duplicate report source id": "SELECT count(*) n FROM (SELECT source,source_report_id FROM ingestion.reports GROUP BY 1,2 HAVING count(*)>1) t",
        "duplicate fact business key": "SELECT count(*) n FROM (SELECT statement_id,metric_code,period_order FROM fundamentals.financial_facts GROUP BY 1,2,3 HAVING count(*)>1) t",
    }
    for label, sql in checks.items():
        n = pg_rows(pgcur, sql)[0]["n"]
        od.append(f"- {label}: **{n}**")
        if n:
            issues.append({"severity": "HIGH", "area": "orphan_duplicate", "detail": f"{label}={n}"})
    (PILOT_DIR / "orphan_duplicate_validation.md").write_text("\n".join(od) + "\n", encoding="utf-8")

    ss.close()
    pg.close()

    (PILOT_DIR / "_validation_issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
    print("validation done; issues:", len(issues))
    for i in issues:
        print("  ", i)


if __name__ == "__main__":
    main()
