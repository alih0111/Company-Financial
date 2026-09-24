"""Pilot data migration: SQL Server (READ ONLY) -> PostgreSQL pilot DB.

Safety:
  * SQL Server: SELECT only. No DML/DDL.
  * Target: only the dedicated pilot database (name-guarded).
  * Requires an explicit --sample-file (no accidental full migration). A full run
    needs --all AND --i-understand-full-migration.
  * Transaction per company; failure rolls back that company only.

Usage:
    python migration_tools/pilot_migrate.py --sample-file migration_tools/sample_companies.json
    python migration_tools/pilot_migrate.py --sample-file ... --dry-run
    python migration_tools/pilot_migrate.py --sample-file ... --inject-failure <CompanyID>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

from common import (BASE, PILOT_DB, PILOT_DIR, jalali_to_gregorian, load_env, now_utc,
                    obs_hash, pg_pilot_conn, sqlserver_conn, to_decimal)

MULT = Decimal(1000000)

METRIC_DEFS = [
    ("revenue", "income_statement", "Revenue", "درآمد عملیاتی", "rial"),
    ("net_profit", "income_statement", "Net profit", "سود خالص", "rial"),
    ("operating_profit", "income_statement", "Operating profit", "سود عملیاتی", "rial"),
    ("finance_cost", "income_statement", "Finance cost", "هزینه مالی", "rial"),
    ("other_non_operating", "income_statement", "Other non-operating", "سایر درآمد/هزینه غیرعملیاتی", "rial"),
    ("eps", "income_statement", "Earnings per share", "سود خالص هر سهم", "rial_per_share"),
    ("operating_eps", "income_statement", "Operating EPS", "سود عملیاتی هر سهم", "rial_per_share"),
    ("capital", "income_statement", "Registered capital", "سرمایه", "rial"),
    ("total_assets", "balance_sheet", "Total assets", "جمع دارایی‌ها", "rial"),
    ("current_assets", "balance_sheet", "Current assets", "دارایی جاری", "rial"),
    ("total_liabilities", "balance_sheet", "Total liabilities", "جمع بدهی‌ها", "rial"),
    ("current_liabilities", "balance_sheet", "Current liabilities", "بدهی جاری", "rial"),
    ("total_equity", "balance_sheet", "Total equity", "حقوق مالکانه", "rial"),
    ("operating_cash_flow", "cash_flow", "Operating cash flow", "جریان نقدی عملیاتی", "rial"),
]

# (statement_type, metric_code, period_order, comparison_type, source_column, kind)
FACT_MAP = [
    ("income_statement", "eps", 1, "current", "Num1_Value1", "ps"),
    ("income_statement", "operating_eps", 1, "current", "Num4_Value1", "ps"),
    ("income_statement", "capital", 1, "current", "Num2_Value1", "m"),
    ("income_statement", "operating_profit", 1, "current", "OperatingProfitNew", "m"),
    ("income_statement", "finance_cost", 1, "current", "FinanceCostsNew", "m"),
    ("income_statement", "other_non_operating", 1, "current", "OtherNonOpNew", "m"),
    ("income_statement", "revenue", 1, "current", "RevenueNew", "m"),
    ("income_statement", "net_profit", 1, "current", "NetProfitAmount", "m"),
    ("income_statement", "eps", 2, "prior_year_same_period", "Num1_Value2", "ps"),
    ("income_statement", "operating_eps", 2, "prior_year_same_period", "Num4_Value2", "ps"),
    ("income_statement", "capital", 2, "prior_year_same_period", "Num2_Value2", "m"),
    ("income_statement", "operating_profit", 2, "prior_year_same_period", "OperatingProfitLastYear", "m"),
    ("income_statement", "finance_cost", 2, "prior_year_same_period", "FinanceCostsLastYear", "m"),
    ("income_statement", "other_non_operating", 2, "prior_year_same_period", "OtherNonOpLastYear", "m"),
    ("income_statement", "revenue", 2, "prior_year_same_period", "RevenueLastYear", "m"),
    ("income_statement", "net_profit", 2, "prior_year_same_period", "NetProfitAmountLY", "m"),
    ("income_statement", "eps", 3, "prior_fiscal_year", "Num1_Value3", "ps"),
    ("income_statement", "operating_eps", 3, "prior_fiscal_year", "Num4_Value3", "ps"),
    ("income_statement", "capital", 3, "prior_fiscal_year", "Num2_Value3", "m"),
    ("income_statement", "operating_profit", 3, "prior_fiscal_year", "OperatingProfitFYPrev", "m"),
    ("income_statement", "revenue", 3, "prior_fiscal_year", "RevenueFYPrev", "m"),
    ("income_statement", "net_profit", 3, "prior_fiscal_year", "NetProfitAmountFYPrev", "m"),
    ("balance_sheet", "total_assets", 1, "current", "TotalAssets", "m"),
    ("balance_sheet", "total_assets", 2, "prior_year_same_period", "TotalAssetsLY", "m"),
    ("balance_sheet", "current_assets", 1, "current", "CurrentAssets", "m"),
    ("balance_sheet", "current_assets", 2, "prior_year_same_period", "CurrentAssetsLY", "m"),
    ("balance_sheet", "total_liabilities", 1, "current", "TotalLiabilities", "m"),
    ("balance_sheet", "total_liabilities", 2, "prior_year_same_period", "TotalLiabilitiesLY", "m"),
    ("balance_sheet", "current_liabilities", 1, "current", "CurrentLiabilities", "m"),
    ("balance_sheet", "current_liabilities", 2, "prior_year_same_period", "CurrentLiabilitiesLY", "m"),
    ("balance_sheet", "total_equity", 1, "current", "TotalEquity", "m"),
    ("balance_sheet", "total_equity", 2, "prior_year_same_period", "TotalEquityLY", "m"),
    ("cash_flow", "operating_cash_flow", 1, "current", "OperatingCashFlow", "m"),
    ("cash_flow", "operating_cash_flow", 2, "prior_year_same_period", "OperatingCashFlowLY", "m"),
    ("cash_flow", "operating_cash_flow", 3, "prior_fiscal_year", "OperatingCashFlowFYPrev", "m"),
]


class Counters:
    def __init__(self):
        self.d = {}

    def add(self, table, n=1):
        self.d[table] = self.d.get(table, 0) + n

    def bump(self, table, inserted):
        if inserted:
            self.add(table, 1)

    def json(self):
        return dict(sorted(self.d.items()))


def ss_rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def pg_exec(conn, sql, params, counters, table, returning=False):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() if returning else None
    if returning and row is not None:
        counters.add(table)
        return row[0]
    return None


# ---------------------------------------------------------------------------
# identity resolution
# ---------------------------------------------------------------------------
def gather_identity(sscur, company_ids):
    """Return per legacy CompanyID: {name, symbol, ins, brs, mh, md, mph}."""
    placeholders = ",".join("?" for _ in company_ids)
    info = {cid: {"names": set(), "symbols": set(), "ins": None, "brs": set(), "mh": 0, "md": 0, "mph": 0}
            for cid in company_ids}

    for row in ss_rows(sscur, f"SELECT CompanyID, CompanyName, COUNT(*) n FROM dbo.mahane WHERE CompanyID IN ({placeholders}) GROUP BY CompanyID, CompanyName", company_ids):
        info[row["CompanyID"]]["mh"] += row["n"]
        if row["CompanyName"]:
            info[row["CompanyID"]]["names"].add(row["CompanyName"])

    for row in ss_rows(sscur, f"SELECT CompanyID, CompanyName, COUNT(*) n FROM dbo.miandore2 WHERE CompanyID IN ({placeholders}) GROUP BY CompanyID, CompanyName", company_ids):
        info[row["CompanyID"]]["md"] += row["n"]
        if row["CompanyName"]:
            info[row["CompanyID"]]["names"].add(row["CompanyName"])

    for row in ss_rows(sscur, f"""SELECT CompanyID, MAX(CompanyName) cn, MAX(Symbol) sym,
                                          MAX(InstrumentCode) ic, MAX(BrsName) brs, COUNT(*) n
                                   FROM dbo.MarketPriceHistory WHERE CompanyID IN ({placeholders})
                                   GROUP BY CompanyID""", company_ids):
        cid = row["CompanyID"]
        info[cid]["mph"] += row["n"]
        if row["cn"]:
            info[cid]["names"].add(row["cn"])
        if row["sym"]:
            info[cid]["symbols"].add(row["sym"])
        info[cid]["ins"] = str(row["ic"]) if row["ic"] is not None else info[cid]["ins"]
        if row["brs"]:
            info[cid]["brs"].add(row["brs"])

    return info


def cluster(info):
    """Group legacy CompanyIDs into canonical clusters keyed by ins_code (else name)."""
    clusters = {}
    for cid, rec in info.items():
        key = ("ins", str(rec["ins"])) if rec["ins"] else ("name", (sorted(rec["names"])[0].strip() if rec["names"] else cid))
        c = clusters.setdefault(key, {"cids": [], "names": set(), "symbols": set(), "brs": set(), "ins": rec["ins"]})
        c["cids"].append(cid)
        c["names"] |= rec["names"]
        c["symbols"] |= rec["symbols"]
        c["brs"] |= rec["brs"]
    return clusters


def choose_name(names):
    # deterministic: longest name wins (full legal name over short ticker),
    # tie-break lexicographic.
    if not names:
        return None
    return sorted(names, key=lambda s: (-len(s.strip()), s.strip()))[0].strip()


# ---------------------------------------------------------------------------
# upserts
# ---------------------------------------------------------------------------
def upsert_security(pg, counters, ins, symbol, brs):
    with pg.cursor() as cur:
        cur.execute("SELECT id, company_id FROM core.securities WHERE tsetmc_ins_code=%s", (ins,))
        row = cur.fetchone()
        if row:
            return row[0], row[1]
    return None, None


def create_company_security(pg, counters, display_name, ins, symbol, brs):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO core.companies (display_name, normalized_name) VALUES (%s,%s) RETURNING id",
            (display_name, display_name.strip().lower()))
        company_id = cur.fetchone()[0]
        counters.add("core.companies")
        cur.execute(
            """INSERT INTO core.securities (company_id, tsetmc_ins_code, codal_symbol, brs_name, security_type, is_primary)
               VALUES (%s,%s,%s,%s,'stock',true) RETURNING id""",
            (company_id, int(ins) if ins and ins.isdigit() else None, symbol, brs))
        security_id = cur.fetchone()[0]
        counters.add("core.securities")
    return company_id, security_id


def add_alias(pg, counters, security_id, alias_type, value, source="legacy_sqlserver"):
    if not value:
        return
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO core.security_aliases (security_id, alias_type, alias_value, source)
                       SELECT %s,%s,%s,%s
                       WHERE NOT EXISTS (SELECT 1 FROM core.security_aliases
                         WHERE security_id=%s AND alias_type=%s AND alias_value=%s AND COALESCE(source,'')=%s)""",
                    (security_id, alias_type, value, source, security_id, alias_type, value, source))
        counters.bump("core.security_aliases", cur.rowcount > 0)


def add_legacy_map(pg, counters, source_table, legacy_key, entity_type, target_uuid, method, confidence):
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO core.legacy_entity_map
                       (source_system, source_table, legacy_key, entity_type, target_uuid, mapping_method, confidence)
                       VALUES ('sqlserver_codal',%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source_system, source_table, legacy_key, entity_type) DO NOTHING""",
                    (source_table, legacy_key, entity_type, str(target_uuid), method, confidence))
        counters.bump("core.legacy_entity_map", cur.rowcount > 0)


def ensure_report(pg, counters, company_id, security_id, source, source_report_id, report_type,
                  period_end, jalali_text, title=None, source_url=None, published_at=None,
                  status="completed", retry=0):
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO ingestion.reports
            (company_id, security_id, source, source_report_id, report_type, title,
             period_end_date, jalali_period_text, published_at, source_url, processing_status, retry_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source, source_report_id)
            DO UPDATE SET title=EXCLUDED.title, processing_status=EXCLUDED.processing_status,
                          period_end_date=EXCLUDED.period_end_date
            RETURNING id""",
            (company_id, security_id, source, source_report_id, report_type, title,
             period_end, jalali_text, published_at, source_url, status, retry))
        rid = cur.fetchone()[0]
        counters.add("ingestion.reports")
    return rid


def ensure_version(pg, counters, report_id, content_hash, source_url=None):
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO ingestion.report_versions (report_id, version_no, content_hash, source_url)
                       VALUES (%s,1,%s,%s)
                       ON CONFLICT (report_id, version_no) DO NOTHING RETURNING id""",
                    (report_id, content_hash, source_url))
        row = cur.fetchone()
        if row:
            counters.add("ingestion.report_versions")
            return row[0]
        cur.execute("SELECT id FROM ingestion.report_versions WHERE report_id=%s AND version_no=1", (report_id,))
        return cur.fetchone()[0]


def ensure_parse_run(pg, counters, report_version_id, parser_name="legacy_sqlserver",
                     parser_version="legacy_import_v1"):
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO ingestion.parse_runs
                       (report_version_id, parser_name, parser_version, status, finished_at)
                       VALUES (%s,%s,%s,'completed',now())
                       ON CONFLICT (report_version_id, parser_name, parser_version) WHERE status='completed'
                       DO UPDATE SET status=EXCLUDED.status RETURNING id""",
                    (report_version_id, parser_name, parser_version))
        row = cur.fetchone()
        if row:
            counters.add("ingestion.parse_runs")
            return row[0]
        cur.execute("""SELECT id FROM ingestion.parse_runs
                       WHERE report_version_id=%s AND parser_name=%s AND parser_version=%s AND status='completed'""",
                    (report_version_id, parser_name, parser_version))
        return cur.fetchone()[0]


def legacy_report_chain(pg, counters, company_id, period_end, jalali_text, kind):
    """Create/lookup synthetic report+version+parse_run for a legacy normalized row."""
    srid = f"legacy:{company_id}:{period_end}:{kind}"
    content_hash = hashlib.sha256(srid.encode()).hexdigest()
    rid = ensure_report(pg, counters, company_id, None, "legacy_sqlserver", srid, kind,
                        period_end, jalali_text, status="completed")
    rv = ensure_version(pg, counters, rid, content_hash)
    pr = ensure_parse_run(pg, counters, rv)
    return rid, rv, pr


def ensure_statement(pg, counters, company_id, report_id, report_version_id, parse_run_id,
                     statement_type, period_end, is_cumulative):
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO fundamentals.financial_statements
            (company_id, report_id, report_version_id, parse_run_id, statement_type,
             period_end_date, is_cumulative, reported_currency_unit)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'million_rial')
            ON CONFLICT (parse_run_id, statement_type) DO NOTHING RETURNING id""",
            (company_id, report_id, report_version_id, parse_run_id, statement_type, period_end, is_cumulative))
        row = cur.fetchone()
        if row:
            counters.add("fundamentals.financial_statements")
            return row[0]
        cur.execute("SELECT id FROM fundamentals.financial_statements WHERE parse_run_id=%s AND statement_type=%s",
                    (parse_run_id, statement_type))
        return cur.fetchone()[0]


def insert_fact(pg, counters, statement_id, metric_code, period_order, comparison, reported, kind):
    canonical_unit = "rial_per_share" if kind == "ps" else "rial"
    reported_unit = "rial_per_share" if kind == "ps" else "million_rial"
    canonical = reported if kind == "ps" else reported * MULT
    with pg.cursor() as cur:
        cur.execute("""INSERT INTO fundamentals.financial_facts
            (statement_id, metric_code, period_order, comparison_type,
             reported_value, reported_unit, canonical_value, canonical_unit)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (statement_id, metric_code, period_order) DO NOTHING""",
            (statement_id, metric_code, period_order, comparison, reported, reported_unit, canonical, canonical_unit))
        counters.bump("fundamentals.financial_facts", cur.rowcount > 0)


# ---------------------------------------------------------------------------
# domain migrations
# ---------------------------------------------------------------------------
def migrate_monthly(pg, counters, sscur, company_id, cids):
    placeholders = ",".join("?" for _ in cids)
    rows = ss_rows(sscur, f"""SELECT CompanyID, ReportDate, Value1, Value2, Value3
                              FROM dbo.mahane WHERE CompanyID IN ({placeholders})""", cids)
    n = 0
    for r in rows:
        gd = jalali_to_gregorian(r["ReportDate"])
        if gd is None:
            continue
        rid, rv, pr = legacy_report_chain(pg, counters, company_id, gd, r["ReportDate"], "monthly")
        sales = to_decimal(r["Value3"])
        with pg.cursor() as cur:
            cur.execute("""INSERT INTO fundamentals.monthly_activities
                (company_id, report_id, report_version_id, parse_run_id, period_end_date,
                 jalali_period_text, production_quantity, sales_quantity, quantity_unit,
                 sales_amount_rial, reported_sales_amount, reported_currency_unit, reported_unit_multiplier)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,'million_rial',1000000)
                ON CONFLICT (parse_run_id) DO NOTHING""",
                (company_id, rid, rv, pr, gd, r["ReportDate"],
                 to_decimal(r["Value1"]), to_decimal(r["Value2"]),
                 None if sales is None else sales * MULT, sales))
            if cur.rowcount > 0:
                counters.add("fundamentals.monthly_activities")
                n += 1
    return n


def migrate_financials(pg, counters, sscur, company_id, cids):
    placeholders = ",".join("?" for _ in cids)
    cols = [m[4] for m in FACT_MAP]
    collist = ", ".join("[" + c + "]" for c in cols)
    rows = ss_rows(sscur,
                   f"SELECT CompanyID, ReportDate, {collist} FROM dbo.miandore2 WHERE CompanyID IN ({placeholders})",
                   cids)
    n_facts = 0
    for r in rows:
        gd = jalali_to_gregorian(r["ReportDate"])
        if gd is None:
            continue
        by_stmt = {}
        for (stype, mcode, order, comp, src, kind) in FACT_MAP:
            val = to_decimal(r.get(src))
            if val is None:
                continue
            reported = val
            by_stmt.setdefault(stype, []).append((mcode, order, comp, reported, kind))
        if not by_stmt:
            continue
        rid, rv, pr = legacy_report_chain(pg, counters, company_id, gd, r["ReportDate"], "financial")
        for stype, facts in by_stmt.items():
            is_cum = stype in ("income_statement", "cash_flow")
            sid = ensure_statement(pg, counters, company_id, rid, rv, pr, stype, gd, is_cum)
            for (mcode, order, comp, reported, kind) in facts:
                insert_fact(pg, counters, sid, mcode, order, comp, reported, kind)
                n_facts += 1
    return n_facts


def migrate_prices(pg, counters, sscur, security_id, cids):
    placeholders = ",".join("?" for _ in cids)
    rows = ss_rows(sscur, f"""SELECT InstrumentCode, GregorianDate, JalaliDate,
            HighPrice, LowPrice, ClosingPrice, LastPrice, FirstPrice, YesterdayPrice,
            ClosingChange, ClosingChangePercent, LastChange, LastChangePercent,
            Volume, TradeValue, TradeCount, Url, CollectedAt
            FROM dbo.MarketPriceHistory WHERE CompanyID IN ({placeholders})""", cids)
    n = 0
    for r in rows:
        fields = {
            "high": str(r["HighPrice"]), "low": str(r["LowPrice"]), "close": str(r["ClosingPrice"]),
            "last": str(r["LastPrice"]), "first": str(r["FirstPrice"]), "yesterday": str(r["YesterdayPrice"]),
            "vol": str(r["Volume"]), "tval": str(r["TradeValue"]), "tcount": str(r["TradeCount"]),
        }
        h = obs_hash(security_id, r["GregorianDate"], "adjusted", "brs", "legacy_brs_adjusted", fields)
        with pg.cursor() as cur:
            cur.execute("""INSERT INTO market.price_observations
                (security_id, trade_date, price_series, first_price_rial, high_price_rial, low_price_rial,
                 closing_price_rial, last_price_rial, yesterday_price_rial, closing_change_rial,
                 closing_change_percent, last_change_rial, last_change_percent, volume, trade_value_rial,
                 trade_count, is_adjusted, adjustment_method, adjustment_version, provenance,
                 source, source_url, collected_at, jalali_date_text, observation_hash)
                VALUES (%s,%s,'adjusted',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,'vendor_adjusted',
                        'legacy_brs_adjusted',%s,'brs',%s,%s,%s,%s)
                ON CONFLICT (security_id, trade_date, source, price_series, observation_hash) DO NOTHING""",
                (security_id, r["GregorianDate"],
                 to_decimal(r["FirstPrice"]), to_decimal(r["HighPrice"]), to_decimal(r["LowPrice"]),
                 to_decimal(r["ClosingPrice"]), to_decimal(r["LastPrice"]), to_decimal(r["YesterdayPrice"]),
                 to_decimal(r["ClosingChange"]), to_decimal(r["ClosingChangePercent"]),
                 to_decimal(r["LastChange"]), to_decimal(r["LastChangePercent"]),
                 r["Volume"], to_decimal(r["TradeValue"]), r["TradeCount"],
                 json.dumps({"legacy_table": "MarketPriceHistory", "legacy_instrument": str(r["InstrumentCode"])}),
                 r["Url"], r["CollectedAt"], r["JalaliDate"], h))
            if cur.rowcount > 0:
                counters.add("market.price_observations")
                n += 1
    return n


def migrate_codal_reports(pg, counters, sscur, company_id, symbols):
    if not symbols:
        return 0
    placeholders = ",".join("?" for _ in symbols)
    rows = ss_rows(sscur, f"""SELECT CodalReportId, Ticker, LetterType, ReportTitle, ReportDate,
                                     PublishedAt, SourceUrl, Status, Attempts
                              FROM dbo.CodalReports WHERE Ticker IN ({placeholders})""", symbols)
    status_map = {"completed": "completed", "failed": "failed", "unsupported": "unsupported",
                  "discovered": "discovered", "processing": "processing"}
    n = 0
    for r in rows:
        gd = jalali_to_gregorian(r["ReportDate"])
        st = status_map.get((r["Status"] or "").strip().lower(), "discovered")
        rid = ensure_report(pg, counters, company_id, None, "codal", r["CodalReportId"], "financial",
                            gd, r["ReportDate"], title=r["ReportTitle"], source_url=r["SourceUrl"],
                            published_at=r["PublishedAt"], status=st, retry=r["Attempts"] or 0)
        rv = ensure_version(pg, counters, rid, hashlib.sha256(f"codal:{r['CodalReportId']}".encode()).hexdigest(),
                            r["SourceUrl"])
        ensure_parse_run(pg, counters, rv)
        add_legacy_map(pg, counters, "CodalReports", r["CodalReportId"], "report", rid, "source_report_id", "1.0")
        n += 1
    return n


# ---------------------------------------------------------------------------
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-file")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--i-understand-full-migration", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--inject-failure", default=None)
    args = ap.parse_args()

    if not args.sample_file and not (args.all and args.i_understand_full_migration):
        print("Refusing: provide --sample-file (or --all WITH --i-understand-full-migration).")
        return 2

    load_env()
    ss = sqlserver_conn()
    sscur = ss.cursor()

    if args.sample_file:
        p = Path(args.sample_file)
        if not p.exists():
            p = BASE / args.sample_file
        sample = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise SystemExit("full --all migration is not implemented in the pilot tool")

    companies = sample["companies"]
    all_cids = [cid for c in companies for cid in c["company_ids"]]

    info = gather_identity(sscur, all_cids)
    clusters = cluster(info)

    counters = Counters()
    issues = []
    per_company = []

    pg = pg_pilot_conn()
    # seed metric definitions (idempotent)
    with pg.cursor() as cur:
        for (mc, st, cn, fa, unit) in METRIC_DEFS:
            cur.execute("""INSERT INTO fundamentals.metric_definitions
                (metric_code, statement_type, canonical_name, display_name_fa, expected_unit)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT (metric_code) DO NOTHING""", (mc, st, cn, fa, unit))
    pg.commit()

    for comp in companies:
        label = comp["label"]
        cids = comp["company_ids"]
        try:
            pg = pg_pilot_conn()
            pg.autocommit = False
            # identity
            rec = info[cids[0]]
            ins = rec["ins"]
            names = set()
            symbols = set()
            brs = set()
            for cid in cids:
                names |= info[cid]["names"]
                symbols |= info[cid]["symbols"]
                brs |= info[cid]["brs"]
            display = choose_name(names)
            symbol = choose_name(symbols)
            brs_name = choose_name(brs)

            sec_id, company_id = upsert_security(pg, counters, ins, symbol, brs_name)
            if sec_id is None:
                company_id, sec_id = create_company_security(pg, counters, display, ins, symbol, brs_name)

            if args.inject_failure and args.inject_failure in cids:
                raise RuntimeError(f"injected failure for {label}")

            for cid in cids:
                add_legacy_map(pg, counters, "mahane", cid, "company", company_id, "ins_code", "1.0")
                add_legacy_map(pg, counters, "miandore2", cid, "company", company_id, "ins_code", "1.0")
                add_legacy_map(pg, counters, "MarketPriceHistory", cid, "company", company_id, "ins_code", "1.0")
                add_legacy_map(pg, counters, "MarketPriceHistory", cid, "security", sec_id, "ins_code", "1.0")
            add_legacy_map(pg, counters, "MarketPriceHistory", str(ins), "security", sec_id, "insp_code", "1.0")
            for nm in names:
                add_alias(pg, counters, sec_id, "company_name", nm)
            for sm in symbols:
                add_alias(pg, counters, sec_id, "symbol", sm)

            n_reports = migrate_codal_reports(pg, counters, sscur, company_id, sorted(symbols))
            n_monthly = migrate_monthly(pg, counters, sscur, company_id, cids)
            n_facts = migrate_financials(pg, counters, sscur, company_id, cids)
            n_prices = migrate_prices(pg, counters, sscur, sec_id, cids)

            if args.dry_run:
                pg.rollback()
                outcome = "dry-run-rollback"
            else:
                pg.commit()
                outcome = "committed"
            per_company.append({"label": label, "company_id": str(company_id), "security_id": str(sec_id),
                                "cids": cids, "reports": n_reports, "monthly": n_monthly,
                                "facts": n_facts, "prices": n_prices, "outcome": outcome})
            print(f"  [{label}] {outcome}: reports={n_reports} monthly={n_monthly} facts={n_facts} prices={n_prices}")
        except Exception as exc:  # noqa: BLE001
            pg.rollback()
            issues.append({"label": label, "company_ids": cids, "error": str(exc)})
            per_company.append({"label": label, "cids": cids, "outcome": "rolled-back", "error": str(exc)})
            print(f"  [{label}] ROLLED BACK: {exc}")
        finally:
            pg.close()

    ss.close()

    summary = {
        "generated_at": now_utc().isoformat(timespec="seconds"),
        "pilot_db": PILOT_DB,
        "sample_labels": [c["label"] for c in companies],
        "counters": counters.json(),
        "per_company": per_company,
        "issues": issues,
        "dry_run": args.dry_run,
    }
    (PILOT_DIR / "_migration_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("counters:", counters.json())
    print("issues:", len(issues))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
