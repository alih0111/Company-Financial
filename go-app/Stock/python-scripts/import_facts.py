import requests
import pyodbc
import os
from dotenv import load_dotenv

# بارگذاری تنظیمات اتصال
load_dotenv()

server = os.getenv('DB_SERVER')
database = os.getenv('DB_NAME')
username = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')

conn_str = (
    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
    f'SERVER={server};DATABASE={database};UID={username};PWD={password}'
)

headers = {"User-Agent": "YourName Contact@YourEmail.com"}


def fetch_company_facts(cik):
    cik_padded = str(cik).zfill(10)  # باید 10 رقمی باشه
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def insert_financial_data(company_id, facts):
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    # Loop همه فکت‌ها
    for taxonomy, items in facts["facts"].items():
        for tag, data in items.items():
            # بعضی فکت‌ها ممکنه unit نداشته باشن
            if "units" not in data:
                continue

            for unit, datapoints in data["units"].items():
                for dp in datapoints:
                    accn = dp.get("accn")
                    fy = dp.get("fy")
                    fp = dp.get("fp")
                    form = dp.get("form")
                    end_date = dp.get("end")
                    filed = dp.get("filed")
                    val = dp.get("val")

                    if not (accn and fy and fp and form and end_date and filed):
                        continue

                    # درج/آپدیت گزارش و گرفتن ReportID
                    cursor.execute("""
                        MERGE FinancialReports AS target
                        USING (SELECT ? AS CompanyID, ? AS FilingType, ? AS FiscalYear, ? AS FiscalPeriod) AS src
                        ON target.CompanyID = src.CompanyID AND target.FilingType = src.FilingType
                           AND target.FiscalYear = src.FiscalYear AND target.FiscalPeriod = src.FiscalPeriod
                        WHEN MATCHED THEN
                            UPDATE SET ReportDate = ?, AcceptedDate = ?, Url = ?
                        WHEN NOT MATCHED THEN
                            INSERT (CompanyID, FilingType, FiscalYear, FiscalPeriod, ReportDate, AcceptedDate, Url, CreatedAt)
                            VALUES (src.CompanyID, src.FilingType, src.FiscalYear, src.FiscalPeriod, ?, ?, ?, GETDATE())
                        OUTPUT inserted.ReportID;
                    """,
                        company_id, form, fy, fp,
                        end_date, filed, f"https://www.sec.gov/Archives/edgar/data/{company_id}/{accn}",
                        end_date, filed, f"https://www.sec.gov/Archives/edgar/data/{company_id}/{accn}"
                    )

                    row = cursor.fetchone()
                    if not row:
                        continue
                    report_id = row[0]

                    # درج Fact (اگر وجود نداشت)
                    cursor.execute("""
                        IF NOT EXISTS (
                            SELECT 1 FROM FinancialFacts
                            WHERE ReportID = ? AND Concept = ? AND Unit = ? AND EndDate = ?
                        )
                        INSERT INTO FinancialFacts (ReportID, Concept, Value, Unit, EndDate)
                        VALUES (?, ?, ?, ?, ?)
                    """, report_id, tag, unit, end_date,
                         report_id, tag, val, unit, end_date)

    conn.commit()
    cursor.close()
    conn.close()


if __name__ == "__main__":
    cik = "0000320193"  # اپل
    print(f"📥 Fetching facts for AAPL (CIK {cik})...")
    facts = fetch_company_facts(cik)

    print("💾 Inserting into SQL Server...")
    insert_financial_data(cik, facts)

    print("🎉 Done! Financial data inserted.")
