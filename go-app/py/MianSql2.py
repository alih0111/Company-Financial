# import re
# import time
# import hashlib
# import jdatetime
# import pyodbc
# import logging
# import sys
# import json
# import os
# from selenium import webdriver
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from bs4 import BeautifulSoup
# from dotenv import load_dotenv

# # --------------------- Logging Setup ---------------------
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s [%(levelname)s] %(message)s',
#     handlers=[logging.StreamHandler(sys.stdout)]
# )

# # --------------------- Load Environment ---------------------
# load_dotenv()

# server = os.getenv('DB_SERVER')
# database = os.getenv('DB_NAME')
# username = os.getenv('DB_USER')
# password = os.getenv('DB_PASSWORD')

# # --------------------- Helpers ---------------------
# def generate_company_id(name):
#     return hashlib.md5(name.encode('utf-8')).hexdigest()

# def to_number(s):
#     s = s.replace(',', '').replace('٬', '')  # Remove commas (Arabic/Persian/English)
#     s = re.sub(r'[^\d\.\-\(\)]', '', s)
#     if re.match(r'^\(\d+(\.\d+)?\)$', s):
#         s = '-' + s.strip('()')
#     return float(s) if s else 0

# def driver_path():
#     # try:
#         # driver_path = ChromeDriverManager().install()
#     # except Exception:
#     driver_path = r"D:\RFA\Company-Financial\go-app\py\chromedriver-win32\chromedriver.exe"
#     return driver_path

# def create_driver():

#     CHROMIUM_BINARY = r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe"
#     options = webdriver.ChromeOptions()
#     options.binary_location = CHROMIUM_BINARY

#     options.add_argument("--disable-gpu")
#     options.add_argument("--no-sandbox")
#     options.add_argument("--disable-dev-shm-usage")

#     return webdriver.Chrome(options=options)

# # --------------------- MAIN FUNCTION ---------------------
# def main_scraper2(companyName, rowMeta, base_url, page_numbers, table_name):
#     base_url = base_url.replace("&PageNumber=1", "")
#     inserted_any = False
#     # options = webdriver.ChromeOptions()
#     # # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
#     # service = Service(driver_path())
#     # driver = webdriver.Chrome(service=service, options=options)
    
#     driver = create_driver()


#     all_data = []
#     flag = True  # Add headers only once

#     for page in page_numbers:
#         current_url = f"{base_url}&PageNumber={page}"
#         logging.info(f"🌐 Opening page: {current_url}")

#         try:
#             driver.get(current_url)
#         except Exception as e:
#             logging.error(f"❌ Page load timeout or error: {e}")
#             continue

#         try:
#             WebDriverWait(driver, 20).until(
#                 EC.presence_of_element_located((By.CLASS_NAME, "scrollContent"))
#             )
#             time.sleep(3)
#         except Exception as e:
#             logging.warning(f"⚠️ Table not found on page {page}: {e}")
#             continue

#         # Extract report links
#         rows = driver.find_elements(By.CSS_SELECTOR, "tbody.scrollContent tr")
#         report_links = []
#         for row in rows[:rowMeta]:
#             try:
#                 link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(4) a")
#                 report_links.append(link_element.get_attribute("href"))
#             except:
#                 continue

#         logging.info(f"✅ Found {len(report_links)} report links on page {page}")

#         for link in report_links:
#             try:
#                 driver.get(link)
#                 logging.info(f"🔍 Scraping report: {link}")

#                 WebDriverWait(driver, 20).until(
#                     EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
#                 )
#                 time.sleep(2)

#                 # Parse date
#                 try:
#                     date_element = driver.find_element(By.ID, "ctl00_lblPeriodEndToDate")
#                     report_date = date_element.text.strip()
#                     report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
#                     min_date = jdatetime.date(1399, 1, 30)
#                     if report_jdate <= min_date:
#                         logging.info(f"⏩ Skipping old report {report_date}")
#                         continue
#                 except Exception as e:
#                     logging.warning(f"⚠️ Could not parse report date: {e}")
#                     continue

#                 soup = BeautifulSoup(driver.page_source, 'html.parser')
#                 table = soup.find('table', {'class': 'rayanDynamicStatement'})
#                 if not table:
#                     logging.warning(f"⚠️ No data table found for {link}")
#                     continue

#                 headers = [th.text.strip() for th in table.find_all('th')]
#                 all_rows = table.find_all('tr')[1:]
#                 first_row = [td.text.strip() for td in all_rows[0].find_all('td')] if all_rows else []

#                 # Extract numeric values from last row
#                 last_row = []
#                 if len(all_rows) >= 3:
#                     row2 = [td.text.strip() for td in all_rows[-1].find_all('td')]
#                     for i in range(len(row2) - 1, 0, -1):
#                         try:
#                             num2 = to_number(row2[i])
#                             if num2 > 0:
#                                 last_row.append(num2)
#                                 if len(last_row) == 3:
#                                     break
#                         except ValueError:
#                             last_row.append(0)

#                 max_cols = max(len(first_row), len(last_row))
#                 headers = headers[3:max_cols + 2]

#                 if flag:
#                     all_data.append(["Report Date"] + headers + ["داخلی", "صادراتی", "مجموع تعدادی"])
#                     flag = False

#                 # Find sales values
#                 dakheli_value = saderati_value = "0"
#                 for tr in all_rows:
#                     tds = tr.find_all('td')
#                     if not tds:
#                         continue
#                     title = tds[0].get_text(strip=True)
#                     if "جمع فروش داخلی" in title:
#                         if len(tds) >= 15:
#                             dakheli_value = tds[14].get_text(strip=True)
#                     if "جمع فروش صادراتی" in title:
#                         if len(tds) >= 15:
#                             saderati_value = tds[14].get_text(strip=True)

#                 dakheli_int = float(dakheli_value.replace(',', '').replace('٬', '') or "0")
#                 saderati_int = float(saderati_value.replace(',', '').replace('٬', '') or "0")
#                 total_value = dakheli_int + saderati_int

#                 all_data.append(
#                     [report_date] + last_row + [dakheli_value, saderati_value, str(total_value)]
#                 )

#                 # ---------- Save to SQL ----------
#                 conn_str = (
#                     f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};'
#                     f'UID={username};PWD={password}'
#                 )
#                 conn = pyodbc.connect(conn_str)
#                 cursor = conn.cursor()

#                 cursor.execute(f'''
#                     IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{table_name}' AND xtype='U')
#                     CREATE TABLE {table_name} (
#                         CompanyID NVARCHAR(50),
#                         CompanyName NVARCHAR(50),
#                         ReportDate NVARCHAR(50),
#                         Value1 FLOAT,
#                         Value2 FLOAT,
#                         Value3 FLOAT,
#                         Url VARCHAR(550),
#                         PRIMARY KEY (CompanyID, ReportDate)
#                     )
#                 ''')
#                 conn.commit()

#                 company_id = generate_company_id(companyName)
#                 calculated_values = last_row[0:3]

#                 cursor.execute(f'''
#                     SELECT COUNT(*) FROM {table_name}
#                     WHERE CompanyID = ? AND ReportDate = ?
#                 ''', company_id, report_date)
#                 exists = cursor.fetchone()[0]

#                 if not exists and all(isinstance(val, (float, int)) for val in calculated_values):
#                     cursor.execute(f'''
#                         INSERT INTO {table_name} (CompanyID, CompanyName, ReportDate, Value1, Value2, Value3, Url)
#                         VALUES (?, ?, ?, ?, ?, ?, ?)
#                     ''', company_id, companyName, report_date,
#                         calculated_values[0], calculated_values[1], calculated_values[2], base_url)
#                     conn.commit()

#                 cursor.close()
#                 conn.close()

#                 logging.info(f"✅ Report {report_date} saved to SQL.")

#             except Exception as e:
#                 logging.exception(f"❌ Error scraping {link}: {e}")
#                 continue

#     driver.quit()
#     logging.info("🎉 Scraping session completed.")


# # MianSql2.py  (فقط بخش‌های تغییر کرده/اضافه شده)

# # # ... import ها همون قبلی ...

# # def main_scraper2_with_driver(driver, companyName, rowMeta, base_url, page_numbers, table_name):
# #     base_url = base_url.replace("&PageNumber=1", "")
# #     inserted_any = False

# #     all_data = []
# #     flag = True

# #     for page in page_numbers:
# #         current_url = f"{base_url}&PageNumber={page}"
# #         logging.info(f"🌐 Opening page: {current_url}")

# #         try:
# #             driver.get(current_url)
# #         except Exception as e:
# #             logging.error(f"❌ Page load timeout or error: {e}")
# #             continue

# #         try:
# #             WebDriverWait(driver, 20).until(
# #                 EC.presence_of_element_located((By.CLASS_NAME, "scrollContent"))
# #             )
# #             time.sleep(3)
# #         except Exception as e:
# #             logging.warning(f"⚠️ Table not found on page {page}: {e}")
# #             continue

# #         rows = driver.find_elements(By.CSS_SELECTOR, "tbody.scrollContent tr")
# #         report_links = []
# #         for row in rows[:rowMeta]:
# #             try:
# #                 link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(4) a")
# #                 report_links.append(link_element.get_attribute("href"))
# #             except:
# #                 continue

# #         logging.info(f"✅ Found {len(report_links)} report links on page {page}")

# #         for link in report_links:
# #             try:
# #                 driver.get(link)
# #                 logging.info(f"🔍 Scraping report: {link}")

# #                 WebDriverWait(driver, 20).until(
# #                     EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
# #                 )
# #                 time.sleep(2)

# #                 try:
# #                     date_element = driver.find_element(By.ID, "ctl00_lblPeriodEndToDate")
# #                     report_date = date_element.text.strip()
# #                     report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
# #                     min_date = jdatetime.date(1399, 1, 30)
# #                     if report_jdate <= min_date:
# #                         logging.info(f"⏩ Skipping old report {report_date}")
# #                         continue
# #                 except Exception as e:
# #                     logging.warning(f"⚠️ Could not parse report date: {e}")
# #                     continue

# #                 soup = BeautifulSoup(driver.page_source, 'html.parser')
# #                 table = soup.find('table', {'class': 'rayanDynamicStatement'})
# #                 if not table:
# #                     logging.warning(f"⚠️ No data table found for {link}")
# #                     continue

# #                 headers = [th.text.strip() for th in table.find_all('th')]
# #                 all_rows = table.find_all('tr')[1:]
# #                 first_row = [td.text.strip() for td in all_rows[0].find_all('td')] if all_rows else []

# #                 last_row = []
# #                 if len(all_rows) >= 3:
# #                     row2 = [td.text.strip() for td in all_rows[-1].find_all('td')]
# #                     for i in range(len(row2) - 1, 0, -1):
# #                         try:
# #                             num2 = to_number(row2[i])
# #                             if num2 > 0:
# #                                 last_row.append(num2)
# #                                 if len(last_row) == 3:
# #                                     break
# #                         except ValueError:
# #                             last_row.append(0)

# #                 max_cols = max(len(first_row), len(last_row))
# #                 headers = headers[3:max_cols + 2]

# #                 if flag:
# #                     all_data.append(["Report Date"] + headers + ["داخلی", "صادراتی", "مجموع تعدادی"])
# #                     flag = False

# #                 dakheli_value = saderati_value = "0"
# #                 for tr in all_rows:
# #                     tds = tr.find_all('td')
# #                     if not tds:
# #                         continue
# #                     title = tds[0].get_text(strip=True)
# #                     if "جمع فروش داخلی" in title:
# #                         if len(tds) >= 15:
# #                             dakheli_value = tds[14].get_text(strip=True)
# #                     if "جمع فروش صادراتی" in title:
# #                         if len(tds) >= 15:
# #                             saderati_value = tds[14].get_text(strip=True)

# #                 dakheli_int = float(dakheli_value.replace(',', '').replace('٬', '') or "0")
# #                 saderati_int = float(saderati_value.replace(',', '').replace('٬', '') or "0")
# #                 total_value = dakheli_int + saderati_int

# #                 all_data.append(
# #                     [report_date] + last_row + [dakheli_value, saderati_value, str(total_value)]
# #                 )

# #                 conn_str = (
# #                     f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};'
# #                     f'UID={username};PWD={password}'
# #                 )
# #                 conn = pyodbc.connect(conn_str)
# #                 cursor = conn.cursor()

# #                 cursor.execute(f'''
# #                     IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{table_name}' AND xtype='U')
# #                     CREATE TABLE {table_name} (
# #                         CompanyID NVARCHAR(50),
# #                         CompanyName NVARCHAR(50),
# #                         ReportDate NVARCHAR(50),
# #                         Value1 FLOAT,
# #                         Value2 FLOAT,
# #                         Value3 FLOAT,
# #                         Url VARCHAR(550),
# #                         PRIMARY KEY (CompanyID, ReportDate)
# #                     )
# #                 ''')
# #                 conn.commit()

# #                 company_id = generate_company_id(companyName)
# #                 calculated_values = last_row[0:3]

# #                 cursor.execute(f'''
# #                     SELECT COUNT(*) FROM {table_name}
# #                     WHERE CompanyID = ? AND ReportDate = ?
# #                 ''', company_id, report_date)
# #                 exists = cursor.fetchone()[0]

# #                 if not exists and all(isinstance(val, (float, int)) for val in calculated_values):
# #                     cursor.execute(f'''
# #                         INSERT INTO {table_name} (CompanyID, CompanyName, ReportDate, Value1, Value2, Value3, Url)
# #                         VALUES (?, ?, ?, ?, ?, ?, ?)
# #                     ''', company_id, companyName, report_date,
# #                         calculated_values[0], calculated_values[1], calculated_values[2], base_url)
# #                     conn.commit()
# #                     inserted_any = True

# #                 cursor.close()
# #                 conn.close()

# #                 logging.info(f"✅ Report {report_date} saved to SQL.")

# #             except Exception as e:
# #                 logging.exception(f"❌ Error scraping {link}: {e}")
# #                 continue

# #     return inserted_any


# # # اگر میخوای سازگاری قبلی هم حفظ بشه:
# # def main_scraper2(companyName, rowMeta, base_url, page_numbers, table_name):
# #     options = webdriver.ChromeOptions()
# #     driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
# #     try:
# #         return main_scraper2_with_driver(driver, companyName, rowMeta, base_url, page_numbers, table_name)
# #     finally:
# #         driver.quit()
# #         logging.info("🎉 Scraping session completed.")

import os
import re
import sys
import hashlib
import logging
from pathlib import Path
from urllib.parse import urljoin

import pyodbc
import jdatetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# --------------------- Logging Setup ---------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


# --------------------- Load Environment ---------------------
load_dotenv()

server = os.getenv("DB_SERVER")
database = os.getenv("DB_NAME")
username = os.getenv("DB_USER")
password = os.getenv("DB_PASSWORD")


# مسیر Chromium خودت
CHROMIUM_BINARY = r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe"

# پروفایل جدا برای Chromium
CHROMIUM_PROFILE_DIR = r"D:\rfa\Company-Financial\go-app\py\chromium-profile"


# --------------------- Helpers ---------------------
def generate_company_id(name):
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def normalize_text(text):
    if text is None:
        return ""

    return (
        str(text)
        .strip()
        .replace("\u200c", "")
        .replace("\xa0", "")
        .replace("ي", "ی")
        .replace("ك", "ک")
    )


def to_number(s):
    if s is None:
        return 0

    s = str(s)
    s = s.replace(",", "").replace("٬", "")
    s = re.sub(r"[^\d\.\-\(\)]", "", s)

    if re.match(r"^\(\d+(\.\d+)?\)$", s):
        s = "-" + s.strip("()")

    return float(s) if s else 0


def safe_sql_identifier(name):
    """
    چون اسم جدول را نمی‌شود با ? پارامتری کرد،
    فقط حروف، عدد و underscore مجاز است.
    """
    table_name = str(name)

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
        raise ValueError(f"Invalid SQL table name: {name}")

    return table_name


def validate_config():
    missing = []

    if not server:
        missing.append("DB_SERVER")
    if not database:
        missing.append("DB_NAME")
    if not username:
        missing.append("DB_USER")
    if not password:
        missing.append("DB_PASSWORD")

    if missing:
        raise RuntimeError(f"Missing .env values: {', '.join(missing)}")

    chromium_path = Path(CHROMIUM_BINARY)
    if not chromium_path.exists():
        raise FileNotFoundError(f"Chromium not found: {CHROMIUM_BINARY}")


def get_db_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password}"
    )

    return pyodbc.connect(conn_str)


def ensure_table(cursor, table_name):
    table_name = safe_sql_identifier(table_name)

    cursor.execute(f"""
        IF OBJECT_ID(N'dbo.{table_name}', N'U') IS NULL
        CREATE TABLE dbo.[{table_name}] (
            CompanyID NVARCHAR(50) NOT NULL,
            CompanyName NVARCHAR(50),
            ReportDate NVARCHAR(50) NOT NULL,
            Value1 FLOAT,
            Value2 FLOAT,
            Value3 FLOAT,
            Url VARCHAR(550),
            CONSTRAINT PK_{table_name}_Company_ReportDate PRIMARY KEY (CompanyID, ReportDate)
        )
    """)


def wait_for_angular_stable(page, timeout=15000):
    try:
        page.wait_for_function(
            """
            () => {
                if (!window.getAllAngularTestabilities) return true;
                return window.getAllAngularTestabilities().every(t => t.isStable());
            }
            """,
            timeout=timeout
        )
    except PlaywrightTimeoutError:
        logging.warning("⚠️ Angular stability wait timed out; continuing anyway.")


def create_context(playwright):
    validate_config()

    Path(CHROMIUM_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=CHROMIUM_PROFILE_DIR,
        executable_path=CHROMIUM_BINARY,
        headless=False,
        viewport={"width": 1366, "height": 768},
        args=[
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    return context


def get_report_links(page, row_meta):
    report_links = []

    page.wait_for_selector("tbody.scrollContent tr", timeout=20000)

    rows = page.locator("tbody.scrollContent tr")
    row_count = rows.count()

    for i in range(min(row_count, row_meta)):
        row = rows.nth(i)
        link_locator = row.locator("td:nth-child(4) a")

        try:
            if link_locator.count() > 0:
                href = link_locator.first.get_attribute("href")

                if href:
                    full_url = urljoin("https://www.codal.ir", href)
                    report_links.append(full_url)

        except Exception:
            continue

    return report_links


def parse_report_table(page, link):
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    logging.info(f"🔍 Scraping report: {link}")

    wait_for_angular_stable(page)

    try:
        page.wait_for_selector("table.rayanDynamicStatement", timeout=20000)
    except PlaywrightTimeoutError:
        logging.warning(f"⚠️ Data table not found for report: {link}")
        return None

    page.wait_for_timeout(2000)

    # --------------------- Parse Date ---------------------
    try:
        report_date = page.locator("#ctl00_lblPeriodEndToDate").inner_text(timeout=10000).strip()

        report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
        min_date = jdatetime.date(1399, 1, 30)

        if report_jdate <= min_date:
            logging.info(f"⏩ Skipping old report {report_date}")
            return None

    except Exception as e:
        logging.warning(f"⚠️ Could not parse report date: {e}")
        return None

    # --------------------- Parse HTML Table ---------------------
    soup = BeautifulSoup(page.content(), "html.parser")
    table = soup.find("table", {"class": "rayanDynamicStatement"})

    if not table:
        logging.warning(f"⚠️ No data table found for {link}")
        return None

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    all_rows = table.find_all("tr")[1:]

    first_row = []
    if all_rows:
        first_row = [td.get_text(strip=True) for td in all_rows[0].find_all("td")]

    # Extract numeric values from last row
    last_row = []

    if len(all_rows) >= 3:
        row2 = [td.get_text(strip=True) for td in all_rows[-1].find_all("td")]

        for i in range(len(row2) - 1, 0, -1):
            try:
                num2 = to_number(row2[i])

                if num2 > 0:
                    last_row.append(num2)

                    if len(last_row) == 3:
                        break

            except ValueError:
                last_row.append(0)

    max_cols = max(len(first_row), len(last_row))
    headers = headers[3:max_cols + 2]

    # --------------------- Find Sales Values ---------------------
    dakheli_value = "0"
    saderati_value = "0"

    for tr in all_rows:
        tds = tr.find_all("td")

        if not tds:
            continue

        title = tds[0].get_text(strip=True)

        if "جمع فروش داخلی" in title:
            if len(tds) >= 15:
                dakheli_value = tds[14].get_text(strip=True)

        if "جمع فروش صادراتی" in title:
            if len(tds) >= 15:
                saderati_value = tds[14].get_text(strip=True)

    try:
        dakheli_int = float(dakheli_value.replace(",", "").replace("٬", "") or "0")
    except Exception:
        dakheli_int = 0

    try:
        saderati_int = float(saderati_value.replace(",", "").replace("٬", "") or "0")
    except Exception:
        saderati_int = 0

    total_value = dakheli_int + saderati_int

    return {
        "report_date": report_date,
        "headers": headers,
        "last_row": last_row,
        "dakheli_value": dakheli_value,
        "saderati_value": saderati_value,
        "total_value": total_value,
    }


def save_report_to_sql(company_name, report_date, last_row, base_url, table_name):
    table_name = safe_sql_identifier(table_name)

    calculated_values = last_row[0:3]

    if len(calculated_values) < 3:
        logging.warning(f"⚠️ Not enough calculated values for {company_name} - {report_date}")
        return False

    if not all(isinstance(val, (float, int)) for val in calculated_values):
        logging.warning(f"⚠️ Invalid calculated values for {company_name} - {report_date}")
        return False

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        ensure_table(cursor, table_name)
        conn.commit()

        company_id = generate_company_id(company_name)

        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM dbo.[{table_name}]
            WHERE CompanyID = ? AND ReportDate = ?
            """,
            company_id,
            report_date
        )

        exists = cursor.fetchone()[0]

        if exists:
            logging.info(f"⏩ Already exists: {company_name} - {report_date}")
            return False

        cursor.execute(
            f"""
            INSERT INTO dbo.[{table_name}] (
                CompanyID,
                CompanyName,
                ReportDate,
                Value1,
                Value2,
                Value3,
                Url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            company_id,
            company_name,
            report_date,
            calculated_values[0],
            calculated_values[1],
            calculated_values[2],
            base_url
        )

        conn.commit()

        logging.info(f"✅ Report {report_date} saved to SQL.")
        return True

    except Exception as e:
        logging.exception(f"❌ SQL error for {company_name} - {report_date}: {e}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# --------------------- MAIN FUNCTION ---------------------
def main_scraper2(companyName, rowMeta, base_url, page_numbers, table_name):
    base_url = base_url.replace("&PageNumber=1", "")
    inserted_any = False

    all_data = []
    flag = True

    with sync_playwright() as playwright:
        context = create_context(playwright)
        page = context.new_page()

        try:
            for page_number in page_numbers:
                current_url = f"{base_url}&PageNumber={page_number}"
                logging.info(f"🌐 Opening page: {current_url}")

                try:
                    page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_selector("tbody.scrollContent tr", timeout=20000)

                    # جایگزین time.sleep(3)
                    page.wait_for_timeout(3000)

                except PlaywrightTimeoutError as e:
                    logging.warning(f"⚠️ Table not found on page {page_number}: {e}")
                    continue

                except Exception as e:
                    logging.error(f"❌ Page load timeout or error: {e}")
                    continue

                # --------------------- Extract Report Links ---------------------
                try:
                    report_links = get_report_links(page, rowMeta)
                    logging.info(f"✅ Found {len(report_links)} report links on page {page_number}")

                except Exception as e:
                    logging.warning(f"⚠️ Could not extract report links on page {page_number}: {e}")
                    continue

                # --------------------- Scrape Reports ---------------------
                for link in report_links:
                    try:
                        result = parse_report_table(page, link)

                        if not result:
                            continue

                        report_date = result["report_date"]
                        headers = result["headers"]
                        last_row = result["last_row"]
                        dakheli_value = result["dakheli_value"]
                        saderati_value = result["saderati_value"]
                        total_value = result["total_value"]

                        if flag:
                            all_data.append(
                                ["Report Date"] + headers + ["داخلی", "صادراتی", "مجموع تعدادی"]
                            )
                            flag = False

                        all_data.append(
                            [report_date] + last_row + [dakheli_value, saderati_value, str(total_value)]
                        )

                        saved = save_report_to_sql(
                            company_name=companyName,
                            report_date=report_date,
                            last_row=last_row,
                            base_url=base_url,
                            table_name=table_name,
                        )

                        if saved:
                            inserted_any = True

                    except Exception as e:
                        logging.exception(f"❌ Error scraping {link}: {e}")
                        continue

        finally:
            context.close()

    logging.info("🎉 Scraping session completed.")

    if inserted_any:
        print(f"{companyName} scraping and saving successful")
    else:
        print(f"{companyName} finished but no new data saved")

    return inserted_any