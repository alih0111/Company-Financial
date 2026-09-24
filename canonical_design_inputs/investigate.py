"""Read-only investigation for canonical PostgreSQL design inputs.

ONLY issues SELECT statements. Never modifies SQL Server or PostgreSQL.
Reads credentials from go-app/.env (never written to output).

Run:
    python canonical_design_inputs/investigate.py
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
ENV_FILE = REPO / "go-app" / ".env"
OUT = {}


def connect():
    load_dotenv(ENV_FILE)
    cs = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cs, timeout=20)


def run(cur, sql, *params):
    cur.execute(sql, *params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def safe(cur, name, sql, *params):
    try:
        rows = run(cur, sql, *params)
        OUT[name] = rows
        print(f"  [{name}] {len(rows)} rows")
        return rows
    except Exception as exc:  # noqa: BLE001
        OUT[name] = {"error": str(exc)}
        print(f"  [{name}] ERROR: {exc}")
        return []


def main():
    cn = connect()
    cur = cn.cursor()
    print("Connected (read-only).")

    # ================= 1) IDENTITY =================
    print("-- identity --")
    safe(cur, "mahane_id_name_count", """
        SELECT CompanyID, COUNT(DISTINCT CompanyName) AS name_count,
               COUNT(*) AS rows, MIN(CompanyName) AS sample_name
        FROM dbo.mahane GROUP BY CompanyID
    """)
    safe(cur, "miandore2_id_name_count", """
        SELECT CompanyID, COUNT(DISTINCT CompanyName) AS name_count,
               COUNT(*) AS rows, MIN(CompanyName) AS sample_name
        FROM dbo.miandore2 GROUP BY CompanyID
    """)
    safe(cur, "name_multi_id_union", """
        SELECT CompanyName, COUNT(DISTINCT CompanyID) AS id_count
        FROM (
            SELECT CompanyName, CompanyID FROM dbo.mahane WHERE CompanyName IS NOT NULL
            UNION ALL
            SELECT CompanyName, CompanyID FROM dbo.miandore2 WHERE CompanyName IS NOT NULL
        ) t
        GROUP BY CompanyName HAVING COUNT(DISTINCT CompanyID) > 1
        ORDER BY id_count DESC
    """)
    safe(cur, "mph_symbol_multi_id", """
        SELECT Symbol, COUNT(DISTINCT CompanyID) AS id_count
        FROM dbo.MarketPriceHistory
        WHERE Symbol IS NOT NULL AND CompanyID IS NOT NULL
        GROUP BY Symbol HAVING COUNT(DISTINCT CompanyID) > 1
        ORDER BY id_count DESC
    """)
    safe(cur, "mph_id_multi_symbol", """
        SELECT CompanyID, COUNT(DISTINCT Symbol) AS symbol_count
        FROM dbo.MarketPriceHistory
        WHERE Symbol IS NOT NULL
        GROUP BY CompanyID HAVING COUNT(DISTINCT Symbol) > 1
        ORDER BY symbol_count DESC
    """)
    safe(cur, "mph_instrument_multi", """
        SELECT InstrumentCode, COUNT(DISTINCT Symbol) AS symbols,
               COUNT(DISTINCT CompanyID) AS ids, COUNT(*) AS rows
        FROM dbo.MarketPriceHistory
        GROUP BY InstrumentCode HAVING COUNT(DISTINCT Symbol) > 1 OR COUNT(DISTINCT CompanyID) > 1
        ORDER BY symbols DESC
    """)
    safe(cur, "mph_id_multi_instrument", """
        SELECT CompanyID, COUNT(DISTINCT InstrumentCode) AS instruments
        FROM dbo.MarketPriceHistory
        GROUP BY CompanyID HAVING COUNT(DISTINCT InstrumentCode) > 1
        ORDER BY instruments DESC
    """)
    safe(cur, "tracked_tickers", "SELECT Symbol, Source, IsActive FROM dbo.TrackedTickers")
    safe(cur, "fullpe_names", "SELECT CompanyName, PE, Price FROM dbo.FullPE")
    safe(cur, "codalreports_tickers", """
        SELECT DISTINCT Ticker, CompanyName FROM dbo.CodalReports
        WHERE Ticker IS NOT NULL AND Ticker <> ''
    """)
    safe(cur, "codalreports_summary", """
        SELECT LetterType, Status, COUNT(*) AS n FROM dbo.CodalReports
        GROUP BY LetterType, Status ORDER BY LetterType, Status
    """)
    safe(cur, "codalreports_url_sample", "SELECT TOP 10 CodalReportId, Ticker, CompanyName, SourceUrl FROM dbo.CodalReports")

    # coverage: how many ids have both financial & monthly & price
    safe(cur, "coverage", """
        WITH m AS (SELECT DISTINCT CompanyID FROM dbo.mahane WHERE CompanyID IS NOT NULL),
             f AS (SELECT DISTINCT CompanyID FROM dbo.miandore2 WHERE CompanyID IS NOT NULL),
             p AS (SELECT DISTINCT CompanyID FROM dbo.MarketPriceHistory WHERE CompanyID IS NOT NULL)
        SELECT
            (SELECT COUNT(*) FROM m) AS monthly_ids,
            (SELECT COUNT(*) FROM f) AS financial_ids,
            (SELECT COUNT(*) FROM p) AS price_ids,
            (SELECT COUNT(*) FROM m JOIN f ON m.CompanyID=f.CompanyID) AS monthly_and_financial,
            (SELECT COUNT(*) FROM f JOIN p ON f.CompanyID=p.CompanyID) AS financial_and_price,
            (SELECT COUNT(*) FROM m JOIN p ON m.CompanyID=p.CompanyID) AS monthly_and_price
    """)

    # ================= 2) UNITS =================
    print("-- units --")
    safe(cur, "statements_units", """
        SELECT StatementType, MetricCode, UnitCode, COUNT(*) AS n,
               MIN(Value) AS min_v, MAX(Value) AS max_v
        FROM dbo.statements GROUP BY StatementType, MetricCode, UnitCode
        ORDER BY StatementType, MetricCode
    """)
    safe(cur, "statements_periodheaders", """
        SELECT TOP 20 StatementType, MetricCode, PeriodHeader, RowTitle, Value, UnitCode
        FROM dbo.statements ORDER BY CompanyName, ReportDate
    """)
    safe(cur, "miandore2_sample10", """
        SELECT TOP 15 CompanyName, ReportDate, Num1_Value1 AS EPS, Num2_Value1 AS Capital,
               Product1, NetProfitAmount, RevenueNew, OperatingProfitNew, FinanceCostsNew,
               TotalAssets, TotalEquity
        FROM dbo.miandore2
        WHERE Num1_Value1 IS NOT NULL AND Num1_Value1 <> 0 AND Product1 IS NOT NULL AND Product1 <> 0
        ORDER BY CompanyName, ReportDate DESC
    """)
    safe(cur, "miandore2_ratio_stats", """
        SELECT
            COUNT(*) AS n,
            AVG(LOG10(ABS(NetProfitAmount / Product1))) AS avg_log10_np_over_p1,
            MIN(LOG10(ABS(NetProfitAmount / Product1))) AS min_log10,
            MAX(LOG10(ABS(NetProfitAmount / Product1))) AS max_log10
        FROM dbo.miandore2
        WHERE Product1 <> 0 AND NetProfitAmount IS NOT NULL AND NetProfitAmount <> 0
          AND Product1 > 0 AND NetProfitAmount > 0
    """)
    safe(cur, "miandore2_ratio_histogram", """
        SELECT ROUND(LOG10(ABS(NetProfitAmount / Product1)), 0) AS log10_bucket, COUNT(*) AS n
        FROM dbo.miandore2
        WHERE Product1 <> 0 AND NetProfitAmount IS NOT NULL AND NetProfitAmount <> 0
          AND Product1 > 0 AND NetProfitAmount > 0
        GROUP BY ROUND(LOG10(ABS(NetProfitAmount / Product1)), 0)
        ORDER BY log10_bucket
    """)
    safe(cur, "miandore2_eps_vs_np", """
        SELECT TOP 15 CompanyName, ReportDate, Num1_Value1 AS EPS, Num2_Value1 AS Capital,
               NetProfitAmount, RevenueNew,
               NetProfitAmount / NULLIF(Num1_Value1, 0) AS implied_shares_x_unit
        FROM dbo.miandore2
        WHERE Num1_Value1 IS NOT NULL AND Num1_Value1 <> 0 AND NetProfitAmount IS NOT NULL
        ORDER BY CompanyName, ReportDate DESC
    """)
    safe(cur, "mahane_value_stats", """
        SELECT COUNT(*) AS n,
               MIN(Value1) AS min_v1, AVG(Value1) AS avg_v1, MAX(Value1) AS max_v1,
               MIN(Value3) AS min_v3, AVG(Value3) AS avg_v3, MAX(Value3) AS max_v3
        FROM dbo.mahane
    """)
    safe(cur, "mahane_sample10", "SELECT TOP 10 CompanyName, ReportDate, Value1, Value2, Value3, Url FROM dbo.mahane ORDER BY ReportDate DESC")

    # ================= 3) PRICE =================
    print("-- price --")
    safe(cur, "mph_overall", """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT InstrumentCode) AS instruments,
               COUNT(DISTINCT CompanyID) AS ids, COUNT(DISTINCT Symbol) AS symbols,
               MIN(GregorianDate) AS min_date, MAX(GregorianDate) AS max_date
        FROM dbo.MarketPriceHistory
    """)
    safe(cur, "stockdata_overall", """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT Ticker) AS tickers,
               MIN(TradeDate) AS min_date, MAX(TradeDate) AS max_date,
               MIN(Close) AS min_close, MAX(Close) AS max_close
        FROM dbo.StockData
    """)
    safe(cur, "stockprices_overall", """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT CompanyName) AS names,
               MIN(TRY_CONVERT(datetime, date)) AS min_date, MAX(TRY_CONVERT(datetime, date)) AS max_date
        FROM dbo.StockPrices
    """)
    safe(cur, "mph_top20", """
        SELECT TOP 20 Symbol, InstrumentCode, CompanyID, CompanyName,
               COUNT(*) AS rows, MIN(GregorianDate) AS min_date, MAX(GregorianDate) AS max_date,
               MIN(ClosingPrice) AS min_close, MAX(ClosingPrice) AS max_close,
               AVG(CAST(ClosingPrice AS FLOAT)) AS avg_close
        FROM dbo.MarketPriceHistory
        GROUP BY Symbol, InstrumentCode, CompanyID, CompanyName
        ORDER BY COUNT(*) DESC
    """)
    # duplicate (CompanyID, date) / (Symbol,date)
    safe(cur, "mph_dup_symbol_date", """
        SELECT COUNT(*) AS dup_groups FROM (
            SELECT Symbol, GregorianDate FROM dbo.MarketPriceHistory
            WHERE Symbol IS NOT NULL
            GROUP BY Symbol, GregorianDate HAVING COUNT(*) > 1
        ) t
    """)
    safe(cur, "mph_dup_id_date", """
        SELECT COUNT(*) AS dup_groups FROM (
            SELECT CompanyID, GregorianDate FROM dbo.MarketPriceHistory
            GROUP BY CompanyID, GregorianDate HAVING COUNT(*) > 1
        ) t
    """)
    # compare MPH vs StockData on overlap
    safe(cur, "price_compare_overall", """
        SELECT TOP 30 d.Ticker AS symbol, COUNT(*) AS overlap_rows,
               AVG(CAST(d.[Close] AS FLOAT)) AS avg_stockdata_close,
               AVG(CAST(p.ClosingPrice AS FLOAT)) AS avg_mph_close,
               AVG(CAST(p.ClosingPrice AS FLOAT) / NULLIF(d.[Close], 0)) AS avg_ratio
        FROM dbo.StockData d
        JOIN dbo.MarketPriceHistory p
          ON p.Symbol = d.Ticker AND p.GregorianDate = d.TradeDate
        GROUP BY d.Ticker
        ORDER BY COUNT(*) DESC
    """)
    safe(cur, "price_ratio_buckets", """
        SELECT ROUND(CAST(p.ClosingPrice AS FLOAT) / NULLIF(d.[Close], 0), 2) AS ratio, COUNT(*) AS n
        FROM dbo.StockData d
        JOIN dbo.MarketPriceHistory p
          ON p.Symbol = d.Ticker AND p.GregorianDate = d.TradeDate
        WHERE d.[Close] <> 0
        GROUP BY ROUND(CAST(p.ClosingPrice AS FLOAT) / NULLIF(d.[Close], 0), 2)
        HAVING COUNT(*) > 100
        ORDER BY ratio
    """)
    safe(cur, "fullpe_vs_mph", """
        SELECT TOP 20 f.CompanyName, f.PE, f.Price AS fullpe_price,
               p.Symbol, p.GregorianDate, p.ClosingPrice AS mph_close, p.LastPrice AS mph_last
        FROM dbo.FullPE f
        JOIN dbo.MarketPriceHistory p ON p.CompanyName = f.CompanyName
        WHERE p.GregorianDate = (SELECT MAX(GregorianDate) FROM dbo.MarketPriceHistory)
        ORDER BY f.CompanyName
    """)

    # ================= 4) DATES =================
    print("-- dates --")
    safe(cur, "date_naive_check", """
        SELECT
            MAX(GregorianDate) AS mph_max_greg, MAX(CollectedAt) AS mph_max_collected,
            (SELECT MAX(PublishedAt) FROM dbo.CodalReports) AS codal_max_published,
            (SELECT MAX(DiscoveredAt) FROM dbo.CodalReports) AS codal_max_discovered,
            (SELECT MAX(ProcessedAt) FROM dbo.CodalReports) AS codal_max_processed
        FROM dbo.MarketPriceHistory
    """)
    safe(cur, "family_recordedat", "SELECT TOP 5 DateKey, RecordedAt FROM dbo.FamilyHistory ORDER BY DateKey DESC")
    safe(cur, "reportdate_formats", "SELECT TOP 20 CompanyName, ReportDate FROM dbo.miandore2 WHERE ReportDate IS NOT NULL ORDER BY ReportDate DESC")
    safe(cur, "reportdate_bad", """
        SELECT COUNT(*) AS bad FROM dbo.miandore2
        WHERE ReportDate IS NOT NULL AND dbo.fn_JalaliKey(ReportDate) IS NULL
    """)

    cn.close()
    (BASE / "_investigation_facts.json").write_text(
        json.dumps(OUT, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("Wrote _investigation_facts.json")


if __name__ == "__main__":
    main()
