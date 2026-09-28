import os, sys
from dotenv import load_dotenv
load_dotenv(r"D:\RFA\Company-Financial\go-app\.env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pyodbc
cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};DATABASE={os.environ['DB_NAME']};"
      f"UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};TrustServerCertificate=yes;Connection Timeout=10")
cn = pyodbc.connect(cs, timeout=15)
cur = cn.cursor()

# How many miandore2 rows have a non-null NetProfitAmount, per company / overall?
cur.execute("SELECT COUNT(*) FROM dbo.miandore2")
total = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM dbo.miandore2 WHERE NetProfitAmount IS NOT NULL")
np = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM dbo.miandore2 WHERE RevenueNew IS NOT NULL")
rev = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM dbo.miandore2 WHERE Num1_Value1 IS NOT NULL")
eps = cur.fetchone()[0]
print(f"miandore2 rows={total}  NetProfitAmount non-null={np}  RevenueNew non-null={rev}  EPS non-null={eps}")

# Kaspin
CID = "7386c9d3264a07cdaacbdba2e1941d42"
cur.execute("SELECT COUNT(*), SUM(CASE WHEN NetProfitAmount IS NOT NULL THEN 1 ELSE 0 END) FROM dbo.miandore2 WHERE CompanyID=?", (CID,))
print("kaspin rows/np:", cur.fetchone())

# distribution: how many companies have >1 non-null netprofit row
cur.execute("""SELECT cnt, COUNT(*) FROM (
                 SELECT CompanyID, SUM(CASE WHEN NetProfitAmount IS NOT NULL THEN 1 ELSE 0 END) AS cnt
                 FROM dbo.miandore2 GROUP BY CompanyID) t GROUP BY cnt ORDER BY cnt""")
print("companies by #non-null net_profit rows:", cur.fetchall())
cn.close()