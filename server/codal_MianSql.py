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
    s = s.replace(',', '').replace('٬', '')
    s = re.sub(r'[^\d\.\-\(\)]', '', s)
    if re.match(r'^\(\d+(\.\d+)?\)$', s):
        s = '-' + s.strip('()')
    return float(s) if s else 0

def is_hidden_row(tr):
    tds = tr.find_all('td')
    return all(td.has_attr('hidden') for td in tds)

def main_scraper(companyName, rowMeta, base_url, page_numbers):
    base_url = base_url.replace("&PageNumber=1", "")
    # options = webdriver.ChromeOptions()
    # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920x1080')

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)


    for page in page_numbers:
        current_url = f"{base_url}&PageNumber={page}"
        driver.get(current_url)
        print(f"Fetching data from page {page}...")

        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "scrollContent"))
            )
            time.sleep(5)
        except:
            print(f"Table did not load on page {page}. Skipping...")
            continue

        rows = driver.find_elements(By.CSS_SELECTOR, "tbody.scrollContent tr")
        report_links = []
        for row in rows[:rowMeta]:
            try:
                link_element = row.find_element(By.CSS_SELECTOR, "td:nth-child(4) a")
                report_links.append(link_element.get_attribute("href"))
            except:
                continue

        for link in report_links:
            try:
                driver.get(link)
                WebDriverWait(driver, 15).until(
                    lambda d: d.execute_script(
                        "return window.getAllAngularTestabilities && window.getAllAngularTestabilities().every(t => t.isStable())"
                    )
                )
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "rayanDynamicStatement"))
                )

                date_element = driver.find_element(By.ID, "ctl00_lblPeriodEndToDate")
                report_date = date_element.text.strip()
                try:
                    report_jdate = jdatetime.datetime.strptime(report_date, "%Y/%m/%d").date()
                    min_date = jdatetime.date(1397, 12, 29)
                    if report_jdate <= min_date:
                        continue
                except:
                    continue

                soup = BeautifulSoup(driver.page_source, 'html.parser')
                table = soup.find('table', {'class': 'rayanDynamicStatement'})
                if not table:
                    continue

                all_rows = table.find_all('tr')[1:]
                # if len(all_rows) < 3:
                #     continue

                # row1 = [td.text.strip() for td in all_rows[-2].find_all('td')]
                # row2 = [td.text.strip() for td in all_rows[-1].find_all('td')]
                

                valid_rows = [tr for tr in all_rows if not is_hidden_row(tr)]

                

                if len(valid_rows) < 2:
                    continue

                row1 = [td.text.strip() for td in valid_rows[-2].find_all('td')]
                row2 = [td.text.strip() for td in valid_rows[-1].find_all('td')]

               

                min_len = min(len(row1), len(row2))

                last_row_num1 = []
                last_row_num2 = []
                last_row_product = []

                for i in range(1, min_len):
                    try:
                        num1 = to_number(row1[i])
                        num2 = to_number(row2[i])
                        last_row_num1.append(num1)
                        last_row_num2.append(num2)
                        last_row_product.append(num1 * num2)
                    except:
                        last_row_num1.append(0)
                        last_row_num2.append(0)
                        last_row_product.append(0)

                if(last_row_num1[0]==0):
                    values_to_insert = (
                        last_row_num1[1], last_row_num2[1], last_row_product[1],
                        last_row_num1[2], last_row_num2[2], last_row_product[2],
                        last_row_num1[3], last_row_num2[3], last_row_product[3]
                    )
                else:
                    values_to_insert = (
                        last_row_num1[0], last_row_num2[0], last_row_product[0],
                        last_row_num1[1], last_row_num2[1], last_row_product[1],
                        last_row_num1[2], last_row_num2[2], last_row_product[2]
                    )

                # print("/////////////////")
                # print(last_row_num1)
                # print(last_row_num2)
                # print("/////////////////")

                server = 'wsn-mis-068'
                database = 'codal'
                username = 'sa'
                password = 'dbco@2023hamkaran'
                table_name = 'miandore2'
                conn_str = (
                    f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};'
                    f'UID={username};PWD={password}'
                )
                conn = pyodbc.connect(conn_str)
                cursor = conn.cursor()

                cursor.execute(f'''
                    IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='{table_name}' AND xtype='U')
                    CREATE TABLE {table_name} (
                        CompanyID NVARCHAR(50),
                        CompanyName NVARCHAR(50),
                        ReportDate NVARCHAR(50),
                        Num1_Value1 FLOAT,
                        Num2_Value1 FLOAT,
                        Product1 FLOAT,
                        Num1_Value2 FLOAT,
                        Num2_Value2 FLOAT,
                        Product2 FLOAT,
                        Num1_Value3 FLOAT,
                        Num2_Value3 FLOAT,
                        Product3 FLOAT,
                        Url VARCHAR(550),
                        PRIMARY KEY (CompanyID, ReportDate)
                    )
                ''')
                conn.commit()

                company_id = generate_company_id(companyName)
                cursor.execute(f'SELECT COUNT(*) FROM {table_name} WHERE CompanyID = ? AND ReportDate = ?', company_id, report_date)
                exists = cursor.fetchone()[0]

                if not exists:
                    cursor.execute(f'''
                        INSERT INTO {table_name} (
                            CompanyID, CompanyName, ReportDate,
                            Num1_Value1, Num2_Value1, Product1,
                            Num1_Value2, Num2_Value2, Product2,
                            Num1_Value3, Num2_Value3, Product3,
                            Url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', company_id, companyName, report_date, *values_to_insert, base_url)
                    conn.commit()

                cursor.close()
                conn.close()

            except Exception as e:
                print(f"Error: {e}")
                continue

    driver.quit()

if __name__ == "__main__":
    companyName = 'قثابت'
    rowMeta = 20
    base_url = "https://www.codal.ir/ReportList.aspx?search&Symbol=%D9%82%D8%AB%D8%A7%D8%A8%D8%AA&LetterType=6&AuditorRef=-1&Audited=false&NotAudited&IsNotAudited=false&Childs&Mains&Publisher=false&CompanyState=0&ReportingType=1000000&name=%DA%A9%D8%A7%D8%B1%D8%AE%D8%A7%D9%86%D9%87%20%D9%87%D8%A7%DB%8C%20%D8%AA%D9%88%D9%84%DB%8C%D8%AF%DB%8C%20%D9%88%20%D8%B5%D9%86%D8%B9%D8%AA%DB%8C%20%D8%AB%D8%A7%D8%A8%D8%AA%20%D8%AE%D8%B1%D8%A7%D8%B3%D8%A7%D9%86&Category=1"
    page_numbers = range(1, 3)
    main_scraper(companyName, rowMeta, base_url, page_numbers)
