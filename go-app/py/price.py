import os
import re
import sys
import math
import hashlib
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

try:
    import pyodbc
except ImportError:
    pyodbc = None
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


# --------------------- Logging Setup ---------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


# --------------------- Load Environment ---------------------
load_dotenv()

server = os.getenv("DB_SERVER")
database = os.getenv("DB_NAME")
username = os.getenv("DB_USER")
password = os.getenv("DB_PASSWORD")


CHROMIUM_BINARY = (
    r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe"
)

CHROMIUM_PROFILE_DIR = (
    r"D:\rfa\Company-Financial\go-app\py\chromium-profile"
)


PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


# --------------------- General Helpers ---------------------
def generate_company_id(name):
    normalized_name = normalize_persian(name)
    return hashlib.md5(normalized_name.encode("utf-8")).hexdigest()


def normalize_persian(text):
    if text is None:
        return ""

    return (
        str(text)
        .replace("ك", "ک")
        .replace("ي", "ی")
        .replace("\u200c", "")
        .replace("\u200f", "")
        .replace("\u200e", "")
        .replace("\xa0", " ")
        .strip()
    )


def normalize_numeric_text(value):
    if value is None:
        return ""

    return (
        str(value)
        .translate(PERSIAN_ARABIC_DIGITS)
        .replace(",", "")
        .replace("٬", "")
        .replace("\xa0", " ")
        .strip()
    )


def to_float(value, none_for_infinity=True):
    if value is None:
        return None

    text = normalize_numeric_text(value)
    lower_text = text.lower()

    if lower_text in {"infinity", "inf", "∞"}:
        return None if none_for_infinity else math.inf

    if not text or text in {"-", "--"}:
        return None

    is_negative = (
        text.startswith("-")
        or (text.startswith("(") and text.endswith(")"))
    )

    text = text.replace("(", "").replace(")", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        number = float(match.group())
    except ValueError:
        return None

    if is_negative and number > 0:
        number = -number

    return number


def to_int(value):
    """
    تبدیل مقدار به عدد صحیح بدون از دست دادن دقت اعداد بزرگ مانند ارزش معاملات.
    """
    if value is None:
        return None

    text = normalize_numeric_text(value)

    if not text or text in {"-", "--"}:
        return None

    is_negative = (
        text.startswith("-")
        or (text.startswith("(") and text.endswith(")"))
    )

    text = text.replace("(", "").replace(")", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        number = Decimal(match.group())
    except InvalidOperation:
        return None

    if is_negative and number > 0:
        number = -number

    return int(number)


def safe_sql_identifier(name):
    table_name = str(name)

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
        raise ValueError(f"Invalid SQL table name: {name}")

    return table_name


def extract_instrument_code(url):
    query = parse_qs(urlparse(url).query)
    return str(query.get("i", [""])[0]).strip()


def normalize_gregorian_date(raw_date):
    digits = re.sub(r"\D", "", normalize_numeric_text(raw_date))

    if len(digits) != 8:
        return None

    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"


# --------------------- Browser ---------------------
def validate_browser_config():
    chromium_path = Path(CHROMIUM_BINARY)

    if not chromium_path.exists():
        raise FileNotFoundError(
            f"Chromium not found: {CHROMIUM_BINARY}"
        )

    Path(CHROMIUM_PROFILE_DIR).mkdir(
        parents=True,
        exist_ok=True,
    )


def create_context(playwright, headless=False):
    validate_browser_config()

    return playwright.chromium.launch_persistent_context(
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


def wait_for_market_rows(page):
    try:
        page.wait_for_selector(
            "div[class^='t0c']",
            timeout=20000,
        )
        page.wait_for_timeout(2000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Market rows did not load: "
            "selector div[class^='t0c'] not found"
        ) from exc


# --------------------- Market Watch ---------------------
def collect_market_rows(
    page,
    market_url,
    normalized_company_names,
):
    """
    اطلاعات جاری بازار را جمع می‌کند.

    خروجی هر آیتم:
    {
        company_name,
        symbol,
        pe_value,
        current_price,
        detail_url,
        instrument_code
    }
    """
    normalized_company_lookup = {
        normalize_persian(name): normalize_persian(name)
        for name in normalized_company_names
        if normalize_persian(name)
    }

    page.goto(
        market_url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        logging.warning(
            "⚠️ networkidle timed out; continuing anyway."
        )

    wait_for_market_rows(page)

    soup = BeautifulSoup(
        page.content(),
        "html.parser",
    )

    all_rows = soup.find_all(
        "div",
        onclick=re.compile(r"mw\.SelectRow"),
    )

    logging.info(
        "✅ Found %s market rows",
        len(all_rows),
    )

    matched_rows = []

    for row in all_rows:
        divs = row.find_all("div")

        # سازگاری با ساختار فعلی دیده‌بان
        if len(divs) < 18:
            continue

        try:
            name_link = divs[0].find("a")

            if not name_link:
                continue

            displayed_name = normalize_persian(
                name_link.get_text(" ", strip=True)
            )

            matched_name = normalized_company_lookup.get(
                displayed_name
            )

            if not matched_name:
                continue

            href = name_link.get("href")

            if not href:
                logging.warning(
                    "⚠️ Detail link not found for %s",
                    matched_name,
                )
                continue

            detail_url = urljoin(
                market_url,
                href,
            )

            pe_value = to_float(
                divs[17].get_text(" ", strip=True),
                none_for_infinity=True,
            )

            current_price = to_float(
                divs[8].get_text(" ", strip=True),
                none_for_infinity=True,
            )

            matched_rows.append(
                {
                    "company_name": matched_name,
                    "symbol": displayed_name,
                    "pe_value": pe_value,
                    "current_price": current_price,
                    "detail_url": detail_url,
                    "instrument_code": extract_instrument_code(
                        detail_url
                    ),
                }
            )

            logging.info(
                "✅ Matched: %s | P/E=%s | Price=%s",
                matched_name,
                pe_value,
                current_price,
            )

        except Exception as exc:
            logging.warning(
                "⚠️ Error parsing market row: %s",
                exc,
            )

    return matched_rows


def scrape_pe_values(
    url,
    normalized_company_names,
    headless=False,
):
    """
    Wrapper سازگار با خروجی قبلی:

    [
        (company_name, pe_value, price),
        ...
    ]
    """
    with sync_playwright() as playwright:
        context = create_context(
            playwright,
            headless=headless,
        )

        page = context.new_page()

        try:
            rows = collect_market_rows(
                page=page,
                market_url=url,
                normalized_company_names=normalized_company_names,
            )

            return [
                (
                    row["company_name"],
                    row["pe_value"],
                    row["current_price"],
                )
                for row in rows
            ]

        finally:
            context.close()


# --------------------- History Parser ---------------------
def exact_integer_from_cell(td):
    """
    برای ستون ارزش و حجم، مقدار دقیق داخل span مخفی قرار دارد:

    <span style="display:none">[1431237513660.00]</span>
    <div>1,431.238B</div>

    این تابع ابتدا مقدار مخفی دقیق را می‌خواند.
    """
    for span in td.find_all("span"):
        style = (
            span.get("style") or ""
        ).replace(" ", "").lower()

        if "display:none" not in style:
            continue

        match = re.search(
            r"\[([-\d.,]+)\]",
            span.get_text(" ", strip=True),
        )

        if match:
            return to_int(match.group(1))

    title = td.get("title")

    if title:
        title_number = to_int(title)

        if title_number is not None:
            return title_number

    return to_int(
        td.get_text(" ", strip=True)
    )


def parse_trade_history_html(html):
    """
    ساختار ستون‌های جدول سابقه:

    0  تاریخ میلادی مخفی
    1  ستون خالی
    2  بیشترین قیمت
    3  کمترین قیمت
    4  درصد تغییر قیمت پایانی
    5  تغییر قیمت پایانی
    6  قیمت پایانی
    7  درصد تغییر آخرین معامله
    8  تغییر آخرین معامله
    9  قیمت آخرین معامله
    10 اولین قیمت
    11 قیمت دیروز
    12 ارزش معاملات
    13 حجم معاملات
    14 تعداد معاملات
    15 تاریخ شمسی
    """
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    rows = soup.select(
        "#trade table.obj tbody "
        "tr.ev_modern, "
        "#trade table.obj tbody "
        "tr.odd_modern"
    )

    parsed_rows = []

    for tr in rows:
        cells = tr.find_all(
            "td",
            recursive=False,
        )

        if len(cells) < 16:
            continue

        gregorian_date = normalize_gregorian_date(
            cells[0].get_text(" ", strip=True)
        )

        jalali_date = normalize_persian(
            cells[15].get_text(" ", strip=True)
        )

        if not gregorian_date or not jalali_date:
            continue

        parsed_rows.append(
            {
                "gregorian_date": gregorian_date,
                "jalali_date": jalali_date,

                "high_price": exact_integer_from_cell(
                    cells[2]
                ),
                "low_price": exact_integer_from_cell(
                    cells[3]
                ),

                "closing_change_percent": to_float(
                    cells[4].get_text(" ", strip=True)
                ),
                "closing_change": exact_integer_from_cell(
                    cells[5]
                ),
                "closing_price": exact_integer_from_cell(
                    cells[6]
                ),

                "last_change_percent": to_float(
                    cells[7].get_text(" ", strip=True)
                ),
                "last_change": exact_integer_from_cell(
                    cells[8]
                ),
                "last_price": exact_integer_from_cell(
                    cells[9]
                ),

                "first_price": exact_integer_from_cell(
                    cells[10]
                ),
                "yesterday_price": exact_integer_from_cell(
                    cells[11]
                ),

                "trade_value": exact_integer_from_cell(
                    cells[12]
                ),
                "volume": exact_integer_from_cell(
                    cells[13]
                ),
                "trade_count": exact_integer_from_cell(
                    cells[14]
                ),
            }
        )

    return parsed_rows


# --------------------- History Browser Actions ---------------------
HISTORY_ROW_SELECTOR = (
    "#trade table.obj tbody "
    "tr.ev_modern, "
    "#trade table.obj tbody "
    "tr.odd_modern"
)


def open_history_tab(page):
    """
    تب «سابقه» را باز کرده و فقط روزهای معامله‌شده را بارگذاری می‌کند.
    """
    try:
        history_tab = page.locator(
            "a[onclick*='ii.ShowTab(17)']"
        ).first

        history_tab.wait_for(
            state="attached",
            timeout=15000,
        )

        history_tab.click()

    except Exception:
        page.wait_for_function(
            """
            () => (
                window.ii
                && typeof window.ii.ShowTab === "function"
            )
            """,
            timeout=15000,
        )

        page.evaluate(
            "() => window.ii.ShowTab(17)"
        )

    page.wait_for_selector(
        "#HistoryContent",
        state="visible",
        timeout=20000,
    )

    # صریحاً حالت «نمایش روزهای معامله‌شده» را انتخاب می‌کنیم.
    try:
        traded_days_link = page.locator(
            "#HistoryContent "
            "a[href*='ShowTradeHistory(999999,0)']"
        ).first

        traded_days_link.wait_for(
            state="attached",
            timeout=5000,
        )

        traded_days_link.click()

    except Exception:
        page.wait_for_function(
            """
            () => (
                window.ii
                && typeof window.ii.ShowTradeHistory
                    === "function"
            )
            """,
            timeout=10000,
        )

        page.evaluate(
            "() => window.ii.ShowTradeHistory(999999, 0)"
        )

    page.wait_for_selector(
        HISTORY_ROW_SELECTOR,
        timeout=30000,
    )


def get_history_page_numbers(page):
    texts = page.locator(
        "#paging a"
    ).all_inner_texts()

    page_numbers = {
        int(text.strip())
        for text in texts
        if text.strip().isdigit()
    }

    if not page_numbers:
        return [1]

    return sorted(page_numbers)


def current_history_page(page):
    try:
        text = page.locator(
            "#paging a.dhx_not_active"
        ).first.inner_text(
            timeout=2000
        ).strip()

        if text.isdigit():
            return int(text)

    except Exception:
        pass

    return 1


def current_first_history_date(page):
    try:
        return (
            page.locator(HISTORY_ROW_SELECTOR)
            .first.locator("td")
            .nth(0)
            .inner_text(timeout=3000)
            .strip()
        )
    except Exception:
        return ""


def go_to_history_page(page, page_number):
    if current_history_page(page) == page_number:
        return

    old_first_date = current_first_history_date(page)

    page_link = page.locator(
        "#paging a"
    ).filter(
        has_text=re.compile(
            rf"^\s*{page_number}\s*$"
        )
    ).first

    if page_link.count() == 0:
        raise RuntimeError(
            f"History page link {page_number} not found"
        )

    page_link.click()

    try:
        page.wait_for_function(
            """
            ({pageNumber, oldFirstDate}) => {
                const active = document.querySelector(
                    "#paging a.dhx_not_active"
                );

                const firstRow = document.querySelector(
                    "#trade table.obj tbody "
                    + "tr.ev_modern, "
                    + "#trade table.obj tbody "
                    + "tr.odd_modern"
                );

                const activePage = active
                    ? active.textContent.trim()
                    : "";

                const firstDate = (
                    firstRow
                    && firstRow.cells
                    && firstRow.cells.length
                )
                    ? firstRow.cells[0].textContent.trim()
                    : "";

                return (
                    activePage === String(pageNumber)
                    && (
                        !oldFirstDate
                        || firstDate !== oldFirstDate
                    )
                );
            }
            """,
            arg={
                "pageNumber": page_number,
                "oldFirstDate": old_first_date,
            },
            timeout=10000,
        )

    except PlaywrightTimeoutError:
        # تغییر صفحه در DHTMLX معمولاً سمت کلاینت و سریع است.
        # در صورت timeout یک مکث کوتاه و بررسی نهایی انجام می‌دهیم.
        page.wait_for_timeout(500)

        if current_history_page(page) != page_number:
            raise RuntimeError(
                f"Could not switch to history page "
                f"{page_number}"
            )


def scrape_trade_history(
    page,
    detail_url,
    max_pages=None,
):
    """
    تمام صفحات بخش سابقه یک نماد را استخراج می‌کند.

    max_pages:
        None  => تمام صفحات
        عدد   => فقط همان تعداد صفحه اول
    """
    logging.info(
        "🌐 Opening instrument page: %s",
        detail_url,
    )

    page.goto(
        detail_url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        logging.warning(
            "⚠️ Instrument networkidle timed out."
        )

    open_history_tab(page)

    page_numbers = get_history_page_numbers(page)

    if max_pages is not None:
        page_numbers = page_numbers[:max_pages]

    all_rows_by_date = {}

    for page_number in page_numbers:
        go_to_history_page(
            page,
            page_number,
        )

        history_html = page.locator(
            "#HistoryContent"
        ).inner_html()

        page_rows = parse_trade_history_html(
            history_html
        )

        for row in page_rows:
            all_rows_by_date[
                row["gregorian_date"]
            ] = row

        logging.info(
            "✅ History page %s: %s rows",
            page_number,
            len(page_rows),
        )

    result = sorted(
        all_rows_by_date.values(),
        key=lambda item: item["gregorian_date"],
        reverse=True,
    )

    logging.info(
        "✅ Total unique history rows: %s",
        len(result),
    )

    return result


# --------------------- SQL ---------------------
def validate_database_config():
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
        raise RuntimeError(
            "Missing .env values: "
            + ", ".join(missing)
        )


def get_db_connection():
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed. Install it with: pip install pyodbc")

    validate_database_config()

    connection_string = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(
        connection_string
    )


def ensure_price_history_table(
    cursor,
    table_name="MarketPriceHistory",
):
    table_name = safe_sql_identifier(
        table_name
    )

    cursor.execute(
        f"""
        IF OBJECT_ID(
            N'dbo.{table_name}',
            N'U'
        ) IS NULL
        BEGIN
            CREATE TABLE dbo.[{table_name}] (
                InstrumentCode VARCHAR(30) NOT NULL,
                CompanyID NVARCHAR(50) NOT NULL,
                CompanyName NVARCHAR(200),
                Symbol NVARCHAR(50),

                GregorianDate DATE NOT NULL,
                JalaliDate CHAR(10) NOT NULL,

                HighPrice BIGINT NULL,
                LowPrice BIGINT NULL,

                ClosingChangePercent DECIMAL(12, 4) NULL,
                ClosingChange BIGINT NULL,
                ClosingPrice BIGINT NULL,

                LastChangePercent DECIMAL(12, 4) NULL,
                LastChange BIGINT NULL,
                LastPrice BIGINT NULL,

                FirstPrice BIGINT NULL,
                YesterdayPrice BIGINT NULL,

                TradeValue DECIMAL(24, 0) NULL,
                Volume BIGINT NULL,
                TradeCount BIGINT NULL,

                Url VARCHAR(550),
                CollectedAt DATETIME2 NOT NULL
                    CONSTRAINT DF_{table_name}_CollectedAt
                    DEFAULT SYSUTCDATETIME(),

                CONSTRAINT
                    PK_{table_name}_Instrument_Date
                PRIMARY KEY (
                    InstrumentCode,
                    GregorianDate
                )
            );
        END
        """
    )


def upsert_price_history(
    cursor,
    table_name,
    company_name,
    symbol,
    instrument_code,
    detail_url,
    history_rows,
):
    table_name = safe_sql_identifier(
        table_name
    )

    if not instrument_code:
        raise ValueError(
            "InstrumentCode is empty; "
            "detail URL must contain query parameter i."
        )

    company_id = generate_company_id(
        company_name
    )

    merge_sql = f"""
        MERGE dbo.[{table_name}] WITH (HOLDLOCK)
        AS target

        USING (
            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            )
        ) AS source (
            InstrumentCode,
            CompanyID,
            CompanyName,
            Symbol,
            GregorianDate,

            JalaliDate,
            HighPrice,
            LowPrice,
            ClosingChangePercent,

            ClosingChange,
            ClosingPrice,
            LastChangePercent,

            LastChange,
            LastPrice,
            FirstPrice,

            YesterdayPrice,
            TradeValue,
            Volume,
            TradeCount
        )

        ON (
            target.InstrumentCode
                = source.InstrumentCode
            AND target.GregorianDate
                = source.GregorianDate
        )

        WHEN MATCHED THEN
            UPDATE SET
                target.CompanyID
                    = source.CompanyID,
                target.CompanyName
                    = source.CompanyName,
                target.Symbol
                    = source.Symbol,
                target.JalaliDate
                    = source.JalaliDate,

                target.HighPrice
                    = source.HighPrice,
                target.LowPrice
                    = source.LowPrice,

                target.ClosingChangePercent
                    = source.ClosingChangePercent,
                target.ClosingChange
                    = source.ClosingChange,
                target.ClosingPrice
                    = source.ClosingPrice,

                target.LastChangePercent
                    = source.LastChangePercent,
                target.LastChange
                    = source.LastChange,
                target.LastPrice
                    = source.LastPrice,

                target.FirstPrice
                    = source.FirstPrice,
                target.YesterdayPrice
                    = source.YesterdayPrice,

                target.TradeValue
                    = source.TradeValue,
                target.Volume
                    = source.Volume,
                target.TradeCount
                    = source.TradeCount,

                target.Url = ?,
                target.CollectedAt
                    = SYSUTCDATETIME()

        WHEN NOT MATCHED THEN
            INSERT (
                InstrumentCode,
                CompanyID,
                CompanyName,
                Symbol,
                GregorianDate,

                JalaliDate,
                HighPrice,
                LowPrice,

                ClosingChangePercent,
                ClosingChange,
                ClosingPrice,

                LastChangePercent,
                LastChange,
                LastPrice,

                FirstPrice,
                YesterdayPrice,

                TradeValue,
                Volume,
                TradeCount,

                Url
            )
            VALUES (
                source.InstrumentCode,
                source.CompanyID,
                source.CompanyName,
                source.Symbol,
                source.GregorianDate,

                source.JalaliDate,
                source.HighPrice,
                source.LowPrice,

                source.ClosingChangePercent,
                source.ClosingChange,
                source.ClosingPrice,

                source.LastChangePercent,
                source.LastChange,
                source.LastPrice,

                source.FirstPrice,
                source.YesterdayPrice,

                source.TradeValue,
                source.Volume,
                source.TradeCount,

                ?
            );
    """

    for row in history_rows:
        cursor.execute(
            merge_sql,
            instrument_code,
            company_id,
            company_name,
            symbol,
            row["gregorian_date"],

            row["jalali_date"],
            row["high_price"],
            row["low_price"],
            row["closing_change_percent"],

            row["closing_change"],
            row["closing_price"],
            row["last_change_percent"],

            row["last_change"],
            row["last_price"],
            row["first_price"],

            row["yesterday_price"],
            row["trade_value"],
            row["volume"],
            row["trade_count"],

            detail_url,
            detail_url,
        )


def save_price_history_to_sql(
    company_name,
    symbol,
    instrument_code,
    detail_url,
    history_rows,
    table_name="MarketPriceHistory",
):
    if not history_rows:
        logging.warning(
            "⚠️ No price history to save for %s",
            company_name,
        )
        return 0

    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        ensure_price_history_table(
            cursor,
            table_name,
        )

        upsert_price_history(
            cursor=cursor,
            table_name=table_name,
            company_name=company_name,
            symbol=symbol,
            instrument_code=instrument_code,
            detail_url=detail_url,
            history_rows=history_rows,
        )

        connection.commit()

        logging.info(
            "✅ Saved/updated %s price rows for %s",
            len(history_rows),
            company_name,
        )

        return len(history_rows)

    except Exception:
        if connection:
            connection.rollback()

        logging.exception(
            "❌ SQL error while saving history for %s",
            company_name,
        )

        return 0

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


# --------------------- Combined Scraper ---------------------
def scrape_market_data_with_history(
    market_url,
    normalized_company_names,
    headless=False,
    max_history_pages=None,
    save_to_sql=True,
    history_table_name="MarketPriceHistory",
):
    """
    اطلاعات جاری + سابقه قیمت را برای شرکت‌های انتخاب‌شده جمع می‌کند.

    خروجی:
    [
        {
            company_name,
            symbol,
            pe_value,
            current_price,
            detail_url,
            instrument_code,
            history: [...]
        }
    ]
    """
    result = []

    with sync_playwright() as playwright:
        context = create_context(
            playwright,
            headless=headless,
        )

        market_page = context.new_page()
        detail_page = context.new_page()

        try:
            matched_rows = collect_market_rows(
                page=market_page,
                market_url=market_url,
                normalized_company_names=normalized_company_names,
            )

            for item in matched_rows:
                try:
                    history_rows = scrape_trade_history(
                        page=detail_page,
                        detail_url=item["detail_url"],
                        max_pages=max_history_pages,
                    )

                    result_item = {
                        **item,
                        "history": history_rows,
                    }

                    result.append(result_item)

                    if save_to_sql:
                        save_price_history_to_sql(
                            company_name=item["company_name"],
                            symbol=item["symbol"],
                            instrument_code=(
                                item["instrument_code"]
                            ),
                            detail_url=item["detail_url"],
                            history_rows=history_rows,
                            table_name=history_table_name,
                        )

                except Exception:
                    logging.exception(
                        "❌ Could not scrape price history "
                        "for %s",
                        item["company_name"],
                    )

        finally:
            context.close()

    return result


# --------------------- Example ---------------------
if __name__ == "__main__":
    MARKET_URL = (
        "http://old.tsetmc.com/Loader.aspx?ParTree=15131F#"
    )

    COMPANIES = [
        "رمپنا",
    ]

    # در اجرای اولیه می‌توان max_history_pages=1 گذاشت.
    # برای دریافت کل سابقه مقدار None استفاده شود.
    data = scrape_market_data_with_history(
        market_url=MARKET_URL,
        normalized_company_names=COMPANIES,
        headless=False,
        max_history_pages=None,
        save_to_sql=True,
        history_table_name="MarketPriceHistory",
    )

    for company in data:
        print(
            company["company_name"],
            company["pe_value"],
            company["current_price"],
            len(company["history"]),
        )
