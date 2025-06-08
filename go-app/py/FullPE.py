from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pyodbc
import hashlib
import os
import re
from dotenv import load_dotenv
from datetime import datetime
from webdriver_manager.chrome import ChromeDriverManager
import time
import math

load_dotenv()

server = os.getenv('DB_SERVER')
database = os.getenv('DB_NAME')
username = os.getenv('DB_USER')
password = os.getenv('DB_PASSWORD')

def generate_company_id(name):
    return hashlib.md5(name.encode('utf-8')).hexdigest()

def normalize_persian(text):
    return text.replace('ك', 'ک').replace('ي', 'ی').strip()

def scrape_pe_values(url, normalized_company_names):
    options = webdriver.ChromeOptions()
    # options.add_argument('--headless')
    
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920x1080')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    driver.get(url)
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div[class^='t0c']"))
    )
    time.sleep(3)
    soup = BeautifulSoup(driver.page_source, 'html.parser')

    all_divs = soup.find_all("div", onclick=re.compile(r"mw.SelectRow"))
    data = []

    for row in all_divs:
        divs = row.find_all("div")
        if len(divs) < 17:
            continue

        try:
            name_div = divs[0].find("a")
            if name_div:
                name = normalize_persian(name_div.text)
                matched_name = next((cname for cname in normalized_company_names if cname == name), None)
                # name = name_div.text.strip()
                # matched_name = next((cname for cname in company_names if cname == name), None)
                pe_text = 0
                if matched_name:
                    pe_div = divs[17]
                    if(pe_div != 'infinity'):                                                    
                        pe_text = pe_div.text.strip().replace(",", "")

                    pe_value = float(pe_text) if pe_text else None

                    price = divs[8]
                    price = price.text.strip().replace(",", "")
                    price = float(price) if price else None

                    data.append((matched_name, pe_value, price))
        except Exception as e:
            print(f"Error parsing row: {e}")
            continue

    driver.quit()
    return data
