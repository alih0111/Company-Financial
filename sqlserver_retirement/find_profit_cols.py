import os, sys
from dotenv import load_dotenv
load_dotenv(r"D:\RFA\Company-Financial\go-app\.env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pyodbc
cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};DATABASE={os.environ['DB_NAME']};"
      f"UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};TrustServerCertificate=yes;Connection Timeout=10")
cn = pyodbc.connect(cs, timeout=15)
cur = cn.cursor()
cur.execute("""SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
               WHERE COLUMN_NAME LIKE '%Profit%' OR COLUMN_NAME LIKE '%profit%'
               ORDER BY TABLE_NAME, COLUMN_NAME""")
for r in cur.fetchall():
    print(r)
print("--- tables like miandore/profit/codal ---")
cur.execute("""SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
               WHERE TABLE_NAME LIKE '%miandore%' OR TABLE_NAME LIKE '%Profit%' OR TABLE_NAME LIKE '%Codal%' OR TABLE_NAME LIKE '%Financial%'""")
for r in cur.fetchall():
    print(r)
cn.close()
