"""Watermark به‌ازای هر feed برای incremental کردن Quick Sync.

برای هر ``LetterType`` جداگانه نگه داشته می‌شود. مقدار، «جدیدترین PublishDateTime
که تا آن نقطه sync شده است» است. اجرای بعدی صفحه‌ها را از جدید به قدیم می‌خواند
و وقتی به گزارش‌های قدیمی‌تر از ``watermark - overlap`` رسید متوقف می‌شود.
"""

from __future__ import annotations

from datetime import datetime

TABLE = "CodalSyncState"


def ensure_state(conn) -> None:
    """جدول CodalSyncState را در صورت نبود می‌سازد (idempotent)."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            IF OBJECT_ID(N'dbo.{TABLE}', N'U') IS NULL
            CREATE TABLE dbo.{TABLE} (
                LetterType         INT NOT NULL PRIMARY KEY,
                LastSuccessfulSync DATETIME2 NULL,
                UpdatedAt          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
            """
        )
        conn.commit()
    finally:
        cursor.close()


def get_watermark(conn, letter_type: int) -> datetime | None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"SELECT LastSuccessfulSync FROM dbo.{TABLE} WHERE LetterType = ?",
            letter_type,
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else None
    except Exception:  # noqa: BLE001 - جدول ممکن است هنوز نباشد
        return None
    finally:
        cursor.close()


def set_watermark(conn, letter_type: int, when: datetime) -> None:
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            IF EXISTS (SELECT 1 FROM dbo.{TABLE} WHERE LetterType = ?)
                UPDATE dbo.{TABLE}
                SET LastSuccessfulSync = ?, UpdatedAt = SYSUTCDATETIME()
                WHERE LetterType = ?
            ELSE
                INSERT INTO dbo.{TABLE} (LetterType, LastSuccessfulSync)
                VALUES (?, ?)
            """,
            letter_type,
            when,
            letter_type,
            letter_type,
            when,
        )
        conn.commit()
    finally:
        cursor.close()


__all__ = ["TABLE", "ensure_state", "get_watermark", "set_watermark"]
