import sys
import json
from MianSql2 import main_scraper2

# if __name__ == "__main__":
#     company = sys.argv[1]
#     row_meta = int(sys.argv[2])
#     base_url = sys.argv[3]
#     page_numbers = json.loads(sys.argv[4])

#     # print(f"Running scraper for {company} with row meta {row_meta} on pages {page_numbers}")
#     sys.stdout.reconfigure(encoding='utf-8')  # ✅ Add this line near the top
#     print(f"Running scraper for {company} with row meta {row_meta} on pages {page_numbers}")

#     main_scraper2(company, row_meta, base_url, page_numbers, "mahane")
import sys
import json
import logging

# ✅ Setup logging at the top
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # log to stdout (important if Go captures output)
        # logging.FileHandler("scraper.log"),  # optional: write to file
    ]
)

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')  # ensure proper Unicode output

    try:
        company = sys.argv[1]
        row_meta = int(sys.argv[2])
        base_url = sys.argv[3]
        page_numbers = json.loads(sys.argv[4])

        logging.info(f"Running scraper for {company} with row_meta={row_meta}, pages={page_numbers}")
        main_scraper2(company, row_meta, base_url, page_numbers, "mahane")
        logging.info("Scraper finished successfully.")

    except Exception as e:
        logging.exception("❌ An error occurred in the scraper:")
        sys.exit(1)
