# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from bs4 import BeautifulSoup
# from webdriver_manager.chrome import ChromeDriverManager
# import time
# import re
# import pyodbc
# import hashlib
# import json
# import jdatetime
# from dotenv import load_dotenv
# import os
# from selenium.webdriver.support.ui import Select
# import logging
# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
# from pathlib import Path

# load_dotenv()

# server = os.getenv('DB_SERVER')
# database = os.getenv('DB_NAME')
# username = os.getenv('DB_USER')
# password = os.getenv('DB_PASSWORD')

# def generate_company_id(name):
#     return hashlib.md5(name.encode('utf-8')).hexdigest()

# def to_number(s):
#     s = s.replace(',', '').replace('٬', '')
#     s = re.sub(r'[^\d\.\-\(\)]', '', s)
#     if re.match(r'^\(\d+(\.\d+)?\)$', s):
#         s = '-' + s.strip('()')
#     return float(s) if s else 0

# def is_hidden_row(tr):
#     tds = tr.find_all('td')
#     return all(td.has_attr('hidden') for td in tds)

# def driver_path():
#     # try:
#         # driver_path = ChromeDriverManager().install()
#     # except Exception:
#     driver_path = r"D:\RFA\Company-Financial\go-app\py\chromedriver-win32\chromedriver.exe"
#     return driver_path
    
# CHROMIUM_BINARY = r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe"

# CHROMEDRIVER_PATH = r"D:\rfa\Company-Financial\go-app\py\chromedriver-win32\chromedriver.exe"

# def create_driver():
#     chromium_path = Path(CHROMIUM_BINARY)
#     driver_path = Path(CHROMEDRIVER_PATH)

#     if not chromium_path.exists():
#         raise FileNotFoundError(f"Chromium not found: {CHROMIUM_BINARY}")

#     if not driver_path.exists():
#         raise FileNotFoundError(f"ChromeDriver not found: {CHROMEDRIVER_PATH}")

#     options = webdriver.ChromeOptions()
#     options.binary_location = CHROMIUM_BINARY

#     # برای اینکه از پروفایل Chrome اصلی استفاده نکند
#     options.add_argument(r"--user-data-dir=D:\rfa\Company-Financial\go-app\py\chromium-profile")

#     # اختیاری، برای پایداری بیشتر
#     options.add_argument("--disable-gpu")
#     options.add_argument("--disable-dev-shm-usage")
#     options.add_argument("--no-first-run")
#     options.add_argument("--no-default-browser-check")

#     service = Service(CHROMEDRIVER_PATH)

#     return webdriver.Chrome(service=service, options=options)
    
# def main_scraper(companyName, rowMeta, base_url, page_numbers, table_name):
#     base_url = base_url.replace("&PageNumber=1", "")
#     inserted_any = False
#     # options = webdriver.ChromeOptions()
#     # # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
#     # service = Service(driver_path())
#     # driver = webdriver.Chrome(service=service, options=options)

#     driver = create_driver()

#     for page in page_numbers:
#         current_url = f"{base_url}&PageNumber={page}"
#         driver.get(current_url)
#         print(f"Fetching data from page {page}...")

#         try:
#             WebDriverWait(driver, 20).until(
#                 EC.presence_of_element_located((By.CLASS_NAME, "scrollContent"))
#             )
#             time.sleep(5)
#         except:
#             print(f"Table did not load on page {page}. Skipping...")
#             continue

#         rows = driver.find_elements(By.CSS_SELECTOR, "tbody.scrollContent tr")
#         report_links = []
#         for row in rows[:rowMeta]:
#             try:
#                 link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(4) a")
#                 report_links.append(link_element.get_attribute("href"))
#             except:
#                 continue

#         for link in report_links:
#             try:
#                 driver.get(link)
#                 # logging.info(f"🔍 Scraping report: {link}")

#                 # ✅ Ensure selectbox is set to "صورت سود و زیان"
#                 # try:
#                 #     select_element = WebDriverWait(driver, 10).until(
#                 #         EC.presence_of_element_located((By.ID, "ctl00_ddlTable"))
#                 #     )
#                 #     select = Select(select_element)
#                 #     selected_text = select.first_selected_option.text.strip()

#                 #     if selected_text != "صورت سود و زیان":
#                 #         select.select_by_visible_text("صورت سود و زیان")
#                 #         # logging.info("🔁 Changed selectbox to 'صورت سود و زیان'")
#                 #         WebDriverWait(driver, 10).until(
#                 #             EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
#                 #         )
#                 #         time.sleep(2)
#                 #     else:
#                 #         c=1
#                 #         # logging.info("✅ Selectbox already on 'صورت سود و زیان'")
#                 # except Exception as e:
#                 #     # logging.warning(f"⚠️ Could not change selectbox: {e}")
#                 #     continue
#                 # from selenium.webdriver.support.ui import Select

#                 driver.get(link)
#                 logging.info(f"🔍 Scraping report: {link}")

#                 # ✅ Ensure selectbox is set to "صورت سود و زیان"
#                 try:
#                     # Try both possible IDs
#                     possible_ids = ["ctl00_ddlTable", "ddlTable"]
#                     select_element = None

#                     for sel_id in possible_ids:
#                         try:
#                             select_element = WebDriverWait(driver, 5).until(
#                                 EC.presence_of_element_located((By.ID, sel_id))
#                             )
#                             logging.info(f"✅ Found selectbox with ID: {sel_id}")
#                             break
#                         except Exception:
#                             continue

#                     if not select_element:
#                         raise Exception("No selectbox found with IDs ctl00_ddlTable or ddlTable")

#                     # Wrap in Selenium Select object
#                     select = Select(select_element)

#                     # Clean and normalize text (trim spaces, invisible chars)
#                     selected_text = select.first_selected_option.text.strip().replace("\u200c", "").replace("\xa0", "")
#                     target_text = "صورت سود و زیان"
#                     # Compare normalized texts
#                     if selected_text != target_text and selected_text != 'صورت سود و زیان تلفیقی':
#                         # Find and select the correct option — ignoring any invisible chars/spaces
#                         matched = False
#                         for option in select.options:
#                             opt_text = option.text.strip().replace("\u200c", "").replace("\xa0", "")
#                             if opt_text == target_text:
#                                 option.click()  # safer than select_by_visible_text for mixed whitespace
#                                 matched = True
#                                 logging.info("🔁 Changed selectbox to 'صورت سود و زیان'")
#                                 break

#                         if not matched:
#                             raise Exception("Option 'صورت سود و زیان' not found in dropdown")

#                         # Wait for postback / reload after changing select
#                         WebDriverWait(driver, 15).until(
#                             EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
#                         )
#                         time.sleep(2)
#                     else:
#                         logging.info("✅ Selectbox already on 'صورت سود و زیان'")

#                 except Exception as e:
#                     logging.warning(f"⚠️ Could not change selectbox: {e}")
#                     continue


#                 WebDriverWait(driver, 15).until(
#                     lambda d: d.execute_script(
#                         "return window.getAllAngularTestabilities && window.getAllAngularTestabilities().every(t => t.isStable())"
#                     )
#                 )
#                 WebDriverWait(driver, 10).until(
#                     EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
#                 )

#                 date_element = driver.find_element(By.ID, "ctl00_lblPeriodEndToDate")
#                 report_date = date_element.text.strip()
#                 try:
#                     report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
#                     min_date = jdatetime.date(1397, 12, 29)
#                     if report_jdate <= min_date:
#                         continue
#                 except:
#                     continue

#                 soup = BeautifulSoup(driver.page_source, 'html.parser')
#                 table = soup.find('table', {'class': 'rayanDynamicStatement'})
#                 if not table:
#                     continue

#                 all_rows = table.find_all('tr')[1:]
#                 # if len(all_rows) < 3:
#                 #     continue

#                 # row1 = [td.text.strip() for td in all_rows[-2].find_all('td')]
#                 # row2 = [td.text.strip() for td in all_rows[-1].find_all('td')]
                

#                 valid_rows = [tr for tr in all_rows if not is_hidden_row(tr)]

#                 if len(valid_rows) < 2:
#                     continue

#                 row1 = [td.text.strip() for td in valid_rows[-2].find_all('td')]
#                 row2 = [td.text.strip() for td in valid_rows[-1].find_all('td')]
#                 row3 = [td.text.strip() for td in valid_rows[3].find_all('td')]     
#                 row4 = [td.text.strip() for td in valid_rows[-7].find_all('td')]  

#                 sayer = [td.text.strip() for td in valid_rows[6].find_all('td')]
#                 sayerGheir = [td.text.strip() for td in valid_rows[10].find_all('td')]  
#                 print("sayerGheir[0]: ",sayer[0])        
#                 Amaliati = 1
#                 if(sayer[0] != "ساير درآمدها" ):
#                     Amaliati= 0
#                 print("Amaliati: ",Amaliati)        

#                 OperatingProfitNew= to_number(sayer[1])+to_number(sayerGheir[1])

#                 min_len = min(len(row4), len(row2))

#                 last_row_num1 = []
#                 last_row_num2 = []
#                 last_row_num4 = []
#                 last_row_product = []                

#                 for i in range(1, min_len):
#                     try:
#                         num1 = to_number(row1[i])
#                         num2 = to_number(row2[i])
#                         num4 = to_number(row4[i])
#                         # num1 = num4 if (num1 is None or num1 == 0) else num1
#                         # OperatingProfitNew = to_number(row3[1])
#                         last_row_num1.append(num1)
#                         last_row_num2.append(num2)
#                         last_row_num4.append(num4)
#                         last_row_product.append(num1 * num2)
#                         OperatingProfitNew = to_number(OperatingProfitNew)/last_row_product[1]
#                     except:
#                         last_row_num1.append(0)
#                         last_row_num2.append(0)
#                         last_row_num4.append(0)
#                         last_row_product.append(0)

#                 if(last_row_num1[0]==0):
#                     values_to_insert = (
#                         last_row_num1[1], last_row_num2[1], last_row_num4[1], last_row_product[1],
#                         last_row_num1[2], last_row_num2[2], last_row_num4[2], last_row_product[2],
#                         last_row_num1[3], last_row_num2[3], last_row_num4[3], last_row_product[3]
#                     )
#                     OperatingProfitNew = OperatingProfitNew/last_row_product[1]*100000
#                 else:
#                     values_to_insert = (
#                         last_row_num1[0], last_row_num2[0], last_row_num4[0], last_row_product[0],
#                         last_row_num1[1], last_row_num2[1], last_row_num4[1], last_row_product[1],
#                         last_row_num1[2], last_row_num2[2], last_row_num4[2], last_row_product[2]
#                     )
                    
#                     OperatingProfitNew = OperatingProfitNew/last_row_product[0]*100000

#                 if(Amaliati==0):
#                     OperatingProfitNew=-1

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
#                         Num1_Value1 FLOAT,
#                         Num2_Value1 FLOAT,
#                         Num4_Value1 FLOAT,
#                         Product1 FLOAT,
#                         Num1_Value2 FLOAT,
#                         Num4_Value2 FLOAT,
#                         Num2_Value2 FLOAT,
#                         Product2 FLOAT,
#                         Num1_Value3 FLOAT,
#                         Num2_Value3 FLOAT,
#                         Num4_Value3 FLOAT,
#                         Product3 FLOAT,
#                         Url VARCHAR(550),
#                         PRIMARY KEY (CompanyID, ReportDate)
#                     )
#                 ''')
#                 conn.commit()

#                 company_id = generate_company_id(companyName)
#                 cursor.execute(f'SELECT COUNT(*) FROM {table_name} WHERE CompanyID = ? AND ReportDate = ?', company_id, report_date)
#                 exists = cursor.fetchone()[0]

#                 if not exists:
#                     cursor.execute(f'''
#                         INSERT INTO {table_name} (
#                             CompanyID, CompanyName, ReportDate,
#                             Num1_Value1, Num2_Value1, Num4_Value1, Product1,
#                             Num1_Value2, Num2_Value2, Num4_Value2, Product2,
#                             Num1_Value3, Num2_Value3, Num4_Value3, Product3,
#                             OperatingProfitNew, OperatingProfitLastYear,
#                             Url
#                         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
#                     ''', company_id, companyName, report_date, *values_to_insert, OperatingProfitNew, 100, base_url)
#                     conn.commit()
#                     inserted_any = True 

#                 cursor.close()
#                 conn.close()

#             except Exception as e:
#                 print(f"Error: {e}")
#                 continue

#     driver.quit()

#     if inserted_any:
#         print(f"{companyName} scraping and saving successful")  # ✅ used by Go to detect success
#     else:
#         print(f"{companyName} finished but no new data saved")  # optional



import os
import re
import hashlib
import logging
import sys
from pathlib import Path

import pyodbc
import jdatetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urljoin


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

# پروفایل جدا برای Chromium، نه Chrome اصلی سیستم
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


def is_hidden_row(tr):
    tds = tr.find_all("td")
    if not tds:
        return False
    return all(td.has_attr("hidden") for td in tds)


def get_row_cells(row):
    if not row:
        return []
    return [td.get_text(strip=True) for td in row.find_all("td")]


def cell(row, index, default="0"):
    try:
        return row[index]
    except Exception:
        return default


def safe_sql_identifier(name):
    """
    چون اسم جدول را نمی‌شود با ? پارامتری کرد،
    فقط حروف، عدد و underscore مجاز است.
    """
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name := str(name)):
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

            Num1_Value1 FLOAT,
            Num2_Value1 FLOAT,
            Num4_Value1 FLOAT,
            Product1 FLOAT,

            Num1_Value2 FLOAT,
            Num2_Value2 FLOAT,
            Num4_Value2 FLOAT,
            Product2 FLOAT,

            Num1_Value3 FLOAT,
            Num2_Value3 FLOAT,
            Num4_Value3 FLOAT,
            Product3 FLOAT,

            OperatingProfitNew FLOAT,
            OperatingProfitLastYear FLOAT,

            Url VARCHAR(550),

            CONSTRAINT PK_{table_name}_Company_ReportDate PRIMARY KEY (CompanyID, ReportDate)
        )
    """)

    # اگر جدول قبلاً با نسخه قدیمی ساخته شده و این ستون‌ها را ندارد، اضافه شوند
    cursor.execute(f"""
        IF COL_LENGTH('dbo.{table_name}', 'OperatingProfitNew') IS NULL
        ALTER TABLE dbo.[{table_name}] ADD OperatingProfitNew FLOAT NULL
    """)

    cursor.execute(f"""
        IF COL_LENGTH('dbo.{table_name}', 'OperatingProfitLastYear') IS NULL
        ALTER TABLE dbo.[{table_name}] ADD OperatingProfitLastYear FLOAT NULL
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
        link = row.locator("td:nth-child(4) a")

        try:
            if link.count() > 0:
                href = link.first.get_attribute("href")
                if href:
                    full_url = urljoin("https://www.codal.ir", href)
                    report_links.append(full_url)
        except Exception:
            continue

    return report_links


def ensure_profit_loss_selected(page):
    """
    تلاش می‌کند selectbox گزارش را روی «صورت سود و زیان» بگذارد.
    اگر از قبل روی صورت سود و زیان یا صورت سود و زیان تلفیقی باشد، ادامه می‌دهد.
    """

    possible_selectors = [
        "select#ctl00_ddlTable",
        "select#ddlTable",
        "#ctl00_ddlTable",
        "#ddlTable",
    ]

    select_locator = None

    for selector in possible_selectors:
        locator = page.locator(selector)
        try:
            locator.first.wait_for(state="attached", timeout=5000)
            select_locator = locator.first
            logging.info(f"✅ Found selectbox: {selector}")
            break
        except PlaywrightTimeoutError:
            continue

    if select_locator is None:
        raise RuntimeError("No selectbox found with IDs ctl00_ddlTable or ddlTable")

    selected_text = ""
    try:
        selected_text = normalize_text(
            select_locator.locator("option:checked").inner_text(timeout=3000)
        )
    except Exception:
        pass

    target_text = normalize_text("صورت سود و زیان")
    consolidated_text = normalize_text("صورت سود و زیان تلفیقی")

    if selected_text in [target_text, consolidated_text]:
        logging.info("✅ Selectbox already on profit/loss table.")
        return True

    options = select_locator.locator("option")
    option_count = options.count()

    target_value = None

    for i in range(option_count):
        option = options.nth(i)
        option_text = normalize_text(option.inner_text())

        if option_text == target_text:
            target_value = option.get_attribute("value")
            break

    if target_value is None:
        raise RuntimeError("Option 'صورت سود و زیان' not found in dropdown")

    select_locator.select_option(value=target_value, timeout=10000)

    # برای postback / ajax / angular
    page.wait_for_timeout(2500)
    wait_for_angular_stable(page)
    page.wait_for_selector("table.rayanDynamicStatement", timeout=15000)

    logging.info("🔁 Changed selectbox to 'صورت سود و زیان'")
    return True


def scrape_report(page, link, company_name, base_url, table_name):
    table_name = safe_sql_identifier(table_name)

    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    logging.info(f"🔍 Scraping report: {link}")

    try:
        ensure_profit_loss_selected(page)
    except Exception as e:
        logging.warning(f"⚠️ Could not change/select profit-loss table: {e}")
        return False

    wait_for_angular_stable(page)

    try:
        page.wait_for_selector("table.rayanDynamicStatement", timeout=15000)
    except PlaywrightTimeoutError:
        logging.warning("⚠️ rayanDynamicStatement table not found.")
        return False

    # تاریخ گزارش
    try:
        report_date = page.locator("#ctl00_lblPeriodEndToDate").inner_text(timeout=10000).strip()
    except Exception as e:
        logging.warning(f"⚠️ Could not read report date: {e}")
        return False

    try:
        report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
        min_date = jdatetime.date(1397, 12, 29)

        if report_jdate <= min_date:
            logging.info(f"⏩ Skipping old report: {report_date}")
            return False
    except Exception as e:
        logging.warning(f"⚠️ Could not parse report date '{report_date}': {e}")
        return False

    soup = BeautifulSoup(page.content(), "html.parser")
    table = soup.find("table", {"class": "rayanDynamicStatement"})

    if not table:
        logging.warning("⚠️ No data table found in page content.")
        return False

    all_rows = table.find_all("tr")[1:]
    valid_rows = [tr for tr in all_rows if not is_hidden_row(tr)]

    # این کد به ردیف‌های 6 و 10 و -7 نیاز دارد
    if len(valid_rows) < 11:
        logging.warning(f"⚠️ Not enough valid rows. Found: {len(valid_rows)}")
        return False

    row1 = get_row_cells(valid_rows[-2])
    row2 = get_row_cells(valid_rows[-1])
    row4 = get_row_cells(valid_rows[-7])

    sayer = get_row_cells(valid_rows[6])
    sayer_gheir = get_row_cells(valid_rows[10])

    logging.info(f"sayer[0]: {cell(sayer, 0, '')}")

    amaliati = 1 if normalize_text(cell(sayer, 0, "")) == normalize_text("سایر درآمدها") else 0
    logging.info(f"Amaliati: {amaliati}")

    operating_profit_total = to_number(cell(sayer, 1)) + to_number(cell(sayer_gheir, 1))

    min_len = min(len(row1), len(row2), len(row4))

    last_row_num1 = []
    last_row_num2 = []
    last_row_num4 = []
    last_row_product = []

    for i in range(1, min_len):
        try:
            num1 = to_number(row1[i])
            num2 = to_number(row2[i])
            num4 = to_number(row4[i])
            product = num1 * num2

            last_row_num1.append(num1)
            last_row_num2.append(num2)
            last_row_num4.append(num4)
            last_row_product.append(product)

        except Exception:
            last_row_num1.append(0)
            last_row_num2.append(0)
            last_row_num4.append(0)
            last_row_product.append(0)

    if len(last_row_num1) < 4:
        logging.warning("⚠️ Not enough numeric columns extracted.")
        return False

    def pick(index):
        return (
            last_row_num1[index],
            last_row_num2[index],
            last_row_num4[index],
            last_row_product[index],
        )

    if last_row_num1[0] == 0:
        picked1 = pick(1)
        picked2 = pick(2)
        picked3 = pick(3)
        denominator = last_row_product[1]
    else:
        picked1 = pick(0)
        picked2 = pick(1)
        picked3 = pick(2)
        denominator = last_row_product[0]

    values_to_insert = (
        *picked1,
        *picked2,
        *picked3,
    )

    if amaliati == 0:
        operating_profit_new = -1
    else:
        operating_profit_new = (operating_profit_total / denominator * 100000) if denominator else 0

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

                Num1_Value1,
                Num2_Value1,
                Num4_Value1,
                Product1,

                Num1_Value2,
                Num2_Value2,
                Num4_Value2,
                Product2,

                Num1_Value3,
                Num2_Value3,
                Num4_Value3,
                Product3,

                OperatingProfitNew,
                OperatingProfitLastYear,

                Url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            company_id,
            company_name,
            report_date,
            *values_to_insert,
            operating_profit_new,
            100,
            base_url
        )

        conn.commit()

        logging.info(f"✅ Saved: {company_name} - {report_date}")
        return True

    except Exception as e:
        logging.exception(f"❌ SQL error for {company_name} - {report_date}: {e}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def main_scraper(companyName, rowMeta, base_url, page_numbers, table_name):
    base_url = base_url.replace("&PageNumber=1", "")
    inserted_any = False

    with sync_playwright() as playwright:
        context = create_context(playwright)
        page = context.new_page()

        try:
            for page_number in page_numbers:
                current_url = f"{base_url}&PageNumber={page_number}"

                logging.info(f"🌐 Fetching data from page {page_number}: {current_url}")

                try:
                    page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_selector("tbody.scrollContent tr", timeout=20000)

                    # جایگزین time.sleep(5)
                    page.wait_for_timeout(5000)

                except PlaywrightTimeoutError:
                    logging.warning(f"⚠️ Table did not load on page {page_number}. Skipping...")
                    continue

                except Exception as e:
                    logging.warning(f"⚠️ Could not open page {page_number}: {e}")
                    continue

                try:
                    report_links = get_report_links(page, rowMeta)
                    logging.info(f"✅ Found {len(report_links)} report links on page {page_number}")
                except Exception as e:
                    logging.warning(f"⚠️ Could not extract report links from page {page_number}: {e}")
                    continue

                for link in report_links:
                    try:
                        saved = scrape_report(
                            page=page,
                            link=link,
                            company_name=companyName,
                            base_url=base_url,
                            table_name=table_name
                        )

                        if saved:
                            inserted_any = True

                    except Exception as e:
                        logging.exception(f"❌ Error scraping report {link}: {e}")
                        continue

        finally:
            context.close()

    if inserted_any:
        print(f"{companyName} scraping and saving successful")
    else:
        print(f"{companyName} finished but no new data saved")