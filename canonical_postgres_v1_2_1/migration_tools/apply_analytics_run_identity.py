"""Apply the idempotent analytics run-identity migration (121_analytics_run_identity.sql).

Adds `score_runs.run_seq` / `input_watermark` / `run_kind` and makes
`metric_snapshots` run-scoped, so the served score is selected by run recency and a
same-as_of recompute is storable instead of colliding.

Safety:
  * Only connects to an allowed test/shadow database (name-prefixed guard).
  * Executes a single idempotent file; no DROP TABLE, no data deletion.
  * The one DROP INDEX replaces a unique key that is re-created run-scoped in the same
    file; the backfill is verified exact before `run_id` is made NOT NULL.

Run:
    python canonical_postgres_v1_2_1/migration_tools/apply_analytics_run_identity.py
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
SQL_FILES = [BASE / "sql" / "121_analytics_run_identity.sql"]

ALLOWED_DB_PREFIXES = (
    "company_financial_migration_pilot_",
    "company_financial_analytics_shadow_",
    "company_financial_test_",
)


def main() -> int:
    load_dotenv(REPO / "go-app" / ".env")
    dbname = (os.getenv("CDF_CANONICAL_DB") or os.getenv("CDF_PILOT_DB") or "").strip()
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
        autocommit=False,
    )
    try:
        for path in SQL_FILES:
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
            print(f"applied {path.name}")
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT count(*) FILTER (WHERE run_kind = 'serving'),
                          count(*) FILTER (WHERE run_kind = 'pit_backfill'),
                          count(*) FILTER (WHERE input_watermark <> '{}'::jsonb)
                     FROM analytics.score_runs"""
            )
            serving, pit, watermarked = cur.fetchone()
            cur.execute(
                """SELECT count(*) FROM analytics.metric_snapshots WHERE run_id IS NULL"""
            )
            unmapped = cur.fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"applied 121 to {dbname}")
    print(f"score_runs: serving={serving} pit_backfill={pit} watermarked={watermarked}")
    print(f"metric_snapshots unmapped run_id: {unmapped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
