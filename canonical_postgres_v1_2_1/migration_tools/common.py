"""Shared helpers for the pilot migration tooling (read-only source, guarded target)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
BASE = HERE.parent  # canonical_postgres_v1_2_1
REPO = BASE.parent
SQL_DIR = BASE / "sql"
PILOT_DIR = BASE / "pilot_migration"

PILOT_DB = os.getenv("CDF_PILOT_DB", "company_financial_migration_pilot_v121")
# Allowed target-database prefixes (safety guard). Any target DB must start with one.
ALLOWED_DB_PREFIXES = (
    "company_financial_migration_pilot_",
    "company_financial_analytics_shadow_",
    "company_financial_test_",
)

SQL_ORDER = [
    "001_extensions.sql", "010_core.sql", "020_ingestion.sql", "030_raw.sql",
    "040_fundamentals.sql", "050_market.sql", "060_auth.sql", "070_portfolio.sql",
    "080_analytics.sql", "090_indexes.sql", "100_family.sql", "110_family_broker.sql",
    "121_analytics_run_identity.sql",
]


def load_env():
    load_dotenv(REPO / "go-app" / ".env")
    load_dotenv(REPO / "go-app" / "py2" / ".env", override=False)


def sqlserver_conn():
    import pyodbc

    load_env()
    cs = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};PWD={os.getenv('DB_PASSWORD')};TrustServerCertificate=yes;"
    )
    cn = pyodbc.connect(cs, timeout=60)
    cn.autocommit = True  # read-only usage; avoids holding locks
    return cn


def _pg_params(dbname: str) -> dict:
    load_env()
    url = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg", "postgresql")
    p = urlparse(url)
    return {
        "host": p.hostname or "localhost",
        "port": p.port or 5432,
        "user": unquote(p.username) if p.username else None,
        "password": unquote(p.password) if p.password else None,
        "dbname": dbname,
    }


def pg_pilot_conn(autocommit: bool = False):
    import psycopg

    if not PILOT_DB.startswith(ALLOWED_DB_PREFIXES):
        raise RuntimeError(f"Refusing: target DB {PILOT_DB!r} is not an allowed test/shadow database")
    return psycopg.connect(**_pg_params(PILOT_DB), connect_timeout=15, autocommit=autocommit)


def pg_maintenance_conn():
    import psycopg

    return psycopg.connect(**_pg_params("postgres"), connect_timeout=15, autocommit=True)


# ---- jalali <-> gregorian ----
try:
    import jdatetime

    def jalali_to_gregorian(text: str) -> date | None:
        if not text:
            return None
        m = re.search(r"((?:13|14)\d{2})[/-](\d{1,2})[/-](\d{1,2})", str(text))
        if not m:
            return None
        y, mo, d = (int(x) for x in m.groups())
        try:
            return jdatetime.date(y, mo, d).togregorian()
        except Exception:
            return None

except Exception:  # pragma: no cover
    jalali_to_gregorian = lambda text: None  # noqa: E731


def to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def scale_rial(value, multiplier=Decimal(1000000)):
    v = to_decimal(value)
    return None if v is None else v * multiplier


def obs_hash(security_id, trade_date, price_series, source, adj_version, fields) -> str:
    payload = {
        "security_id": str(security_id),
        "trade_date": str(trade_date),
        "price_series": price_series,
        "source": source,
        "adjustment_version": adj_version,
        "f": fields,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def write_report(name: str, text: str):
    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    (PILOT_DIR / name).write_text(text.rstrip() + "\n", encoding="utf-8")
