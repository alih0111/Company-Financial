"""Bounded dual-write sample runner + reconciliation.

Usage (from repo root, with the ingestion venv):
    set CDF_INGESTION_MODE=dual_write
    set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
    python -m canonical_ingest            # uses defaults below
    python -m canonical_ingest --sample-file path.json

SQL Server is read-only here; the canonical write is additive. LEGACY_ONLY mode
performs no canonical writes.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from decimal import Decimal
from pathlib import Path

import jdatetime
import pyodbc

from .config import canonical_dsn, load_mode
from .db import transaction
from .identity import resolve_company, resolve_security
from .reconcile import (
    EXACT_EQUIVALENT, MISSING_CANONICAL, EXPECTED_UNIT_CONVERSION, NUMERIC_MISMATCH,
    reconcile_fact, reconcile_market, reconcile_monthly,
)
from .service import dual_write_financial, dual_write_market, dual_write_monthly

DEFAULT_SAMPLE = ["قاسم", "تاصیکو", "کسرا", "زگلدشت", "افق", "دکپسول", "هجرت", "چخزر", "بفجر", "خاهن"]

PERIOD_ORDER_LABELS = {1: "current", 2: "prior_year_same_period", 3: "prior_fiscal_year"}

# (statement_type, metric_code, period_order, source_column, kind, comparison)
FACT_MAP = [
    ("income_statement", "eps", 1, "Num1_Value1", "ps", "current"),
    ("income_statement", "operating_eps", 1, "Num4_Value1", "ps", "current"),
    ("income_statement", "capital", 1, "Num2_Value1", "m", "current"),
    ("income_statement", "operating_profit", 1, "OperatingProfitNew", "m", "current"),
    ("income_statement", "finance_cost", 1, "FinanceCostsNew", "m", "current"),
    ("income_statement", "other_non_operating", 1, "OtherNonOpNew", "m", "current"),
    ("income_statement", "revenue", 1, "RevenueNew", "m", "current"),
    ("income_statement", "net_profit", 1, "NetProfitAmount", "m", "current"),
    ("income_statement", "eps", 2, "Num1_Value2", "ps", "prior_year_same_period"),
    ("income_statement", "operating_eps", 2, "Num4_Value2", "ps", "prior_year_same_period"),
    ("income_statement", "capital", 2, "Num2_Value2", "m", "prior_year_same_period"),
    ("income_statement", "operating_profit", 2, "OperatingProfitLastYear", "m", "prior_year_same_period"),
    ("income_statement", "revenue", 2, "RevenueLastYear", "m", "prior_year_same_period"),
    ("income_statement", "net_profit", 2, "NetProfitAmountLY", "m", "prior_year_same_period"),
    ("income_statement", "eps", 3, "Num1_Value3", "ps", "prior_fiscal_year"),
    ("income_statement", "capital", 3, "Num2_Value3", "m", "prior_fiscal_year"),
    ("income_statement", "operating_profit", 3, "OperatingProfitFYPrev", "m", "prior_fiscal_year"),
    ("income_statement", "revenue", 3, "RevenueFYPrev", "m", "prior_fiscal_year"),
    ("income_statement", "net_profit", 3, "NetProfitAmountFYPrev", "m", "prior_fiscal_year"),
    ("balance_sheet", "total_assets", 1, "TotalAssets", "m", "current"),
    ("balance_sheet", "current_assets", 1, "CurrentAssets", "m", "current"),
    ("balance_sheet", "total_liabilities", 1, "TotalLiabilities", "m", "current"),
    ("balance_sheet", "current_liabilities", 1, "CurrentLiabilities", "m", "current"),
    ("balance_sheet", "total_equity", 1, "TotalEquity", "m", "current"),
    ("cash_flow", "operating_cash_flow", 1, "OperatingCashFlow", "m", "current"),
]
MULT = Decimal(1000000)


def _sqlserver_conn():
    server = os.environ["DB_SERVER"]
    db = os.environ["DB_NAME"]
    user = os.environ["DB_USER"]
    pwd = os.environ["DB_PASSWORD"]
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={db};"
          f"UID={user};PWD={pwd};TrustServerCertificate=yes;Connection Timeout=10")
    return pyodbc.connect(cs, timeout=15)


def _rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _jalali_to_gregorian(text: str) -> str | None:
    try:
        y, m, d = (int(x) for x in str(text).strip().replace("-", "/").split("/"))
        return jdatetime.date(y, m, d).togregorian().isoformat()
    except Exception:
        return None


def _dec(value):
    if value is None:
        return None
    return Decimal(str(value))


def _sample_companies(ss, names):
    ph = ",".join("?" for _ in names)
    found = {}
    for table in ("miandore2", "mahane", "MarketPriceHistory"):
        for r in _rows(ss.cursor(), f"SELECT CompanyName, CompanyID FROM dbo.{table} WHERE CompanyName IN ({ph})", names):
            found.setdefault(r["CompanyName"], r["CompanyID"])
    return [(n, found[n]) for n in names if n in found]


def run(sample_names):
    mode = load_mode()
    print(f"mode={mode.value} dsn_db={canonical_dsn().rsplit('/', 1)[-1]}")
    if mode.value == "legacy_only":
        print("LEGACY_ONLY: no canonical writes will be performed")

    ss = _sqlserver_conn()
    companies = _sample_companies(ss, sample_names)
    print(f"sample companies resolved: {len(companies)}")

    results = []
    recon = []

    for name, cid in companies:
        # ---- monthly ----
        monthly = _rows(ss.cursor(),
                        "SELECT CompanyID, CompanyName, ReportDate, Value1, Value2, Value3 "
                        "FROM dbo.mahane WHERE CompanyID=? ORDER BY ReportDate DESC", (cid,))[:6]
        for row in monthly:
            g = _jalali_to_gregorian(row["ReportDate"])
            if not g:
                continue
            res = dual_write_monthly(
                legacy_company_id=cid, period_end_date=g, jalali_period_text=row["ReportDate"],
                production_quantity=_dec(row["Value1"]), sales_quantity=_dec(row["Value2"]),
                reported_sales_amount=_dec(row["Value3"]),
                sales_amount_rial=(_dec(row["Value3"]) * MULT) if row["Value3"] is not None else None,
                reported_currency_unit="million_rial", reported_unit_multiplier=MULT,
            )
            results.append(_result_row("monthly_activity", name, cid, row["ReportDate"], res))
            if res.written:
                recon.append(_reconcile_monthly(cid, g, row))

        # ---- financial ----
        fin = _rows(ss.cursor(),
                    "SELECT * FROM dbo.miandore2 WHERE CompanyID=? ORDER BY ReportDate DESC", (cid,))[:4]
        for row in fin:
            g = _jalali_to_gregorian(row["ReportDate"])
            if not g:
                continue
            facts = _build_facts(row)
            if not facts:
                continue
            res = dual_write_financial(
                legacy_company_id=cid, period_end_date=g, jalali_period_text=row["ReportDate"],
                facts=facts,
            )
            results.append(_result_row("financial_statement", name, cid, row["ReportDate"], res))
            if res.written:
                recon.append(_reconcile_financial(cid, g, facts))

        # ---- market ----
        mph = _rows(ss.cursor(),
                    "SELECT TOP 30 CompanyID, Symbol, CompanyName, InstrumentCode, "
                    "CONVERT(NVARCHAR(20), GregorianDate, 23) AS gd, JalaliDate, "
                    "ISNULL(FirstPrice,0) fp, ISNULL(HighPrice,0) hp, ISNULL(LowPrice,0) lp, "
                    "ISNULL(ClosingPrice,0) cp, ISNULL(LastPrice,0) lastp, ISNULL(YesterdayPrice,0) yp, "
                    "ISNULL(ClosingChange,0) cc, ISNULL(ClosingChangePercent,0) ccp, "
                    "ISNULL(Volume,0) vol, ISNULL(TradeValue,0) tv, ISNULL(TradeCount,0) tc, "
                    "CONVERT(NVARCHAR(40), CollectedAt, 126) AS collected "
                    "FROM dbo.MarketPriceHistory WHERE CompanyID=? ORDER BY GregorianDate DESC", (cid,))
        if mph:
            observations = [{
                "trade_date": r["gd"], "jalali_date_text": r["JalaliDate"],
                "first_price_rial": _dec(r["fp"]), "high_price_rial": _dec(r["hp"]),
                "low_price_rial": _dec(r["lp"]), "closing_price_rial": _dec(r["cp"]),
                "last_price_rial": _dec(r["lastp"]), "yesterday_price_rial": _dec(r["yp"]),
                "closing_change_rial": _dec(r["cc"]), "closing_change_percent": _dec(r["ccp"]),
                "volume": int(r["vol"] or 0), "trade_value_rial": _dec(r["tv"]),
                "trade_count": int(r["tc"] or 0),
                "collected_at": (r["collected"] + "+03:30") if r["collected"] else None,
                "is_adjusted": True, "price_series": "adjusted",
            } for r in mph]
            res = dual_write_market(legacy_company_id=cid, symbol=mph[0]["Symbol"], observations=observations)
            results.append(_result_row("market_price", name, cid, f"{len(mph)} obs", res))
            if res.written:
                recon.append(_reconcile_market(cid, mph))

    out_dir = _out_dir()
    _write_csv(out_dir / "dual_write_results.csv", results)
    _write_csv(out_dir / "ingestion_reconciliation.csv", recon)
    _summarize(results, recon)
    return results, recon


def _build_facts(row):
    facts = []
    for stype, mcode, order, col, kind, comp in FACT_MAP:
        if col not in row or row[col] is None:
            continue
        reported = _dec(row[col])
        facts.append({
            "statement_type": stype, "metric_code": mcode, "period_order": order,
            "comparison_type": comp, "reported_value": reported,
            "reported_unit": "rial_per_share" if kind == "ps" else "million_rial",
            "canonical_value": reported if kind == "ps" else reported * MULT,
            "canonical_unit": "rial_per_share" if kind == "ps" else "rial",
            "kind": kind, "source_row_key": f"{stype}:{mcode}:{order}",
            "is_cumulative": stype in ("income_statement", "cash_flow"),
        })
    return facts


def _result_row(domain, name, cid, period, res):
    return {
        "domain": domain, "company_name": name, "legacy_company_id": cid, "period": period,
        "status": res.status, "inserted": res.inserted, "skipped": res.skipped,
        "detail": res.detail, "error": res.error,
    }


def _reconcile_monthly(cid, g, row):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT ma.production_quantity, ma.sales_quantity, ma.reported_sales_amount, ma.sales_amount_rial
               FROM fundamentals.monthly_activities ma
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=ma.company_id AND lem.legacy_key=%s
               WHERE ma.period_end_date=%s LIMIT 1""", (cid, g))
        r = cur.fetchone()
    canon = None if not r else {"production_quantity": r[0], "sales_quantity": r[1],
                                "reported_sales_amount": r[2], "sales_amount_rial": r[3]}
    legacy = {"production_quantity": _dec(row["Value1"]), "sales_quantity": _dec(row["Value2"]),
              "reported_sales_amount": _dec(row["Value3"])}
    return {"domain": "monthly_activity", "company_name": row.get("CompanyName", ""),
            "legacy_company_id": cid, "period": row["ReportDate"],
            "classification": reconcile_monthly(legacy, canon)}


def _reconcile_financial(cid, g, facts):
    out = []
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT f.metric_code, f.period_order, f.reported_value, f.canonical_value
               FROM fundamentals.financial_facts f
               JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
               JOIN core.legacy_entity_map lem
                 ON lem.entity_type='company' AND lem.target_uuid=fs.company_id AND lem.legacy_key=%s
               WHERE fs.period_end_date=%s""", (cid, g))
        cmap = {(r[1], r[0]): {"metric_code": r[0], "reported_value": r[2], "canonical_value": r[3]}
                for r in cur.fetchall()}
    for f in facts:
        canon = cmap.get((f["period_order"], f["metric_code"]))
        out.append({"domain": "financial_fact", "company_name": "", "legacy_company_id": cid,
                    "period": g, "metric": f"{f['metric_code']}:{f['period_order']}",
                    "classification": reconcile_fact(f, canon)})
    return {"domain": "financial_fact", "company_name": "", "legacy_company_id": cid,
            "period": g, "classification": _aggregate([o["classification"] for o in out]),
            "detail": f"{len(out)} facts"}


def _reconcile_market(cid, mph):
    out = []
    with transaction() as conn:
        cur = conn.cursor()
        sec = resolve_security(cur, legacy_company_id=cid)
        dates = [r["gd"] for r in mph]
        if sec and dates:
            cur.execute(
                """SELECT trade_date::text, closing_price_rial, volume FROM market.price_observations
                   WHERE security_id=%s AND trade_date = ANY(%s) AND source='brs' AND price_series='adjusted'""",
                (sec, dates))
            cmap = {r[0]: {"trade_date": r[0], "closing_price_rial": r[1], "volume": r[2]} for r in cur.fetchall()}
        else:
            cmap = {}
    for r in mph:
        canon = cmap.get(r["gd"])
        legacy = {"trade_date": r["gd"], "closing_price_rial": _dec(r["cp"]), "volume": int(r["vol"] or 0)}
        out.append(reconcile_market(legacy, canon))
    return {"domain": "market_price", "company_name": mph[0].get("CompanyName", ""),
            "legacy_company_id": cid, "period": f"{len(mph)} obs",
            "classification": _aggregate(out), "detail": f"{len(mph)} observations"}


def _aggregate(classes):
    for c in (NUMERIC_MISMATCH, MISSING_CANONICAL):
        if c in classes:
            return c
    if EXPECTED_UNIT_CONVERSION in classes:
        return EXPECTED_UNIT_CONVERSION
    return EXACT_EQUIVALENT


def _out_dir():
    here = Path(__file__).resolve()
    go_app = here.parents[3]
    out = go_app.parent / "ingestion_migration_v1" / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_csv(path: Path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = []
    for row in rows:
        for k in row.keys():
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader()
        w.writerows(rows)


def _summarize(results, recon):
    from collections import Counter
    print("dual-write status:", dict(Counter(r["status"] for r in results)))
    print("reconciliation:", dict(Counter(r["classification"] for r in recon)))
    inserted = sum(r["inserted"] for r in results)
    skipped = sum(r["skipped"] for r in results)
    print(f"inserted={inserted} skipped(idempotent)={skipped}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="canonical_ingest")
    ap.add_argument("--sample-file", help="JSON list of company names")
    args = ap.parse_args(argv)
    names = DEFAULT_SAMPLE
    if args.sample_file and Path(args.sample_file).exists():
        names = json.loads(Path(args.sample_file).read_text(encoding="utf-8"))
    run(names)


if __name__ == "__main__":
    main()
