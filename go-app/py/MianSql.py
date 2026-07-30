import os
import re
import hashlib
import logging
import sys
from pathlib import Path
from urllib.parse import urljoin

import pyodbc
import jdatetime
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


# مسیر Chromium خودت
CHROMIUM_BINARY = (
    r"C:\Users\aliheyd\AppData\Local\Chromium\Application\chrome.exe"
)

# پروفایل جدا برای Chromium، نه Chrome اصلی سیستم
CHROMIUM_PROFILE_DIR = (
    r"D:\rfa\Company-Financial\go-app\py\chromium-profile"
)


PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

INVISIBLE_CHARS_RE = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)

DATE_RE = re.compile(r"(?:13|14)\d{2}/\d{1,2}/\d{1,2}")


# --------------------- Helpers ---------------------
def generate_company_id(name):
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def normalize_text(text):
    if text is None:
        return ""

    text = str(text).translate(PERSIAN_ARABIC_DIGITS)
    text = INVISIBLE_CHARS_RE.sub("", text)

    return (
        text.strip()
        .replace("\xa0", " ")
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .replace("ۀ", "ه")
    )


def normalize_label(text):
    """
    متن عنوان ردیف را برای مقایسه پایدار می‌کند.
    تفاوت فاصله، نیم‌فاصله، پرانتز، خط تیره و حروف عربی نادیده گرفته می‌شود.
    """
    text = normalize_text(text).lower()
    text = text.replace("ؤ", "و").replace("إ", "ا").replace("أ", "ا")
    text = re.sub(r"[()\[\]{}:؛،,.%٪/\\ـ_\-–—]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def to_number(value):
    if value is None:
        return 0.0

    text = normalize_text(value)
    text = text.replace(",", "").replace("٬", "")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.strip()

    if text in {"", "-", "--", "---"}:
        return 0.0

    is_parenthesized_negative = bool(
        re.fullmatch(r"\(\s*[+-]?\d+(?:\.\d+)?\s*\)", text)
    )

    cleaned = re.sub(r"[^\d.\-+()]", "", text)

    if is_parenthesized_negative:
        cleaned = "-" + cleaned.strip("() +-")
    else:
        cleaned = cleaned.replace("(", "").replace(")", "")

    if cleaned in {"", "+", "-", "."}:
        return 0.0

    try:
        return float(cleaned)
    except ValueError:
        logging.warning("⚠️ Could not convert value to number: %r", value)
        return 0.0


def is_hidden_cell(tag):
    if tag is None:
        return False

    if tag.has_attr("hidden"):
        return True

    aria_hidden = normalize_text(tag.get("aria-hidden", "")).lower()
    if aria_hidden == "true":
        return True

    style = (tag.get("style") or "").replace(" ", "").lower()

    return (
        "display:none" in style
        or "visibility:hidden" in style
        or "opacity:0" in style
    )


def visible_direct_cells(row, cell_name="td"):
    if row is None:
        return []

    return [
        cell
        for cell in row.find_all(cell_name, recursive=False)
        if not is_hidden_cell(cell)
    ]


def expand_visible_cells(row, cell_name="td"):
    """
    سلول‌های قابل مشاهده را با لحاظ colspan توسعه می‌دهد تا اندیس سلول
    دقیقاً با اندیس ستون هدر یکسان باشد.
    """
    expanded = []

    for cell_tag in visible_direct_cells(row, cell_name):
        try:
            colspan = max(1, int(cell_tag.get("colspan", 1)))
        except (TypeError, ValueError):
            colspan = 1

        expanded.extend([cell_tag] * colspan)

    return expanded


def build_header_grid(table):
    """
    هدرهای rowspan/colspan را به یک ماتریس ستونی تبدیل می‌کند.
    ستون‌های hidden وارد ماتریس نمی‌شوند.
    """
    header_rows = table.select("thead tr")
    grid = []

    for row_index, tr in enumerate(header_rows):
        while len(grid) <= row_index:
            grid.append([])

        column_index = 0

        for th in visible_direct_cells(tr, "th"):
            while (
                column_index < len(grid[row_index])
                and grid[row_index][column_index] is not None
            ):
                column_index += 1

            text = normalize_text(th.get_text(" ", strip=True))

            try:
                colspan = max(1, int(th.get("colspan", 1)))
            except (TypeError, ValueError):
                colspan = 1

            try:
                rowspan = max(1, int(th.get("rowspan", 1)))
            except (TypeError, ValueError):
                rowspan = 1

            for target_row in range(row_index, row_index + rowspan):
                while len(grid) <= target_row:
                    grid.append([])

                required_length = column_index + colspan
                if len(grid[target_row]) < required_length:
                    grid[target_row].extend(
                        [None] * (required_length - len(grid[target_row]))
                    )

                for target_column in range(
                    column_index,
                    column_index + colspan,
                ):
                    grid[target_row][target_column] = text

            column_index += colspan

    return grid


def get_column_headers(table):
    grid = build_header_grid(table)
    if not grid:
        return []

    max_columns = max(len(row) for row in grid)
    columns = []

    for column_index in range(max_columns):
        parts = []

        for header_row in grid:
            if column_index >= len(header_row):
                continue

            value = header_row[column_index]
            if value and value not in parts:
                parts.append(value)

        columns.append(
            {
                "index": column_index,
                "parts": parts,
                "text": normalize_label(" ".join(parts)),
            }
        )

    return columns


def get_period_columns(table):
    """
    ستون‌های واقعی دوره را برمی‌گرداند و ستون «شرح»، «درصد تغییر» و
    ستون‌های hidden را حذف می‌کند.
    """
    columns = get_column_headers(table)
    period_columns = []

    for column in columns:
        text = column["text"]
        raw_text = " ".join(column["parts"])

        if column["index"] == 0 or text == "شرح":
            continue

        if "درصد تغییر" in text:
            continue

        if DATE_RE.search(normalize_text(raw_text)) or "دوره منتهی" in text:
            period_columns.append(column)

    # بعضی نسخه‌ها در هدر فقط وضعیت حسابرسی را نمایش می‌دهند.
    # در این حالت همه ستون‌های بین «شرح» و «درصد تغییر» دوره محسوب می‌شوند.
    if not period_columns:
        for column in columns:
            text = column["text"]

            if column["index"] == 0 or text == "شرح":
                continue

            if "درصد تغییر" in text:
                continue

            period_columns.append(column)

    period_columns.sort(key=lambda item: item["index"])
    return period_columns


def get_table_rows(table):
    rows = []

    for tr in table.select("tbody tr"):
        cells = expand_visible_cells(tr, "td")
        if not cells:
            continue

        title = normalize_label(cells[0].get_text(" ", strip=True))
        if not title:
            continue

        rows.append(
            {
                "title": title,
                "raw_title": normalize_text(cells[0].get_text(" ", strip=True)),
                "cells": cells,
                "tr": tr,
            }
        )

    return rows


def row_has_numeric_data(row, column_indexes=None):
    if row is None:
        return False

    cells = row["cells"]
    indexes = column_indexes or range(1, len(cells))

    for index in indexes:
        if index >= len(cells):
            continue

        text = normalize_text(cells[index].get_text(" ", strip=True))
        if re.search(r"[0-9۰-۹٠-٩]", text):
            return True

    return False


def find_row(
    rows,
    exact_titles=(),
    contains_all=(),
    excludes=(),
    column_indexes=None,
):
    exact_titles = {normalize_label(title) for title in exact_titles}
    contains_all = tuple(normalize_label(part) for part in contains_all)
    excludes = tuple(normalize_label(part) for part in excludes)

    exact_matches = []
    partial_matches = []

    for row in rows:
        title = row["title"]

        if any(excluded and excluded in title for excluded in excludes):
            continue

        if not row_has_numeric_data(row, column_indexes):
            continue

        if title in exact_titles:
            exact_matches.append(row)
            continue

        if contains_all and all(part in title for part in contains_all):
            partial_matches.append(row)

    if exact_matches:
        return exact_matches[0]

    if partial_matches:
        return partial_matches[0]

    return None


def value_from_row(row, column_index):
    if row is None or column_index is None:
        return 0.0

    cells = row["cells"]
    if column_index >= len(cells):
        return 0.0

    return to_number(cells[column_index].get_text(" ", strip=True))


def find_profit_loss_table(soup):
    """
    در صفحه‌هایی که چند جدول دارند، جدولی را انتخاب می‌کند که بیشترین
    نشانه‌های صورت سود و زیان را داشته باشد.
    """
    candidates = soup.select("table.rayanDynamicStatement")
    best_table = None
    best_score = -1

    required_markers = (
        "درآمدهای عملیاتی",
        "سود زیان ناخالص",
        "سود زیان عملیاتی",
        "سود زیان خالص",
        "سرمایه",
    )

    for table in candidates:
        table_text = normalize_label(table.get_text(" ", strip=True))
        score = sum(
            1
            for marker in required_markers
            if normalize_label(marker) in table_text
        )

        if score > best_score:
            best_score = score
            best_table = table

    if best_score < 2:
        return None

    return best_table


def extract_report_date_from_table(table):
    period_columns = get_period_columns(table)
    if not period_columns:
        return None

    first_header = " ".join(period_columns[0]["parts"])
    match = DATE_RE.search(normalize_text(first_header))
    return match.group(0) if match else None


def extract_profit_loss_values(table):
    """
    خروجی سازگار با ساختار فعلی SQL:

    Num1 = سود/زیان خالص هر سهم - ریال
    Num2 = سرمایه
    Num4 = سود/زیان عملیاتی هر سهم - ریال
    Product = Num1 * Num2

    Value1/2/3 به ترتیب سه ستون دوره‌ای قابل مشاهده جدول هستند.

    OperatingProfitNew = سود/زیان عملیاتی دوره جاری
    OperatingProfitLastYear = سود/زیان عملیاتی دوره مقایسه‌ای سال قبل
    """
    period_columns = get_period_columns(table)

    # if len(period_columns) < 3:
    #     logging.warning(
    #         "⚠️ Expected at least 3 period columns, found %s: %s",
    #         len(period_columns),
    #         [column["parts"] for column in period_columns],
    #     )
    #     return None
    if len(period_columns) < 2:
        logging.warning(
            "⚠️ Expected at least 2 period columns, found %s: %s",
            len(period_columns),
            [column["parts"] for column in period_columns],
        )
        return None

    # period_columns = period_columns[:3]
    # فقط سه دوره اصلی ذخیره می‌شوند؛ ستون درصد تغییر قبلاً حذف شده است.
    period_columns = period_columns[:3]
    period_indexes = [column["index"] for column in period_columns]

    rows = get_table_rows(table)

    net_eps_row = find_row(
        rows,
        exact_titles=(
            "سود (زیان) خالص هر سهم - ریال",
            "سود (زیان) خالص هر سهم– ریال",
            "سود زیان خالص هر سهم ریال",
        ),
        contains_all=("سود", "زیان", "خالص", "هر سهم", "ریال"),
        excludes=("درصد",),
        column_indexes=period_indexes,
    )

    # در برخی گزارش‌ها ردیف «خالص هر سهم» وجود ندارد؛ ردیف پایه fallback است.
    if net_eps_row is None:
        net_eps_row = find_row(
            rows,
            exact_titles=("سود (زیان) پایه هر سهم",),
            contains_all=("سود", "زیان", "پایه", "هر سهم"),
            column_indexes=period_indexes,
        )

    capital_row = find_row(
        rows,
        exact_titles=("سرمایه",),
        contains_all=("سرمایه",),
        excludes=("افزایش", "کاهش"),
        column_indexes=period_indexes,
    )

    operating_eps_row = find_row(
        rows,
        exact_titles=("عملیاتی (ریال)", "عملیاتی ریال"),
        contains_all=("عملیاتی", "ریال"),
        excludes=("غیرعملیاتی", "سود", "زیان"),
        column_indexes=period_indexes,
    )

    operating_profit_row = find_row(
        rows,
        exact_titles=("سود (زیان) عملیاتی", "سود(زیان) عملیاتی"),
        contains_all=("سود", "زیان", "عملیاتی"),
        excludes=(
            "هر سهم",
            "قبل از مالیات",
            "در حال تداوم",
            "متوقف شده",
            "غیرعملیاتی",
        ),
        column_indexes=period_indexes,
    )

    # ردیف «درآمدهای عملیاتی» برای محاسبه حاشیه سود عملیاتی (اختیاری)
    revenue_row = find_row(
        rows,
        exact_titles=("درآمدهای عملیاتی",),
        contains_all=("درآمد", "عملیاتی"),
        excludes=(
            "بهای تمام شده",
            "تامین",
            "هر سهم",
            "سایر",
            "هزینه",
        ),
        column_indexes=period_indexes,
    )

    # ردیف‌های «غیرعملیاتی» (اختیاری — اگه نباشند، fetch شکست نمی‌خوره)
    finance_costs_row = find_row(
        rows,
        exact_titles=("هزینه مالی", "هزینه\u200cهای مالی", "هزینه های مالی"),
        contains_all=("هزینه", "مالی"),
        excludes=(
            "مالیات",
            "فروش",
            "کاهش",
            "سایر",
        ),
        column_indexes=period_indexes,
    )

    other_non_op_row = find_row(
        rows,
        exact_titles=(
            "سایر درآمدها و هزینه\u200cهای غیرعملیاتی",
            "سایر درآمدها و هزینه های غیرعملیاتی",
        ),
        contains_all=("سایر", "غیرعملیاتی"),
        excludes=("هر سهم", "ریال"),
        column_indexes=period_indexes,
    )

    # در گزارش‌های کشاورزی/دامداری، ردیف «سود/زیان فروش دارایی زیستی مولد»
    # به‌صورت جداگانه ذکر می‌شود و جزء درآمدهای غیرعملیاتی است.
    biological_asset_sale_row = find_row(
        rows,
        exact_titles=(
            "سود (زیان) فروش دارایی زیستی مولد",
            "سود زیان فروش دارایی زیستی مولد",
            "سود (زیان) فروش دارایی\u200cهای زیستی مولد",
        ),
        contains_all=("فروش", "دارایی", "زیستی"),
        column_indexes=period_indexes,
    )

    missing = []
    if net_eps_row is None:
        missing.append("net EPS")
    if capital_row is None:
        missing.append("capital")
    if operating_eps_row is None:
        missing.append("operating EPS")
    if operating_profit_row is None:
        missing.append("operating profit")

    if missing:
        logging.warning(
            "⚠️ Required profit/loss rows not found: %s. Available rows: %s",
            ", ".join(missing),
            [row["raw_title"] for row in rows],
        )
        return None

    period_values = []

    for column in period_columns:
        index = column["index"]
        net_eps = value_from_row(net_eps_row, index)
        capital = value_from_row(capital_row, index)
        operating_eps = value_from_row(operating_eps_row, index)

        period_values.extend(
            (
                net_eps,
                capital,
                operating_eps,
                net_eps * capital,
            )
        )
    
    # INSERT همیشه ۱۲ مقدار می‌خواهد:
    # سه دوره × چهار مقدار
    #
    # اگر دوره سوم در گزارش وجود نداشت، مقادیر آن باید NULL باشند.
    # از صفر استفاده نمی‌کنیم، چون صفر ممکن است داده مالی واقعی باشد.
    while len(period_values) < 12:
        period_values.extend((None, None, None, None))

    operating_profit_new = value_from_row(
        operating_profit_row,
        period_columns[0]["index"],
    )
    operating_profit_last_year = value_from_row(
        operating_profit_row,
        period_columns[1]["index"],
    )

    # مقادیر ردیف‌های غیرعملیاتی (اگر موجود نباشند، صفر درج می‌شود)
    finance_costs_new = value_from_row(
        finance_costs_row,
        period_columns[0]["index"],
    )
    finance_costs_last_year = value_from_row(
        finance_costs_row,
        period_columns[1]["index"],
    )

    other_non_op_new = value_from_row(
        other_non_op_row,
        period_columns[0]["index"],
    )
    other_non_op_last_year = value_from_row(
        other_non_op_row,
        period_columns[1]["index"],
    )

    # افزودن سود/زیان فروش دارایی زیستی مولد به درآمد غیرعملیاتی
    # (در گزارش‌های کشاورزی/دامداری به‌صورت ردیف جداگانه ذکر می‌شود)
    bio_sale_new = value_from_row(
        biological_asset_sale_row,
        period_columns[0]["index"],
    )
    bio_sale_last_year = value_from_row(
        biological_asset_sale_row,
        period_columns[1]["index"],
    )

    if biological_asset_sale_row is not None:
        other_non_op_new = other_non_op_new + bio_sale_new
        other_non_op_last_year = other_non_op_last_year + bio_sale_last_year

    # مقادیر ردیف «درآمدهای عملیاتی» (اگر موجود نباشد، NULL ذخیره می‌شود)
    if revenue_row is not None:
        revenue_new = value_from_row(
            revenue_row,
            period_columns[0]["index"],
        )
        revenue_last_year = value_from_row(
            revenue_row,
            period_columns[1]["index"],
        )
    else:
        revenue_new = None
        revenue_last_year = None

    result = {
        "period_headers": [column["parts"] for column in period_columns],
        "values_to_insert": tuple(period_values),
        "operating_profit_new": operating_profit_new,
        "operating_profit_last_year": operating_profit_last_year,
        "finance_costs_new": finance_costs_new,
        "finance_costs_last_year": finance_costs_last_year,
        "other_non_op_new": other_non_op_new,
        "other_non_op_last_year": other_non_op_last_year,
        "revenue_new": revenue_new,
        "revenue_last_year": revenue_last_year,
        "matched_rows": {
            "net_eps": net_eps_row["raw_title"],
            "capital": capital_row["raw_title"],
            "operating_eps": operating_eps_row["raw_title"],
            "operating_profit": operating_profit_row["raw_title"],
            "revenue": (
                revenue_row["raw_title"] if revenue_row else None
            ),
            "finance_costs": (
                finance_costs_row["raw_title"] if finance_costs_row else None
            ),
            "other_non_op": (
                other_non_op_row["raw_title"] if other_non_op_row else None
            ),
            "biological_asset_sale": (
                biological_asset_sale_row["raw_title"]
                if biological_asset_sale_row
                else None
            ),
        },
    }

    logging.info("✅ Profit/loss period columns: %s", result["period_headers"])
    logging.info("✅ Matched profit/loss rows: %s", result["matched_rows"])
    logging.info(
        "✅ Operating profit: current=%s, prior=%s",
        operating_profit_new,
        operating_profit_last_year,
    )
    logging.info(
        "✅ Finance costs: current=%s, prior=%s | Other non-op: current=%s, prior=%s",
        finance_costs_new,
        finance_costs_last_year,
        other_non_op_new,
        other_non_op_last_year,
    )
    logging.info(
        "✅ Revenue: current=%s, prior=%s",
        revenue_new,
        revenue_last_year,
    )

    return result


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

    cursor.execute(
        f"""
        IF OBJECT_ID(N'dbo.{table_name}', N'U') IS NULL
        CREATE TABLE dbo.[{table_name}] (
            CompanyID NVARCHAR(50) NOT NULL,
            CompanyName NVARCHAR(50),
            ReportDate NVARCHAR(50) NOT NULL,

            Num1_Value1 FLOAT,
            Num2_Value1 FLOAT,
            Num4_Value1 FLOAT,
            Product1 FLOAT,

            Num1_Value2 FLOAT,
            Num2_Value2 FLOAT,
            Num4_Value2 FLOAT,
            Product2 FLOAT,

            Num1_Value3 FLOAT,
            Num2_Value3 FLOAT,
            Num4_Value3 FLOAT,
            Product3 FLOAT,

            OperatingProfitNew FLOAT,
            OperatingProfitLastYear FLOAT,

            FinanceCostsNew FLOAT,
            FinanceCostsLastYear FLOAT,
            OtherNonOpNew FLOAT,
            OtherNonOpLastYear FLOAT,

            RevenueNew FLOAT,
            RevenueLastYear FLOAT,

            Url VARCHAR(550),

            CONSTRAINT PK_{table_name}_Company_ReportDate
                PRIMARY KEY (CompanyID, ReportDate)
        )
        """
    )

    for col in ("OperatingProfitNew", "OperatingProfitLastYear",
                "FinanceCostsNew", "FinanceCostsLastYear",
                "OtherNonOpNew", "OtherNonOpLastYear",
                "RevenueNew", "RevenueLastYear"):
        cursor.execute(
            f"""
            IF COL_LENGTH('dbo.{table_name}', '{col}') IS NULL
            ALTER TABLE dbo.[{table_name}]
            ADD {col} FLOAT NULL
            """
        )


def wait_for_angular_stable(page, timeout=15000):
    try:
        page.wait_for_function(
            """
            () => {
                if (!window.getAllAngularTestabilities) return true;
                return window.getAllAngularTestabilities().every(t => t.isStable());
            }
            """,
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        logging.warning("⚠️ Angular stability wait timed out; continuing anyway.")


def create_context(playwright):
    validate_config()

    Path(CHROMIUM_PROFILE_DIR).mkdir(parents=True, exist_ok=True)

    return playwright.chromium.launch_persistent_context(
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


def get_report_links(page, row_meta):
    report_links = []

    page.wait_for_selector("tbody.scrollContent tr", timeout=20000)
    rows = page.locator("tbody.scrollContent tr")
    row_count = rows.count()

    for index in range(min(row_count, row_meta)):
        row = rows.nth(index)
        link = row.locator("td:nth-child(4) a")

        try:
            if link.count() == 0:
                continue

            href = link.first.get_attribute("href")
            if href:
                report_links.append(urljoin("https://www.codal.ir", href))
        except Exception:
            continue

    return report_links


def page_contains_profit_loss_table(page):
    try:
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        return find_profit_loss_table(soup) is not None
    except Exception:
        return False


def ensure_profit_loss_selected(page):
    """
    جدول «صورت سود و زیان» را انتخاب می‌کند.
    اگر selectbox در نسخه جدید وجود نداشته باشد ولی جدول درست نمایش داده شده
    باشد، پردازش متوقف نمی‌شود.
    """
    if page_contains_profit_loss_table(page):
        logging.info("✅ Profit/loss table is already visible.")
        return True

    selectors = (
        "select#ctl00_ddlTable",
        "select#ddlTable",
        "select[name*='ddlTable']",
        "select[id*='ddlTable']",
    )

    select_locator = None

    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() > 0:
                select_locator = locator.first
                select_locator.wait_for(state="attached", timeout=3000)
                logging.info("✅ Found report selectbox: %s", selector)
                break
        except PlaywrightTimeoutError:
            continue

    # fallback: هر select که option صورت سود و زیان داشته باشد
    if select_locator is None:
        all_selects = page.locator("select")
        for index in range(all_selects.count()):
            candidate = all_selects.nth(index)
            option_texts = []

            try:
                options = candidate.locator("option")
                for option_index in range(options.count()):
                    option_texts.append(
                        normalize_label(options.nth(option_index).inner_text())
                    )
            except Exception:
                continue

            if normalize_label("صورت سود و زیان") in option_texts:
                select_locator = candidate
                break

    if select_locator is None:
        raise RuntimeError("Profit/loss selectbox was not found")

    target_value = None
    selected_text = ""

    try:
        selected_text = normalize_label(
            select_locator.locator("option:checked").inner_text(timeout=3000)
        )
    except Exception:
        pass

    if selected_text in {
        normalize_label("صورت سود و زیان"),
        normalize_label("صورت سود و زیان تلفیقی"),
    }:
        logging.info("✅ Selectbox already points to a profit/loss table.")
        return True

    options = select_locator.locator("option")

    for index in range(options.count()):
        option = options.nth(index)
        option_text = normalize_label(option.inner_text())

        if option_text == normalize_label("صورت سود و زیان"):
            target_value = option.get_attribute("value")
            break

    if target_value is None:
        raise RuntimeError("Option 'صورت سود و زیان' was not found")

    select_locator.select_option(value=target_value, timeout=10000)
    page.wait_for_timeout(2500)
    wait_for_angular_stable(page)
    page.wait_for_selector("table.rayanDynamicStatement", timeout=15000)

    if not page_contains_profit_loss_table(page):
        raise RuntimeError("Selected table is not recognized as profit/loss")

    logging.info("🔁 Changed report table to 'صورت سود و زیان'")
    return True


def read_report_date(page, table):
    selectors = (
        "#ctl00_lblPeriodEndToDate",
        "#lblPeriodEndToDate",
        "[id*='lblPeriodEndToDate']",
    )

    for selector in selectors:
        locator = page.locator(selector)
        try:
            if locator.count() == 0:
                continue

            text = normalize_text(locator.first.inner_text(timeout=3000))
            match = DATE_RE.search(text)
            if match:
                return match.group(0)
        except Exception:
            continue

    return extract_report_date_from_table(table)


def save_profit_loss_to_sql(
    company_name,
    report_date,
    values_to_insert,
    operating_profit_new,
    operating_profit_last_year,
    base_url,
    table_name,
    finance_costs_new=None,
    finance_costs_last_year=None,
    other_non_op_new=None,
    other_non_op_last_year=None,
    revenue_new=None,
    revenue_last_year=None,
):
    table_name = safe_sql_identifier(table_name)

    if len(values_to_insert) != 12:
        logging.warning(
            "⚠️ Expected 12 calculated values, got %s: %s",
            len(values_to_insert),
            values_to_insert,
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
            report_date,
        )

        exists = cursor.fetchone()[0]

        if exists:
            # رکورد موجود است — ستون‌های جدید را آپدیت کن (اگر NULL باشند)
            cursor.execute(
                f"""
                UPDATE dbo.[{table_name}]
                SET
                    FinanceCostsNew     = COALESCE(FinanceCostsNew, ?),
                    FinanceCostsLastYear = COALESCE(FinanceCostsLastYear, ?),
                    OtherNonOpNew       = COALESCE(OtherNonOpNew, ?),
                    OtherNonOpLastYear  = COALESCE(OtherNonOpLastYear, ?),
                    RevenueNew          = COALESCE(RevenueNew, ?),
                    RevenueLastYear     = COALESCE(RevenueLastYear, ?)
                WHERE CompanyID = ? AND ReportDate = ?
                """,
                finance_costs_new,
                finance_costs_last_year,
                other_non_op_new,
                other_non_op_last_year,
                revenue_new,
                revenue_last_year,
                company_id,
                report_date,
            )
            conn.commit()
            logging.info("🔄 Updated missing columns: %s - %s", company_name, report_date)
            return True

        cursor.execute(
            f"""
            INSERT INTO dbo.[{table_name}] (
                CompanyID,
                CompanyName,
                ReportDate,

                Num1_Value1,
                Num2_Value1,
                Num4_Value1,
                Product1,

                Num1_Value2,
                Num2_Value2,
                Num4_Value2,
                Product2,

                Num1_Value3,
                Num2_Value3,
                Num4_Value3,
                Product3,

                OperatingProfitNew,
                OperatingProfitLastYear,

                FinanceCostsNew,
                FinanceCostsLastYear,
                OtherNonOpNew,
                OtherNonOpLastYear,

                RevenueNew,
                RevenueLastYear,

                Url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            company_id,
            company_name,
            report_date,
            *values_to_insert,
            operating_profit_new,
            operating_profit_last_year,
            finance_costs_new,
            finance_costs_last_year,
            other_non_op_new,
            other_non_op_last_year,
            revenue_new,
            revenue_last_year,
            base_url,
        )

        conn.commit()
        logging.info("✅ Saved: %s - %s", company_name, report_date)
        return True

    except Exception as exc:
        logging.exception(
            "❌ SQL error for %s - %s: %s",
            company_name,
            report_date,
            exc,
        )
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def scrape_report(page, link, company_name, base_url, table_name):
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    logging.info("🔍 Scraping report: %s", link)

    try:
        ensure_profit_loss_selected(page)
    except Exception as exc:
        logging.warning(
            "⚠️ Could not change/select profit-loss table: %s",
            exc,
        )
        return False

    wait_for_angular_stable(page)

    try:
        page.wait_for_selector("table.rayanDynamicStatement", timeout=15000)
    except PlaywrightTimeoutError:
        logging.warning("⚠️ rayanDynamicStatement table not found.")
        return False

    page.wait_for_timeout(1000)

    soup = BeautifulSoup(page.content(), "html.parser")
    table = find_profit_loss_table(soup)

    if table is None:
        logging.warning("⚠️ Profit/loss table was not found in page content.")
        return False

    report_date = read_report_date(page, table)
    if not report_date:
        logging.warning("⚠️ Could not read report date.")
        return False

    try:
        report_jdate = jdatetime.datetime.strptime(
            report_date,
            "%Y/%m/%d",
        ).date()
        min_date = jdatetime.date(1397, 12, 29)

        if report_jdate <= min_date:
            logging.info("⏩ Skipping old report: %s", report_date)
            return False
    except Exception as exc:
        logging.warning(
            "⚠️ Could not parse report date %r: %s",
            report_date,
            exc,
        )
        return False

    extracted = extract_profit_loss_values(table)
    if extracted is None:
        return False

    return save_profit_loss_to_sql(
        company_name=company_name,
        report_date=report_date,
        values_to_insert=extracted["values_to_insert"],
        operating_profit_new=extracted["operating_profit_new"],
        operating_profit_last_year=extracted["operating_profit_last_year"],
        base_url=base_url,
        table_name=table_name,
        finance_costs_new=extracted.get("finance_costs_new"),
        finance_costs_last_year=extracted.get("finance_costs_last_year"),
        other_non_op_new=extracted.get("other_non_op_new"),
        other_non_op_last_year=extracted.get("other_non_op_last_year"),
        revenue_new=extracted.get("revenue_new"),
        revenue_last_year=extracted.get("revenue_last_year"),
    )


# --------------------- Main Function ---------------------
def main_scraper(companyName, rowMeta, base_url, page_numbers, table_name):
    base_url = base_url.replace("&PageNumber=1", "")
    inserted_any = False

    with sync_playwright() as playwright:
        context = create_context(playwright)
        page = context.new_page()

        try:
            for page_number in page_numbers:
                current_url = f"{base_url}&PageNumber={page_number}"

                logging.info(
                    "🌐 Fetching data from page %s: %s",
                    page_number,
                    current_url,
                )

                try:
                    page.goto(
                        current_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    page.wait_for_selector(
                        "tbody.scrollContent tr",
                        timeout=20000,
                    )
                    page.wait_for_timeout(5000)

                except PlaywrightTimeoutError:
                    logging.warning(
                        "⚠️ Table did not load on page %s. Skipping...",
                        page_number,
                    )
                    continue

                except Exception as exc:
                    logging.warning(
                        "⚠️ Could not open page %s: %s",
                        page_number,
                        exc,
                    )
                    continue

                try:
                    report_links = get_report_links(page, rowMeta)
                    logging.info(
                        "✅ Found %s report links on page %s",
                        len(report_links),
                        page_number,
                    )
                except Exception as exc:
                    logging.warning(
                        "⚠️ Could not extract report links from page %s: %s",
                        page_number,
                        exc,
                    )
                    continue

                for link in report_links:
                    try:
                        saved = scrape_report(
                            page=page,
                            link=link,
                            company_name=companyName,
                            base_url=base_url,
                            table_name=table_name,
                        )

                        if saved:
                            inserted_any = True

                    except Exception as exc:
                        logging.exception(
                            "❌ Error scraping report %s: %s",
                            link,
                            exc,
                        )
                        continue

        finally:
            context.close()

    if inserted_any:
        print(f"{companyName} scraping and saving successful")
    else:
        print(f"{companyName} finished but no new data saved")

    return inserted_any
