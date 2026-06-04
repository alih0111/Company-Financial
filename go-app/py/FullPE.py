# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
# from selenium.webdriver.common.by import By
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.webdriver.support import expected_conditions as EC
# from bs4 import BeautifulSoup
# import pyodbc
# import hashlib
# import os
# import re
# from dotenv import load_dotenv
# from datetime import datetime
# from webdriver_manager.chrome import ChromeDriverManager
# import time
# import math

# load_dotenv()

# server = os.getenv('DB_SERVER')
# database = os.getenv('DB_NAME')
# username = os.getenv('DB_USER')
# password = os.getenv('DB_PASSWORD')

# def generate_company_id(name):
#     return hashlib.md5(name.encode('utf-8')).hexdigest()

# def normalize_persian(text):
#     return text.replace('ك', 'ک').replace('ي', 'ی').strip()

# def driver_path():
#     # try:
#         # driver_path = ChromeDriverManager().install()
#     # except Exception:
#     driver_path = r"D:\RFA\Company-Financial\go-app\py\chromedriver-win32\chromedriver.exe"
#     return driver_path

# def scrape_pe_values(url, normalized_company_names):
#     options = webdriver.ChromeOptions()
#     # options.add_argument('--headless')
    
#     # options.add_argument('--headless')
#     # options.add_argument('--disable-gpu')
#     # options.add_argument('--window-size=1920x1080')
#     # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
#     # chrome_driver_path = r"D:\RFA\Company-Financial\go-app\py\chromedriver-win32\chromedriver.exe"
#     # driver = webdriver.Chrome(service=Service(chrome_driver_path), options=options)
#     # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
#     service = Service(driver_path())
#     driver = webdriver.Chrome(service=service, options=options)

#     driver.get(url)
#     WebDriverWait(driver, 20).until(
#         EC.presence_of_element_located((By.CSS_SELECTOR, "div[class^='t0c']"))
#     )
#     time.sleep(3)
#     soup = BeautifulSoup(driver.page_source, 'html.parser')

#     all_divs = soup.find_all("div", onclick=re.compile(r"mw.SelectRow"))
#     data = []

#     for row in all_divs:
#         divs = row.find_all("div")
#         if len(divs) < 17:
#             continue

#         try:
#             name_div = divs[0].find("a")
#             if name_div:
#                 name = normalize_persian(name_div.text)
#                 matched_name = next((cname for cname in normalized_company_names if cname == name), None)
#                 # name = name_div.text.strip()
#                 # matched_name = next((cname for cname in company_names if cname == name), None)
#                 pe_text = 0
#                 if matched_name:
#                     pe_div = divs[17]
#                     if(pe_div != 'infinity'):                                                    
#                         pe_text = pe_div.text.strip().replace(",", "")

#                     pe_value = float(pe_text) if pe_text else None

#                     price = divs[8]
#                     price = price.text.strip().replace(",", "")
#                     price = float(price) if price else None

#                     data.append((matched_name, pe_value, price))
#         except Exception as e:
#             print(f"Error parsing row: {e}")
#             continue

#     driver.quit()
#     return data


import os
import re
import sys
import math
import hashlib
import logging
from pathlib import Path

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


def normalize_persian(text):
    if text is None:
        return ""

    return (
        str(text)
        .replace("ك", "ک")
        .replace("ي", "ی")
        .replace("\u200c", "")
        .replace("\xa0", " ")
        .strip()
    )


def to_float(value, none_for_infinity=True):
    if value is None:
        return None

    text = str(value).strip()
    text = text.replace(",", "").replace("٬", "")

    lower_text = text.lower()

    if lower_text in ["infinity", "inf", "∞"]:
        return None if none_for_infinity else math.inf

    text = re.sub(r"[^\d\.\-\(\)]", "", text)

    if not text:
        return None

    if re.match(r"^\(\d+(\.\d+)?\)$", text):
        text = "-" + text.strip("()")

    try:
        return float(text)
    except Exception:
        return None


def validate_browser_config():
    chromium_path = Path(CHROMIUM_BINARY)

    if not chromium_path.exists():
        raise FileNotFoundError(f"Chromium not found: {CHROMIUM_BINARY}")

    Path(CHROMIUM_PROFILE_DIR).mkdir(parents=True, exist_ok=True)


def create_context(playwright, headless=False):
    validate_browser_config()

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=CHROMIUM_PROFILE_DIR,
        executable_path=CHROMIUM_BINARY,
        headless=headless,
        viewport={"width": 1366, "height": 768},
        args=[
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    return context


def wait_for_market_rows(page):
    try:
        page.wait_for_selector("div[class^='t0c']", timeout=20000)
        page.wait_for_timeout(3000)
    except PlaywrightTimeoutError:
        raise RuntimeError("Market rows did not load: selector div[class^='t0c'] not found")


def scrape_pe_values(url, normalized_company_names, headless=False):
    """
    خروجی:
    [
        (company_name, pe_value, price),
        ...
    ]
    """

    normalized_company_lookup = {
        normalize_persian(name): normalize_persian(name)
        for name in normalized_company_names
        if normalize_persian(name)
    }

    data = []

    with sync_playwright() as playwright:
        context = create_context(playwright, headless=headless)
        page = context.new_page()

        try:
            logging.info(f"🌐 Opening URL: {url}")

            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                logging.warning("⚠️ networkidle timed out; continuing anyway.")

            wait_for_market_rows(page)

            soup = BeautifulSoup(page.content(), "html.parser")

            all_rows = soup.find_all("div", onclick=re.compile(r"mw\.SelectRow"))

            logging.info(f"✅ Found {len(all_rows)} market rows")

            for row in all_rows:
                divs = row.find_all("div")

                # چون پایین divs[17] استفاده می‌شود، حداقل باید 18 آیتم وجود داشته باشد
                if len(divs) < 18:
                    continue

                try:
                    name_link = divs[0].find("a")

                    if not name_link:
                        continue

                    name = normalize_persian(name_link.get_text(strip=True))
                    matched_name = normalized_company_lookup.get(name)

                    if not matched_name:
                        continue

                    pe_text = divs[17].get_text(strip=True)
                    pe_value = to_float(pe_text, none_for_infinity=True)

                    price_text = divs[8].get_text(strip=True)
                    price = to_float(price_text, none_for_infinity=True)

                    data.append((matched_name, pe_value, price))

                    logging.info(
                        f"✅ Matched: {matched_name} | P/E: {pe_value} | Price: {price}"
                    )

                except Exception as e:
                    logging.warning(f"⚠️ Error parsing row: {e}")
                    continue

        finally:
            context.close()

    return data