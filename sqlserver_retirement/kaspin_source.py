import os, sys
from dotenv import load_dotenv
load_dotenv(r"D:\RFA\Company-Financial\go-app\.env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pyodbc

CID = "7386c9d3264a07cdaacbdba2e1941d42"
cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};DATABASE={os.environ['DB_NAME']};"
      f"UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};TrustServerCertificate=yes;Connection Timeout=10")
cn = pyodbc.connect(cs, timeout=15)
cur = cn.cursor()
cur.execute("""SELECT ReportDate, Num1_Value1, Num1_Value2, Num1_Value3,
                      NetProfitAmount, NetProfitAmountLY, NetProfitAmountFYPrev,
                      RevenueNew, OperatingProfitNew, Num2_Value1, Product1
               FROM dbo.miandore2 WHERE CompanyID=? ORDER BY ReportDate DESC""", (CID,))
cols = [c[0] for c in cur.description]
print(" | ".join(cols))
for r in cur.fetchall():
    print(" | ".join(str(x) for x in r))
cn.close()
