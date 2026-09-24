"""Units + price cross-checks -> compact JSON. SELECT only."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import pyodbc
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = Path(__file__).resolve().parent
REPO = BASE.parent
load_dotenv(REPO / "go-app" / ".env")
cs = ("DRIVER={ODBC Driver 17 for SQL Server};SERVER=%s;DATABASE=%s;UID=%s;PWD=%s;TrustServerCertificate=yes" % (
    os.getenv("DB_SERVER"), os.getenv("DB_NAME"), os.getenv("DB_USER"), os.getenv("DB_PASSWORD")))
cn = pyodbc.connect(cs, timeout=20); cur = cn.cursor()
out = {}

def q(name, sql, *p):
    cur.execute(sql, *p)
    cols = [c[0] for c in cur.description]
    out[name] = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(name, len(out[name]))

# 10-12 companies across industries: latest row each
q("miandore2_latest_per_company", """
    WITH r AS (
        SELECT CompanyName, ReportDate, Num1_Value1, Num2_Value1, Num4_Value1, Product1,
               NetProfitAmount, NetProfitAmountLY, NetProfitAmountFYPrev,
               OperatingProfitNew, RevenueNew, FinanceCostsNew,
               TotalAssets, TotalEquity,
               ROW_NUMBER() OVER (PARTITION BY CompanyName ORDER BY dbo.fn_JalaliKey(ReportDate) DESC) rn
        FROM dbo.miandore2
        WHERE Num1_Value1 IS NOT NULL
    )
    SELECT CompanyName, ReportDate, Num1_Value1 AS EPS, Num2_Value1 AS Capital,
           Product1, NetProfitAmount, RevenueNew, OperatingProfitNew,
           TotalAssets, TotalEquity,
           CASE WHEN Product1>0 AND NetProfitAmount>0 THEN ROUND(LOG10(ABS(NetProfitAmount/Product1)),3) END AS log10_np_over_p1,
           CASE WHEN Num1_Value1>0 AND NetProfitAmount IS NOT NULL THEN NetProfitAmount/Num1_Value1 END AS np_over_eps,
           CASE WHEN Num1_Value1>0 AND Num2_Value1>0 AND NetProfitAmount>0
                THEN (NetProfitAmount/Num1_Value1) / Num2_Value1 END AS implied_shares_over_capital
    FROM r WHERE rn=1
""")

# statements: distinct statement types and sample values
q("statements_types", "SELECT StatementType, COUNT(*) n, COUNT(DISTINCT CompanyName) companies FROM dbo.statements GROUP BY StatementType")
q("statements_sample", "SELECT TOP 25 CompanyName, ReportDate, StatementType, MetricCode, PeriodOrder, PeriodHeader, RowTitle, Value, UnitCode FROM dbo.statements ORDER BY CompanyName")

# mahane latest per company value magnitudes
q("mahane_latest", """
    WITH r AS (SELECT CompanyName, ReportDate, Value1, Value2, Value3,
        ROW_NUMBER() OVER (PARTITION BY CompanyName ORDER BY dbo.fn_JalaliKey(ReportDate) DESC) rn
        FROM dbo.mahane)
    SELECT TOP 20 CompanyName, ReportDate, Value1, Value2, Value3 FROM r WHERE rn=1 ORDER BY CompanyName
""")

# price cross-check by year for a few tickers
q("price_ratio_by_year", """
    SELECT d.Ticker, YEAR(d.TradeDate) yr, COUNT(*) n,
           AVG(CAST(p.ClosingPrice AS FLOAT)/NULLIF(d.[Close],0)) avg_ratio
    FROM dbo.StockData d JOIN dbo.MarketPriceHistory p ON p.Symbol=d.Ticker AND p.GregorianDate=d.TradeDate
    WHERE d.[Close]<>0 AND d.Ticker IN ('شپاکسا','بترانس','قثابت','خموتور','سهگمت')
    GROUP BY d.Ticker, YEAR(d.TradeDate)
    ORDER BY d.Ticker, yr
""")

# mph price magnitude by symbol sample
q("mph_price_sample", "SELECT TOP 15 Symbol, GregorianDate, ClosingPrice, LastPrice, HighPrice, LowPrice, Volume, TradeValue, TradeCount FROM dbo.MarketPriceHistory ORDER BY GregorianDate DESC")

cn.close()
(BASE / "_units_price_facts.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("wrote _units_price_facts.json")
