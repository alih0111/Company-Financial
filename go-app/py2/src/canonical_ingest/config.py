from __future__ import annotations

import os
import urllib.parse
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

# Only test/shadow/pilot databases may receive canonical writes.
_ALLOWED_DB_PREFIXES = (
    "company_financial_analytics_shadow_",
    "company_financial_migration_pilot_",
    "company_financial_test_",
)

_ENV_MODE = "CDF_INGESTION_MODE"
_ENV_ALLOW_NON_TEST = "CDF_ALLOW_NON_TEST_PG"


class IngestionMode(str, Enum):
    LEGACY_ONLY = "legacy_only"
    DUAL_WRITE = "dual_write"
    CANONICAL_ONLY = "canonical_only"


def _load_env_files() -> None:
    """Load .env files from the repo without overriding existing variables."""
    here = Path(__file__).resolve()
    # .../go-app/py2/src/canonical_ingest/config.py -> go-app
    go_app = here.parents[3]
    for candidate in (go_app / ".env", go_app / "py2" / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def load_mode() -> IngestionMode:
    _load_env_files()
    raw = os.environ.get(_ENV_MODE, "").strip().lower()
    if raw in ("dual_write", "dual-write", "dualwrite"):
        return IngestionMode.DUAL_WRITE
    if raw in ("canonical_only", "canonical-only"):
        return IngestionMode.CANONICAL_ONLY
    return IngestionMode.LEGACY_ONLY


def writes_canonical(mode: IngestionMode | None = None) -> bool:
    mode = mode or load_mode()
    return mode in (IngestionMode.DUAL_WRITE, IngestionMode.CANONICAL_ONLY)


def _database_name(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.path.lstrip("/")


def canonical_dsn() -> str:
    """Return a psycopg DSN for the canonical database.

    Reads DATABASE_URL (SQLAlchemy form), strips the ``+psycopg`` dialect, applies
    CDF_CANONICAL_DB / CDF_PILOT_DB override, and refuses non test/shadow/pilot
    databases unless CDF_ALLOW_NON_TEST_PG=1.
    """
    _load_env_files()
    raw = (
        os.environ.get("CANONICAL_DATABASE_URL")
        or os.environ.get("CDF_CANONICAL_URL")
        or os.environ.get("DATABASE_URL")
        or ""
    ).strip()
    if not raw:
        raise RuntimeError("canonical DSN not configured (DATABASE_URL empty)")
    parsed = urllib.parse.urlparse(raw)
    scheme = parsed.scheme.split("+", 1)[0]
    if scheme not in ("postgres", "postgresql"):
        raise RuntimeError(f"canonical DSN must be postgres, got {parsed.scheme}")

    db = (os.environ.get("CDF_CANONICAL_DB") or os.environ.get("CDF_PILOT_DB") or "").strip() \
        or parsed.path.lstrip("/")
    if not db:
        raise RuntimeError("canonical DSN has no database name")
    allow = os.environ.get(_ENV_ALLOW_NON_TEST, "").strip().lower() in ("1", "true", "yes")
    if not allow and not db.startswith(_ALLOWED_DB_PREFIXES):
        raise RuntimeError(
            f"refusing to write to database {db!r}: not an allowed test/shadow/pilot name "
            f"(set {_ENV_ALLOW_NON_TEST}=1 to override)"
        )

    # Rebuild a libpq-style DSN (psycopg accepts URL too; keep URL form).
    netloc = parsed.netloc
    return f"postgresql://{netloc}/{db}"
