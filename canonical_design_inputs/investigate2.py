"""Focused read-only queries + identity CSV. SELECT only."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pyodbc
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
load_dotenv(REPO / "go-app" / ".env")


def connect():
    cs = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};PWD={os.getenv('DB_PASSWORD')};TrustServerCertificate=yes;"
    )
    return pyodbc.connect(cs, timeout=20)


def show(cur, title, sql, *p):
    try:
        cur.execute(sql, *p)
        rows = cur.fetchall()
        print(f"\n=== {title} ({len(rows)}) ===")
        for r in rows[:40]:
            print("  ", tuple(r))
        return rows
    except Exception as e:
        print(f"\n=== {title} ERROR: {e} ===")
        return []


cn = connect()
cur = cn.cursor()

show(cur, "max name_count mahane", "SELECT MAX(c) FROM (SELECT COUNT(DISTINCT CompanyName) c FROM dbo.mahane GROUP BY CompanyID) t")
show(cur, "max name_count miandore2", "SELECT MAX(c) FROM (SELECT COUNT(DISTINCT CompanyName) c FROM dbo.miandore2 GROUP BY CompanyID) t")

show(cur, "mahane-only ids", """
    SELECT COUNT(*) FROM (SELECT DISTINCT CompanyID FROM dbo.mahane) m
    WHERE NOT EXISTS (SELECT 1 FROM dbo.miandore2 f WHERE f.CompanyID=m.CompanyID)
""")
show(cur, "miandore2-only ids", """
    SELECT COUNT(*) FROM (SELECT DISTINCT CompanyID FROM dbo.miandore2) f
    WHERE NOT EXISTS (SELECT 1 FROM dbo.mahane m WHERE m.CompanyID=f.CompanyID)
""")
show(cur, "coverage", """
    WITH m AS (SELECT DISTINCT CompanyID FROM dbo.mahane WHERE CompanyID IS NOT NULL),
         f AS (SELECT DISTINCT CompanyID FROM dbo.miandore2 WHERE CompanyID IS NOT NULL),
         p AS (SELECT DISTINCT CompanyID FROM dbo.MarketPriceHistory WHERE CompanyID IS NOT NULL)
    SELECT (SELECT COUNT(*) FROM m) monthly_ids,
           (SELECT COUNT(*) FROM f) financial_ids,
           (SELECT COUNT(*) FROM p) price_ids,
           (SELECT COUNT(*) FROM m JOIN f ON m.CompanyID=f.CompanyID) m_f,
           (SELECT COUNT(*) FROM f JOIN p ON f.CompanyID=p.CompanyID) f_p,
           (SELECT COUNT(*) FROM m JOIN p ON m.CompanyID=p.CompanyID) m_p
""")

show(cur, "symbol -> multiple ids", """
    SELECT Symbol, COUNT(DISTINCT CompanyID) ids, MIN(CompanyName) n1, MIN(InstrumentCode) i1,
           COUNT(DISTINCT InstrumentCode) instr
    FROM dbo.MarketPriceHistory WHERE Symbol IS NOT NULL
    GROUP BY Symbol HAVING COUNT(DISTINCT CompanyID)>1
""")
show(cur, "id -> multiple symbols", """
    SELECT CompanyID, COUNT(DISTINCT Symbol) syms
    FROM dbo.MarketPriceHistory WHERE Symbol IS NOT NULL
    GROUP BY CompanyID HAVING COUNT(DISTINCT Symbol)>1
""")
show(cur, "instrument -> multiple", """
    SELECT InstrumentCode, COUNT(DISTINCT Symbol) syms, COUNT(DISTINCT CompanyID) ids
    FROM dbo.MarketPriceHistory GROUP BY InstrumentCode
    HAVING COUNT(DISTINCT Symbol)>1 OR COUNT(DISTINCT CompanyID)>1
""")
show(cur, "id -> multiple instrument", """
    SELECT CompanyID, COUNT(DISTINCT InstrumentCode) instrs
    FROM dbo.MarketPriceHistory GROUP BY CompanyID HAVING COUNT(DISTINCT InstrumentCode)>1
""")

show(cur, "company name mismatch between mahane/miandore2", """
    SELECT m.CompanyID, m.cn AS monthly_name, f.cn AS financial_name
    FROM (SELECT DISTINCT CompanyID, CompanyName cn FROM dbo.mahane) m
    JOIN (SELECT DISTINCT CompanyID, CompanyName cn FROM dbo.miandore2) f ON m.CompanyID=f.CompanyID
    WHERE m.cn <> f.cn
""")
show(cur, "name appears in >1 id across tables (normalized)", """
    SELECT REPLACE(REPLACE(CompanyName,'ي','ی'),'ك','ک') nm, COUNT(DISTINCT CompanyID) ids
    FROM (SELECT CompanyName, CompanyID FROM dbo.mahane UNION ALL SELECT CompanyName, CompanyID FROM dbo.miandore2) t
    WHERE CompanyName IS NOT NULL
    GROUP BY REPLACE(REPLACE(CompanyName,'ي','ی'),'ك','ک') HAVING COUNT(DISTINCT CompanyID)>1
""")

show(cur, "statements distinct units", "SELECT DISTINCT StatementType, UnitCode FROM dbo.statements ORDER BY StatementType, UnitCode")
show(cur, "statements metric x unit", """
    SELECT StatementType, MetricCode, UnitCode, COUNT(*) n FROM dbo.statements
    GROUP BY StatementType, MetricCode, UnitCode ORDER BY StatementType, MetricCode
""")

show(cur, "miandore2 ratio histogram", """
    SELECT ROUND(LOG10(ABS(NetProfitAmount/Product1)),0) b, COUNT(*) n
    FROM dbo.miandore2 WHERE Product1>0 AND NetProfitAmount>0
    GROUP BY ROUND(LOG10(ABS(NetProfitAmount/Product1)),0) ORDER BY b
""")
show(cur, "miandore2 ratio by company sample", """
    SELECT TOP 20 CompanyName, ReportDate, Num1_Value1 EPS, Num2_Value1 Capital, Product1,
           NetProfitAmount, RevenueNew,
           LOG10(ABS(NetProfitAmount/Product1)) log_ratio,
           Product1 - (Num1_Value1*Num2_Value1) product_check
    FROM dbo.miandore2
    WHERE Product1>0 AND NetProfitAmount>0 AND Num1_Value1>0
    ORDER BY CompanyName, ReportDate DESC
""")
show(cur, "miandore2 capital/EPS vs NetProfit sample", """
    SELECT TOP 20 CompanyName, ReportDate, Num1_Value1 EPS, Num2_Value1 Capital,
           NetProfitAmount, NetProfitAmount/NULLIF(Num1_Value1,0) implied_shares_x_U,
           Num2_Value1/NULLIF(NetProfitAmount/NULLIF(Num1_Value1,0),0) capital_over_implied
    FROM dbo.miandore2
    WHERE Num1_Value1>0 AND Num2_Value1>0 AND NetProfitAmount>0
    ORDER BY CompanyName
""")

show(cur, "mph overall", """
    SELECT COUNT(*) rows_, COUNT(DISTINCT InstrumentCode) instr, COUNT(DISTINCT CompanyID) ids,
           COUNT(DISTINCT Symbol) syms, MIN(GregorianDate) mn, MAX(GregorianDate) mx
    FROM dbo.MarketPriceHistory
""")
show(cur, "stockdata overall", """
    SELECT COUNT(*) rows_, COUNT(DISTINCT Ticker) tickers, MIN(TradeDate) mn, MAX(TradeDate) mx,
           MIN([Close]) min_close, MAX([Close]) max_close, AVG([Close]) avg_close
    FROM dbo.StockData
""")
show(cur, "price ratio buckets", """
    SELECT ROUND(CAST(p.ClosingPrice AS FLOAT)/NULLIF(d.[Close],0),2) ratio, COUNT(*) n
    FROM dbo.StockData d JOIN dbo.MarketPriceHistory p ON p.Symbol=d.Ticker AND p.GregorianDate=d.TradeDate
    WHERE d.[Close]<>0 GROUP BY ROUND(CAST(p.ClosingPrice AS FLOAT)/NULLIF(d.[Close],0),2)
    HAVING COUNT(*)>50 ORDER BY n DESC
""")
show(cur, "stockdata per ticker", "SELECT TOP 15 Ticker, COUNT(*) n, MIN(TradeDate) mn, MAX(TradeDate) mx FROM dbo.StockData GROUP BY Ticker ORDER BY n DESC")
show(cur, "fullpe vs latest mph", """
    SELECT TOP 15 f.CompanyName, f.PE, f.Price fullpe_price, p.Symbol, p.ClosingPrice mph_close,
           CAST(f.Price AS FLOAT)/NULLIF(p.ClosingPrice,0) ratio
    FROM dbo.FullPE f
    JOIN dbo.MarketPriceHistory p ON p.CompanyName=f.CompanyName
    WHERE p.GregorianDate=(SELECT MAX(GregorianDate) FROM dbo.MarketPriceHistory)
    ORDER BY f.CompanyName
""")
show(cur, "familyprices nature", "SELECT TOP 10 fp.DateKey, fa.Name, fa.Category, fp.Price FROM dbo.FamilyPrices fp JOIN dbo.FamilyAssets fa ON fa.AssetID=fp.AssetID ORDER BY fp.DateKey DESC")

show(cur, "date naive", """
    SELECT MAX(CollectedAt) mph_collected, (SELECT MAX(PublishedAt) FROM dbo.CodalReports) max_pub,
           (SELECT MAX(DiscoveredAt) FROM dbo.CodalReports) max_disc
    FROM dbo.MarketPriceHistory
""")
show(cur, "reportdate bad jalali", "SELECT COUNT(*) bad FROM dbo.miandore2 WHERE ReportDate IS NOT NULL AND dbo.fn_JalaliKey(ReportDate) IS NULL")
show(cur, "reportdate max/min", "SELECT MIN(ReportDate) mn, MAX(ReportDate) mx FROM dbo.miandore2")

# ---------- identity CSV ----------
print("\nBuilding company_identity_candidates.csv ...")
cur.execute("""
    WITH ids AS (
        SELECT CompanyID FROM dbo.mahane WHERE CompanyID IS NOT NULL
        UNION SELECT CompanyID FROM dbo.miandore2 WHERE CompanyID IS NOT NULL
        UNION SELECT CompanyID FROM dbo.MarketPriceHistory WHERE CompanyID IS NOT NULL
    ),
    names AS (
        SELECT CompanyID, CompanyName, COUNT(*) n FROM (
            SELECT CompanyID, CompanyName FROM dbo.mahane WHERE CompanyName IS NOT NULL
            UNION ALL SELECT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyName IS NOT NULL
        ) t GROUP BY CompanyID, CompanyName
    ),
    best_name AS (
        SELECT CompanyID, CompanyName FROM (
            SELECT CompanyID, CompanyName, ROW_NUMBER() OVER (PARTITION BY CompanyID ORDER BY n DESC, CompanyName) rn
            FROM names
        ) x WHERE rn=1
    ),
    name_distinct AS (
        SELECT CompanyID, COUNT(DISTINCT CompanyName) distinct_names FROM names GROUP BY CompanyID
    ),
    mph AS (
        SELECT CompanyID,
               MAX(Symbol) symbol, MAX(InstrumentCode) instrument_code, MAX(BrsName) brs_name,
               COUNT(DISTINCT Symbol) syms, COUNT(DISTINCT InstrumentCode) instrs
        FROM dbo.MarketPriceHistory GROUP BY CompanyID
    )
    SELECT i.CompanyID,
           bn.CompanyName, nd.distinct_names,
           mph.symbol, mph.syms, mph.instrument_code, mph.instrs, mph.brs_name,
           CASE WHEN m.CompanyID IS NOT NULL THEN 1 ELSE 0 END has_monthly,
           CASE WHEN f.CompanyID IS NOT NULL THEN 1 ELSE 0 END has_financial,
           CASE WHEN p.CompanyID IS NOT NULL THEN 1 ELSE 0 END has_price
    FROM ids i
    LEFT JOIN best_name bn ON bn.CompanyID=i.CompanyID
    LEFT JOIN name_distinct nd ON nd.CompanyID=i.CompanyID
    LEFT JOIN mph ON mph.CompanyID=i.CompanyID
    LEFT JOIN (SELECT DISTINCT CompanyID FROM dbo.mahane) m ON m.CompanyID=i.CompanyID
    LEFT JOIN (SELECT DISTINCT CompanyID FROM dbo.miandore2) f ON f.CompanyID=i.CompanyID
    LEFT JOIN (SELECT DISTINCT CompanyID FROM dbo.MarketPriceHistory) p ON p.CompanyID=i.CompanyID
""")
rows = cur.fetchall()
# codal tickers lookup
cur.execute("SELECT DISTINCT Ticker, CompanyName FROM dbo.CodalReports WHERE Ticker IS NOT NULL AND Ticker<>''")
codal = cur.fetchall()
codal_by_ticker = {t: n for t, n in codal}
codal_names = {n for _, n in codal}

out = BASE / "company_identity_candidates.csv"
with out.open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["current_company_id", "company_name", "symbol", "instrument_code", "brs_name",
                "codal_ticker", "has_monthly", "has_financial", "has_price", "confidence", "issues"])
    for r in rows:
        (cid, name, distinct_names, symbol, syms, instr, instrs, brs,
         has_m, has_f, has_p) = r
        syms = syms or 0
        instrs = instrs or 0
        issues = []
        if not symbol:
            issues.append("no_symbol")
        if syms and syms > 1:
            issues.append(f"multi_symbol({syms})")
        if instrs and instrs > 1:
            issues.append(f"multi_instrument({instrs})")
        if distinct_names and distinct_names > 1:
            issues.append(f"multi_name({distinct_names})")
        if not has_m:
            issues.append("no_monthly")
        if not has_f:
            issues.append("no_financial")
        if not has_p:
            issues.append("no_price")
        codal_ticker = symbol if symbol in codal_by_ticker else ""
        # confidence heuristic
        if symbol and syms <= 1 and (not distinct_names or distinct_names <= 1) and has_p and (has_f or has_m):
            conf = "HIGH"
        elif symbol:
            conf = "MEDIUM"
        else:
            conf = "LOW"
        w.writerow([cid, name, symbol, instr, brs, codal_ticker,
                    has_m, has_f, has_p, conf, "; ".join(issues)])
print(f"  wrote {out} ({len(rows)} rows)")
cn.close()
