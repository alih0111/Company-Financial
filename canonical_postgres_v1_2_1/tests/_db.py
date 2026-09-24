"""Shared DB connection helpers for the v1.2.1 test suite.

SAFETY:
  * Reads the PostgreSQL server/user/password from go-app/py2/.env (gitignored),
    but ALWAYS overrides the database name to the dedicated test database.
  * Refuses to operate unless the target database name matches the expected
    test-database pattern. This prevents accidental use of `postgres` (py2 prod).
  * Never prints or stores credentials.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE.parent
ENV_FILE = REPO / "go-app" / "py2" / ".env"

TEST_DB = os.getenv("CDF_TEST_DB", "company_financial_test_v121")
TEST_DB_PREFIX = "company_financial_test_"


def _parse_env_url() -> dict:
    load_dotenv(ENV_FILE)
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not found in go-app/py2/.env")
    # strip sqlalchemy driver prefix if present
    url = url.replace("postgresql+psycopg", "postgresql")
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
    }


def server_params() -> dict:
    p = _parse_env_url()
    return {k: v for k, v in p.items() if k in ("host", "port", "user", "password")}


def test_params() -> dict:
    if not TEST_DB.startswith(TEST_DB_PREFIX):
        raise RuntimeError(
            f"Refusing: test database name {TEST_DB!r} does not start with "
            f"{TEST_DB_PREFIX!r}. This is a safety guard."
        )
    p = server_params()
    p["dbname"] = TEST_DB
    return p


def maintenance_params() -> dict:
    p = server_params()
    p["dbname"] = "postgres"  # only used to CREATE/DROP the test database
    return p


def connect(dbname_params: dict, autocommit: bool = False):
    import psycopg

    conn = psycopg.connect(**dbname_params, connect_timeout=10)
    conn.autocommit = autocommit
    return conn


def connect_test(autocommit: bool = False):
    return connect(test_params(), autocommit=autocommit)
