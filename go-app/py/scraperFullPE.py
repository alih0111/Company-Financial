import sys
import json
from FullPE import scrape_pe_values
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

def normalize_persian(text):
    return text.replace('ك', 'ک').replace('ي', 'ی').strip()


def get_company_names():
    conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}'
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT CompanyName FROM codal.dbo.miandore2")
    rows = cursor.fetchall()
    conn.close()
    return [row[0].strip() for row in rows if row[0]]

# def save_to_db(pe_data):
#     conn = pyodbc.connect(
#         'DRIVER={ODBC Driver 17 for SQL Server};'
#         'SERVER=localhost;'
#         'DATABASE=codal;'
#         'Trusted_Connection=yes;'
#     )
#     cursor = conn.cursor()

#     # Delete all existing records before inserting new ones
#     try:
#         cursor.execute("DELETE FROM [codal].[dbo].[FullPE]")
#         conn.commit()
#     except Exception as e:
#         print(f"Error deleting existing records: {e}")
#         cursor.close()
#         conn.close()
#         return  # Exit early if delete fails

#     # Now insert new data
#     for item in pe_data:
#         company_name = str(item[0]).strip()
#         pe = safe_float(item[1])
#         price = safe_float(item[2])
#         last_modified = datetime.now()

#         try:
#             cursor.execute('''
#                 INSERT INTO [codal].[dbo].[FullPE] (CompanyName, PE, Price, LastModified)
#                 VALUES (?, ?, ?, ?)
#             ''', company_name, pe, price, last_modified)
#         except Exception as e:
#             print(f"Error inserting {company_name}: {e}")
#             continue

#     conn.commit()
#     cursor.close()
#     conn.close()
import pyodbc
from datetime import datetime

def safe_float(val):
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

def get_eps_from_miandore2(cursor, company_name):
    cursor.execute('''
        SELECT TOP 1 [Num1_Value1]
        FROM [codal].[dbo].[miandore2]
        WHERE CompanyName = ?
        ORDER BY ReportDate DESC
    ''', company_name)
    row = cursor.fetchone()
    return safe_float(row[0]) if row else 0.0

def save_to_db(pe_data):
    conn = pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=localhost;'
        'DATABASE=codal;'
        'Trusted_Connection=yes;'
    )
    cursor = conn.cursor()

    # Delete all existing records before inserting new ones
    try:
        cursor.execute("DELETE FROM [codal].[dbo].[FullPE]")
        conn.commit()
    except Exception as e:
        print(f"Error deleting existing records: {e}")
        cursor.close()
        conn.close()
        return  # Exit early if delete fails

    # Now insert new data
    for item in pe_data:
        company_name = str(item[0]).strip()
        pe = safe_float(item[1])
        price = safe_float(item[2])
        last_modified = datetime.now()

        # If PE is zero or missing, try to calculate it using EPS
        if (pe is None or pe == 0) and price > 0:
            eps = get_eps_from_miandore2(cursor, company_name)
            if eps != 0:
                pe = round(price / eps, 2)

        try:
            cursor.execute('''
                INSERT INTO [codal].[dbo].[FullPE] (CompanyName, PE, Price, LastModified)
                VALUES (?, ?, ?, ?)
            ''', company_name, pe, price, last_modified)
        except Exception as e:
            print(f"Error inserting {company_name}: {e}")
            continue

    conn.commit()
    cursor.close()
    conn.close()


def safe_float(value):
    try:
        value = float(str(value).replace(',', '').strip())
        if math.isfinite(value):
            return value
        else:
            return None  # Reject inf, -inf, nan
    except:
        return None


if __name__ == "__main__":
    company_names = get_company_names()
    normalized_company_names = [normalize_persian(cname) for cname in company_names]
    url = "http://old.tsetmc.com/Loader.aspx?ParTree=15131F#"  # Replace with actual target URL
    pe_data = scrape_pe_values(url, normalized_company_names)    
    save_to_db(pe_data)
    print("Finished scraping and saving PE data.")


