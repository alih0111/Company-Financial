"""Read-only profiling of SQL Server to choose a heterogeneous pilot sample.

Issues only SELECT against SQL Server. No writes anywhere.
Run with the test venv python.
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
from urllib.parse import unquote, urlparse

import pyodbc
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / "go-app" / ".env")


def connect_sqlserver():
    cs = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};PWD={os.getenv('DB_PASSWORD')};TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cs, timeout=30, readonly=True)


def main():
    cn = connect_sqlserver()
    cur = cn.cursor()

    print("== top companies by mahane rows ==")
    cur.execute("""
        SELECT TOP 15 CompanyID, MAX(CompanyName), COUNT(*) n
        FROM dbo.mahane GROUP BY CompanyID ORDER BY COUNT(*) DESC
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("== top companies by miandore2 rows ==")
    cur.execute("""
        SELECT TOP 15 CompanyID, MAX(CompanyName), COUNT(*) n
        FROM dbo.miandore2 GROUP BY CompanyID ORDER BY COUNT(*) DESC
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("== top companies by MPH rows ==")
    cur.execute("""
        SELECT TOP 15 CompanyID, MAX(CompanyName), MAX(Symbol), MAX(InstrumentCode), COUNT(*) n
        FROM dbo.MarketPriceHistory GROUP BY CompanyID ORDER BY COUNT(*) DESC
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("== kastra conflict (Symbol='کسرا') ==")
    cur.execute("""
        SELECT CompanyID, CompanyName, InstrumentCode, Symbol, COUNT(*) n,
               MIN(GregorianDate) mn, MAX(GregorianDate) mx
        FROM dbo.MarketPriceHistory WHERE Symbol = N'کسرا'
        GROUP BY CompanyID, CompanyName, InstrumentCode, Symbol
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("== instrument with multiple company ids ==")
    cur.execute("""
        SELECT InstrumentCode, COUNT(DISTINCT CompanyID) ids, COUNT(DISTINCT Symbol) syms
        FROM dbo.MarketPriceHistory GROUP BY InstrumentCode
        HAVING COUNT(DISTINCT CompanyID) > 1
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("== CodalReports per ticker (correction candidates) ==")
    cur.execute("""
        SELECT Ticker, COUNT(*) n, COUNT(DISTINCT ReportTitle) titles
        FROM dbo.CodalReports GROUP BY Ticker ORDER BY COUNT(*) DESC
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("== statements company/types ==")
    cur.execute("SELECT CompanyName, StatementType, COUNT(*) n FROM dbo.statements GROUP BY CompanyName, StatementType")
    for r in cur.fetchall():
        print("  ", r)

    print("== null-heavy miandore2 (sample) ==")
    cur.execute("""
        SELECT TOP 10 CompanyName, COUNT(*) n,
               SUM(CASE WHEN TotalAssets IS NULL THEN 1 ELSE 0 END) ta_null,
               SUM(CASE WHEN RevenueNew IS NULL THEN 1 ELSE 0 END) rev_null
        FROM dbo.miandore2 GROUP BY CompanyName ORDER BY COUNT(*) DESC
    """)
    for r in cur.fetchall():
        print("  ", r)

    cn.close()


if __name__ == "__main__":
    main()
