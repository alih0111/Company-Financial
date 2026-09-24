"""کشف گزارش‌های جدید کدال از روی feed لیست گزارش‌ها (Discovery Layer).

این ماژول مستقیماً از endpoint داخلی JSON کدال می‌خواند:

    https://search.codal.ir/api/search/v2/q

که همان منبع ReportList.aspx است (صفحه‌ی AngularJS داده را از این API می‌گیرد).
هدف: به‌جای جستجوی تک‌تک نمادها، فقط لیست گزارش‌ها را صفحه‌به‌صفحه بخوانیم و
بفهمیم چه گزارش‌های جدیدی آمده‌اند.

شناسه‌ی یکتای هر گزارش کدال: ``TracingNo`` (عدد صحیح). گزارش اصلاحیه هم
شناسه‌ی مستقل خودش را دارد و بنابراین گزارش جدید محسوب می‌شود.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

try:
    import jdatetime
except ImportError:  # pragma: no cover
    jdatetime = None


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ثابت‌ها
# ---------------------------------------------------------------------------
FINANCIAL_LETTER_TYPE = 6
MONTHLY_LETTER_TYPE = 58

SEARCH_API_BASE = "https://search.codal.ir/api/search/v2/q"
CODAL_BASE_URL = "https://www.codal.ir"

# اندازه‌ی هر صفحه در API کدال ثابت و ۲۰ است.
PAGE_SIZE = 20

DEFAULT_TIMEOUT = 45
DEFAULT_RETRIES = 3

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Referer": "https://www.codal.ir/ReportList.aspx",
}

PERSIAN_ARABIC_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

# الگوی تاریخ/زمان شمسی در پاسخ API: «۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴»
_PUBLISH_RE = re.compile(
    r"(\d{4})/(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?"
)


# ---------------------------------------------------------------------------
# مدل داده
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CodalReport:
    """metadata یک گزارش کدال — بدون هیچ داده‌ی استخراج‌شده از خود گزارش."""

    report_id: str          # TracingNo به‌صورت رشته (شناسه‌ی یکتا)
    tracing_no: int         # TracingNo عددی
    letter_type: int        # 6 = صورت‌های مالی، 58 = فعالیت ماهانه
    ticker: str             # Symbol
    company_name: str       # CompanyName
    title: str
    letter_code: str
    published_at_raw: str   # رشته‌ی تاریخ شمسی خام کدال
    published_at: datetime | None
    report_url: str         # آدرس کامل صفحه‌ی گزارش
    has_html: bool
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def route(self) -> str:
        """مسیر پردازش بر اساس LetterType."""
        return route_for_letter_type(self.letter_type)


@dataclass(frozen=True)
class FeedPage:
    letter_type: int
    page_number: int
    total: int
    reports: list[CodalReport]

    @property
    def total_pages(self) -> int:
        if self.total <= 0:
            return 0
        return (self.total + PAGE_SIZE - 1) // PAGE_SIZE

    @property
    def is_last_page(self) -> bool:
        return len(self.reports) < PAGE_SIZE


def route_for_letter_type(letter_type: int) -> str:
    if letter_type == FINANCIAL_LETTER_TYPE:
        return "financial"
    if letter_type == MONTHLY_LETTER_TYPE:
        return "monthly"
    return "unknown"


# ---------------------------------------------------------------------------
# کمکی‌ها
# ---------------------------------------------------------------------------
def parse_persian_datetime(text: str | None) -> datetime | None:
    """تاریخ/زمان شمسی کدال را به ``datetime`` میلادی تبدیل می‌کند."""
    if not text:
        return None

    normalized = str(text).translate(PERSIAN_ARABIC_DIGITS)
    match = _PUBLISH_RE.search(normalized)
    if not match:
        return None

    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)

    if jdatetime is None:
        return None

    try:
        return jdatetime.datetime(
            year, month, day, hour, minute, second
        ).togregorian()
    except (ValueError, TypeError):
        return None


def build_report_url(relative_url: str | None) -> str:
    if not relative_url:
        return ""
    return urllib.parse.urljoin(CODAL_BASE_URL, relative_url.strip())


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_letter(letter: dict, letter_type: int) -> CodalReport:
    tracing_no = int(letter.get("TracingNo") or 0)
    published_raw = str(letter.get("PublishDateTime") or "").strip()

    return CodalReport(
        report_id=str(tracing_no),
        tracing_no=tracing_no,
        letter_type=letter_type,
        ticker=str(letter.get("Symbol") or "").strip(),
        company_name=str(letter.get("CompanyName") or "").strip(),
        title=str(letter.get("Title") or "").strip(),
        letter_code=str(letter.get("LetterCode") or "").strip(),
        published_at_raw=published_raw,
        published_at=parse_persian_datetime(published_raw),
        report_url=build_report_url(letter.get("Url")),
        has_html=_to_bool(letter.get("HasHtml")),
        raw=letter,
    )


# ---------------------------------------------------------------------------
# طبقه‌بندی (Routing / Unsupported detection)
# ---------------------------------------------------------------------------
def classify_report(report: CodalReport) -> str:
    """``supported`` یا ``unsupported`` را بر اساس metadata برمی‌گرداند.

    گزارش‌های بدون HTML (مثل XBRL/PDF-only) یا عنوان‌های نامرتبط با parser
    فعلی، unsupported علامت می‌خورند تا کل sync متوقف نشود.
    """
    if not report.report_url:
        return "unsupported"

    if not report.has_html:
        return "unsupported"

    title = report.title or ""
    if report.letter_type == MONTHLY_LETTER_TYPE:
        return "supported" if "فعالیت ماهانه" in title else "unsupported"

    if report.letter_type == FINANCIAL_LETTER_TYPE:
        if "صورت" in title or "مالی" in title:
            return "supported"
        return "unsupported"

    return "unsupported"


def filter_supported(reports: Iterable[CodalReport]) -> list[CodalReport]:
    return [r for r in reports if classify_report(r) == "supported"]


# ---------------------------------------------------------------------------
# دسترسی به API
# ---------------------------------------------------------------------------
def _build_query(
    letter_type: int,
    page_number: int,
    from_date: str | None = None,
    to_date: str | None = None,
) -> str:
    params: dict[str, object] = {
        "LetterType": letter_type,
        "PageNumber": page_number,
        "Audited": "true",
        "NotAudited": "true",
        "IsNotAudited": "false",
        "Childs": "true",
        "Mains": "true",
        "Publisher": "false",
        "CompanyState": "-1",
        "ReportingType": "-1",
        "Category": "-1",
        "CompanyType": "-1",
        "Consolidatable": "true",
        "NotConsolidatable": "true",
        "AuditorRef": "-1",
    }
    if from_date:
        params["FromDate"] = from_date
    if to_date:
        params["ToDate"] = to_date

    return f"{SEARCH_API_BASE}?{urllib.parse.urlencode(params)}"


def _fetch_json(url: str, timeout: int, retries: int) -> dict:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "⚠️ Codal feed request failed (attempt %s/%s): %s",
                attempt,
                retries,
                exc,
            )
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"Codal feed request failed: {last_error}")


def discover_reports(
    letter_type: int,
    page_number: int = 1,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> FeedPage:
    """یک صفحه از feed کدال را می‌خواند و metadata گزارش‌ها را برمی‌گرداند."""
    if page_number < 1:
        raise ValueError("page_number must be >= 1")

    url = _build_query(letter_type, page_number, from_date, to_date)
    logger.info("🌐 Codal discovery: LetterType=%s PageNumber=%s", letter_type, page_number)

    data = _fetch_json(url, timeout=timeout, retries=retries)

    raw_letters = data.get("Letters") or []
    reports = [parse_letter(letter, letter_type) for letter in raw_letters]

    # توجه: فیلد ``Page`` در پاسخ API «تعداد کل صفحات» است نه شماره‌ی صفحه‌ی
    # جاری؛ بنابراین شماره‌ی درخواستی را نگه می‌داریم و total_pages از Total
    # محاسبه می‌شود.
    total = int(data.get("Total") or 0)

    return FeedPage(
        letter_type=letter_type,
        page_number=page_number,
        total=total,
        reports=reports,
    )


def iter_reports(
    letter_type: int,
    *,
    start_page: int = 1,
    max_pages: int = 5,
    from_date: str | None = None,
    to_date: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> Iterator[FeedPage]:
    """صفحه‌های feed را از ``start_page`` تا سقف ``max_pages`` پیمایش می‌کند."""
    page_number = start_page
    pages_read = 0

    while pages_read < max_pages:
        page = discover_reports(
            letter_type,
            page_number,
            from_date=from_date,
            to_date=to_date,
            timeout=timeout,
            retries=retries,
        )
        yield page

        pages_read += 1
        if page.is_last_page:
            break
        if page.total_pages and page_number >= page.total_pages:
            break

        page_number += 1


def _main() -> None:  # pragma: no cover - ابزار دستی
    import argparse

    parser = argparse.ArgumentParser(description="Codal report feed reader")
    parser.add_argument("--letter-type", type=int, default=FINANCIAL_LETTER_TYPE)
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    page = discover_reports(args.letter_type, args.page)
    print(f"Total={page.total} Page={page.page_number} TotalPages={page.total_pages}")
    for report in page.reports:
        print(
            f"{report.report_id} | {report.ticker} | {report.title} | "
            f"{report.published_at_raw} | {classify_report(report)}"
        )


if __name__ == "__main__":  # pragma: no cover
    _main()
