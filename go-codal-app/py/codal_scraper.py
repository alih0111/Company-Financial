import sys
import json
from codal_MianSql import main_scraper  # We need to put scraping logic in a callable function

if __name__ == "__main__":
    company = sys.argv[1]
    row_meta = int(sys.argv[2])
    base_url = sys.argv[3]
    page_numbers = json.loads(sys.argv[4])

    # print(f"Running scraper for {company} with row meta {row_meta} on pages {page_numbers}")

    sys.stdout.reconfigure(encoding='utf-8')  # ✅ Add this line near the top
    print(f"Running scraper for {company} with row meta {row_meta} on pages {page_numbers}")

    # Assuming your main scraping code is inside a function main_scraper() with params
    main_scraper(company, row_meta, base_url, page_numbers)
