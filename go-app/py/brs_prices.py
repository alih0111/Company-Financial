"""
BRS API Price Collector
======================================================================
جمع‌آوری قیمت روزانه و تاریخچه‌ی بازار از وب‌سرویس BRS (مبتنی بر TSETMC)
و ذخیره در جدول dbo.MarketPriceHistory.

دو حالت اجرا:

    python py/brs_prices.py daily
        یک درخواست AllSymbols.php → قیمت روزانه کل بازار را در یک بار
        دریافت و در دیتابیس upsert می‌کند. مناسب اجرای روزانه پس از
        پایان معاملات (cron / Task Scheduler).

    python py/brs_prices.py backfill [--limit N] [--symbol فملی]
        برای نمادهای تطبیق‌یافته، تاریخچه‌ی روزانه‌ی تعدیل‌شده را از
        Candelstick.php?type=3 می‌گیرد و ذخیره می‌کند. مناسب برای
        پر کردن سابقه‌ی اولیه.

تطبیق نماد:
    جدول‌های codal (mahane / miandore2) فقط CompanyName دارند و نماد
    ذخیره نمی‌کنند، در حالی که BRS نماد (l18) و نام شرکت (l30) را
    می‌دهد. بنابراین تطبیق بر اساس نام شرکت انجام می‌شود:
        1) فایل override  py/symbol_override.json  (بالاترین اولویت)
        2) تطبیق دقیق نام نرمال‌شده
        3) تطبیق از روی نمادی که قبلاً در MarketPriceHistory ثبت شده
        4) تطبیق فازی بر اساس شباهت توکن‌ها (آستانه‌ی ۰.۸)

متغیرهای محیطی (در go-app/.env):
    DB_SERVER, DB_NAME, DB_USER, DB_PASSWORD, BRS_API_KEY
======================================================================
"""

import argparse
import hashlib
import json
import logging
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import pyodbc
except ImportError:
    pyodbc = None

from dotenv import load_dotenv


# رفع مشکل encoding ویندوز (cp1252): کنسول نمی‌تواند فارسی/ایموجی چاپ کند
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# --------------------- Logging ---------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("brs_prices")


# --------------------- Environment ---------------------
SCRIPT_DIR = Path(__file__).resolve().parent
# ابتدا .env کنار اسکریپت، سپس .env دایرکتوری بالاتر (go-app/.env)
load_dotenv(SCRIPT_DIR / ".env")
load_dotenv(SCRIPT_DIR.parent / ".env")
load_dotenv()

SERVER = os.getenv("DB_SERVER")
DATABASE = os.getenv("DB_NAME")
USERNAME = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASSWORD")
API_KEY = os.getenv("BRS_API_KEY", "").strip()

API_BASE = "https://Api.BrsApi.ir/Tsetmc"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 60

PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

# کلمات/پسوندهای عمومی شرکت که برای تطبیق فازی حذف می‌شوند
# (فقط مواردی که با حذفشان ریسک ادغام دو شرکت مجاور ایجاد نمی‌شود)
COMPANY_STOPWORDS = {"شرکت", "سهامی", "عام", "خاص"}


# --------------------- Text helpers ---------------------
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


def to_int(value):
    """تبدیل به int بدون از دست دادن دقت اعداد بزرگ (ارزش معاملات)."""
    if value is None or value == "":
        return None
    text = normalize_numeric_text(value)
    if not text or text in {"-", "--"}:
        return None
    is_negative = text.startswith("-") or (
        text.startswith("(") and text.endswith(")")
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
    return int(number)


def safe_sql_identifier(name):
    table_name = str(name)
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table_name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return table_name


def is_md5(value):
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", value or ""))


# --------------------- Date conversion ---------------------
def jalali_to_gregorian(jy, jm, jd):
    """تبدیل تاریخ جلالی به میلادی (پورت از full_run_scripts.go)."""
    jy += 1595
    days = -355668 + 365 * jy + jy // 33 * 8 + (jy % 33 + 3) // 4 + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += (jm - 7) * 30 + 186

    gy = 400 * (days // 146097)
    days %= 146097
    leap = True
    if days > 36524:
        gy += 100 * ((days - 1) // 36524)
        days = (days - 1) % 36524
        if days >= 365:
            days += 1
        else:
            leap = False

    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
        leap = False

    sal_a = (
        [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366]
        if leap
        else [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]
    )

    gm = 0
    gd = 0
    for i in range(12):
        if days < sal_a[i + 1]:
            gd = days - sal_a[i] + 1
            gm = i + 1
            break
    return gy, gm, gd


def gregorian_to_jalali(gy, gm, gd):
    """
    تبدیل میلادی به جلالی با جستجو روی نام سالِ تقریبی، با استفاده از
    تابع معکوسِ اثبات‌شده‌ی jalali_to_gregorian. حداکثر ~۳۶ تلاش.
    """
    approx_jy = gy - 621
    for jy in (approx_jy - 1, approx_jy, approx_jy + 1):
        for jm in range(1, 13):
            max_day = 30 if jm > 6 else 31
            for jd in range(1, max_day + 1):
                yg, mg, dg = jalali_to_gregorian(jy, jm, jd)
                if (yg, mg, dg) == (gy, gm, gd):
                    return jy, jm, jd
    raise ValueError(f"Cannot convert gregorian {gy}-{gm}-{gd} to jalali")


def parse_brs_date(raw):
    """
    تاریخ BRS را به (gregorian 'YYYY-MM-DD', jalali 'YYYY/MM/DD') تبدیل می‌کند.
    به‌صورت دفاعی هم فرمت میلادی و هم جلالی (با/بدون جداساز) را هندل می‌کند.
    """
    if raw is None or raw == "":
        return None, None

    digits = re.sub(r"\D", "", normalize_numeric_text(raw))

    # ممکن است تاریخ+زمان باشد؛ فقط ۸ رقم اول کافی است
    if len(digits) >= 8:
        digits = digits[:8]

    if len(digits) != 8:
        return None, None

    y = int(digits[0:4])
    m = int(digits[4:6])
    d = int(digits[6:8])

    try:
        if y > 1500:
            # میلادی
            gy, gm, gd = y, m, d
            jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
        elif 1300 <= y <= 1500:
            # جلالی
            jy, jm, jd = y, m, d
            gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        else:
            return None, None
    except (ValueError, OverflowError):
        return None, None

    if not (1 <= gm <= 12 and 1 <= gd <= 31 and 1 <= jm <= 12 and 1 <= jd <= 31):
        return None, None

    return f"{gy:04d}-{gm:02d}-{gd:02d}", f"{jy:04d}/{jm:02d}/{jd:02d}"


# --------------------- HTTP ---------------------
def http_get_json(url, params=None):
    full_url = url
    if params:
        from urllib.parse import urlencode

        full_url = f"{url}?{urlencode(params)}"

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
        },
    )

    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {full_url}: {exc}; head={raw[:200]}")


def fetch_all_symbols():
    """دریافت اطلاعات لحظه‌ای همه‌ی نمادها در یک درخواست."""
    return http_get_json(f"{API_BASE}/AllSymbols.php", {"key": API_KEY})


def fetch_history(l18, ctype=0):
    """
    دریافت تاریخچه‌ی روزانه‌ی یک نماد از History.php.
    خروجی: لیستی از آبجکت‌ها با فیلدهای مشابه AllSymbols
    (date, time, pmin, pmax, py, pf, pl, pc, plc, plp, pcc, pcp, tno, tvol, tval).

    نکته: آزمایش نشان داد type=0 و type=1 هر دو تعدیل‌نشده برمی‌گردانند،
    بنابراین برای داده‌ی واقعاً تعدیل‌شده از fetch_candlestick استفاده کنید.

    type:
        0 = ادعای تعدیل‌شده (در عمل تعدیل‌نشده)
        1 = تعدیل‌نشده
    """
    return http_get_json(
        f"{API_BASE}/History.php",
        {"key": API_KEY, "type": ctype, "l18": l18},
    )


def fetch_candlestick(l18, ctype=3):
    """
    دریافت تاریخچه‌ی روزانه‌ی تعدیل‌شده‌ی یک نماد از Candlestick.php.
    این تنها منبع برای داده‌ی واقعاً تعدیل‌شده است (نیازمند اشتراک).

    خروجی: dict شامل کلید candle_daily_adjusted (وقتی type=3) با لیستی از
    {date: "1404-02-24", open, high, low, close, volume}.

    type:
        1 = لحظه‌ای روز جاری (۲ دقیقه‌ای)
        2 = روزانه تعدیل‌نشده
        3 = روزانه تعدیل‌شده  ← برای backfill
    """
    return http_get_json(
        f"{API_BASE}/Candlestick.php",
        {"key": API_KEY, "type": ctype, "l18": l18},
    )


# --------------------- DB ---------------------
def validate_env():
    missing = []
    if not SERVER:
        missing.append("DB_SERVER")
    if not DATABASE:
        missing.append("DB_NAME")
    if not USERNAME:
        missing.append("DB_USER")
    if not PASSWORD:
        missing.append("DB_PASSWORD")
    if not API_KEY:
        missing.append("BRS_API_KEY")
    if missing:
        raise RuntimeError("Missing env values: " + ", ".join(missing))


def get_db_connection():
    if pyodbc is None:
        raise RuntimeError(
            "pyodbc is not installed. Install: pip install pyodbc"
        )
    connection_string = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(connection_string)


def ensure_price_history_table(cursor, table_name="MarketPriceHistory"):
    table_name = safe_sql_identifier(table_name)
    cursor.execute(
        f"""
        IF OBJECT_ID(N'dbo.{table_name}', N'U') IS NULL
        BEGIN
            CREATE TABLE dbo.[{table_name}] (
                InstrumentCode VARCHAR(30) NOT NULL,
                CompanyID NVARCHAR(50) NOT NULL,
                CompanyName NVARCHAR(200),
                Symbol NVARCHAR(50),
                BrsName NVARCHAR(200),

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

                CONSTRAINT PK_{table_name}_Instrument_Date
                PRIMARY KEY (InstrumentCode, GregorianDate)
            );
        END
        """
    )
    # افزودن ستون BrsName به جدول‌های موجود (idempotent)
    cursor.execute(
        f"""
        IF COL_LENGTH(N'dbo.{table_name}', N'BrsName') IS NULL
        ALTER TABLE dbo.[{table_name}] ADD BrsName NVARCHAR(200) NULL
        """
    )


# --------------------- Matching ---------------------
def tokens_for_match(name):
    """نرمال‌سازی نام شرکت برای تطبیق فازی و استخراج توکن‌ها."""
    text = normalize_persian(name)
    text = re.sub(r"[()\[\].،,؛;:\-_/\\]+", " ", text)
    toks = [t for t in text.split() if t and t not in COMPANY_STOPWORDS]
    return toks


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def load_name_maps(cursor):
    """
    ساخت نقشه‌ی تطبیق از روی داده‌ی موجود:
        name_index:   {normalized_name: CompanyID}
        token_index:  [(tokens, name, CompanyID), ...]
        symbol_index: {Symbol: CompanyID}  (از MarketPriceHistory)
        id_to_name:   {CompanyID: original_codal_name}  (نام اصلی، بدون تغییر)
    """
    name_index = {}
    id_to_name = {}
    token_index = []
    seen = set()

    for table in ("mahane", "miandore2"):
        try:
            cursor.execute(
                f"""
                SELECT DISTINCT CompanyName, CompanyID
                FROM dbo.{table}
                WHERE CompanyName IS NOT NULL
                  AND CompanyID IS NOT NULL
                """
            )
        except pyodbc.Error as exc:
            log.warning("⚠️ cannot read %s for name map: %s", table, exc)
            continue

        for cname, cid in cursor.fetchall():
            cid = str(cid)
            # نگه‌داشتن نام اصلی codal برای ذخیره در MarketPriceHistory
            if cid not in id_to_name and cname:
                id_to_name[cid] = cname

            norm = normalize_persian(cname)
            if not norm or cid in seen:
                continue
            seen.add(cid)
            name_index[norm] = cid
            toks = tokens_for_match(norm)
            if toks:
                token_index.append((toks, norm, cid))

    # نقشه‌ی نماد از MarketPriceHistory (تغذیه‌ی خودکار با گذشت زمان)
    try:
        cursor.execute(
            """
            SELECT Symbol, CompanyID
            FROM dbo.MarketPriceHistory
            WHERE Symbol IS NOT NULL AND CompanyID IS NOT NULL
            """
        )
        symbol_index = {
            normalize_persian(sym): str(cid)
            for sym, cid in cursor.fetchall()
            if sym
        }
    except pyodbc.Error:
        symbol_index = {}

    return name_index, token_index, symbol_index, id_to_name


def load_override():
    """بارگذاری فایل override: {symbol: company_id | company_name}."""
    path = SCRIPT_DIR / "symbol_override.json"
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("⚠️ cannot load override file %s: %s", path, exc)
        return {}

    if not isinstance(data, dict):
        return {}

    return {normalize_persian(k): v for k, v in data.items()}


def resolve_company_id(
    l18, l30, name_index, token_index, symbol_index, override
):
    """
    برگرداندن (CompanyID, how, best_candidate_info) برای یک نماد BRS.
    ترتیب: override → نام دقیق → نماد ذخیره‌شده → تطبیق محتوایی (containment)
           → تطبیق فازی (Jaccard >= 0.3).

    best_candidate_info همیشه پر می‌شود (برای عیب‌یابی نمادهای بدون تطبیق).
    """
    sym = normalize_persian(l18)
    name = normalize_persian(l30)
    best_info = {"score": 0.0, "name": "", "how": "none"}

    # 1) override
    if sym and sym in override:
        val = override[sym]
        if isinstance(val, str) and is_md5(val):
            return val, "override(id)", best_info
        if isinstance(val, str) and normalize_persian(val) in name_index:
            return name_index[normalize_persian(val)], "override(name)", best_info

    # 2) نام دقیق
    if name and name in name_index:
        return name_index[name], "exact-name", best_info

    # 2b) نماد BRS با نام codal برابر است (مثلاً نماد «خودرو» = نام codal «خودرو»)
    #     این قدرتمندترین تطبیق برای نمادهای ایرانی است.
    if sym and sym in name_index:
        return name_index[sym], "symbol-equals-name", best_info

    # 3) نماد ذخیره‌شده در MarketPriceHistory
    if sym and sym in symbol_index:
        return symbol_index[sym], "stored-symbol", best_info

    # 4 + 5) containment و fuzzy — در یک پاس روی token_index
    target_tokens = tokens_for_match(name) if name else []
    target_str = " ".join(target_tokens)

    if target_tokens:
        best_fuzzy = (0.0, None, None)
        for toks, cname, cid in token_index:
            cand_str = " ".join(toks)

            # 4) containment: یکی در دیگری محتواست — ولی فقط وقتی هر دو
            # طرف حداقل ۲ توکن دارند، تا کلمه‌ی تخصصی مشترک (مثل «فولاد»
            # یا «پارس») باعث وصل‌شدن اشتباه شرکت‌های مجزا نشود.
            if (
                len(target_tokens) >= 2
                and len(toks) >= 2
                and len(target_str) >= 5
                and len(cand_str) >= 5
                and (
                    target_str in cand_str or cand_str in target_str
                )
            ):
                return cid, f"containment({cname})", best_info

            # 5) fuzzy
            score = jaccard(target_tokens, toks)
            if score > best_fuzzy[0]:
                best_fuzzy = (score, cname, cid)

        if best_fuzzy[0] >= 0.75 and best_fuzzy[2]:
            best_info = {
                "score": round(best_fuzzy[0], 3),
                "name": best_fuzzy[1],
                "how": "fuzzy",
            }
            return best_fuzzy[2], f"fuzzy({best_fuzzy[0]:.2f}:{best_fuzzy[1]})", best_info

        # ذخیره بهترین کاندید برای عیب‌یابی
        if best_fuzzy[2]:
            best_info = {
                "score": round(best_fuzzy[0], 3),
                "name": best_fuzzy[1],
                "how": "below-threshold",
            }

    return None, None, best_info


# نام‌های ممکن فیلد تاریخ در پاسخ BRS (به ترتیب اولویت)
DATE_FIELDS = ("date", "Date", "date_update", "dt", "gdate", "d", "trade_date")
# نام‌های ممکن فیلد timestamp میلی‌ثانیه‌ای (TSETMC z)
TIMESTAMP_FIELDS = ("z", "Z", "timestamp", "ts", "utime")


def _first_present(item, fields):
    """اولین فیلد موجود و غیرخالی را برمی‌گرداند."""
    for f in fields:
        v = item.get(f)
        if v not in (None, "", []):
            return v
    return None


def parse_brs_timestamp(raw):
    """
    Unix timestamp (میلی‌ثانیه یا ثانیه) را به تاریخ تبدیل می‌کند.
    برمی‌گرداند: (gregorian 'YYYY-MM-DD', jalali 'YYYY/MM/DD') یا (None, None).

    نکته: TSETMC گاهی از epoch غیراستاندارد استفاده می‌کند؛ بنابراین فقط
    مقادیر معقول (بین سال‌های 2005 و 2099 میلادی) پذیرفته می‌شوند.
    """
    if raw is None or raw == "":
        return None, None

    digits = re.sub(r"\D", "", normalize_numeric_text(raw))
    if not digits:
        return None, None

    try:
        ts = float(digits)
    except ValueError:
        return None, None

    # تشخیص ثانیه در برابر میلی‌ثانیه
    if abs(ts) > 1e12:
        ts_seconds = ts / 1000.0
    elif abs(ts) > 1e9:
        ts_seconds = ts
    else:
        return None, None

    try:
        import time as _time

        t_struct = _time.gmtime(ts_seconds)
        gy, gm, gd = t_struct.tm_year, t_struct.tm_mon, t_struct.tm_mday
    except (ValueError, OverflowError, OSError):
        return None, None

    # محافظه‌کارانه: فقط تاریخ‌های منطقی (امروز یا کمی گذشته)
    import time as _time
    now_struct = _time.localtime()
    now_y = now_struct.tm_year
    # فقط سال‌های اخیر تا حداکثر امسال پذیرفته می‌شوند ( نه آینده)
    if not (2010 <= gy <= now_y and 1 <= gm <= 12 and 1 <= gd <= 31):
        return None, None

    try:
        jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
        if not (1 <= jm <= 12 and 1 <= jd <= 31):
            return None, None
    except (ValueError, OverflowError):
        return None, None

    return f"{gy:04d}-{gm:02d}-{gd:02d}", f"{jy:04d}/{jm:02d}/{jd:02d}"


def today_jalali():
    """تاریخ روز جاری را برمی‌گرداند: (gregorian, jalali)."""
    import time as _time

    t = _time.localtime()
    gy, gm, gd = t.tm_year, t.tm_mon, t.tm_mday
    jy, jm, jd = gregorian_to_jalali(gy, gm, gd)
    return (
        f"{gy:04d}-{gm:02d}-{gd:02d}",
        f"{jy:04d}/{jm:02d}/{jd:02d}",
    )


# --------------------- Row builders ---------------------
def build_daily_row(item, company_id, codal_name, brs_name):
    """
    ساخت ردیف روزانه.
        codal_name: نام اصلی شرکت از codal (دست‌نخورده)
        brs_name:   نام منبع BRS (در ستون جداگانه)
    """
    # اولویت ۱: timestamp (TSETMC از فیلد z استفاده می‌کند)
    raw_ts = _first_present(item, TIMESTAMP_FIELDS)
    gdate, jdate = parse_brs_timestamp(raw_ts)

    # اولویت ۲: فیلد تاریخ مستقیم
    if gdate is None:
        raw_date = _first_present(item, DATE_FIELDS)
        gdate, jdate = parse_brs_date(raw_date)

    # اولویت ۳: AllSymbols داده‌ی روز جاری است → تاریخ سیستم
    if gdate is None:
        gdate, jdate = today_jalali()

    pc = to_int(item.get("pc") or item.get("Price"))
    pl = to_int(item.get("pl") or item.get("LastPrice"))
    pf = to_int(item.get("pf") or item.get("FirstPrice"))
    pmin = to_int(item.get("pmin") or item.get("LowPrice"))
    pmax = to_int(item.get("pmax") or item.get("HighPrice"))
    py = to_int(item.get("py") or item.get("YesterdayPrice"))

    closing_change = (pc - py) if (pc is not None and py is not None) else None
    closing_change_percent = (
        ((pc - py) / py * 100.0) if (pc is not None and py not in (None, 0)) else None
    )
    last_change = (pl - py) if (pl is not None and py is not None) else None
    last_change_percent = (
        ((pl - py) / py * 100.0) if (pl is not None and py not in (None, 0)) else None
    )

    return {
        "instrument_code": str(
            item.get("id") or item.get("isin") or item.get("l18") or ""
        ),
        "company_id": company_id,
        "company_name": codal_name,
        "symbol": item.get("l18"),
        "brs_name": brs_name,
        "gregorian_date": gdate,
        "jalali_date": jdate,
        "high_price": pmax,
        "low_price": pmin,
        "closing_change_percent": closing_change_percent,
        "closing_change": closing_change,
        "closing_price": pc,
        "last_change_percent": last_change_percent,
        "last_change": last_change,
        "last_price": pl,
        "first_price": pf,
        "yesterday_price": py,
        "trade_value": to_int(item.get("tval")),
        "volume": to_int(item.get("tvol")),
        "trade_count": to_int(item.get("tno")),
    }


def build_history_row(candle, company_id, symbol, codal_name, brs_name):
    """
    ساخت ردیف تاریخچه از یک کندلِ Candlestick.php (type=3 تعدیل‌شده).
    ساختار: {date: "1404-02-24", open, high, low, close, volume}

    Candlestick فقط ۵ فیلد دارد؛ فیلدهای ناقص (TradeValue، TradeCount،
    YesterdayPrice و درصد تغییر) به‌صورت محلی از close محاسبه یا NULL می‌شوند.
    فیلدهای کامل روزانه از AllSymbols (در daily) تأمین می‌شوند.
    """
    gdate, jdate = parse_brs_date(candle.get("date"))
    if gdate is None:
        return None

    close = to_int(candle.get("close"))
    openp = to_int(candle.get("open"))
    high = to_int(candle.get("high"))
    low = to_int(candle.get("low"))
    volume = to_int(candle.get("volume"))

    # قیمت پایانی = آخرین قیمت (در داده‌ی روزانه)
    pc = close
    pl = close

    return {
        "instrument_code": None,  # در cmd_backfill از مچ‌شده پر می‌شود
        "company_id": company_id,
        "company_name": codal_name,
        "symbol": symbol,
        "brs_name": brs_name,
        "gregorian_date": gdate,
        "jalali_date": jdate,
        "high_price": high,
        "low_price": low,
        # Candlestick درصد تغییر مستقیم نمی‌دهد → در cmd_backfill از close دیروز محاسبه می‌شود
        "closing_change_percent": None,
        "closing_change": None,
        "closing_price": pc,
        "last_change_percent": None,
        "last_change": None,
        "last_price": pl,
        "first_price": openp,
        "yesterday_price": None,  # در cmd_backfill از close دیروز پر می‌شود
        "trade_value": None,      # فقط از AllSymbols روزانه
        "volume": volume,
        "trade_count": None,      # فقط از AllSymbols روزانه
    }


def to_float_safe(value):
    """تبدیل امن به float برای درصدها."""
    try:
        return float(normalize_numeric_text(value))
    except (ValueError, TypeError):
        return None


# --------------------- Upsert ---------------------
UPSERT_SQL = """
    MERGE dbo.[{table}] WITH (HOLDLOCK) AS target
    USING (
        VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?
        )
    ) AS source (
        InstrumentCode, CompanyID, CompanyName, Symbol, BrsName, GregorianDate, JalaliDate,
        HighPrice, LowPrice, ClosingChangePercent,
        ClosingChange, ClosingPrice, LastChangePercent,
        LastChange, LastPrice, FirstPrice,
        YesterdayPrice, TradeValue, Volume, TradeCount
    )
    ON (
        target.InstrumentCode = source.InstrumentCode
        AND target.GregorianDate = source.GregorianDate
    )
    WHEN MATCHED THEN
        UPDATE SET
            target.CompanyID = source.CompanyID,
            target.CompanyName = source.CompanyName,
            target.Symbol = source.Symbol,
            target.BrsName = source.BrsName,
            target.JalaliDate = source.JalaliDate,
            target.HighPrice = source.HighPrice,
            target.LowPrice = source.LowPrice,
            target.ClosingChangePercent = source.ClosingChangePercent,
            target.ClosingChange = source.ClosingChange,
            target.ClosingPrice = source.ClosingPrice,
            target.LastChangePercent = source.LastChangePercent,
            target.LastChange = source.LastChange,
            target.LastPrice = source.LastPrice,
            target.FirstPrice = source.FirstPrice,
            target.YesterdayPrice = source.YesterdayPrice,
            target.TradeValue = source.TradeValue,
            target.Volume = source.Volume,
            target.TradeCount = source.TradeCount,
            target.CollectedAt = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN
        INSERT (
            InstrumentCode, CompanyID, CompanyName, Symbol, BrsName, GregorianDate, JalaliDate,
            HighPrice, LowPrice, ClosingChangePercent,
            ClosingChange, ClosingPrice, LastChangePercent,
            LastChange, LastPrice, FirstPrice,
            YesterdayPrice, TradeValue, Volume, TradeCount
        )
        VALUES (
            source.InstrumentCode, source.CompanyID, source.CompanyName, source.Symbol, source.BrsName,
            source.GregorianDate, source.JalaliDate,
            source.HighPrice, source.LowPrice, source.ClosingChangePercent,
            source.ClosingChange, source.ClosingPrice, source.LastChangePercent,
            source.LastChange, source.LastPrice, source.FirstPrice,
            source.YesterdayPrice, source.TradeValue, source.Volume, source.TradeCount
        );
"""


def upsert_rows(cursor, rows, table_name="MarketPriceHistory"):
    sql = UPSERT_SQL.format(table=safe_sql_identifier(table_name))
    for row in rows:
        if not row.get("instrument_code") or not row.get("gregorian_date"):
            continue
        cursor.execute(
            sql,
            row["instrument_code"],
            row["company_id"],
            row["company_name"],
            row["symbol"],
            row.get("brs_name"),
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
        )


# --------------------- Resolution shared by both modes ---------------------
def resolve_matched_symbols(table_name="MarketPriceHistory"):
    """
    AllSymbols را می‌گیرد و برای هر نماد CompanyID را تعیین می‌کند.
    خروجی: (matched: list[dict], unmatched: list[dict])
    هر آیتم matched شامل instrument_code, company_id, symbol, company_name, raw

    همچنین یک فایل گزارش brs_match_report.json تولید می‌کند که برای
    عیب‌یابی نمادهای بدون تطبیق و ساخت فایل override مفید است.
    """
    data = fetch_all_symbols()
    if not isinstance(data, list):
        raise RuntimeError(f"AllSymbols returned non-list: {type(data).__name__}")

    log.info("🌐 AllSymbols: %s نماد دریافت شد", len(data))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        ensure_price_history_table(cursor, table_name)
        name_index, token_index, symbol_index, id_to_name = load_name_maps(cursor)
    finally:
        cursor.close()
        conn.close()

    override = load_override()
    log.info(
        "📇 نقشه‌ها: نام‌ها=%s، نمادها=%s، override=%s",
        len(name_index), len(symbol_index), len(override),
    )

    matched, unmatched = [], []
    match_how_counts = {}
    unmatched_report = []

    for item in data:
        sym = item.get("l18")
        name = item.get("l30")
        company_id, how, best_info = resolve_company_id(
            sym, name, name_index, token_index, symbol_index, override
        )
        if company_id:
            # نام اصلی codal (دست‌نخورده) برای CompanyName
            codal_name = id_to_name.get(company_id) or name or sym
            # نام منبع BRS در ستون جداگانه
            brs_name = name or sym
            matched.append(
                {
                    "instrument_code": str(
                        item.get("id") or item.get("isin") or sym or ""
                    ),
                    "company_id": company_id,
                    "symbol": sym,
                    "company_name": codal_name,
                    "brs_name": brs_name,
                    "raw": item,
                    "how": how,
                }
            )
            key = (how or "").split("(")[0]
            match_how_counts[key] = match_how_counts.get(key, 0) + 1
        else:
            unmatched.append(item)
            unmatched_report.append(
                {
                    "symbol": sym,
                    "brs_name": name,
                    "best_candidate": best_info.get("name", ""),
                    "best_score": best_info.get("score", 0),
                }
            )

    # --- تولید گزارش تشخیصی ---
    report = {
        "summary": {
            "total_brs_symbols": len(data),
            "matched": len(matched),
            "unmatched": len(unmatched),
            "match_breakdown": match_how_counts,
            "codal_names_in_index": len(name_index),
        },
        "brs_raw_sample": {
            "_comment": "ساختار واقعی پاسخ BRS برای عیب‌یابی فیلدها",
            "first_item": data[0] if data else None,
            "first_matched_raw": matched[0]["raw"] if matched else None,
            "first_item_keys": sorted(data[0].keys()) if data else [],
        },
        "unmatched_sample": sorted(
            unmatched_report,
            key=lambda x: x["best_score"],
            reverse=True,
        )[:200],
    }
    report_path = SCRIPT_DIR / "brs_match_report.json"
    try:
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("📊 گزارش تطبیق ذخیره شد: %s", report_path)
    except OSError as exc:
        log.warning("⚠️ نوشتن گزارش ناموفق: %s", exc)

    log.info("🔎 تفکیک تطبیق: %s", match_how_counts)

    return matched, unmatched


# --------------------- Commands ---------------------
def cmd_daily(table_name="MarketPriceHistory"):
    matched, unmatched = resolve_matched_symbols(table_name)

    rows = [
        build_daily_row(m["raw"], m["company_id"], m["company_name"], m["brs_name"])
        for m in matched
    ]
    valid_rows = [r for r in rows if r["gregorian_date"]]
    dropped = len(rows) - len(valid_rows)

    # --- تشخیص: اگه ردیف‌ها دراپ شدن، دلیل رو نشون بده ---
    if dropped > 0:
        log.warning("⚠️ %s ردیف به دلیل تاریخ نامعتبر حذف شد", dropped)
        if matched and dropped == len(rows):
            sample = matched[0]["raw"]
            log.warning("⚠️ نمونه‌ی اولین matched:")
            log.warning("    keys = %s", sorted(sample.keys()))
            for f in DATE_FIELDS:
                log.warning("    %s = %r", f, sample.get(f))
            log.warning(
                "    full = %s",
                json.dumps(sample, ensure_ascii=False)[:500],
            )

    conn = get_db_connection()
    cursor = conn.cursor()
    upserted = 0
    try:
        ensure_price_history_table(cursor, table_name)
        upsert_rows(cursor, valid_rows, table_name)
        conn.commit()
        upserted = len(valid_rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    _print_summary("daily", upserted, len(matched), len(unmatched), unmatched)


def tsetmc_search(keyword):
    """
    جستجوی نماد در TSETMC (بدون مرورگر — درخواست HTTP ساده).
    خروجی: لیستی از {ticker, company_name, instrument_code} یا None.
    """
    from urllib.parse import quote
    url = f"http://www.tsetmc.com/tsev2/data/search.aspx?skey={quote(keyword)}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/plain, */*"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    if not text or not text.strip():
        return None

    # فرمت هر خط: InsCode;LVal18A;LVal30A;CSVal;CGrValC;Flow;...
    results = []
    for line in text.strip().split("\n"):
        parts = line.split(";")
        if len(parts) >= 3 and parts[1].strip():
            results.append({
                "ticker": parts[1].strip(),
                "company_name": parts[2].strip(),
                "instrument_code": parts[0].strip(),
            })
    return results if results else None


def fallback_tsetmc_scrape(symbol, table_name="MarketPriceHistory"):
    """
    Fallback: استخراج قیمت از TSETMC مستقیم با Playwright.
    وقتی BRS نماد را ندارد، این تابع اجرا می‌شود.

    ۱. جستجوی نماد در TSETMC (HTTP) برای یافتن ticker دقیق
    ۲. استفاده از price.py موجود برای استخراج با Playwright
    """
    log.info("🌐 Fallback به TSETMC مستقیم...")

    # ۱. جستجوی ticker دقیق
    ticker = symbol
    search_results = tsetmc_search(symbol)
    if search_results:
        best = search_results[0]
        ticker = best.get("ticker", symbol)
        log.info(
            "🔍 TSETMC search: «%s» → %s (%s)",
            symbol, ticker, best.get("company_name"),
        )
    else:
        log.info("🔍 TSETMC search کار نکرد، استفاده از ورودی مستقیم: %s", ticker)

    # ۲. استخراج با Playwright (price.py)
    try:
        import importlib.util as _ilu
        price_spec = _ilu.spec_from_file_location(
            "tsetmc_price", str(SCRIPT_DIR / "price.py")
        )
        if not price_spec or not price_spec.loader:
            log.error("❌ price.py بارگذاری نشد")
            return False
        tsetmc = _ilu.module_from_spec(price_spec)
        price_spec.loader.exec_module(tsetmc)
    except Exception as exc:
        log.error("❌ بارگذاری price.py ناموفق: %s", exc)
        log.error("   مطمئن شو Playwright نصب است: pip install playwright")
        return False

    MARKET_URL = "http://old.tsetmc.com/Loader.aspx?ParTree=15131F#"

    try:
        result = tsetmc.scrape_market_data_with_history(
            market_url=MARKET_URL,
            normalized_company_names=[ticker],
            headless=True,
            max_history_pages=None,
            save_to_sql=True,
            history_table_name=table_name,
        )

        if result:
            for company in result:
                rows_count = len(company.get("history", []))
                log.info(
                    "✅ %s: %s ردیف از TSETMC ذخیره شد",
                    company.get("company_name", ticker),
                    rows_count,
                )
            return True
        else:
            log.warning("⚠️ نماد «%s» در TSETMC market watch یافت نشد", ticker)
            return False
    except Exception as exc:
        log.error("❌ خطا در TSETMC fallback: %s", exc)
        return False


def cmd_backfill_raw(symbol, table_name="MarketPriceHistory"):
    """
    جمع‌آوری تاریخچه‌ی قیمت یک نماد — بدون نیاز به تطبیق با codal.
    فقط با نماد (l18) از BRS می‌گیرد و با CompanyID تولید‌شده از نام ذخیره می‌کند.

    مناسب برای نمادهایی که در codal نیستند ولی قیمت آن‌ها لازم است.
    """
    sym_norm = normalize_persian(symbol)

    # ۱. پیدا کردن نماد در AllSymbols — چند روش جستجو
    data = fetch_all_symbols()
    if not isinstance(data, list):
        raise RuntimeError("AllSymbols returned non-list")

    item = None

    # روش ۱: تطبیق دقیق l18 (نماد) یا l30 (نام شرکت)
    for d in data:
        l18 = normalize_persian(d.get("l18"))
        l30 = normalize_persian(d.get("l30"))
        if l18 == sym_norm or (l30 and l30 == sym_norm):
            item = d
            break

    # روش ۲: جستجوی محتوایی — ورودی در نام BRS یا برعکس
    if not item:
        for d in data:
            l18 = normalize_persian(d.get("l18"))
            l30 = normalize_persian(d.get("l30"))
            if l18 and (l18 in sym_norm or sym_norm in l18):
                item = d
                break
            if l30 and len(sym_norm) >= 4 and (
                l30 in sym_norm or sym_norm in l30
            ):
                item = d
                break

    # روش ۳: تطبیق فازی بر اساس توکن‌ها
    if not item:
        target_tokens = tokens_for_match(symbol)
        if target_tokens:
            best = (0.0, None)
            for d in data:
                l30 = d.get("l30") or ""
                cand_tokens = tokens_for_match(l30)
                if cand_tokens:
                    score = jaccard(target_tokens, cand_tokens)
                    if score > best[0]:
                        best = (score, d)
            if best[0] >= 0.4 and best[1]:
                item = best[1]
                log.info(
                    "🔍 تطبیق فازی: «%s» → %s (امتیاز: %.2f)",
                    symbol,
                    best[1].get("l18"),
                    best[0],
                )

    if not item:
        log.warning("⚠️ «%s» در BRS یافت نشد — تلاش با TSETMC مستقیم...", symbol)
        if fallback_tsetmc_scrape(symbol, table_name):
            print(f"RESULT|mode=backfill-raw|source=tsetmc|symbol={symbol}")
        else:
            log.error("❌ «%s» نه در BRS و نه در TSETMC یافت نشد", symbol)
            print(f"RESULT|mode=backfill-raw|error=not-found|symbol={symbol}")
        return

    sym = item.get("l18")
    name = item.get("l30") or sym
    instrument_code = str(item.get("id") or item.get("isin") or sym or "")

    # CompanyID = md5(normalize_persian(name)) — اینطوری اگه بعداً شرکت
    # به codal اضافه بشه، قیمت‌ها خودکار لینک می‌شن.
    company_id = hashlib.md5(normalize_persian(name).encode("utf-8")).hexdigest()

    log.info(
        "🔧 raw backfill: %s (%s) → CompanyID=%s...",
        sym, name, company_id[:12],
    )

    # ۲. دریافت تاریخچه از Candlestick (تعدیل‌شده)
    try:
        payload = fetch_candlestick(sym, ctype=3)
    except urllib.error.HTTPError as exc:
        if exc.code in (402, 429):
            # سهمیه BRS تموم شده → fallback به TSETMC
            log.warning(
                "⚠️ BRS محدودیت (HTTP %s) — fallback به TSETMC مستقیم...",
                exc.code,
            )
            if fallback_tsetmc_scrape(sym, table_name):
                print(f"RESULT|mode=backfill-raw|source=tsetmc-fallback|symbol={sym}")
            else:
                print(f"RESULT|mode=backfill-raw|error=tsetmc-failed|symbol={sym}")
            return
        log.error("⛔ fetch fail %s: HTTP %s", sym, exc.code)
        print(f"RESULT|mode=backfill-raw|error=http-{exc.code}|symbol={sym}")
        return
    except Exception as exc:
        log.error("⛔ fetch fail %s: %s", sym, exc)
        print(f"RESULT|mode=backfill-raw|error=fetch|symbol={sym}")
        return

    candles = (
        payload.get("candle_daily_adjusted", [])
        if isinstance(payload, dict)
        else (payload if isinstance(payload, list) else [])
    )
    if not candles:
        log.warning("⚠️ %s: هیچ کندلی دریافت نشد", sym)
        print(f"RESULT|mode=backfill-raw|upserted=0|symbol={sym}")
        return

    # ۳. ساخت و ذخیره ردیف‌ها
    conn = get_db_connection()
    cursor = conn.cursor()
    total = 0
    try:
        ensure_price_history_table(cursor, table_name)

        rows = []
        prev_close = None
        for candle in candles:
            row = build_history_row(candle, company_id, sym, name, name)
            if row is None:
                prev_close = None
                continue
            row["instrument_code"] = instrument_code
            if prev_close is not None and row["closing_price"] is not None:
                row["yesterday_price"] = prev_close
                py_val = prev_close
                pc_val = row["closing_price"]
                if py_val not in (None, 0):
                    row["closing_change"] = pc_val - py_val
                    row["closing_change_percent"] = round(
                        (pc_val - py_val) / py_val * 100.0, 4
                    )
                    row["last_change"] = row["closing_change"]
                    row["last_change_percent"] = row["closing_change_percent"]
            prev_close = row["closing_price"]
            rows.append(row)

        if rows:
            upsert_rows(cursor, rows, table_name)
            conn.commit()
            total = len(rows)
            log.info("✅ %s: %s ردیف ذخیره شد", sym, total)
        else:
            log.warning("⚠️ %s: ردیف معتبری ساخته نشد", sym)
    finally:
        cursor.close()
        conn.close()

    print(f"RESULT|mode=backfill-raw|upserted={total}|symbol={sym}")


def detect_corporate_events(days=14, threshold=-12.0, table_name="MarketPriceHistory"):
    """
    شناسایی نمادهایی که احتمالاً رویداد شرکتی (تقسیم سود، افزایش سرمایه، تجزیه)
    داشته‌اند.

    منطق: در بورس ایران دامنه‌ی نوسان روزانه ±۶٪ است. هر تغییر خارج از این
    محدوده (با تلورانس) عملاً فقط ناشی از تعدیل قیمت پایه به دلیل رویداد
    شرکتی است.

    خروجی: لیستی از {symbol, instrument_code, company_id, date, pct_change}
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    events = []
    try:
        cursor.execute(
            f"""
            WITH Recent AS (
                SELECT Symbol, InstrumentCode, CompanyID,
                    GregorianDate, ClosingPrice,
                    LAG(ClosingPrice) OVER (
                        PARTITION BY InstrumentCode
                        ORDER BY GregorianDate
                    ) AS PrevClosing,
                    ROW_NUMBER() OVER (
                        PARTITION BY InstrumentCode
                        ORDER BY GregorianDate DESC
                    ) AS rn
                FROM dbo.[{safe_sql_identifier(table_name)}]
                WHERE CompanyID IS NOT NULL
            )
            SELECT Symbol, InstrumentCode, CompanyID,
                GregorianDate,
                CAST((ClosingPrice - PrevClosing) AS FLOAT)
                    / NULLIF(PrevClosing, 0) * 100.0 AS pct
            FROM Recent
            WHERE rn BETWEEN 1 AND ?
              AND PrevClosing IS NOT NULL AND PrevClosing > 0
              AND (
                  CAST((ClosingPrice - PrevClosing) AS FLOAT)
                      / NULLIF(PrevClosing, 0) * 100.0 < ?
                  OR
                  CAST((ClosingPrice - PrevClosing) AS FLOAT)
                      / NULLIF(PrevClosing, 0) * 100.0 > ?
              )
            ORDER BY GregorianDate DESC
            """,
            days, threshold, abs(threshold),
        )
        for sym, ic, cid, gdate, pct in cursor.fetchall():
            events.append({
                "symbol": sym,
                "instrument_code": str(ic) if ic else "",
                "company_id": str(cid) if cid else "",
                "date": str(gdate),
                "pct_change": round(float(pct), 2) if pct is not None else None,
            })
    finally:
        cursor.close()
        conn.close()
    return events


PRICE_COLUMNS = (
    "ClosingPrice", "LastPrice", "FirstPrice",
    "HighPrice", "LowPrice", "YesterdayPrice",
)


def local_adjust_prices(cursor, instrument_code, events, table_name):
    """
    تعدیل محلی قیمت‌ها بدون نیاز به API.

    برای هر رویداد شرکتی، ضریب تعدیل محاسبه و روی قیمت‌های قبل از رویداد
    اعمال می‌شود:
        factor = close روز رویداد / close روز قبل

    رویدادها از قدیم به جدید پردازش می‌شوند تا ضریب‌ها تجمعی اعمال شوند.

    خروجی: تعداد ردیف‌های تعدیل‌شده.
    """
    table = safe_sql_identifier(table_name)

    # بارگذاری همه‌ی قیمت‌های این نماد به ترتیب تاریخ
    cursor.execute(
        f"""
        SELECT GregorianDate, ClosingPrice, LastPrice, FirstPrice,
               HighPrice, LowPrice, YesterdayPrice
        FROM dbo.[{table}]
        WHERE InstrumentCode = ?
        ORDER BY GregorianDate
        """,
        instrument_code,
    )
    cols = [d[0] for d in cursor.description]
    rows = []
    by_date = {}
    for r in cursor.fetchall():
        row = dict(zip(cols, r))
        rows.append(row)
        by_date[str(row["GregorianDate"])] = row

    if not rows:
        return 0

    # مرتب‌سازی رویدادها از قدیم به جدید
    sorted_events = sorted(events, key=lambda e: e["date"])

    total_adjusted = 0
    for event in sorted_events:
        event_date = event["date"]
        gap_row = by_date.get(event_date)
        if gap_row is None:
            continue

        gap_close = gap_row.get("ClosingPrice")
        if gap_close is None or gap_close <= 0:
            continue

        # پیدا کردن close روز قبل از رویداد
        prev_close = None
        for r in rows:
            if str(r["GregorianDate"]) < event_date:
                prev_close = r.get("ClosingPrice")
            else:
                break

        if prev_close is None or prev_close <= 0:
            continue

        factor = gap_close / prev_close
        # اگه ضریب خیلی به ۱ نزدیکه، نیازی به تعدیل نیست
        if abs(factor - 1.0) < 0.02:
            continue

        # اعمال ضریب روی همه‌ی ردیف‌های قبل از تاریخ رویداد
        adjusted_count = 0
        for r in rows:
            if str(r["GregorianDate"]) < event_date:
                for col in PRICE_COLUMNS:
                    val = r.get(col)
                    if val is not None and val > 0:
                        r[col] = round(val * factor)
                adjusted_count += 1

        total_adjusted += adjusted_count

    if total_adjusted == 0:
        return 0

    # بازمحاسبه‌ی YesterdayPrice برای همه‌ی ردیف‌ها
    prev_close = None
    for r in rows:
        close = r.get("ClosingPrice")
        if close is None:
            prev_close = None
            continue
        if prev_close is not None and prev_close > 0:
            r["YesterdayPrice"] = prev_close
        else:
            r["YesterdayPrice"] = None
        prev_close = close

    # ذخیره‌ی تغییرات: UPDATE گروهی با executemany برای سرعت
    set_cols = list(PRICE_COLUMNS)
    set_clause = ", ".join(f"{col} = ?" for col in set_cols)
    update_sql = f"""
        UPDATE dbo.[{table}]
        SET {set_clause}
        WHERE InstrumentCode = ? AND GregorianDate = ?
    """
    batch = []
    for r in rows:
        gd = str(r["GregorianDate"])
        params = [r.get(c) for c in set_cols] + [instrument_code, gd]
        batch.append(params)

    cursor.fast_executemany = True
    cursor.executemany(update_sql, batch)

    return total_adjusted


def cmd_sync(days=14, threshold=-8.0, use_api=False, table_name="MarketPriceHistory"):
    """
    شناسایی نمادهای متأثر از رویداد شرکتی و تعدیل قیمت‌ها.

    threshold: آستانه‌ی تشخیص شکاف (پیش‌فرض: ±۸٪).
        در بورس ایران دامنه‌ی نوسان روزانه ±۶٪ است، پس هر شکاف بیشتر
        از ۷٪ عملاً فقط از رویداد شرکتی ناشی می‌شود. ۸٪ حاشیه‌ی امن است.
        برای محتاط‌تر بودن می‌توان ۱۰ یا ۱۲ گذاشت.

    حالت پیش‌فرض (use_api=False): تعدیل محلی — بدون نیاز به API پولی.
    ضریب تعدیل از شکاف قیمت محاسبه و روی تاریخچه اعمال می‌شود.

    حالت use_api=True: re-backfill از Candlestick.php (نیازمند اشتراک).

    فرکانس توصیه‌شده: هفتگی یا ماهانه.
    """
    log.info("🔍 بررسی رویدادهای شرکتی در %s روز اخیر (آستانه: ±%s%%)...", days, abs(threshold))
    events = detect_corporate_events(days=days, threshold=threshold, table_name=table_name)

    if not events:
        log.info("✅ هیچ رویداد شرکتی در %s روز اخیر یافت نشد.", days)
        print(f"RESULT|mode=sync|events=0|adjusted=0|failed=0")
        return

    # حذف تکراری‌ها و گروه‌بندی بر اساس instrument_code
    by_instrument = {}
    for e in events:
        ic = e["instrument_code"]
        if ic not in by_instrument:
            by_instrument[ic] = {**e, "events": []}
        by_instrument[ic]["events"].append(e)

    unique = list(by_instrument.values())
    log.info(
        "📋 %s رویداد در %s نماد یافت شد:",
        len(events), len(unique),
    )
    for e in unique[:15]:
        log.info(
            "  • %s: %s%% در %s",
            e["symbol"], e["pct_change"], e["date"],
        )
    if len(unique) > 15:
        log.info("  ... و %s نماد دیگر", len(unique) - 15)

    mode_label = "API re-fetch" if use_api else "تعدیل محلی"
    log.info("🔧 حالت: %s", mode_label)

    conn = get_db_connection()
    cursor = conn.cursor()
    total_adjusted = 0
    failed = 0
    quota_exhausted = False
    try:
        ensure_price_history_table(cursor, table_name)

        for idx, item in enumerate(unique, 1):
            ic = item["instrument_code"]
            sym = item["symbol"]

            if use_api:
                # --- حالت API: re-fetch از Candlestick ---
                try:
                    cursor.execute(
                        f"DELETE FROM dbo.[{safe_sql_identifier(table_name)}] WHERE InstrumentCode = ?",
                        ic,
                    )
                    conn.commit()

                    payload = fetch_candlestick(sym, ctype=3)
                except urllib.error.HTTPError as exc:
                    if exc.code in (402, 429):
                        log.warning("⛔ محدودیت سهمیه API روی %s.", sym)
                        quota_exhausted = True
                        break
                    log.warning("⚠️ fetch fail %s: %s", sym, exc)
                    failed += 1
                    continue

                candles = (
                    payload.get("candle_daily_adjusted", [])
                    if isinstance(payload, dict)
                    else (payload if isinstance(payload, list) else [])
                )
                rows = []
                prev_close = None
                for candle in candles:
                    row = build_history_row(
                        candle, item["company_id"], sym, sym, sym
                    )
                    if row is None:
                        prev_close = None
                        continue
                    row["instrument_code"] = ic
                    if prev_close is not None and row["closing_price"] is not None:
                        row["yesterday_price"] = prev_close
                        py_val = prev_close
                        pc_val = row["closing_price"]
                        if py_val not in (None, 0):
                            row["closing_change_percent"] = round(
                                (pc_val - py_val) / py_val * 100.0, 4
                            )
                    prev_close = row["closing_price"]
                    rows.append(row)

                if rows:
                    upsert_rows(cursor, rows, table_name)
                    conn.commit()
                    total_adjusted += len(rows)
                    log.info(
                        "✅ [%s/%s] %s: %s ردیف re-fetch شد",
                        idx, len(unique), sym, len(rows),
                    )
                time.sleep(0.5)

            else:
                # --- حالت تعدیل محلی: بدون API ---
                try:
                    n = local_adjust_prices(cursor, ic, item["events"], table_name)
                    conn.commit()
                    total_adjusted += n
                    if n > 0:
                        log.info(
                            "✅ [%s/%s] %s: %s ردیف تعدیل شد (%s%%)",
                            idx, len(unique), sym, n, item["pct_change"],
                        )
                    else:
                        log.info(
                            "⏭️ [%s/%s] %s: نیازی به تعدیل نبود",
                            idx, len(unique), sym,
                        )
                except Exception as exc:
                    conn.rollback()
                    log.error("❌ تعدیل %s ناموفق: %s", sym, exc)
                    failed += 1

    finally:
        cursor.close()
        conn.close()

    log.info(
        "🏁 sync پایان: %s نماد، %s ردیف تعدیل، %s ناموفق",
        len(unique), total_adjusted, failed,
    )
    if quota_exhausted:
        log.warning("⏸️ سهمیه API تمام شد.")
    print(
        f"RESULT|mode=sync|events={len(unique)}|"
        f"adjusted={total_adjusted}|failed={failed}|"
        f"quota_exhausted={int(quota_exhausted)}"
    )


def cmd_backfill(limit=None, symbol=None, force=False, table_name="MarketPriceHistory"):
    matched, unmatched = resolve_matched_symbols(table_name)

    if symbol:
        sym_norm = normalize_persian(symbol)
        matched = [m for m in matched if normalize_persian(m["symbol"]) == sym_norm]
        if not matched:
            log.error("❌ نماد %s تطبیق داده نشد؛ backfill لغو شد", symbol)
            _print_summary("backfill", 0, 0, len(unmatched), unmatched)
            return

    if limit:
        matched = matched[:limit]

    # --- skip کردن نمادهایی که قبلاً تاریخچه‌ی واقعی دارند ---
    # نکته: daily فقط ۱ ردیف برای امروز می‌سازد؛ پس برای تشخیص اینکه backfill
    # قبلاً انجام شده، حداقل ۳۰ ردیف تاریخچه را شرط می‌گذاریم.
    # با --force می‌توان مجدداً همه را backfill کرد (مثلاً بعد از خرید اشتراک
    # تعدیل‌شده یا تغییر منبع داده).
    MIN_HISTORY_ROWS = 30

    # در حالت --force، تاریخچه‌ی قدیمی پاک می‌شود اما N روز اخیر نگه داشته
    # می‌شود تا فیلدهای کامل روزانه (TradeValue و...) برای محاسبه‌ی نقدشوندگی
    # حفظ شوند. candle‌های جدیدتر از این تاریخ نیز skip می‌شوند تا overwrite نشوند.
    KEEP_RECENT_DAYS = 35
    cutoff_date = None

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        ensure_price_history_table(cursor, table_name)
        already_done = set()
        if force:
            # محاسبه‌ی تاریخ برش (KEEP_RECENT_DAYS روز پیش)
            import datetime as _dt
            cutoff_date = (_dt.date.today() - _dt.timedelta(days=KEEP_RECENT_DAYS)).isoformat()
            log.info(
                "🔄 حالت --force: پاک‌سازی تاریخچه‌ی قدیمی‌تر از %s و حفظ %s روز اخیر",
                cutoff_date, KEEP_RECENT_DAYS,
            )
            try:
                cursor.execute(
                    f"""
                    DELETE FROM dbo.[{safe_sql_identifier(table_name)}]
                    WHERE GregorianDate < ?
                    """,
                    cutoff_date,
                )
                conn.commit()
                log.info("🔄 %s ردیف قدیمی حذف شد", cursor.rowcount)
            except Exception as exc:
                log.warning("⚠️ cannot clear old history: %s", exc)
                conn.rollback()
        else:
            try:
                cursor.execute(
                    f"""
                    SELECT InstrumentCode
                    FROM dbo.[{safe_sql_identifier(table_name)}]
                    WHERE InstrumentCode IS NOT NULL
                    GROUP BY InstrumentCode
                    HAVING COUNT(*) >= ?
                    """,
                    MIN_HISTORY_ROWS,
                )
                for (ic,) in cursor.fetchall():
                    if ic:
                        already_done.add(str(ic))
            except Exception as exc:
                log.warning("⚠️ cannot read existing instruments: %s", exc)
    except Exception:
        cursor.close()
        conn.close()
        raise

    total = len(matched)
    skipped = sum(1 for m in matched if m["instrument_code"] in already_done)
    todo = [m for m in matched if m["instrument_code"] not in already_done]

    log.info(
        "🚀 backfill: %s نماد کاندید، %s تا قبلاً جمع شده (skip)، %s تا باقی‌مانده",
        total, skipped, len(todo),
    )
    matched = todo  # فقط نمادهای باقی‌مانده پردازش می‌شوند

    total_upserted = 0
    failed = 0
    quota_exhausted = False
    try:
        for idx, m in enumerate(matched, 1):
            sym = m["symbol"]
            if not sym:
                continue
            try:
                # type=3 = روزانه تعدیل‌شده
                payload = fetch_candlestick(sym, ctype=3)
            except urllib.error.HTTPError as exc:
                # 402/429 یعنی محدودیت سهمیه — ادامه‌ی درخواست‌ها هم fail می‌شود
                if exc.code in (402, 429):
                    log.warning(
                        "⛔ محدودیت سهمیه API (HTTP %s) روی %s. "
                        "باقی‌مانده‌ی نمادها برای اجرای بعدی به تعویق افتاد.",
                        exc.code, sym,
                    )
                    quota_exhausted = True
                    break
                log.warning("⚠️ Candlestick fetch fail %s: %s", sym, exc)
                failed += 1
                continue
            except Exception as exc:
                log.warning("⚠️ Candlestick fetch fail %s: %s", sym, exc)
                failed += 1
                continue

            # Candlestick پاسخ dict با کلید candle_daily_adjusted است
            candles = (
                payload.get("candle_daily_adjusted", [])
                if isinstance(payload, dict)
                else (payload if isinstance(payload, list) else [])
            )
            if not candles:
                continue

            rows = []
            prev_close = None  # برای محاسبه‌ی yesterday_price و درصد تغییر
            skipped_recent = 0
            # candle_daily_adjusted معمولاً از جدید به قدیم مرتب است؛
            # برای محاسبه‌ی yesterday (روز قبل) از همان ترتیب استفاده می‌کنیم.
            for candle in candles:
                row = build_history_row(
                    candle, m["company_id"], sym, m["company_name"], m["brs_name"]
                )
                if row is None:
                    # ترتیب تاریخ به‌هم می‌خورد؛ prev_close را ریست کن
                    prev_close = None
                    continue

                # در حالت --force، ردیف‌های اخیر (داخل پنجره‌ی KEEP_RECENT_DAYS)
                # skip می‌شوند تا داده‌ی کاملِ daily (با TradeValue و...) حفظ شود.
                if cutoff_date and row["gregorian_date"] >= cutoff_date:
                    skipped_recent += 1
                    # prev_close را همچنان به‌روز نگه می‌داریم تا محاسبه‌ی
                    # درصد تغییر برای ردیف بعدی (قدیمی‌تر) درست بماند.
                    prev_close = row["closing_price"]
                    continue

                # پر کردن instrument_code از مچ‌شده
                row["instrument_code"] = m["instrument_code"]

                # محاسبه‌ی yesterday_price و درصد تغییر از close روز قبل
                # (candle_daily_adjusted معمولاً نزولی بر اساس تاریخ است؛
                #  بنابراین prev_close = closeِ روز بعد در لیست = دیروزِ شمسی)
                if prev_close is not None and row["closing_price"] is not None:
                    row["yesterday_price"] = prev_close
                    py_val = prev_close
                    pc_val = row["closing_price"]
                    if py_val not in (None, 0):
                        row["closing_change"] = pc_val - py_val
                        row["closing_change_percent"] = round(
                            (pc_val - py_val) / py_val * 100.0, 4
                        )
                        row["last_change"] = row["closing_change"]
                        row["last_change_percent"] = row["closing_change_percent"]

                prev_close = row["closing_price"]
                rows.append(row)

            if not rows:
                continue

            try:
                upsert_rows(cursor, rows, table_name)
                conn.commit()
                total_upserted += len(rows)
                log.info(
                    "✅ [%s/%s] %s: %s ردیف تاریخچه (تعدیل‌شده)",
                    idx, len(matched), sym, len(rows),
                )
            except Exception as exc:
                conn.rollback()
                log.error("❌ upsert %s ناموفق: %s", sym, exc)
                failed += 1

            # احترام به محدودیت نرخ API
            time.sleep(0.5)
    finally:
        cursor.close()
        conn.close()

    remaining = len(matched) - failed - (total_upserted and len(todo) or 0)
    log.info(
        "🏁 backfill پایان: تاریخچه‌ی جدید=%s ردیف، ناموفق=%s",
        total_upserted, failed,
    )
    if quota_exhausted:
        log.warning(
            "⏸️ سهمیه‌ی روزانه API تمام شد. %s نماد باقی‌مانده. "
            "فردا دوباره اجرا کنید — خودکار از همان‌جا ادامه می‌دهد (skip می‌شود).",
            remaining,
        )
    elif remaining > 0:
        log.info("ℹ️ %s نماد باقی‌مانده.", remaining)
    else:
        log.info("✅ همه‌ی نمادهای باقی‌مانده تکمیل شد!")
    print(
        f"RESULT|mode=backfill|upserted={total_upserted}|failed={failed}|"
        f"skipped={skipped}|quota_exhausted={int(quota_exhausted)}"
    )


def _print_summary(mode, upserted, matched_count, unmatched_count, unmatched):
    log.info(
        "✅ %s انجام شد — upsert=%s، تطبیق‌خورده=%s، بدون‌تطبیق=%s",
        mode, upserted, matched_count, unmatched_count,
    )
    sample = [u.get("l18") for u in unmatched[:25] if u.get("l18")]
    if sample:
        log.info("نمونه‌ای نمادهای بدون تطبیق: %s", ", ".join(sample))
    print(
        f"RESULT|mode={mode}|upserted={upserted}|"
        f"matched={matched_count}|unmatched={unmatched_count}"
    )


# --------------------- CLI ---------------------
def main():
    parser = argparse.ArgumentParser(description="BRS API price collector")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("daily", help="دریافت و ذخیره‌ی قیمت روزانه‌ی کل بازار")

    bf = sub.add_parser("backfill", help="پر کردن تاریخچه‌ی گذشته‌ی نمادها")
    bf.add_argument("--limit", type=int, default=None, help="حداکثر تعداد نماد")
    bf.add_argument("--symbol", type=str, default=None, help="فقط یک نماد خاص")
    bf.add_argument(
        "--force",
        action="store_true",
        help="نادیده‌گرفتن تاریخچه‌ی موجود؛ برای re-backfill بعد از تغییر منبع داده",
    )
    bf.add_argument(
        "--raw", action="store_true",
        help="جمع‌آوری بدون تطبیق codal — فقط با نماد BRS (نیازمند --symbol)",
    )

    sy = sub.add_parser(
        "sync",
        help="شناسایی خودکار رویدادهای شرکتی و تعدیل قیمت‌ها",
    )
    sy.add_argument(
        "--days", type=int, default=14,
        help="بازه‌ی بررسی رویدادها به روز (پیش‌فرض: ۱۴)",
    )
    sy.add_argument(
        "--threshold", type=float, default=-8.0,
        help="آستانه‌ی تشخیص شکاف به درصد (پیش‌فرض: ۸، یعنی ±۸٪). "
             "دامنه‌ی نوسان روزانه بورس ۶٪ است؛ ۸ حاشیه‌ی امن.",
    )
    sy.add_argument(
        "--api", action="store_true",
        help="استفاده از API برای re-fetch به‌جای تعدیل محلی (نیازمند اشتراک)",
    )

    args = parser.parse_args()
    validate_env()

    if args.command == "daily":
        cmd_daily()
    elif args.command == "backfill":
        if args.raw:
            if not args.symbol:
                log.error("--raw نیازمند --symbol است")
                sys.exit(1)
            cmd_backfill_raw(args.symbol)
        else:
            cmd_backfill(limit=args.limit, symbol=args.symbol, force=args.force)
    elif args.command == "sync":
        cmd_sync(days=args.days, threshold=args.threshold, use_api=args.api)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception("❌ اجرای کالکتور ناموفق بود")
        print(f"RESULT|mode=error|error={exc}")
        sys.exit(1)
