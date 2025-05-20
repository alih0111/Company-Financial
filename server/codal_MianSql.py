from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import pyodbc
import hashlib
import json
import jdatetime


def generate_company_id(name):
    return hashlib.md5(name.encode('utf-8')).hexdigest()


def to_number(s):
    s = s.replace(',', '').replace('٬', '')  # Remove commas (Arabic/Persian/English)
    s = re.sub(r'[^\d\.\-\(\)]', '', s)      # Remove non-numeric except (), - and .

    # Check for parentheses to indicate negative numbers
    if re.match(r'^\(\d+(\.\d+)?\)$', s):
        s = '-' + s.strip('()')

    return float(s) if s else 0


def main_scraper(companyName, rowMeta, base_url, page_numbers):
    
    base_url = base_url.replace("&PageNumber=1", "")

    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    all_data = []
    flag = True  # Ensure headers added only once

    for page in page_numbers:
        current_url = f"{base_url}&PageNumber={page}"
        driver.get(current_url)
        print(f"📄 Fetching data from page {page}...")

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "scrollContent"))
            )
            time.sleep(5)
        except:
            print(f"❌ The table did not load on page {page}. Skipping...")
            continue

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        report_links = []
        rows = driver.find_elements(By.CSS_SELECTOR, "tbody.scrollContent tr")

        for row in rows[:rowMeta]:
            try:
                link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(4) a")
                report_links.append(link_element.get_attribute("href"))
            except:
                continue

        if not report_links:
            print(f"⚠️ No report links found on page {page}. Retrying after extra wait time...")
            time.sleep(5)
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody.scrollContent tr")
            for row in rows:
                try:
                    link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(4) a")
                    report_links.append(link_element.get_attribute("href"))
                except:
                    continue

        print(f"✅ Found {len(report_links)} report links on page {page}.")

        for link in report_links:
            try:
                driver.get(link)
                print(f"🔍 Scraping: {link}")

                # Wait for Angular stability
                WebDriverWait(driver, 15).until(
                    lambda d: d.execute_script(
                        "return window.getAllAngularTestabilities && window.getAllAngularTestabilities().every(t => t.isStable())"
                    )
                )
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
                )

                # Extract report date
                try:
                    date_element = driver.find_element(By.ID, "ctl00_lblPeriodEndToDate")
                    report_date = date_element.text.strip()

                    # Skip reports earlier than 1397/09/30
                    try:
                        report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
                        min_date = jdatetime.date(1397, 12, 29)
                        if report_jdate <= min_date:
                            print(f"⏩ Skipping report dated {report_date} (before or on 1397/09/30)")
                            continue
                    except Exception as e:
                        print(f"❌ Failed to parse date '{report_date}': {e}")
                        continue

                except:
                    report_date = "N/A"

                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')

                table = soup.find('table', {'class': 'rayanDynamicStatement'})

                if table:
                    headers = [th.text.strip() for th in table.find_all('th')]
                    all_rows = table.find_all('tr')[1:]

                    first_row = [td.text.strip() for td in all_rows[0].find_all('td')] if len(all_rows) > 0 else []
                    last_row = []
                    if len(all_rows) >= 3:
                        row1 = [td.text.strip() for td in all_rows[-3].find_all('td')]
                        row2 = [td.text.strip() for td in all_rows[-2].find_all('td')]

                        min_len = min(len(row1), len(row2)) 
                        last_row = []

                        for i in range(1, min_len):
                            try:
                                num1 = to_number(row1[i])
                                num2 = to_number(row2[i])
                                last_row.append(num1 * num2)
                            except ValueError:
                                last_row.append(0)
                    else:
                        last_row = []

                    max_cols = max(len(first_row), len(last_row))
                    headers = headers[3:max_cols + 2]
                    first_row += [""] * (max_cols - len(first_row))
                    last_row += [""] * (max_cols - len(last_row))

                    if flag:
                        all_data.append(
                            ["Report Date"] + headers + ["داخلی"] + ["صادراتی"] + ["مجموع تعدادی"]
                        )
                        flag = False

                    dakheli_value = "0"
                    saderati_value = "0"

                    for tr in all_rows:
                        tds = tr.find_all('td')
                        if tds and "جمع فروش داخلی" in tds[0].get_text(strip=True):
                            if len(tds) >= 15:
                                dakheli_value = tds[14].get_text(strip=True)
                        if tds and "جمع فروش صادراتی" in tds[0].get_text(strip=True):
                            if len(tds) >= 15:
                                saderati_value = tds[14].get_text(strip=True)
                            break

                    # Clean and convert to float
                    dakheli_int = float(dakheli_value.replace(',', '').replace('٬', '') or "0")
                    saderati_int = float(saderati_value.replace(',', '').replace('٬', '') or "0")
                    total_value = dakheli_int + saderati_int

                    all_data.append(
                        [report_date] + last_row + [dakheli_value] + [saderati_value] + [str(total_value)]
                    )

                    # Database connection details
                    server = 'wsn-mis-068'
                    database = 'codal'
                    username = 'sa'
                    password = 'dbco@2023hamkaran'
                    table_name = 'miandore'

                    conn_str = (
                        f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};'
                        f'UID={username};PWD={password}'
                    )
                    conn = pyodbc.connect(conn_str)
                    cursor = conn.cursor()

                    # Create table if not exists
                    cursor.execute(f'''
                        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{table_name}' AND xtype='U')
                        CREATE TABLE {table_name} (
                            CompanyID NVARCHAR(50),
                            CompanyName NVARCHAR(50),
                            ReportDate NVARCHAR(50),
                            Value1 FLOAT,
                            Value2 FLOAT,
                            Value3 FLOAT,
                            Url VARCHAR(550),
                            PRIMARY KEY (CompanyID, ReportDate)
                        )
                    ''')
                    conn.commit()

                    company_id = generate_company_id(companyName)

                    # Extract calculated values from last_row slice (adjust indices if needed)
                    # Here assuming last_row contains these values at index 7-9 like before
                    print(last_row)
                    calculated_values = last_row[0:3] 

                    # Insert or skip if exists
                    cursor.execute(f'''
                        SELECT COUNT(*) FROM {table_name}
                        WHERE CompanyID = ? AND ReportDate = ?
                    ''', company_id, report_date)
                    exists = cursor.fetchone()[0]

                    if not exists and all(isinstance(val, (float, int)) for val in calculated_values):
                        cursor.execute(f'''
                            INSERT INTO {table_name} (CompanyID, CompanyName, ReportDate, Value1, Value2, Value3, Url)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', company_id, companyName, report_date,
                            calculated_values[0], calculated_values[1], calculated_values[2], base_url)

                    conn.commit()
                    cursor.close()
                    conn.close()

                    print(f"✅ Calculated values saved to SQL Server table '{table_name}'")
                    print(f"✅ Data extracted from: {link}")

            except Exception as e:
                print(f"❌ Error scraping {link}: {e}")
                continue

    # if all_data:
    #     df = pd.DataFrame(all_data)
    #     filename = f'codal_reports_{len(page_numbers) * rowMeta}_{companyName}.xlsx'
    #     df.to_excel(filename, index=False, header=False, engine='openpyxl')
    #     print(f"✅ All data saved to '{filename}'")

    driver.quit()


# For testing or direct script running
if __name__ == "__main__":
    # Defaults
    companyName = 'قثابت'
    rowMeta = 20
    base_url = "https://www.codal.ir/ReportList.aspx?search&Symbol=%D9%82%D8%AB%D8%A7%D8%A8%D8%AA&LetterType=6&AuditorRef=-1&Audited=false&NotAudited&IsNotAudited=false&Childs&Mains&Publisher=false&CompanyState=0&ReportingType=1000000&name=%DA%A9%D8%A7%D8%B1%D8%AE%D8%A7%D9%86%D9%87%20%D9%87%D8%A7%DB%8C%20%D8%AA%D9%88%D9%84%DB%8C%D8%AF%DB%8C%20%D9%88%20%D8%B5%D9%86%D8%B9%D8%AA%DB%8C%20%D8%AB%D8%A7%D8%A8%D8%AA%20%D8%AE%D8%B1%D8%A7%D8%B3%D8%A7%D9%86&Category=1&CompanyType=-1&Consolidatable&NotConsolidatable&Name=%DA%A9%D8%A7%D8%B1%D8%AE%D8%A7%D9%86%D9%87%20%D9%87%D8%A7%DB%8C%20%D8%AA%D9%88%D9%84%DB%8C%D8%AF%DB%8C%20%D9%88%20%D8%B5%D9%86%D8%B9%D8%AA%DB%8C%20%D8%AB%D8%A7%D8%A8%D8%AA%20%D8%AE%D8%B1%D8%A7%D8%B3%D8%A7%D9%86&IndustryGroup=38"
    page_numbers = range(1, 3)

    main_scraper(companyName, rowMeta, base_url, page_numbers)
