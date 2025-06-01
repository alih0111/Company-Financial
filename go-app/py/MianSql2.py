import re
import time
import hashlib
import jdatetime
import pyodbc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import os

load_dotenv()

server = os.getenv('DB_SERVER')
database = os.getenv('DB_NAME')
username = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')
def generate_company_id(name):

    return hashlib.md5(name.encode('utf-8')).hexdigest()

def to_number(s):
    s = s.replace(',', '').replace('٬', '')  # Remove commas (Arabic/Persian/English)
    s = re.sub(r'[^\d\.\-\(\)]', '', s)      # Remove non-numeric except (), - and .

    # Check for parentheses to indicate negative numbers
    if re.match(r'^\(\d+(\.\d+)?\)$', s):
        s = '-' + s.strip('()')

    return float(s) if s else 0

def main_scraper2(companyName, rowMeta, base_url, page_numbers, table_name):
    base_url = base_url.replace("&PageNumber=1", "")

    # options = webdriver.ChromeOptions()
    # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920x1080')

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
                        min_date = jdatetime.date(1399, 1, 30)
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
                        row2 = [td.text.strip() for td in all_rows[-1].find_all('td')]

                        last_row = []

                        cc = 0
                        for i in range(len(row2) - 1, 0, -1):
                            try:
                                num2 = to_number(row2[i])
                                if num2 > 0:
                                    cc = cc + 1
                                    last_row.append(num2)
                                    if(cc==3):
                                        break
                            except ValueError:
                                last_row.append(0)

                    else:
                        last_row = []

                    max_cols = max(len(first_row), len(last_row))
                    headers = headers[3:max_cols + 2]
                                       
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
                    # Here assuming last_row contains these values at index 0-2
                    print(last_row)
                    calculated_values = last_row[0:3] 
                    print(calculated_values)
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

    driver.quit()
