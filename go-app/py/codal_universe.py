"""Universe نمادهای تحت پوشش (master ticker list).

چرا این جدول لازم است:
- منبعِ فعلیِ «چه شرکت‌هایی را دنبال می‌کنیم» در پروژه، distinctِ
  ``miandore2.CompanyName`` است (همان که ``GetCompanyNames`` و BulkFetch
  از آن استفاده می‌کنند). این منبع از داده‌ی تاریخی ساخته می‌شود؛ پس شرکتی
  که tracked است ولی هنوز هیچ گزارش/داده‌ای ندارد هرگز در آن ظاهر نمی‌شود.
- هیچ جدول mapping/company دیگری برای شرکت‌های بورسی ایران در دیتابیس‌های
  codal / Stock / BIGateway وجود ندارد (Stock.Company از SEC آمریکا و
  BIGateway.Company کلاینت‌های API است).
- ``MarketPriceHistory`` فقط نمادهایی را نگه می‌دارد که به یک شرکت codal
  موجود match شده‌اند؛ برای همین آن هم شرکتِ بدونِ داده را پوشش نمی‌دهد.

بنابراین یک جدول کوچک master می‌سازیم که:
  * از منابع موجودِ نماد-محور seed می‌شود (Symbol ↔ Symbol)،
  * و می‌توان نماد شرکت‌های tracked-but-no-data را دستی در آن افزود
    (بدون اینکه به mahane/miandore2 وابسته باشد).
"""

from __future__ import annotations

import logging

from codal_prefilter import normalize_symbol

logger = logging.getLogger(__name__)

UNIVERSE_TABLE = "TrackedTickers"

# منابع seed — همه نماد-محور هستند (نه نام کامل شرکت).
SOURCE_QUERIES = (
    (
        "market_price_history",
        """
        SELECT DISTINCT Symbol FROM dbo.MarketPriceHistory
        WHERE Symbol IS NOT NULL AND LTRIM(RTRIM(Symbol)) <> ''
        """,
    ),
    (
        "miandore2",
        """
        SELECT DISTINCT CompanyName FROM dbo.miandore2
        WHERE CompanyName IS NOT NULL AND LTRIM(RTRIM(CompanyName)) <> ''
        """,
    ),
    (
        "mahane",
        """
        SELECT DISTINCT CompanyName FROM dbo.mahane
        WHERE CompanyName IS NOT NULL AND LTRIM(RTRIM(CompanyName)) <> ''
        """,
    ),
    (
        "fullpe",
        """
        SELECT DISTINCT CompanyName FROM dbo.FullPE
        WHERE CompanyName IS NOT NULL AND LTRIM(RTRIM(CompanyName)) <> ''
        """,
    ),
)


def ensure_universe(conn) -> None:
    """جدول TrackedTickers را در صورت نبود می‌سازد (idempotent)."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            IF OBJECT_ID(N'dbo.{UNIVERSE_TABLE}', N'U') IS NULL
            CREATE TABLE dbo.{UNIVERSE_TABLE} (
                Symbol    NVARCHAR(50) NOT NULL PRIMARY KEY,
                Source    NVARCHAR(50) NULL,
                IsActive  BIT NOT NULL DEFAULT 1,
                CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
            """
        )
        conn.commit()
    finally:
        cursor.close()


def refresh_universe(conn) -> int:
    """نمادهای جدیدِ منابع موجود را (به‌صورت additive) اضافه می‌کند.

    نمادهای دستیِ موجود حذف/غیرفعال نمی‌شوند. خروجی: تعداد نماد جدید.
    """
    cursor = conn.cursor()
    added = 0
    try:
        cursor.execute(f"SELECT Symbol FROM dbo.{UNIVERSE_TABLE}")
        existing = {normalize_symbol(row[0]) for row in cursor.fetchall()}

        pending: dict[str, str] = {}
        for source, sql in SOURCE_QUERIES:
            try:
                cursor.execute(sql)
            except Exception as exc:  # noqa: BLE001 - منبع ممکن است وجود نداشته باشد
                logger.warning("⚠️ universe seed source '%s' skipped: %s", source, exc)
                continue
            for row in cursor.fetchall():
                ticker = normalize_symbol(row[0])
                if not ticker or ticker in existing or ticker in pending:
                    continue
                pending[ticker] = source

        for ticker, source in pending.items():
            cursor.execute(
                f"""
                IF NOT EXISTS (SELECT 1 FROM dbo.{UNIVERSE_TABLE} WHERE Symbol = ?)
                INSERT INTO dbo.{UNIVERSE_TABLE} (Symbol, Source, IsActive)
                VALUES (?, ?, 1)
                """,
                ticker,
                ticker,
                source,
            )
            added += 1
        conn.commit()
    finally:
        cursor.close()
    return added


def load_tickers(conn) -> set[str]:
    """مجموعه‌ی نمادهای فعال (نرمال‌شده) را برمی‌گرداند."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT Symbol FROM dbo.{UNIVERSE_TABLE} WHERE IsActive = 1")
        return {normalize_symbol(row[0]) for row in cursor.fetchall() if row[0]}
    finally:
        cursor.close()


def count_tickers(conn, active_only: bool = True) -> int:
    cursor = conn.cursor()
    try:
        where = "WHERE IsActive = 1" if active_only else ""
        cursor.execute(f"SELECT COUNT(*) FROM dbo.{UNIVERSE_TABLE} {where}")
        return int(cursor.fetchone()[0])
    finally:
        cursor.close()


def load_tickers_inmemory(conn) -> set[str]:
    """universe را بدون هیچ نوشتنی می‌سازد (برای dry-run).

    = نمادهای دستیِ موجود در TrackedTickers (اگر جدول باشد)
      ∪ همه‌ی نمادهای منابع seed.
    """
    result: set[str] = set()

    try:
        result |= load_tickers(conn)
    except Exception as exc:  # noqa: BLE001 - جدول ممکن است هنوز نباشد
        logger.debug("universe table not readable yet: %s", exc)

    cursor = conn.cursor()
    try:
        for source, sql in SOURCE_QUERIES:
            try:
                cursor.execute(sql)
            except Exception as exc:  # noqa: BLE001
                logger.warning("⚠️ universe source '%s' skipped: %s", source, exc)
                continue
            for row in cursor.fetchall():
                ticker = normalize_symbol(row[0])
                if ticker:
                    result.add(ticker)
    finally:
        cursor.close()

    return result


__all__ = [
    "SOURCE_QUERIES",
    "UNIVERSE_TABLE",
    "count_tickers",
    "ensure_universe",
    "load_tickers",
    "load_tickers_inmemory",
    "refresh_universe",
]
