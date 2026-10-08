# -*- coding: utf-8 -*-
"""
بک‌فیل v3.2 کل جهان نمادها — تعمیم‌یافته‌ی _backfill_v32.py

هدف: شرکت‌هایی که آخرین گزارششان در miandore2 ستون‌های مبلغی (درآمد، ترازنامه،
جریان نقدی، هزینه مالی) را ندارد → دقیقاً همین‌ها در UI امتیاز «بدون داده»
می‌گیرند. برای هر شرکت، لیست گزارش‌های میان‌دوره‌ای کدال (LetterType=6) صفحه ۱
با py/scraper.py اسکرپ و ستون‌های خالی با COALESCE پر می‌شوند (idempotent).

- هدف‌ها از خود DB انتخاب می‌شوند، پس اجرای دوباره فقط ناقص‌ها را برمی‌دارد.
- برای هر شرکت یک‌بار rowMeta=1 (جدیدترین نامه)؛ اگر ستون‌ها پر نشد یک‌بار
  دیگر با rowMeta=4 (نامه‌های جدیدترِ بیشتر).
- پروسه‌ی فرزند با CDF_SQLSERVER_MODE=active اجرا می‌شود تا نوشتن legacy
  (miandore2) انجام شود و هوک کانونی هم همان گزارش را دو-نویسی کند؛ با
  offline_expected اسکرپر SQL Server را کلاً رد می‌شود و این بک‌فیل بی‌اثر
  می‌ماند.
"""
import csv
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

for line in open("../.env", encoding="utf-8-sig"):
    line = line.strip()
    if line and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

import pyodbc  # noqa: E402

# ستون‌های مبلغی که ویوی امتیاز به آن‌ها نیاز دارد
AMOUNT_COLUMNS = [
    "RevenueNew",
    "NetProfitAmount",
    "TotalEquity",
    "TotalAssets",
    "OperatingCashFlow",
    "FinanceCostsNew",
]

RESULTS_CSV = os.path.join("output", "backfill_universe_results.csv")

# سیاست نرخ مطابق CAPTCHA_AWARE_RUNBOOK: بین شرکت‌ها ۶۰ ثانیه، قبل از تلاش
# دوم ۲۰ ثانیه. در برخورد با چالش امنیتی: بدون دور زدن — توقف ۳۰ دقیقه‌ای،
# حداکثر ۸ بار (پوشش ~۴ ساعت)؛ بعدش خروج تمیز (BACKFILL_PAUSED_CAPTCHA).
PAUSE_BETWEEN_COMPANIES_S = 60
PAUSE_BEFORE_RETRY_S = 20
CAPTCHA_PAUSE_S = 30 * 60
CAPTCHA_MAX_PAUSES = 8

CHALLENGE_MARKERS = [
    "کد امنیتی", "تصویر امنیتی", "لطفا کد", "لطفاً کد",
    "چالش امنیتی", "تأیید ایمنی", "تایید ایمنی",
]

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


def targets(cur, only_symbol=None):
    """شرکت‌هایی که آخرین ردیف miandore2 آن‌ها ستون مبلغی خالی دارد."""
    cols = ", ".join(AMOUNT_COLUMNS)
    placeholders = " OR ".join(f"l.{c} IS NULL" for c in AMOUNT_COLUMNS)
    sql = f"""
    WITH Universe AS (
        SELECT CompanyID FROM dbo.mahane WHERE CompanyID IS NOT NULL
        UNION SELECT CompanyID FROM dbo.miandore2 WHERE CompanyID IS NOT NULL
    ),
    Latest AS (
        SELECT CompanyID, CompanyName, Url, ReportDate,
               {cols},
               ROW_NUMBER() OVER (
                   PARTITION BY CompanyID
                   ORDER BY dbo.fn_JalaliKey(ReportDate) DESC
               ) AS rn
        FROM dbo.miandore2
        WHERE CompanyID IS NOT NULL AND Url IS NOT NULL
    )
    SELECT l.CompanyID, l.CompanyName, l.Url, l.ReportDate
    FROM Universe u
    JOIN Latest l ON l.CompanyID = u.CompanyID AND l.rn = 1
    WHERE ({placeholders})
    """
    args = []
    if only_symbol:
        sql += " AND l.CompanyName LIKE ?"
        args.append(only_symbol)
    cur.execute(sql, args)
    return cur.fetchall()


def missing_columns(cur, company_id):
    """کدام ستون‌های مبلغیِ آخرین ردیف هنوز NULL هستند."""
    cols = ", ".join(AMOUNT_COLUMNS)
    cur.execute(
        f"""
        SELECT TOP 1 {cols}
        FROM dbo.miandore2
        WHERE CompanyID = ?
        ORDER BY dbo.fn_JalaliKey(ReportDate) DESC
        """,
        company_id,
    )
    row = cur.fetchone()
    if row is None:
        return list(AMOUNT_COLUMNS)
    return [c for c, v in zip(AMOUNT_COLUMNS, row) if v is None]


def run_scraper(name, url, row_meta, timeout=300):
    env = os.environ.copy()
    # نوشتن legacy + دو-نویسی کانونی؛ offline_expected مسیر legacy را حذف می‌کند
    env["CDF_SQLSERVER_MODE"] = "active"
    try:
        result = subprocess.run(
            [
                sys.executable, "py/scraper.py",
                name, str(row_meta), url, "[1]",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=os.path.dirname(os.path.abspath(__file__)) + "/..",
        )
        out = (result.stdout or "") + (result.stderr or "")
        tail = [l for l in out.splitlines() if l.strip()][-3:]
        return result.returncode, tail
    except subprocess.TimeoutExpired:
        return -1, ["timeout"]


def captcha_detected():
    """بررسی چالش امنیتی کدال — در پروسه‌ی فرزند با تایم‌اوت سخت، تا اگر
    مرورگر هنگ کند اجرای اصلی قفل نشود."""
    try:
        probe = subprocess.run(
            [sys.executable, __file__, "--probe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=150,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except subprocess.TimeoutExpired:
        return True  # محتاط: مثل چالش رفتار کن
    out = (probe.stdout or "") + (probe.stderr or "")
    if "PROBE_ERROR" in out:
        return True  # محتاط: مثل چالش رفتار کن
    if "PROBE_CHALLENGE" in out:
        return True
    if "PROBE_CLEAR" in out:
        return False
    return True  # خروجی نامشخص → محتاط


def _probe_once():
    """پروب واقعی کدال با کانتکست ایزوله headless (بدون پروفایل)."""
    try:
        from playwright.sync_api import sync_playwright

        html = ""
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe",
                headless=True,
                timeout=45000,
                args=["--disable-gpu", "--no-first-run"],
            )
            page = browser.new_page()
            page.goto(
                "https://www.codal.ir/ReportList.aspx?search&LetterType=6&PageNumber=1",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            page.wait_for_timeout(8000)
            html = page.content()
            browser.close()
        if any(m in html for m in CHALLENGE_MARKERS):
            print("PROBE_CHALLENGE")
            return
        # جدول نامه‌ها لود نشد ولی ماکر چالش هم نیست → مشکوک، چالش فرض کن
        if "scrollContent" not in html:
            print("PROBE_CHALLENGE")
            return
        print("PROBE_CLEAR")
    except Exception as exc:
        print(f"PROBE_ERROR {exc}")


def main():
    # حالت پروب: فقط وضعیت چالش کدال را چاپ می‌کند (برای فراخوانی با تایم‌اوت)
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        _probe_once()
        return

    only_symbol = None
    if len(sys.argv) > 1:
        only_symbol = sys.argv[1]

    conn = pyodbc.connect(CS)
    cur = conn.cursor()

    rows = targets(cur, only_symbol)
    print(f"هدف‌ها: {len(rows)} شرکت", flush=True)

    # پروب شروع: فقط اطلاع‌رسانی. پروب headless توسط WAF کدال چالش می‌شود حتی
    # وقتی پروفایل واقعی (headful) رد می‌شود؛ تصمیم را رفتار واقعی اسکرپر
    # می‌گیرد — دو شکست متوالی در حلقه‌ی اصلی → پروب → توقف ۳۰ دقیقه‌ای.
    if captcha_detected():
        print("⚠️ پروب headless چالش امنیتی نشان می‌دهد؛ ادامه با پروفایل واقعی "
              "اسکرپر (در صورت چالش واقعی، حلقه‌ی اصلی خودش متوقف می‌شود).", flush=True)

    results = []
    counts = {"ok": 0, "partial": 0, "fail": 0, "no_url": 0}
    consecutive_fails = 0
    captcha_pauses = 0

    for i, (company_id, name, url, report_date) in enumerate(rows, 1):
        status = "fail"
        before = missing_columns(cur, company_id)

        if not url:
            status = "no_url"
            counts["no_url"] += 1
            print(f"[{i}/{len(rows)}] {name}: بدون URL ✗", flush=True)
            results.append((company_id, name, status, ",".join(before), ",".join(before)))
            continue

        code, tail = run_scraper(name, url, row_meta=1)
        after = missing_columns(cur, company_id)

        # اگر جدول نامه‌ها اصلاً لود نشد (علامت چالش/محدودیت)، تلاش دوم فقط
        # درخواست اضافه است؛ فقط وقتی نامه خوانده شد ولی مناسب نبود retry کن.
        blocked = any("Table did not load" in t for t in tail)
        if after and not blocked:
            time.sleep(PAUSE_BEFORE_RETRY_S)
            code, tail = run_scraper(name, url, row_meta=4)
            after = missing_columns(cur, company_id)

        if not after:
            status = "ok"
        elif len(after) < len(before):
            status = "partial"
        else:
            status = "fail"

        if status == "fail":
            consecutive_fails += 1
        else:
            consecutive_fails = 0

        # دو شکست متوالی → چالش امنیتی را بررسی کن؛ در صورت چالش، توقف و صبر
        if consecutive_fails >= 2 and captcha_detected():
            captcha_pauses += 1
            if captcha_pauses > CAPTCHA_MAX_PAUSES:
                print("BACKFILL_PAUSED_CAPTCHA — چالش امنیتی پابرجاست؛ "
                      "نیاز به حل دستی (یک بار در مرورگر) و اجرای دوباره همین "
                      "اسکریپت (خودش از میانه ادامه می‌دهد).", flush=True)
                break
            print(f"  🛑 چالش امنیتی کدال — توقف {CAPTCHA_PAUSE_S // 60} دقیقه "
                  f"(pause {captcha_pauses}/{CAPTCHA_MAX_PAUSES})", flush=True)
            time.sleep(CAPTCHA_PAUSE_S)
            consecutive_fails = 0

        counts[status] = counts.get(status, 0) + 1
        mark = {"ok": "✓", "partial": "◐", "fail": "✗"}[status]
        print(
            f"[{i}/{len(rows)}] {name}: {mark} {status}"
            + (f" | هنوز خالی: {','.join(after)}" if after else "")
            + (f" | {' / '.join(tail)}" if status == "fail" else ""),
            flush=True,
        )
        results.append((company_id, name, status, ",".join(before), ",".join(after)))
        time.sleep(PAUSE_BETWEEN_COMPANIES_S)

    os.makedirs(os.path.dirname(RESULTS_CSV), exist_ok=True)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["company_id", "company_name", "status", "missing_before", "missing_after"])
        w.writerows(results)

    print("=" * 50, flush=True)
    print(f"پایان: کامل={counts['ok']} ناقص={counts['partial']} "
          f"شکست={counts['fail']} بدون‌URL={counts['no_url']}", flush=True)
    print(f"نتایج: {RESULTS_CSV}", flush=True)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
