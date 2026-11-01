#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""بک‌فیل ستون‌های NULL فروش (RevenueNew و خانواده) در dbo.miandore2 — گام ۲.

چرا: ستون‌های فروش منبع legacy برای اکثر گزارش‌های تاریخی بخشی از نمادها
NULL است (اسکرپر قدیمی این ستون‌ها را نداشت)؛ در نتیجه فکت‌های canonical
«revenue» غایب‌اند و پنج فاکتور امتیاز (رشد درآمد دقیق، حاشیه عملیاتی،
حاشیه خالص، روند حاشیه، P/S) «بدون داده → ۳۰٪» می‌شوند.

چه می‌کند:
  * برای هر نماد، نامه‌های «اطلاعات و صورت‌های مالی» (میاندوره‌ای + سالانه)
    را از مسیرهای عمومی کدال می‌گیرد — API جستجو + خروجی Excel
    (search.codal.ir و excel.codal.ir؛ بدون مرورگر، بدون ورود).
  * با پارسر اکید پروژه (provenance_v1/codal_fs_parse.parse_report) جدول‌های
    سود و زیان هر نامه را می‌خواند (ستون‌های ۱/۲/۳ ردیف «درآمدهای عملیاتی»).
  * برای هر ردیف miandore2 که ستون فروشش NULL است، بین همهٔ نسخه‌های نامهٔ
    همان دوره (اصلی/اصلاحیه) آن نسخه‌ای انتخاب می‌شود که لنگرهای خودِ ردیف —
    EPS ریالی، EPS عملیاتی یا سود عملیاتی ذخیره‌شدهٔ MianSql — را دقیقاً
    بازتولید کند؛ اگر هیچ نسخه‌ای دقیق نبود، انحراف نسبی ≤ ۱٪ با ثبت انحراف.
    این تضمین می‌کند درآمدِ پرشده هم‌مبنای بقیهٔ ستون‌های همان ردیف است
    (نامهٔ اصلاحیه‌دار دو نسخه با اعداد متفاوت دارد).
  * فقط ردیف موجودِ همان دوره با COALESCE به‌روزرسانی می‌شود — هیچ مقدار
    موجودی بازنویسی نمی‌شود و هیچ ردیفی ساخته نمی‌شود.
  * واحد: خروجی Excel کدال «میلیون ریال» است؛ miandore2 هم «میلیون ریال».

قواعد سخت:
  * بدون حدس: بدون لنگر، یا بدون تطبیق جدول → رد شدن و ثبت در گزارش.
  * idempotent: اجرای مکرر بی‌خطر است (COALESCE فقط NULL را پر می‌کند).

اجرا:
    python revenue_backfill_v1/backfill_revenue_legacy.py شکام
    python revenue_backfill_v1/backfill_revenue_legacy.py --symbols-file \
        revenue_backfill_v1/output/symbols_for_backfill.txt
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(ROOT / "go-app" / "py2" / "src"))

import codal_fs_fetch as F  # noqa: E402
import codal_fs_parse as P  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"

REVENUE_COLUMNS = ("RevenueNew", "RevenueLastYear", "RevenueFYPrev")
ANCHOR_REL_DEV_MAX = 0.01  # ۱٪ — فقط برای وقتی هیچ نسخه‌ای دقیق نیست؛ ثبت می‌شود


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


def revenue_rows(cur, name):
    """[{report_date, nulls, anchors}] برای ردیف‌های نماد که ستون فروش NULL دارند.

    anchors = مقادیر همان ردیف که اسکرپر legacy (MianSql) از قبل ذخیره کرده
    و مبنای دادهٔ ردیف را مشخص می‌کنند.
    """
    cur.execute(
        """
        SELECT ReportDate, RevenueNew, RevenueLastYear, RevenueFYPrev,
               Num1_Value1, Num4_Value1, OperatingProfitNew
        FROM dbo.miandore2
        WHERE CompanyName = ? AND dbo.fn_JalaliKey(ReportDate) IS NOT NULL
        ORDER BY dbo.fn_JalaliKey(ReportDate) DESC
        """,
        name,
    )
    rows = []
    for rd, r1, r2, r3, eps, oeps, op in cur.fetchall():
        nulls = [c for c, v in zip(REVENUE_COLUMNS, (r1, r2, r3)) if v is None]
        if not nulls:
            continue
        rows.append({
            "report_date": str(rd).strip(),
            "nulls": nulls,
            "anchors": {"eps": eps, "operating_eps": oeps, "operating_profit": op},
        })
    return rows


def anchor_dev(table, anchors):
    """انحراف نسبی نسبیِ بهترین لنگر جدول نسبت به ردیف؛ None اگر هیچ لنگری نباشد.

    eps ردیف legacy (Num1_Value1) معادل سطر «سود خالص هر سهم» نامه است؛
    در نامه‌های سالانه گاهی سطر EPS پارس نمی‌شود — بعد از EPS، EPS عملیاتی و
    سپس سود عملیاتی مقایسه می‌شود. کمینهٔ انحراف بین لنگرهای موجود برمی‌گردد.
    """
    bucket = table.get("bucket") or {}
    devs = []
    for metric, want in (
        ("eps", anchors.get("eps")),
        ("operating_eps", anchors.get("operating_eps")),
        ("operating_profit", anchors.get("operating_profit")),
    ):
        v = bucket.get(metric, {}).get(1)
        if want is None or v is None:
            continue
        if float(want) == 0:
            continue
        devs.append(abs(float(v) - float(want)) / abs(float(want)))
    return min(devs) if devs else None


def anchor_dev_values(vals, anchors):
    """انحراف نسبی بهترین لنگر بین مقادیر (eps, operating_eps, op) و ردیف legacy."""
    devs = []
    for want, v in (
        (anchors.get("eps"), (vals.get("eps") or {}).get(1)),
        (anchors.get("operating_eps"), (vals.get("operating_eps") or {}).get(1)),
        (anchors.get("operating_profit"), (vals.get("operating_profit") or {}).get(1)),
    ):
        if want is None or v is None or float(want) == 0:
            continue
        devs.append(abs(float(v) - float(want)) / abs(float(want)))
    return min(devs) if devs else None


def archive_tables_for_period(pg_cur, legacy_company_id, period_g):
    """جدول‌های سود و زیانِ صفحات نامهٔ آرشیوشدهٔ همان دوره (raw.report_payloads).

    صفحات نامه همان چیزی هستند که اسکرپر legacy (MianSql) می‌خواند؛ جایی که
    خروجی Excel با مبنای ردیف هم‌خوان نبود، صفحهٔ نامه لنگرها را بازتولید
    می‌کند. خروجی: list[(payload_meta, {eps, operating_eps, operating_profit,
    revenue: {1,2,3}})].
    """
    from codal_ingestor.parsers.profit_loss import (
        find_profit_loss_table, get_period_columns, get_rows,
    )

    pg_cur.execute(
        """
        SELECT lem.legacy_key
        FROM core.legacy_entity_map lem
        WHERE lem.entity_type = 'company' AND lem.legacy_key = %s
          AND lem.target_uuid IS NOT NULL
        """,
        (legacy_company_id,),
    )
    if pg_cur.fetchone() is None:
        return []
    pg_cur.execute(
        """
        SELECT rp.content_text, rv.collected_at::text
        FROM raw.report_payloads rp
        JOIN ingestion.report_versions rv ON rv.id = rp.report_version_id
        JOIN ingestion.reports r ON r.id = rv.report_id
        WHERE r.company_id IN (SELECT target_uuid FROM core.legacy_entity_map
                               WHERE entity_type='company' AND legacy_key=%s)
          AND r.period_end_date = %s
          AND rp.content_text IS NOT NULL
        ORDER BY rv.collected_at DESC
        """,
        (legacy_company_id, period_g),
    )
    payloads = pg_cur.fetchall()

    out = []
    for content_text, collected in payloads:
        try:
            table = find_profit_loss_table(content_text)
            if table is None:
                continue
            periods = get_period_columns(table)
            if not periods:
                continue
            idx = [int(p["index"]) for p in periods]
            rows = get_rows(table)

            from codal_ingestor.domain import to_decimal

            def numeric(row):
                if row is None:
                    return False
                for i in idx:
                    if i < len(row.cells) and to_decimal(
                            row.cells[i].get_text(" ", strip=True)) is not None:
                        return True
                return False

            def find(exact=(), contains=(), excludes=()):
                hits = []
                for r in rows:
                    t = r.raw_title
                    if any(x in t for x in excludes):
                        continue
                    if (t in exact) if exact else all(x in t for x in contains):
                        if numeric(r):
                            hits.append(r)
                return hits[0] if hits else None

            rev_row = find(exact=("درآمدهای عملیاتی",)) or \
                find(contains=("درآمد", "عملیاتی"), excludes=("بهای تمام شده", "سایر", "جمع"))
            # EPS پایه — همان سطری که MianSql در Num1_Value1 ذخیره می‌کند
            eps_row = find(exact=("سود (زیان) پایه هر سهم",)) or \
                find(contains=("پایه", "هر سهم"), excludes=("عملیاتی", "غیرعملیاتی", "ناشی", "خالص"))
            oeps_row = find(exact=("عملیاتی (ریال)",))
            op_row = find(exact=("سود(زیان) عملیاتی",)) or \
                find(exact=("سود (زیان) عملیاتی",)) or \
                find(contains=("عملیاتی",), excludes=("هر سهم", "غیرعملیاتی", "قبل از مالیات",
                                                      "درآمد", "بهای"))

            def row_value(row, order):
                if row is None or order > len(idx):
                    return None
                v = to_decimal(row.cells[idx[order - 1]].get_text(" ", strip=True))
                return float(v) if v is not None else None

            if rev_row is None:
                continue
            vals = {
                "revenue": {o: row_value(rev_row, o) for o in (1, 2, 3)
                            if row_value(rev_row, o) is not None},
                "eps": {1: row_value(eps_row, 1)} if eps_row else {},
                "operating_eps": {1: row_value(oeps_row, 1)} if oeps_row else {},
                "operating_profit": {1: row_value(op_row, 1)} if op_row else {},
            }
            out.append(({"collected_at": collected}, vals))
        except Exception:  # noqa: BLE001 — نامهٔ خراب فقط رد می‌شود
            continue
    return out


def fill_row(cur, name, report_date, values):
    """COALESCE فقط برای ستون‌های ارسالی؛ برمی‌گرداند (rows_affected, filled[])."""
    sets, params, filled = [], [], []
    for col, val in zip(REVENUE_COLUMNS, values):
        if val is None:
            continue
        sets.append(f"{col} = COALESCE({col}, ?)")
        params.append(val)
        filled.append(col)
    if not sets:
        return 0, []
    cur.execute(
        f"UPDATE dbo.miandore2 SET {', '.join(sets)} "
        "WHERE CompanyName = ? AND ReportDate = ?",
        (*params, name, report_date),
    )
    return cur.rowcount, filled


def fs_candidates(letters, cutoff):
    """همهٔ نامه‌های صورت مالی (بدون dedupe) — جدیدترین اول؛ برای تطبیق لنگر."""
    out = []
    for L in letters:
        kind = F.classify_letter(L)
        if kind is None:
            continue
        pub = F.publish_date(L.get("PublishDateTime") or "")
        if pub is None or pub > cutoff.date():
            continue
        period = F.jalali_date_in(L.get("Title") or "")
        if period is None:
            continue
        out.append({
            "tracing_no": L.get("TracingNo"),
            "title": F._norm(L.get("Title") or ""),
            "kind": kind,
            "publish_date": pub.isoformat(),
            "period_end": period.isoformat(),
            "excel_url": L.get("ExcelUrl") or "",
            "decision_url": ("https://www.codal.ir" + L["Url"]) if L.get("Url") else "",
        })
    out.sort(key=lambda r: (r["period_end"], r["publish_date"]), reverse=True)
    return out


def local_candidates(pg_cur, legacy_company_id, cutoff):
    """فهرست نامه‌های صورت مالی از آرquivo محلی canonical (بدون API جستجو).

    از ingestion.reports (منبع کدال پروژه) — سریال نامه در source_url هست و
    خروجی Excel با الگوی عمومی excel.codal.ir/service/Excel/GetAll/<serial>/0
    ساخته می‌شود. جدیدترین اول. PIT: period_end_date <= cutoff (قرارداد
    گزارش‌های بدون published_at، همان موتور امتیازدهی).
    """
    pg_cur.execute(
        """
        SELECT r.period_end_date::text, r.title, r.source_url
        FROM ingestion.reports r
        WHERE r.company_id IN (SELECT target_uuid FROM core.legacy_entity_map
                               WHERE entity_type='company' AND legacy_key=%s)
          AND r.source = 'codal'
          AND r.period_end_date IS NOT NULL
          AND r.period_end_date <= %s
          AND r.id NOT IN (SELECT supersedes_report_id FROM ingestion.reports
                           WHERE supersedes_report_id IS NOT NULL)
        ORDER BY r.period_end_date DESC
        """,
        (legacy_company_id, cutoff.date().isoformat()),
    )
    out = []
    for period_end, title, source_url in pg_cur.fetchall():
        title = F._norm(title or "")
        if F.classify_letter({"Title": title}) is None:
            continue
        serial = None
        if "LetterSerial=" in (source_url or ""):
            raw = source_url.split("LetterSerial=", 1)[1].split("&", 1)[0]
            serial = urllib.parse.unquote(raw)
        if not serial:
            continue
        out.append({
            "tracing_no": serial,
            "title": title,
            "kind": F.classify_letter({"Title": title}),
            "publish_date": None,
            "period_end": period_end,
            "excel_url": f"https://excel.codal.ir/service/Excel/GetAll/{serial}/0",
            "decision_url": None,
        })
    return out


def backfill_symbol(cur, name, cutoff, pages, fetch_cache, pg_cur=None):
    rows = revenue_rows(cur, name)
    res = {"symbol": name, "rows_missing_revenue": len(rows),
           "updated_rows": {}, "skipped": []}
    if not rows:
        res["skipped"].append("no rows with NULL revenue columns")
        return res

    # CompanyID legacy برای دسترسی به آرشیو صفحات نامه (raw.report_payloads)
    cur.execute("SELECT TOP 1 CompanyID FROM dbo.miandore2 WHERE CompanyName=?", (name,))
    cid_row = cur.fetchone()
    legacy_company_id = cid_row[0] if cid_row else None

    import jdatetime

    def period_of(row):
        try:
            jy, jm, jd = (int(x) for x in row["report_date"].split("/"))
            return jdatetime.date(jy, jm, jd).togregorian().isoformat()
        except Exception:
            return None

    def apply_fill(row, rev, basis, letter_label, dev):
        vals_row = [rev.get(1), rev.get(2), rev.get(3)]
        n, filled = fill_row(cur, name, row["report_date"], vals_row)
        if not n:
            res["skipped"].append(f"{row['report_date']}: nothing new to fill")
            return False
        res["updated_rows"][row["report_date"]] = {
            "filled": filled,
            "values_million_rial": dict(zip(REVENUE_COLUMNS, vals_row)),
            "letter": letter_label,
            "anchor_rel_dev": dev,
            "basis": basis,
        }
        for col in filled:
            if col in row["nulls"]:
                row["nulls"].remove(col)
        return True

    # ---- گام ۱: آرشیو صفحات نامهٔ پروژه (بدون شبکه) ----
    remaining = []
    for row in rows:
        if not any(v is not None for v in row["anchors"].values()):
            res["skipped"].append(f"{row['report_date']}: row has no legacy anchor (EPS/op)")
            continue
        period_g = period_of(row)
        if period_g is None:
            res["skipped"].append(f"{row['report_date']}: unparsable ReportDate")
            continue
        row["_period"] = period_g
        picked = None
        if pg_cur is not None and legacy_company_id:
            for meta, vals in archive_tables_for_period(pg_cur, legacy_company_id, period_g):
                d = anchor_dev_values(vals, row["anchors"])
                if d is None:
                    continue
                if d == 0.0:
                    picked = (vals, "letter_page", meta.get("collected_at", "")[:10], 0.0)
                    break
                if d <= ANCHOR_REL_DEV_MAX and (picked is None or d < picked[3]):
                    picked = (vals, "letter_page", meta.get("collected_at", "")[:10], d)
        if picked is not None and (picked[0].get("revenue") or {}):
            if apply_fill(row, picked[0]["revenue"], picked[1], picked[2], picked[3]):
                time.sleep(0.2)
                continue
        remaining.append(row)

    if not remaining:
        return res

    # ---- گام ۲: نامه‌های کدال — اول از فهرست محلی canonical، بعد API جستجو ----
    cands = []
    if pg_cur is not None and legacy_company_id:
        try:
            cands = local_candidates(pg_cur, legacy_company_id, cutoff)
            if cands:
                res["fs_letters_local"] = len(cands)
        except Exception as exc:  # noqa: BLE001
            res["skipped"].append(f"local candidate list failed: {type(exc).__name__}")
            cands = []
    res["fs_letters"] = len(cands)

    if not cands:
        # WAF کدال: پنجره‌ی نرخ غلتان دارد؛ فشار پیوسته دوباره گرمش می‌کند.
        # با فاصله‌ی ۴۵ ثانیه‌ای تا ~۹ دقیقه صبورانه تلاش می‌کنیم.
        letters = None
        for attempt in range(12):
            letters = F.search_symbol(name, pages=pages)
            err = next((L for L in letters if "__error__" in L), None)
            if err is None:
                break
            if "429" not in str(err):
                break
            print(f"    429 — ۴۵ ثانیه وقفه (تلاش {attempt + 1}/۱۲)", flush=True)
            time.sleep(45)
        err = next((L for L in letters if "__error__" in L), None)
        if err:
            res["skipped"].append(f"search error: {err['__error__']} "
                                  f"({len(remaining)} rows left unfiled)")
            return res
        cands = fs_candidates(letters, cutoff)
        res["fs_letters"] = len(cands)
    by_period: dict[str, list] = {}
    for c in cands:
        by_period.setdefault(c["period_end"], []).append(c)

    for row in remaining:
        cands_p = by_period.get(row["_period"]) or []
        if not cands_p:
            res["skipped"].append(f"{row['report_date']}: no FS letter found for period")
            continue

        chosen = None
        best = None
        for c in cands_p:
            key = c["tracing_no"]
            parsed = fetch_cache.get(key)
            if parsed is None:
                got = F.fetch_report_html(c)
                if not got.get("ok"):
                    parsed = {"error": got.get("via")}
                else:
                    try:
                        parsed = P.parse_report(got["html"], with_order3=True)
                    except Exception as exc:  # noqa: BLE001
                        parsed = {"error": type(exc).__name__}
                fetch_cache[key] = parsed
                time.sleep(0.4)
            if not isinstance(parsed, dict) or "error" in parsed:
                continue
            tables = (parsed.get("statements_all") or {}).get("income_statement") or []
            exact = [t for t in tables if anchor_dev(t, row["anchors"]) == 0.0]
            if exact:
                chosen = (c, exact[0], 0.0)
                break
            for t in tables:
                d = anchor_dev(t, row["anchors"])
                if d is not None and d <= ANCHOR_REL_DEV_MAX and (best is None or d < best[2]):
                    best = (c, t, d)
        if chosen is None and best is not None:
            chosen = best
        if chosen is None:
            res["skipped"].append(
                f"{row['report_date']}: no letter table reproduces the row anchors")
            continue
        c, table, dev = chosen
        rev = (table.get("bucket") or {}).get("revenue") or {}
        if not rev:
            res["skipped"].append(f"{row['report_date']}: selected table has no revenue row")
            continue
        apply_fill(row, rev, "consolidated" if table.get("consolidated") else "parent",
                   c["title"][:80], dev)
        time.sleep(0.3)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--symbols-file")
    ap.add_argument("--pages", type=int, default=5,
                    help="تعداد صفحات API جستجوی کدال (پیش‌فرض ۵ ≈ ۱۰۰ نامه)")
    ap.add_argument("--cutoff", default=dt.datetime.now(dt.timezone.utc).isoformat())
    ap.add_argument("--out", default=str(OUT / "backfill_report.json"))
    args = ap.parse_args()

    symbols = list(args.symbols)
    if args.symbols_file:
        symbols += [s.strip() for s in open(args.symbols_file, encoding="utf-8")
                    if s.strip()]
    if not symbols:
        raise SystemExit("نمادی داده نشد")
    cutoff = dt.datetime.fromisoformat(args.cutoff)

    OUT.mkdir(parents=True, exist_ok=True)
    cn = sqlserver()
    cur = cn.cursor()
    pg_cur = None
    try:
        os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
        from common import pg_pilot_conn
        pg_cur = pg_pilot_conn(autocommit=True).cursor()
    except Exception as exc:  # noqa: BLE001 — بدون آرشیو فقط مسیر Excel
        print(f"archive fallback unavailable: {exc}", flush=True)
    fetch_cache: dict = {}
    results = []
    for i, name in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {name} ...", flush=True)
        r = None
        try:
            r = backfill_symbol(cur, name, cutoff, args.pages, fetch_cache, pg_cur)
        except Exception as exc:  # noqa: BLE001
            r = {"symbol": name, "error": f"{type(exc).__name__}: {exc}"}
        results.append(r)
        upd = r.get("updated_rows") or {}
        print(f"    rows with NULL revenue: {r.get('rows_missing_revenue')} · "
              f"FS letters: {r.get('fs_letters')} · "
              f"updated: {list(upd) or '—'} · skipped: {len(r.get('skipped') or [])}",
              flush=True)
        time.sleep(4.0)

    cn.close()
    (OUT / "backfill_report.json").write_text(
        json.dumps({"cutoff": args.cutoff, "symbols": results}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    total_updated = sum(len(r.get("updated_rows") or {}) for r in results)
    print(f"جمع: {total_updated} ردیف به‌روزرسانی شد → {args.out}")


if __name__ == "__main__":
    main()
