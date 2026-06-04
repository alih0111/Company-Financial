import requests
import pyodbc
import os
from dotenv import load_dotenv

# بارگذاری تنظیمات اتصال از فایل .env
load_dotenv()

server = os.getenv('DB_SERVER')
database = os.getenv('DB_NAME')
username = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')

# رشته اتصال
conn_str = (
    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
    f'SERVER={server};DATABASE={database};UID={username};PWD={password}'
)

# هدر مورد نیاز برای درخواست‌های SEC
headers = {"User-Agent": "YourName Contact@YourEmail.com"}

def fetch_company_list():
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def insert_companies(companies):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    for _, info in companies.items():
        cik = str(info["cik_str"])
        ticker = info.get("ticker")
        name = info.get("title")

        # اگر وجود نداشت، اضافه کن
        cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM Companies WHERE CIK = ?)
            INSERT INTO Companies (CIK, Ticker, CompanyName, CreatedAt)
            VALUES (?, ?, ?, GETDATE())
        """, cik, cik, ticker, name)

    conn.commit()
    cursor.close()
    conn.close()

if __name__ == "__main__":
    print("📥 Fetching companies from SEC...")
    companies = fetch_company_list()
    print(f"✅ Fetched {len(companies)} companies")

    print("💾 Inserting into SQL Server...")
    insert_companies(companies)

    print("🎉 Done! All companies inserted/updated.")
