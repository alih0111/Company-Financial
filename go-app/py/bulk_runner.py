# # py/bulk_runner.py  (فایل جدید)

# import sys
# import json
# import traceback
# from selenium import webdriver
# from selenium.webdriver.chrome.service import Service
# from webdriver_manager.chrome import ChromeDriverManager

# from MianSql import main_scraper_with_driver
# from MianSql2 import main_scraper2_with_driver

# if __name__ == "__main__":
#     sys.stdout.reconfigure(encoding="utf-8")

#     script = sys.argv[1]           # script1 / script2
#     row_meta = int(sys.argv[2])
#     page_numbers = json.loads(sys.argv[3])
#     jobs = json.loads(sys.argv[4])  # [{company,url}, ...]

#     options = webdriver.ChromeOptions()
#     driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

#     try:
#         for job in jobs:
#             company = job.get("company", "")
#             url = job.get("url", "")

#             if not company or not url:
#                 print(f"RESULT|{company}|FAIL|missing company/url")
#                 continue

#             try:
#                 inserted_any = False
#                 if script == "script1":
#                     inserted_any = main_scraper_with_driver(driver, company, row_meta, url, page_numbers, "miandore2")
#                 else:
#                     inserted_any = main_scraper2_with_driver(driver, company, row_meta, url, page_numbers, "mahane")

#                 if inserted_any:
#                     print(f"RESULT|{company}|OK")
#                 else:
#                     print(f"RESULT|{company}|FAIL|no new data saved")

#             except Exception as e:
#                 print(f"RESULT|{company}|FAIL|{str(e)}")
#                 # برای دیباگ اگر خواستی:
#                 # traceback.print_exc()

#     finally:
#         driver.quit()