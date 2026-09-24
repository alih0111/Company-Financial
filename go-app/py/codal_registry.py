"""Registry گزارش‌های کدال در SQL Server — لایه‌ی deduplication و status.

جدول ``dbo.CodalReports`` به‌عنوان منبع حقیقت برای «کدام گزارش قبلاً دیده/پردازش
شده است» عمل می‌کند. شناسه‌ی یکتا ``CodalReportId`` (همان TracingNo) است و یک
unique index آخرین خط دفاعی در برابر درج تکراری هنگام اجرای هم‌زمان دو process است.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import pyodbc
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

SERVER = os.getenv("DB_SERVER")
DATABASE = os.getenv("DB_NAME")
USERNAME = os.getenv("DB_USER")
PASSWORD = os.getenv("DB_PASSWORD")

TABLE = "CodalReports"

# وضعیت‌های چرخه‌ی عمر
STATUS_DISCOVERED = "discovered"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_UNSUPPORTED = "unsupported"

# وضعیت‌هایی که دیگر پردازش نمی‌شوند
TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_UNSUPPORTED}


@dataclass(frozen=True)
class RegistryRow:
    report_id: str
    status: str
    letter_type: int


def get_db_connection() -> pyodbc.Connection:
    if not SERVER or not DATABASE or not USERNAME or not PASSWORD:
        raise RuntimeError(
            "Missing DB env values: DB_SERVER, DB_NAME, DB_USER, DB_PASSWORD"
        )

    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SERVER};"
        f"DATABASE={DATABASE};"
        f"UID={USERNAME};"
        f"PWD={PASSWORD}"
    )
    return pyodbc.connect(conn_str)


def ensure_registry(conn: pyodbc.Connection) -> None:
    """جدول registry و unique index آن را در صورت نبود می‌سازد (idempotent)."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            IF OBJECT_ID(N'dbo.{TABLE}', N'U') IS NULL
            CREATE TABLE dbo.{TABLE} (
                Id            BIGINT IDENTITY(1,1) PRIMARY KEY,
                CodalReportId NVARCHAR(100) NOT NULL,
                LetterType    INT NOT NULL,
                Ticker        NVARCHAR(50) NULL,
                CompanyName   NVARCHAR(300) NULL,
                ReportTitle   NVARCHAR(1000) NULL,
                ReportDate    NVARCHAR(20) NULL,
                PublishedAt   DATETIME2 NULL,
                SourceUrl     NVARCHAR(2000) NULL,
                Status        NVARCHAR(30) NOT NULL,
                Attempts      INT NOT NULL DEFAULT 0,
                DiscoveredAt  DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                ProcessedAt   DATETIME2 NULL,
                ErrorMessage  NVARCHAR(MAX) NULL
            )
            """
        )
        # مهاجرت برای جدول‌های ساخته‌شده قبل از افزودن ستون Attempts
        cursor.execute(
            f"""
            IF COL_LENGTH('dbo.{TABLE}', 'Attempts') IS NULL
            ALTER TABLE dbo.{TABLE} ADD Attempts INT NOT NULL DEFAULT 0
            """
        )
        cursor.execute(
            f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE name = 'UX_CodalReports_ReportId'
                  AND object_id = OBJECT_ID(N'dbo.{TABLE}')
            )
            CREATE UNIQUE INDEX UX_CodalReports_ReportId
            ON dbo.{TABLE}(CodalReportId)
            """
        )
        cursor.execute(
            f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.indexes
                WHERE name = 'IX_CodalReports_LetterType_Status'
                  AND object_id = OBJECT_ID(N'dbo.{TABLE}')
            )
            CREATE INDEX IX_CodalReports_LetterType_Status
            ON dbo.{TABLE}(LetterType, Status)
            """
        )
        conn.commit()
    finally:
        cursor.close()


def get_statuses(
    conn: pyodbc.Connection, report_ids: list[str]
) -> dict[str, str]:
    """وضعیت گزارش‌های داده‌شده را برمی‌گرداند (برای تشخیص new/known)."""
    if not report_ids:
        return {}

    result: dict[str, str] = {}
    cursor = conn.cursor()
    try:
        placeholders = ",".join("?" for _ in report_ids)
        cursor.execute(
            f"""
            SELECT CodalReportId, Status
            FROM dbo.{TABLE}
            WHERE CodalReportId IN ({placeholders})
            """,
            *report_ids,
        )
        for report_id, status in cursor.fetchall():
            result[str(report_id)] = str(status)
    except pyodbc.Error as exc:
        # در حالت dry-run ممکن است جدول هنوز ساخته نشده باشد.
        logger.warning("⚠️ Could not read CodalReports (assuming empty): %s", exc)
        return {}
    finally:
        cursor.close()

    return result


def register_discovered(conn: pyodbc.Connection, report) -> str:
    """گزارش تازه‌کشف‌شده را ثبت می‌کند. خروجی: ``new`` یا ``exists``."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT 1 FROM dbo.{TABLE} WHERE CodalReportId = ?
            """,
            report.report_id,
        )
        if cursor.fetchone():
            return "exists"

        try:
            cursor.execute(
                f"""
                INSERT INTO dbo.{TABLE} (
                    CodalReportId, LetterType, Ticker, CompanyName,
                    ReportTitle, PublishedAt, SourceUrl, Status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                report.report_id,
                report.letter_type,
                report.ticker,
                report.company_name,
                (report.title or "")[:1000],
                report.published_at,
                (report.report_url or "")[:2000],
                STATUS_DISCOVERED,
            )
            conn.commit()
            return "new"
        except pyodbc.IntegrityError:
            # رقابت هم‌زمان: process دیگری زودتر درج کرده است.
            conn.rollback()
            return "exists"
    finally:
        cursor.close()


def claim_for_processing(
    conn: pyodbc.Connection, report_id: str, max_attempts: int = 3
) -> bool:
    """وضعیت را اگر هنوز پردازش‌نشده است به processing تغییر می‌دهد (اتمیک).

    گزارش‌هایی که به‌تعداد ``max_attempts`` بار fail شده‌اند دوباره claim نمی‌شوند.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE dbo.{TABLE}
            SET Status = ?, ProcessedAt = NULL, ErrorMessage = NULL,
                Attempts = Attempts + 1
            WHERE CodalReportId = ?
              AND Status IN (?, ?)
              AND Attempts < ?
            """,
            STATUS_PROCESSING,
            report_id,
            STATUS_DISCOVERED,
            STATUS_FAILED,
            max_attempts,
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        cursor.close()


def mark_completed(
    conn: pyodbc.Connection, report_id: str, report_date: str | None = None
) -> None:
    _set_status(conn, report_id, STATUS_COMPLETED, report_date=report_date)


def mark_unsupported(
    conn: pyodbc.Connection, report_id: str, reason: str | None = None
) -> None:
    _set_status(conn, report_id, STATUS_UNSUPPORTED, error=reason)


def mark_failed(conn: pyodbc.Connection, report_id: str, error: str) -> None:
    _set_status(conn, report_id, STATUS_FAILED, error=error)


def _set_status(
    conn: pyodbc.Connection,
    report_id: str,
    status: str,
    *,
    report_date: str | None = None,
    error: str | None = None,
) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE dbo.{TABLE}
            SET Status = ?,
                ProcessedAt = SYSUTCDATETIME(),
                ErrorMessage = ?,
                ReportDate = COALESCE(?, ReportDate)
            WHERE CodalReportId = ?
            """,
            status,
            (error or "")[:4000] or None,
            report_date,
            report_id,
        )
        conn.commit()
    finally:
        cursor.close()


def stats(conn: pyodbc.Connection) -> dict[str, int]:
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT Status, COUNT(*) FROM dbo.{TABLE} GROUP BY Status")
        return {str(status): int(count) for status, count in cursor.fetchall()}
    except pyodbc.Error:
        return {}
    finally:
        cursor.close()
