"""Pre-filter گزارش‌های کدال — تصمیم‌گیری فقط از روی metadata قبل از باز کردن مرورگر.

هدف: brower/navigation فقط برای «گزارش‌های جدید و مرتبط» باز شود.

ترتیب تصمیم (همه بدون navigation):

    ۱) آیا Symbol در universe شرکت‌های ما وجود دارد؟   (cheap DB)
    ۲) آیا نوع گزارش توسط parser فعلی پشتیبانی می‌شود؟ (Title/LetterCode/HasHtml)
    ۳) آیا metadata لازم کامل است؟                       (Url/TracingNo/HasHtml)
    → سپس در لایه‌ی sync، dedup با CodalReportId از SQL Server انجام می‌شود.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codal_feed import FINANCIAL_LETTER_TYPE, MONTHLY_LETTER_TYPE

# نشانه‌های عنوان برای گزارش فعالیت ماهانه (LetterType=58)
MONTHLY_TITLE_MARKERS = (
    "فعالیت ماهانه",
    "گزارش فعالیت ماهانه",
)

# نشانه‌های عنوان برای صورت‌های مالی / میاندوره‌ای (LetterType=6)
FINANCIAL_TITLE_MARKERS = (
    "صورت های مالی",
    "صورتهای مالی",
    "صورت مالی",
    "صورت سود و زیان",
    "اطلاعات و صورت",
    "میان دوره",
    "میاندوره",
)

# عنوان‌هایی که با وجود LetterType=6 برای parser فعلی ما مرتبط نیستند
FINANCIAL_UNSUPPORTED_MARKERS = (
    "تصمیمات مجمع",
    "افشای اطلاعات",
    "اظهارنظر حسابرس",
    "عدم اظهارنظر",
    "گزارش تفسیر",
    "آگهی",
    "دعوت به مجمع",
    "نرخ",
    "بازگشایی نماد",
)

INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\ufeff]")


@dataclass(frozen=True)
class CandidateDecision:
    should_fetch: bool
    route: str | None
    reason: str
    ticker_known: bool = True


def normalize_symbol(value: str | None) -> str:
    """نرمال‌سازی سبک نماد/نام برای مقایسه با SQL Server."""
    if not value:
        return ""
    text = str(value).replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = INVISIBLE_CHARS_RE.sub("", text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def classify_report_type(report) -> tuple[str | None, str]:
    """نوع گزارش را فقط از روی Title/LetterType تعیین می‌کند.

    خروجی: ``(route, reason)``. اگر پشتیبانی نشود route برابر None است.
    """
    title = normalize_symbol(report.title)

    if report.letter_type == MONTHLY_LETTER_TYPE:
        if any(marker in title for marker in MONTHLY_TITLE_MARKERS):
            return "monthly", "supported_monthly_report"
        return None, "unsupported_monthly_title"

    if report.letter_type == FINANCIAL_LETTER_TYPE:
        if any(marker in title for marker in FINANCIAL_UNSUPPORTED_MARKERS):
            return None, "unsupported_financial_title"
        if any(marker in title for marker in FINANCIAL_TITLE_MARKERS):
            return "financial", "supported_financial_report"
        return None, "unsupported_financial_title"

    return None, "unsupported_letter_type"


def is_candidate(report, ticker_universe: set[str] | None = None) -> CandidateDecision:
    """تصمیم ارزان فقط از روی metadata (بدون هیچ navigation/DB lookup).

    ``ticker_universe=None`` یعنی فیلتر نماد غیرفعال است (مثلاً dry-run بدون DB).
    """
    ticker = normalize_symbol(report.ticker)
    if not ticker:
        return CandidateDecision(False, None, "missing_symbol", False)

    if ticker_universe is not None and ticker not in ticker_universe:
        return CandidateDecision(False, None, "unknown_ticker", False)

    if not report.report_url or not report.report_id:
        return CandidateDecision(False, None, "missing_metadata", True)

    if not report.has_html:
        return CandidateDecision(False, None, "no_html", True)

    route, reason = classify_report_type(report)
    if route is None:
        return CandidateDecision(False, None, reason, True)

    return CandidateDecision(True, route, reason, True)


@dataclass
class ReportPreFilter:
    """pre-filter با universe نمادها؛ در صورت نیاز از SQL Server بارگذاری می‌شود."""

    ticker_universe: set[str] | None = None
    _enforce_ticker: bool = field(default=False)

    @classmethod
    def from_db(cls, conn) -> ReportPreFilter:
        """universe را از master ticker list (dbo.TrackedTickers.Symbol) می‌خواند."""
        import codal_universe

        tickers = codal_universe.load_tickers(conn)
        return cls(ticker_universe=tickers, _enforce_ticker=True)

    @classmethod
    def allow_all(cls) -> ReportPreFilter:
        """بدون فیلتر نماد (وقتی DB در دسترس نیست)."""
        return cls(ticker_universe=None, _enforce_ticker=False)

    def decide(self, report) -> CandidateDecision:
        universe = self.ticker_universe if self._enforce_ticker else None
        return is_candidate(report, ticker_universe=universe)


__all__ = [
    "CandidateDecision",
    "ReportPreFilter",
    "classify_report_type",
    "is_candidate",
    "normalize_symbol",
]
