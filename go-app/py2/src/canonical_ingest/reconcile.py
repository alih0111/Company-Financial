"""Post dual-write reconciliation: legacy input vs canonical output."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

EXACT_EQUIVALENT = "EXACT_EQUIVALENT"
EXPECTED_UNIT_CONVERSION = "EXPECTED_UNIT_CONVERSION"
EXPECTED_CANONICAL_SEMANTIC_CHANGE = "EXPECTED_CANONICAL_SEMANTIC_CHANGE"
LEGACY_ONLY_HEURISTIC = "LEGACY_ONLY_HEURISTIC"
CANONICAL_ONLY_METADATA = "CANONICAL_ONLY_METADATA"
MISSING_CANONICAL = "MISSING_CANONICAL"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
NUMERIC_MISMATCH = "NUMERIC_MISMATCH"
DATE_MISMATCH = "DATE_MISMATCH"
WRITE_ERROR = "WRITE_ERROR"
UNCLASSIFIED = "UNCLASSIFIED"

ALL_CLASSIFICATIONS = [
    EXACT_EQUIVALENT, EXPECTED_UNIT_CONVERSION, EXPECTED_CANONICAL_SEMANTIC_CHANGE,
    LEGACY_ONLY_HEURISTIC, CANONICAL_ONLY_METADATA, MISSING_CANONICAL,
    IDENTITY_MISMATCH, NUMERIC_MISMATCH, DATE_MISMATCH, WRITE_ERROR, UNCLASSIFIED,
]


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _eq(a: Any, b: Any, tol: Decimal = Decimal("0.000001")) -> bool:
    da, db = _dec(a), _dec(b)
    if da is None and db is None:
        return True
    if da is None or db is None:
        return False
    return abs(da - db) <= tol


def reconcile_monthly(legacy: dict, canon: Optional[dict]) -> str:
    if canon is None:
        return MISSING_CANONICAL
    if not _eq(legacy.get("production_quantity"), canon.get("production_quantity")):
        return NUMERIC_MISMATCH
    if not _eq(legacy.get("sales_quantity"), canon.get("sales_quantity")):
        return NUMERIC_MISMATCH
    if not _eq(legacy.get("reported_sales_amount"), canon.get("reported_sales_amount")):
        return NUMERIC_MISMATCH
    if _eq(canon.get("sales_amount_rial"), _mul(canon.get("reported_sales_amount"), 1000000)):
        return EXPECTED_UNIT_CONVERSION
    return NUMERIC_MISMATCH


def reconcile_fact(legacy: dict, canon: Optional[dict]) -> str:
    if canon is None:
        return MISSING_CANONICAL
    if canon.get("metric_code") != legacy.get("metric_code"):
        return IDENTITY_MISMATCH
    if not _eq(legacy.get("reported_value"), canon.get("reported_value")):
        return NUMERIC_MISMATCH
    # money: canonical_value = reported_value * 1e6 for million_rial sources
    if legacy.get("kind") == "m":
        if _eq(canon.get("canonical_value"), _mul(canon.get("reported_value"), 1000000)):
            return EXPECTED_UNIT_CONVERSION
        return NUMERIC_MISMATCH
    if _eq(canon.get("canonical_value"), canon.get("reported_value")):
        return EXACT_EQUIVALENT
    return NUMERIC_MISMATCH


def reconcile_market(legacy: dict, canon: Optional[dict]) -> str:
    if canon is None:
        return MISSING_CANONICAL
    if str(canon.get("trade_date")) != str(legacy.get("trade_date")):
        return DATE_MISMATCH
    if _eq(canon.get("closing_price_rial"), legacy.get("closing_price_rial")) and \
       _eq(canon.get("volume"), legacy.get("volume")):
        return EXACT_EQUIVALENT
    return NUMERIC_MISMATCH


def _mul(value: Any, factor: int) -> Optional[Decimal]:
    d = _dec(value)
    return None if d is None else d * factor
