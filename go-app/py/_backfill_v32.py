# -*- coding: utf-8 -*-
"""
بک‌فیل v3.2 — معادل دقیق POST /api/fetchAllData:
برای هر شرکت، آخرین URL از miandore2 و اجرای py/scraper.py با rowMeta=1، صفحه 1
شرکت‌هایی که گزارش آخرشان قبلاً ترازنامه دارد، رد می‌شوند (idempotent).
"""
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

COMPANIES = [
    "شمواد", "سباقر", "غکورش", "غپینو", "کاما", "غمینو",
    "دجابر", "دلقما", "غاذر", "قاسم",
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


def fetch_url_and_done(cur, name):
    """آخرین URL + اینکه آیا گزارش آخر همین شرکت قبلاً ترازنامه دارد"""
    cur.execute(
        """
        SELECT TOP 1 Url, TotalEquity
        FROM dbo.miandore2
        WHERE CompanyName LIKE ?
        ORDER BY ReportDate DESC
        """,
        name,
    )
    return cur.fetchone()


def coverage(cur):
    cur.execute(
        "SELECT COUNT(DISTINCT CompanyName) FROM dbo.miandore2 WHERE TotalEquity IS NOT NULL"
    )
    return cur.fetchone()[0]


def main():
    conn = pyodbc.connect(CS)
    cur = conn.cursor()
    ok = skip = fail = 0
    failed = []

    print(f"شروع: {len(COMPANIES)} شرکت | پوشش فعلی: {coverage(cur)}", flush=True)

    for i, name in enumerate(COMPANIES, 1):
        try:
            row = fetch_url_and_done(cur, name)
        except Exception as exc:
            print(f"[{i}/{len(COMPANIES)}] {name}: خطای DB {exc}", flush=True)
            fail += 1
            failed.append(name)
            continue

        if row is None or not row.Url:
            print(f"[{i}/{len(COMPANIES)}] {name}: URL پیدا نشد ✗", flush=True)
            fail += 1
            failed.append(name)
            continue

        if row.TotalEquity is not None:
            print(f"[{i}/{len(COMPANIES)}] {name}: از قبل کامل است — رد شد", flush=True)
            skip += 1
            continue

        try:
            result = subprocess.run(
                [sys.executable, "py/scraper.py", name, "1", row.Url, "[1]"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                cwd=os.path.dirname(os.path.abspath(__file__)) + "/..",
            )
            out = (result.stdout or "") + (result.stderr or "")
            if "scraping and saving successful" in out:
                ok += 1
                print(f"[{i}/{len(COMPANIES)}] {name}: ✓ ذخیره شد | پوشش: {coverage(cur)}", flush=True)
            else:
                fail += 1
                failed.append(name)
                tail = [l for l in out.splitlines() if l.strip()][-3:]
                print(f"[{i}/{len(COMPANIES)}] {name}: ✗ | {' / '.join(tail)}", flush=True)
        except subprocess.TimeoutExpired:
            fail += 1
            failed.append(name)
            print(f"[{i}/{len(COMPANIES)}] {name}: ✗ timeout", flush=True)

        time.sleep(2)

    print("=" * 50, flush=True)
    print(f"پایان: موفق={ok} رد‌شده={skip} شکست={fail}", flush=True)
    if failed:
        print("شکست‌خورده‌ها:", "، ".join(failed), flush=True)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
