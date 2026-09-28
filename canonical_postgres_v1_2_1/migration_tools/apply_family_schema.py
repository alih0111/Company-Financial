"""Apply the idempotent `family` schema (100_family.sql) to an existing database.

Safety:
  * Only connects to an allowed test/shadow database (name-prefixed guard).
  * Executes a single idempotent file; no DROP, no data mutation.
  * Intended for the live shadow DB (CDF_CANONICAL_DB) without a full rebuild.

Run:
    python canonical_postgres_v1_2_1/migration_tools/apply_family_schema.py
"""

from __future__ import annotations

import os
import pathlib
import sys
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE.parent
SQL_FILES = [BASE / "sql" / "100_family.sql", BASE / "sql" / "110_family_broker.sql"]

ALLOWED_DB_PREFIXES = (
    "company_financial_migration_pilot_",
    "company_financial_analytics_shadow_",
    "company_financial_test_",
)


def main() -> int:
    load_dotenv(REPO / "go-app" / ".env")
    dbname = (
        os.getenv("CDF_CANONICAL_DB")
        or os.getenv("CDF_PILOT_DB")
        or ""
    ).strip()
    if not dbname:
        print("FAIL: neither CDF_CANONICAL_DB nor CDF_PILOT_DB is set")
        return 1
    if not dbname.startswith(ALLOWED_DB_PREFIXES):
        print(f"FAIL: refusing to write to {dbname!r} (not an allowed test/shadow prefix)")
        return 1

    url = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg", "postgresql")
    p = urlparse(url)
    if p.scheme.split("+")[0] not in ("postgres", "postgresql"):
        print(f"FAIL: DATABASE_URL must be postgres, got {p.scheme!r}")
        return 1

    import psycopg

    conn = psycopg.connect(
        host=p.hostname or "localhost",
        port=p.port or 5432,
        user=unquote(p.username) if p.username else None,
        password=unquote(p.password) if p.password else None,
        dbname=dbname,
        connect_timeout=15,
        autocommit=True,
    )
    try:
        for path in SQL_FILES:
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
            print(f"applied {path.name}")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'family' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            tables = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    print(f"applied 100_family.sql to {dbname}")
    print("family tables:", ", ".join(tables) if tables else "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
