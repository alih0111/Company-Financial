import sys
import json
from codal_MianSql2 import main_scraper2

if __name__ == "__main__":
    company = sys.argv[1]
    row_meta = int(sys.argv[2])
    base_url = sys.argv[3]
    page_numbers = json.loads(sys.argv[4])

    print(f"Running scraper for {company} with row meta {row_meta} on pages {page_numbers}")
    main_scraper2(company, row_meta, base_url, page_numbers)
