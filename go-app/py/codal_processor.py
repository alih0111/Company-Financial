"""اجرای parserهای موجود روی گزارش‌های کشف‌شده.

این ماژول هیچ منطق parsing جدیدی ندارد؛ فقط parserهای سالم فعلی
(``MianSql`` برای صورت‌های مالی و ``MianSql2`` برای فعالیت ماهانه) را با یک
browser context مشترک صدا می‌زند تا برای هر گزارش مرورگر جدید باز نشود.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterable

import pyodbc
from codal_feed import FINANCIAL_LETTER_TYPE, MONTHLY_LETTER_TYPE, route_for_letter_type
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

FINANCIAL_TABLE = "miandore2"
MONTHLY_TABLE = "mahane"

_ALLOWED_TABLES = {FINANCIAL_TABLE, MONTHLY_TABLE}


def _company_id(name: str) -> str:
    """همان الگوریتم CompanyID که در parserهای فعلی استفاده می‌شود."""
    return hashlib.md5(name.encode("utf-8")).hexdigest()


def _report_exists(
    conn: pyodbc.Connection, table_name: str, company_id: str, report_date: str
) -> bool:
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"Unsupported table: {table_name}")

    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT COUNT(*) FROM dbo.[{table_name}] WHERE CompanyID = ? AND ReportDate = ?",
            company_id,
            report_date,
        )
        return int(cursor.fetchone()[0]) > 0
    finally:
        cursor.close()


def process_batch(
    route: str,
    items: Iterable[dict],
    conn: pyodbc.Connection,
    on_result: Callable[[dict, str, str | None, str | None], None],
) -> None:
    """گزارش‌های ``items`` را با parser مربوط به ``route`` پردازش می‌کند.

    هر item: ``{"report_id", "url", "company_name"}``.
    ``on_result(item, status, report_date, error)`` بعد از هر گزارش صدا زده
    می‌شود تا registry فوراً به‌روز شود (error isolation).
    """
    import MianSql
    import MianSql2

    items = list(items)
    if not items:
        return

    with sync_playwright() as playwright:
        context = MianSql.create_context(playwright)
        page = context.new_page()
        try:
            for item in items:
                company_name = item["company_name"]
                url = item["url"]

                try:
                    if route == "monthly":
                        status, report_date, error = _process_monthly(
                            MianSql2, page, conn, url, company_name
                        )
                    else:
                        status, report_date, error = _process_financial(
                            MianSql, page, url, company_name
                        )
                except Exception as exc:
                    logger.exception("❌ Report processing crashed: %s", url)
                    status, report_date, error = "failed", None, str(exc)

                on_result(item, status, report_date, error)
        finally:
            context.close()


def _process_financial(
    miansql, page, url: str, company_name: str
) -> tuple[str, str | None, str | None]:
    ok = miansql.scrape_report(
        page=page,
        link=url,
        company_name=company_name,
        base_url=url,
        table_name=FINANCIAL_TABLE,
    )
    if ok:
        return "completed", None, None
    return "failed", None, "parser returned no saved data"


def _process_monthly(
    miansql2, page, conn, url: str, company_name: str
) -> tuple[str, str | None, str | None]:
    parsed = miansql2.parse_report_table(page, url)
    if not parsed:
        # parser فعلی برای این قالب جدول پشتیبانی ندارد → unsupported (نه failed)
        return "unsupported", None, "monthly report format not supported by parser"

    report_date = parsed.get("report_date")
    monthly_values = parsed.get("monthly_values")

    if not report_date or not monthly_values:
        return "unsupported", report_date, "missing report date or monthly values"

    company_id = _company_id(company_name)
    if _report_exists(conn, MONTHLY_TABLE, company_id, report_date):
        return "completed", report_date, None

    ok = miansql2.save_report_to_sql(
        company_name=company_name,
        report_date=report_date,
        monthly_values=monthly_values,
        base_url=url,
        table_name=MONTHLY_TABLE,
    )
    if ok:
        return "completed", report_date, None
    return "failed", report_date, "sql save returned False"


__all__ = [
    "FINANCIAL_LETTER_TYPE",
    "FINANCIAL_TABLE",
    "MONTHLY_LETTER_TYPE",
    "MONTHLY_TABLE",
    "process_batch",
    "route_for_letter_type",
]
