# -*- coding: utf-8 -*-
"""
بک‌فیل تاریخی گزارش‌های میان‌دوره (برای فاز ۲ بک‌تست)

برای هر نماد مهم، تمام صفحات لیست گزارش‌های CODAL اسکرپ می‌شود و ستون‌های
خالی ردیف‌های موجود (RevenueNew / FinanceCosts / OtherNonOp / ترازنامه /
جریان نقدی / NetProfitAmount و خانواده‌ی FYPrev) پر می‌شوند.

نکات:
  - idempotent: UPDATE با COALESCE فقط NULL را پر می‌کند؛ اجرای مکرر بی‌ضرر است
  - گزارش‌های قدیمی‌تر از ۱۳۹۷/۱۲/۲۹ توسط خود MianSql رد می‌شوند
  - گزارش کامل = RevenueNew + TotalEquity + NetProfitAmount همه NOT NULL
  - شرکتِ همه‌کامل رد می‌شود؛ اجرای دوباره از همان‌جا ادامه می‌یابد

اجرا:
  python backfill_history.py                    # هر ۱۰ نماد مهم
  python backfill_history.py شمواد سباقر        # زیرمجموعه خاص
"""
import json
import math
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

for _line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8-sig"):
    _line = _line.strip()
    if _line and "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k, _v)

import pyodbc  # noqa: E402

IMPORTANT = [
    "شمواد", "سباقر", "غکورش", "غپینو", "کاما", "غمینو",
    "دجابر", "دلقما", "غاذر", "قاسم",
]
ROWS_PER_PAGE = 20
ROW_META = 40          # تمام ردیف‌های هر صفحه‌ی لیست (سقف واقعی توسط خود اسکرپر اعمال می‌شود)
MAX_PAGES = 6
PER_COMPANY_TIMEOUT = 5400

CS = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER="
    + os.environ["DB_SERVER"]
    + ";DATABASE="
    + os.environ["DB_NAME"]
    + ";UID="
    + os.environ["DB_USER"]
    + ";PWD="
    + os.environ["DB_PASSWORD"]
    + ";TrustServerCertificate=yes;"
)


def company_state(cur, name):
    """(آخرین url لیست، تعداد کل، تعداد کامل) برای نماد"""
    cur.execute(
        """
        SELECT TOP 1 Url FROM dbo.miandore2
        WHERE CompanyName = ? AND Url IS NOT NULL
        ORDER BY ReportDate DESC
        """,
        name,
    )
    row = cur.fetchone()
    url = row[0] if row else None
    cur.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN RevenueNew IS NOT NULL AND TotalEquity IS NOT NULL
                         AND NetProfitAmount IS NOT NULL THEN 1 ELSE 0 END)
        FROM dbo.miandore2 WHERE CompanyName = ?
        """,
        name,
    )
    total, complete = cur.fetchone()
    return url, int(total or 0), int(complete or 0)


def run_company(name, url, n_reports):
    pages = list(range(1, min(math.ceil(n_reports / ROWS_PER_PAGE) + 2, MAX_PAGES + 1)))
    print(f"  شروع اسکرپ: صفحات {pages}", flush=True)
    cwd = os.path.dirname(os.path.abspath(__file__)) + os.sep + ".."
    try:
        result = subprocess.run(
            [sys.executable, "py/scraper.py", name, str(ROW_META), url, json.dumps(pages)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PER_COMPANY_TIMEOUT,
            cwd=cwd,
        )
        out = (result.stdout or "") + (result.stderr or "")
        if "scraping and saving successful" in out:
            return "ok", out
        if "no new data saved" in out:
            return "empty", out
        return "fail", out
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except Exception as exc:  # noqa: BLE001
        return "fail", str(exc)


def main():
    companies = sys.argv[1:] or IMPORTANT
    conn = pyodbc.connect(CS)
    cur = conn.cursor()

    print("=" * 70, flush=True)
    print(f"بک‌فیل تاریخی {len(companies)} نماد: {companies}", flush=True)
    print("=" * 70, flush=True)

    results = {}
    for i, name in enumerate(companies, 1):
        url, total, complete = company_state(cur, name)
        if not url:
            print(f"[{i}/{len(companies)}] {name}: URL یافت نشد — رد شد", flush=True)
            results[name] = "no-url"
            continue
        if total > 0 and complete >= total:
            print(f"[{i}/{len(companies)}] {name}: از قبل کامل ({complete}/{total}) — رد شد", flush=True)
            results[name] = "skip"
            continue
        print(f"[{i}/{len(companies)}] {name}: {complete}/{total} کامل", flush=True)
        status, out = run_company(name, url, total)
        url2, total2, complete2 = company_state(cur, name)
        delta = complete2 - complete
        tail = [ln for ln in out.splitlines() if ln.strip()][-2:] if out else []
        print(f"  نتیجه: {status} | پوشش {complete2}/{total2} (+{delta})", flush=True)
        if status == "fail" and tail:
            print("  " + " / ".join(tail), flush=True)
        results[name] = status
        time.sleep(3)

    print("=" * 70, flush=True)
    print("خلاصه نهایی:", flush=True)
    conn2 = pyodbc.connect(CS)
    cur2 = conn2.cursor()
    for name in companies:
        _, total, complete = company_state(cur2, name)
        mark = "✓" if total and complete >= total else "…" if complete > 0 else "✗"
        print(f"  {mark} {name}: {complete}/{total}", flush=True)
    conn.close()
    conn2.close()


if __name__ == "__main__":
    main()
