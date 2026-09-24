"""Final identity details -> JSON. SELECT only."""
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
def q(n, s, *p):
    cur.execute(s, *p); cols=[c[0] for c in cur.description]
    out[n]=[dict(zip(cols,r)) for r in cur.fetchall()]; print(n, len(out[n]))

q("symbol_collision", """
    SELECT Symbol, CompanyID, CompanyName, InstrumentCode, COUNT(*) n, MIN(GregorianDate) mn, MAX(GregorianDate) mx
    FROM dbo.MarketPriceHistory
    WHERE Symbol IN (SELECT Symbol FROM dbo.MarketPriceHistory WHERE Symbol IS NOT NULL AND CompanyID IS NOT NULL
                     GROUP BY Symbol HAVING COUNT(DISTINCT CompanyID)>1)
    GROUP BY Symbol, CompanyID, CompanyName, InstrumentCode
""")
q("multi_symbol_ids", """
    SELECT CompanyID, Symbol, COUNT(*) n, MIN(GregorianDate) mn, MAX(GregorianDate) mx
    FROM dbo.MarketPriceHistory
    WHERE CompanyID IN ('5d9142cab82acfbf6d12ef1824abd59b','62475be81f64f0f74b0f1f4a798dd2c5','fa2e3267b28da291dc990ba6910786d0')
    GROUP BY CompanyID, Symbol ORDER BY CompanyID, n DESC
""")
q("tracked_sources", "SELECT Source, COUNT(*) n, SUM(CASE WHEN IsActive=1 THEN 1 ELSE 0 END) active FROM dbo.TrackedTickers GROUP BY Source")
q("codalreports_status", "SELECT LetterType, Status, COUNT(*) n FROM dbo.CodalReports GROUP BY LetterType, Status ORDER BY LetterType, Status")
q("instrument_examples", "SELECT TOP 10 CompanyID, MIN(CompanyName) name, MIN(Symbol) symbol, MIN(InstrumentCode) ic, COUNT(DISTINCT InstrumentCode) icount FROM dbo.MarketPriceHistory GROUP BY CompanyID ORDER BY name")
cn.close()
(BASE / "_identity_details.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("wrote _identity_details.json")
