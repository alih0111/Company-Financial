#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""درج ردیف miandore2 برای دوره‌ای که نامه‌اش هست ولی ردیف legacy نیست.

زمینه: برای بخشی از نمادها آخرین سلول canonical سود و زیان فقط order 1 دارد
چون ردیف miandore2 آن دوره در منبع legacy ثبت نشده (شکست اسکرپر)؛ ستون‌های
order 2/3 (نظیر دوره قبل / سال مالی قبل) برای «روند حاشیه» و «رشد درآمد
دقیق» و TTM مستقیم لازم‌اند.

این اسکریپت همان کاری را می‌کند که save_profit_loss_to_sql در MianSql برای
ردیف غایب می‌کند (INSERT)، با همین قرارداد ارزش‌ها (میلیون ریال از خروجی
Excel کدال) و با گیت لنگر: جدول Excel باید سود عملیاتی order-1 سلول canonical
موجود را «دقیقاً» بازتولید کند، وگرنه هیچ نوشتنی انجام نمی‌شود.

اجرا:
    python revenue_backfill_v1/insert_missing_legacy_row.py شکام 1405/06/31
    python revenue_backfill_v1/insert_missing_legacy_row.py --batch \
        revenue_backfill_v1/output/symbols_for_backfill.txt
        # برای هر نماد: آخرین دورهٔ سود و زیان canonical که ردیف legacy آن
        # غایب است — با همان گیت لنگر.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "provenance_v1"))
sys.path.insert(0, str(ROOT / "canonical_postgres_v1_2_1" / "migration_tools"))

os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")

import codal_fs_fetch as F  # noqa: E402
import codal_fs_parse as P  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"


def sqlserver():
    for line in open(ROOT / "go-app" / ".env", encoding="utf-8-sig"):
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    import pyodbc

    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};"
          f"DATABASE={os.environ['DB_NAME']};UID={os.environ['DB_USER']};"
          f"PWD={os.environ['DB_PASSWORD']};TrustServerCertificate=yes;")
    cn = pyodbc.connect(cs, timeout=30)
    cn.autocommit = True
    return cn


def canonical_cell_anchor(company_id, period_g):
    """سود عملیاتی order-1 سلول canonical موجود (لنگر مبنا)."""
    from common import pg_pilot_conn
    pg = pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    cur.execute(
        """
        SELECT f.canonical_value
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id
        WHERE st.company_id IN (SELECT target_uuid FROM core.legacy_entity_map
                                WHERE entity_type='company' AND legacy_key=%s)
          AND st.statement_type='income_statement'
          AND st.period_end_date = %s
          AND f.metric_code='operating_profit' AND f.period_order = 1
        """,
        (company_id, period_g),
    )
    row = cur.fetchone()
    return (float(row[0]) / 1_000_000.0) if row and row[0] is not None else None


def letter_excel_for_period(company_id, period_g, symbol):
    """(excel_url, title) نامهٔ صورت مالی همان دوره — اول فهرست محلی، بعد API."""
    from common import pg_pilot_conn
    pg = pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    cur.execute(
        """
        SELECT r.title, r.source_url FROM ingestion.reports r
        WHERE r.company_id IN (SELECT target_uuid FROM core.legacy_entity_map
                               WHERE entity_type='company' AND legacy_key=%s)
          AND r.source='codal' AND r.period_end_date = %s
        ORDER BY r.published_at DESC NULLS LAST
        """,
        (company_id, period_g),
    )
    for title, source_url in cur.fetchall():
        if "LetterSerial=" in (source_url or ""):
            raw = source_url.split("LetterSerial=", 1)[1].split("&", 1)[0]
            serial = urllib.parse.unquote(raw)
            return (f"https://excel.codal.ir/service/Excel/GetAll/{serial}/0",
                    F._norm(title or ""))
    # جایگزین: API جستجوی کدال (با صبر برای 429)
    import jdatetime

    jy, jm, jd = (int(x) for x in period_g.split("-"))
    for attempt in range(10):
        letters = F.search_symbol(symbol, pages=5)
        err = next((L for L in letters if "__error__" in L), None)
        if err is None:
            break
        if "429" not in str(err):
            break
        print(f"    429 — ۴۵ ثانیه وقفه (تلاش {attempt + 1}/۱۰)", flush=True)
        time.sleep(45)
    for L in letters:
        if F.classify_letter(L) is None:
            continue
        period = F.jalali_date_in(L.get("Title") or "")
        if period is None or period.isoformat() != period_g:
            continue
        excel_url = L.get("ExcelUrl") or ""
        if excel_url:
            return excel_url, F._norm(L.get("Title") or "")
    return None, None


def insert_row(cur, name, company_id, report_date, period_g, excel_url, title):
    """گیت لنگر + INSERT ردیف؛ خروجی: (status, detail)."""
    cur.execute("SELECT COUNT(*) FROM dbo.miandore2 WHERE CompanyName=? AND ReportDate=?",
                (name, report_date))
    if cur.fetchone()[0]:
        return "exists", None

    anchor = canonical_cell_anchor(company_id, period_g)
    if anchor is None:
        return "no-anchor", None

    got = F.fetch_report_html({"excel_url": excel_url, "decision_url": None})
    if not got.get("ok"):
        return "fetch-failed", got.get("via")
    parsed = P.parse_report(got["html"], with_order3=True)
    tables = (parsed.get("statements_all") or {}).get("income_statement") or []
    cands = [t for t in tables
             if (t.get("bucket") or {}).get("operating_profit", {}).get(1) is not None
             and float(t["bucket"]["operating_profit"][1]) == float(anchor)]
    if len(cands) != 1:
        return "anchor-mismatch", len(cands)
    b = cands[0]["bucket"]

    vals = {
        "Num1_Value1": (b.get("eps") or {}).get(1),
        "Num1_Value2": (b.get("eps") or {}).get(2),
        "Num1_Value3": (b.get("eps") or {}).get(3),
        "Num4_Value1": (b.get("operating_eps") or {}).get(1),
        "Num4_Value2": (b.get("operating_eps") or {}).get(2),
        "Num4_Value3": (b.get("operating_eps") or {}).get(3),
        "OperatingProfitNew": (b.get("operating_profit") or {}).get(1),
        "OperatingProfitLastYear": (b.get("operating_profit") or {}).get(2),
        "OperatingProfitFYPrev": (b.get("operating_profit") or {}).get(3),
        "RevenueNew": (b.get("revenue") or {}).get(1),
        "RevenueLastYear": (b.get("revenue") or {}).get(2),
        "RevenueFYPrev": (b.get("revenue") or {}).get(3),
    }
    cols = ["CompanyID", "CompanyName", "ReportDate", "Url"]
    params = [company_id, name, report_date, excel_url]
    for k, v in vals.items():
        cols.append(k)
        params.append(v)
    cur.execute(
        f"INSERT INTO dbo.miandore2 ({', '.join(cols)}) "
        f"VALUES ({', '.join('?' for _ in cols)})",
        params,
    )
    return "inserted", vals


def main():
    import jdatetime

    if len(sys.argv) >= 3 and sys.argv[1] == "--batch":
        symbols = [s.strip() for s in open(sys.argv[2], encoding="utf-8") if s.strip()]
        cn = sqlserver()
        cur = cn.cursor()
        from common import pg_pilot_conn
        pg = pg_pilot_conn(autocommit=True)
        pgc = pg.cursor()
        results = []
        for i, name in enumerate(symbols, 1):
            cur.execute("SELECT TOP 1 CompanyID FROM dbo.miandore2 WHERE CompanyName=?", (name,))
            cid_row = cur.fetchone()
            if not cid_row:
                results.append({"symbol": name, "status": "no-legacy-company"})
                print(f"[{i}/{len(symbols)}] {name}: not in miandore2", flush=True)
                continue
            company_id = cid_row[0]

            # آخرین دورهٔ سود و زیان canonical این نماد
            pgc.execute(
                """
                SELECT st.period_end_date::text
                FROM fundamentals.financial_statements st
                WHERE st.company_id IN (SELECT target_uuid FROM core.legacy_entity_map
                                        WHERE entity_type='company' AND legacy_key=%s)
                  AND st.statement_type='income_statement'
                ORDER BY st.period_end_date DESC LIMIT 1
                """,
                (company_id,),
            )
            row = pgc.fetchone()
            if not row:
                results.append({"symbol": name, "status": "no-canonical-cell"})
                print(f"[{i}/{len(symbols)}] {name}: no canonical cell", flush=True)
                continue
            # period_g میلادی است؛ معادل جلالی با fromgregorian
            gy, gm, gd = (int(x) for x in row[0].split("-"))
            report_date = jdatetime.date.fromgregorian(
                date=dt.date(gy, gm, gd)).strftime("%Y/%m/%d")

            excel_url, title = letter_excel_for_period(company_id, period_g, name)
            if not excel_url:
                results.append({"symbol": name, "status": "letter-not-found",
                                "period": report_date})
                print(f"[{i}/{len(symbols)}] {name} {report_date}: letter not found", flush=True)
                continue
            status, detail = insert_row(cur, name, company_id, report_date, period_g,
                                        excel_url, title)
            results.append({"symbol": name, "period": report_date, "status": status,
                            "values": detail})
            print(f"[{i}/{len(symbols)}] {name} {report_date}: {status}", flush=True)
            time.sleep(1.0)
        cn.close()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "insert_missing_report.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        from collections import Counter
        print("خلاصه:", dict(Counter(r["status"] for r in results)))
        return

    name, report_date = sys.argv[1], sys.argv[2]
    jy, jm, jd = (int(x) for x in report_date.split("/"))
    period_g = jdatetime.date(jy, jm, jd).togregorian().isoformat()

    cn = sqlserver()
    cur = cn.cursor()
    cur.execute("SELECT TOP 1 CompanyID FROM dbo.miandore2 WHERE CompanyName=?", (name,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"نماد {name} در miandore2 نیست")
    company_id = row[0]

    anchor = canonical_cell_anchor(company_id, period_g)
    print(f"لنگر canonical (سود عملیاتی o1، میلیون ریال): {anchor}")

    excel_url, title = letter_excel_for_period(company_id, period_g, name)
    if not excel_url:
        raise SystemExit("نامهٔ کدال این دوره در فهرست محلی پیدا نشد")
    print(f"نامه: {title[:70]}")

    status, detail = insert_row(cur, name, company_id, report_date, period_g,
                                excel_url, title)
    if status == "inserted":
        print("مقادیر (میلیون ریال / ریال برای EPS):")
        print(json.dumps(detail, ensure_ascii=False, indent=1))
        print("INSERT انجام شد")
    else:
        print(f"وضعیت: {status} {detail or ''}")


if __name__ == "__main__":
    main()
