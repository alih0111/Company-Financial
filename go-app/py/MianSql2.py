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
PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789"
)


def generate_company_id(name):
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def normalize_text(text):
    if text is None:
        return ""

    return (
        str(text)
        .strip()
        .replace("\u200c", "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .replace("\ufeff", "")
        .replace("\xa0", " ")
        .replace("ي", "ی")
        .replace("ك", "ک")
    )


def to_number(s):
    if s is None:
        return 0.0

    s = normalize_text(s).translate(PERSIAN_ARABIC_DIGITS)
    s = s.replace(",", "").replace("٬", "")
    s = re.sub(r"[^\d\.\-\(\)]", "", s)

    if re.fullmatch(r"\(\d+(?:\.\d+)?\)", s):
        s = "-" + s[1:-1]

    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


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
        # min_date = jdatetime.date(1399, 1, 30)

        # if report_jdate <= min_date:
        #     logging.info(f"⏩ Skipping old report {report_date}")
        #     return None

    except Exception as e:
        logging.warning(f"⚠️ Could not parse report date: {e}")
        return None

    # --------------------- Parse HTML Table ---------------------
    soup = BeautifulSoup(page.content(), "html.parser")
    table = find_supported_statement_table(soup)

    if not table:
        logging.warning(f"⚠️ No supported data table found for {link}")
        return None

    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    all_rows = table.select("tbody tr")

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
    monthly_values = extract_one_month_values(table)

    if len(monthly_values) != 3:
        logging.warning(
            f"⚠️ Could not extract one-month values for {link}"
        )
        return None

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

    # در جدول خدمات، ردیف‌های فروش داخلی/صادراتی وجود ندارند.
    if total_value == 0 and monthly_values[2] != 0:
        total_value = monthly_values[2]

    logging.info(f"ℹ️ total_value={total_value}")

    return {
        "report_date": report_date,
        "headers": headers,
        "monthly_values": monthly_values,
        "dakheli_value": dakheli_value,
        "saderati_value": saderati_value,
        "total_value": total_value,
    }


def save_report_to_sql(
    company_name,
    report_date,
    monthly_values,
    base_url,
    table_name
):
    table_name = safe_sql_identifier(table_name)

    calculated_values = monthly_values

    if len(calculated_values) != 3:
        logging.warning(
            f"⚠️ Invalid monthly values for "
            f"{company_name} - {report_date}: {calculated_values}"
        )
        return False

    if not all(
        isinstance(value, (float, int))
        for value in calculated_values
    ):
        logging.warning(
            f"⚠️ Non-numeric monthly values for "
            f"{company_name} - {report_date}: {calculated_values}"
        )
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
            logging.info(
                f"⏩ Already exists: {company_name} - {report_date}"
            )
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
            calculated_values[0],  # تعداد تولید یک‌ماهه؛ برای خدمات صفر
            calculated_values[1],  # تعداد فروش یک‌ماهه؛ برای خدمات صفر
            calculated_values[2],  # مبلغ فروش/درآمد شناسایی‌شده یک‌ماهه
            base_url
        )

        conn.commit()

        logging.info(
            f"✅ Monthly report {report_date} saved to SQL: "
            f"{calculated_values}"
        )
        return True

    except Exception as e:
        logging.exception(
            f"❌ SQL error for {company_name} - {report_date}: {e}"
        )
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

                        monthly_values = result["monthly_values"]
                        report_date = result["report_date"]
                        # headers = result["headers"]
                        # last_row = result["last_row"]
                        dakheli_value = result["dakheli_value"]
                        saderati_value = result["saderati_value"]
                        total_value = result["total_value"]

                        # if flag:
                        #     all_data.append(
                        #         ["Report Date"] + headers + ["داخلی", "صادراتی", "مجموع تعدادی"]
                        #     )
                        #     flag = False
                        if flag:
                            all_data.append([
                                "Report Date",
                                "تعداد تولید یک‌ماهه",
                                "تعداد فروش یک‌ماهه",
                                "مبلغ فروش یک‌ماهه",
                                "داخلی",
                                "صادراتی",
                                "مجموع تعدادی",
                            ])
                            flag = False

                        # all_data.append(
                        #     [report_date] + last_row + [dakheli_value, saderati_value, str(total_value)]
                        # )
                        all_data.append(
                            [report_date]
                            + monthly_values
                            + [dakheli_value, saderati_value, total_value]
                        )

                        # saved = save_report_to_sql(
                        #     company_name=companyName,
                        #     report_date=report_date,
                        #     last_row=last_row,
                        #     base_url=base_url,
                        #     table_name=table_name,
                        # )
                        saved = save_report_to_sql(
                            company_name=companyName,
                            report_date=report_date,
                            monthly_values=monthly_values,
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


def normalize_header(text):
    text = normalize_text(text)
    text = text.translate(PERSIAN_ARABIC_DIGITS)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_one_month_header(text):
    """
    تشخیص هدرهایی مانند:
    دوره یک ماهه منتهی به ...
    دوره 1 ماهه منتهی به ...
    """
    text = normalize_header(text)

    return bool(
        re.search(r"دوره\s*(?:یک|1)\s*ماهه", text)
    )


def expand_data_cells(tr):
    """
    دریافت سلول‌های قابل مشاهده ردیف با درنظرگرفتن colspan.
    """
    expanded_cells = []

    for td in tr.find_all("td", recursive=False):

        # سلول مخفی نباید شماره ستون را جابه‌جا کند
        if is_hidden_cell(td):
            continue

        try:
            colspan = int(td.get("colspan", 1))
        except (TypeError, ValueError):
            colspan = 1

        expanded_cells.extend([td] * colspan)

    return expanded_cells


# def find_total_cells(table):
#     """آخرین ردیف جمع واقعی جدول را برمی‌گرداند."""
#     for tr in reversed(table.select("tbody tr")):
#         cells = expand_data_cells(tr)

#         if not cells:
#             continue

#         title = normalize_header(cells[0].get_text(" ", strip=True))

#         if title in {"جمع", "جمع کل", "مجموع"}:
#             return cells

#     return None

def find_total_cells(table):
    """آخرین ردیف جمع واقعی جدول را برمی‌گرداند."""

    for tr in reversed(table.select("tbody tr")):
        cells = expand_data_cells(tr)

        if not cells:
            continue

        title = normalize_header(
            cells[0].get_text(" ", strip=True)
        )

        is_total_row = (
            title in {"جمع", "جمع کل", "مجموع"}
            or bool(
                re.fullmatch(
                    r"جمع(?: کل)? درآمدهای? عملیاتی",
                    title
                )
            )
        )

        if is_total_row:
            logging.info(f"✅ Final total row found: {title}")
            return cells

    return None

def find_supported_statement_table(soup):
    """
    از میان جدول‌های داینامیک، جدولی را انتخاب می‌کند که ستون دوره
    یک‌ماهه فروش/تولید یا درآمد شناسایی‌شده داشته باشد.
    """
    tables = soup.select("table.rayanDynamicStatement")

    for table in tables:
        header_texts = [
            normalize_header(th.get_text(" ", strip=True))
            for th in table.select("thead th")
            if not is_hidden_cell(th)
        ]

        has_one_month = any(is_one_month_header(text) for text in header_texts)
        has_supported_metric = any(
            any(keyword in text for keyword in (
                "تعداد تولید",
                "تعداد فروش",
                "مبلغ فروش",
                "درآمد",
                "درامد",
            ))
            for text in header_texts
        )

        if has_one_month and has_supported_metric:
            return table

    # برای حفظ سازگاری با گزارش‌های قدیمی که متن هدر متفاوتی دارند.
    return tables[0] if tables else None


def extract_one_month_values(table):
    """
    خروجی سازگار با ساختار فعلی دیتابیس:

    گزارش تولید/فروش:
        [تعداد تولید یک‌ماهه، تعداد فروش یک‌ماهه، مبلغ فروش یک‌ماهه]

    گزارش خدمات/درآمد:
        [0، 0، درآمد شناسایی‌شده طی دوره یک‌ماهه]
    """
    header_grid = build_header_grid(table)

    if not header_grid:
        logging.warning("⚠️ Table header grid is empty.")
        return []

    max_columns = max(len(row) for row in header_grid)
    one_month_columns = []

    for column_index in range(max_columns):
        column_headers = []

        for header_row in header_grid:
            if column_index >= len(header_row):
                continue

            header_text = header_row[column_index]

            if header_text and header_text not in column_headers:
                column_headers.append(header_text)

        if any(is_one_month_header(header) for header in column_headers):
            combined_header = normalize_header(" | ".join(column_headers))

            one_month_columns.append({
                "index": column_index,
                "field": normalize_header(column_headers[-1]),
                "combined": combined_header,
                "headers": column_headers,
            })

    if not one_month_columns:
        logging.warning("⚠️ One-month period header was not found.")
        return []

    logging.info(
        "✅ One-month columns: %s",
        [(item["index"], item["field"]) for item in one_month_columns]
    )

    total_cells = find_total_cells(table)

    if total_cells is None:
        logging.warning("⚠️ Final total row was not found.")
        return []

    # حالت قدیمی: جدول تولید و فروش محصول
    product_indexes = {}

    for item in one_month_columns:
        header = item["combined"]
        index = item["index"]

        if "تعداد تولید" in header:
            product_indexes["production"] = index
        elif "تعداد فروش" in header:
            product_indexes["sales_quantity"] = index
        elif "مبلغ فروش" in header:
            product_indexes["sales_amount"] = index

    required_product_fields = {
        "production",
        "sales_quantity",
        "sales_amount",
    }

    if required_product_fields.issubset(product_indexes):
        selected_indexes = [
            product_indexes["production"],
            product_indexes["sales_quantity"],
            product_indexes["sales_amount"],
        ]

        if max(selected_indexes) >= len(total_cells):
            logging.warning(
                "⚠️ Product one-month index is outside total row. "
                f"Row cells={len(total_cells)}, indexes={selected_indexes}"
            )
            return []

        monthly_values = [
            to_number(total_cells[index].get_text(" ", strip=True))
            for index in selected_indexes
        ]

        logging.info(
            "✅ Product one-month values extracted: "
            f"production={monthly_values[0]}, "
            f"sales_quantity={monthly_values[1]}, "
            f"sales_amount={monthly_values[2]}"
        )
        return monthly_values

    # حالت جدید: جدول خدمات/فروش با ستون درآمد شناسایی‌شده طی یک ماه
    revenue_candidates = [
        item
        for item in one_month_columns
        if "درآمد" in item["combined"] or "درامد" in item["combined"]
    ]

    if revenue_candidates:
        # هدر «طی دوره یک‌ماهه» نسبت به عبارات تجمعی اولویت دارد.
        revenue_item = next(
            (
                item for item in revenue_candidates
                if "طی دوره" in item["combined"]
            ),
            revenue_candidates[0],
        )
        revenue_index = revenue_item["index"]

        if revenue_index >= len(total_cells):
            logging.warning(
                "⚠️ Revenue one-month index is outside total row. "
                f"Row cells={len(total_cells)}, index={revenue_index}"
            )
            return []

        one_month_revenue = to_number(
            total_cells[revenue_index].get_text(" ", strip=True)
        )
        monthly_values = [0.0, 0.0, one_month_revenue]

        logging.info(
            "✅ Service one-month revenue extracted: "
            f"revenue={one_month_revenue}"
        )
        return monthly_values

    logging.warning(
        "⚠️ One-month columns were found, but their metric type is unsupported: %s",
        [item["combined"] for item in one_month_columns]
    )
    return []

def is_hidden_cell(tag):
    if tag.has_attr("hidden"):
        return True

    style = (tag.get("style") or "").replace(" ", "").lower()

    return (
        "display:none" in style
        or "visibility:hidden" in style
    )


def build_header_grid(table):
    """
    ساخت ماتریس هدر فقط براساس ستون‌های قابل مشاهده.
    ستون‌های hidden در محاسبه اندیس دخالت نمی‌کنند.
    """
    header_rows = table.select("thead tr")
    grid = []

    for row_index, tr in enumerate(header_rows):
        while len(grid) <= row_index:
            grid.append([])

        column_index = 0

        for th in tr.find_all("th", recursive=False):

            # ستون‌های مخفی را کاملاً نادیده بگیر
            if is_hidden_cell(th):
                continue

            while (
                column_index < len(grid[row_index])
                and grid[row_index][column_index] is not None
            ):
                column_index += 1

            text = normalize_header(
                th.get_text(" ", strip=True)
            )

            try:
                colspan = int(th.get("colspan", 1))
            except (TypeError, ValueError):
                colspan = 1

            try:
                rowspan = int(th.get("rowspan", 1))
            except (TypeError, ValueError):
                rowspan = 1

            for target_row in range(
                row_index,
                row_index + rowspan
            ):
                while len(grid) <= target_row:
                    grid.append([])

                required_length = column_index + colspan

                if len(grid[target_row]) < required_length:
                    grid[target_row].extend(
                        [None] * (
                            required_length
                            - len(grid[target_row])
                        )
                    )

                for target_column in range(
                    column_index,
                    column_index + colspan
                ):
                    grid[target_row][target_column] = text

            column_index += colspan

    return grid



