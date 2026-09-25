"""Canonical PostgreSQL ingestion layer (Phase 1 dual-write).

Targets the canonical schema (core/ingestion/raw/fundamentals/market) and is
invoked alongside the existing SQL Server ingestion path. SQL Server remains
authoritative and unchanged; the canonical write is additive and best-effort.
"""

from .config import IngestionMode, load_mode, canonical_dsn
from .db import transaction, connect
from .writer import CanonicalWriter
from .service import (
    dual_write_monthly,
    dual_write_financial,
    dual_write_market,
    dual_write_report,
    DualWriteResult,
)

__all__ = [
    "IngestionMode",
    "load_mode",
    "canonical_dsn",
    "transaction",
    "connect",
    "CanonicalWriter",
    "dual_write_monthly",
    "dual_write_financial",
    "dual_write_market",
    "dual_write_report",
    "DualWriteResult",
]
