"""Unit tests for canonical_ingest (no database required)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from canonical_ingest import config
from canonical_ingest.config import IngestionMode, writes_canonical
from canonical_ingest.reconcile import (
    EXACT_EQUIVALENT, EXPECTED_UNIT_CONVERSION, MISSING_CANONICAL, NUMERIC_MISMATCH,
    reconcile_fact, reconcile_market, reconcile_monthly,
)
from canonical_ingest.service import dual_write_monthly
from canonical_ingest.writer import _observation_hash


def test_default_mode_is_legacy_only(monkeypatch):
    monkeypatch.delenv("CDF_INGESTION_MODE", raising=False)
    assert config.load_mode() == IngestionMode.LEGACY_ONLY
    assert writes_canonical() is False


def test_mode_parsing(monkeypatch):
    for raw, want in [("dual_write", IngestionMode.DUAL_WRITE),
                      ("canonical_only", IngestionMode.CANONICAL_ONLY),
                      ("bogus", IngestionMode.LEGACY_ONLY)]:
        monkeypatch.setenv("CDF_INGESTION_MODE", raw)
        assert config.load_mode() == want


def test_canonical_only_not_default(monkeypatch):
    monkeypatch.delenv("CDF_INGESTION_MODE", raising=False)
    assert config.load_mode() != IngestionMode.CANONICAL_ONLY


def test_legacy_only_makes_no_canonical_write(monkeypatch):
    monkeypatch.setenv("CDF_INGESTION_MODE", "legacy_only")
    res = dual_write_monthly(legacy_company_id="x", period_end_date="2026-01-01")
    assert res.status == "skipped_legacy_only"
    assert res.inserted == 0


def test_dsn_prefix_guard(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/production_pg")
    monkeypatch.delenv("CDF_CANONICAL_DB", raising=False)
    monkeypatch.delenv("CDF_PILOT_DB", raising=False)
    monkeypatch.delenv("CDF_ALLOW_NON_TEST_PG", raising=False)
    with pytest.raises(RuntimeError):
        config.canonical_dsn()


def test_dsn_strips_dialect_and_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/postgres")
    monkeypatch.setenv("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")
    dsn = config.canonical_dsn()
    assert dsn.startswith("postgresql://")
    assert "+psycopg" not in dsn
    assert dsn.endswith("/company_financial_analytics_shadow_v121")


def test_reconcile_monthly_unit_conversion():
    legacy = {"production_quantity": Decimal("10"), "sales_quantity": Decimal("9"),
              "reported_sales_amount": Decimal("500")}
    canon = {"production_quantity": Decimal("10"), "sales_quantity": Decimal("9"),
             "reported_sales_amount": Decimal("500"), "sales_amount_rial": Decimal("500000000")}
    assert reconcile_monthly(legacy, canon) == EXPECTED_UNIT_CONVERSION
    assert reconcile_monthly(legacy, None) == MISSING_CANONICAL
    bad = dict(canon, sales_quantity=Decimal("8"))
    assert reconcile_monthly(legacy, bad) == NUMERIC_MISMATCH


def test_reconcile_fact_units():
    legacy = {"metric_code": "revenue", "reported_value": Decimal("100"), "kind": "m"}
    canon = {"metric_code": "revenue", "reported_value": Decimal("100"), "canonical_value": Decimal("100000000")}
    assert reconcile_fact(legacy, canon) == EXPECTED_UNIT_CONVERSION
    eps = {"metric_code": "eps", "reported_value": Decimal("255"), "kind": "ps"}
    canon_eps = {"metric_code": "eps", "reported_value": Decimal("255"), "canonical_value": Decimal("255")}
    assert reconcile_fact(eps, canon_eps) == EXACT_EQUIVALENT


def test_reconcile_market():
    L = {"trade_date": "2026-09-24", "closing_price_rial": Decimal("100"), "volume": 5}
    C = {"trade_date": "2026-09-24", "closing_price_rial": Decimal("100"), "volume": 5}
    assert reconcile_market(L, C) == EXACT_EQUIVALENT
    assert reconcile_market(L, None) == MISSING_CANONICAL
    assert reconcile_market(L, dict(C, closing_price_rial=Decimal("101"))) == NUMERIC_MISMATCH


def test_observation_hash_deterministic_and_sensitive():
    v = {"closing_price_rial": Decimal("100"), "volume": 5}
    h1 = _observation_hash("sec", "2026-09-24", "brs", v)
    h2 = _observation_hash("sec", "2026-09-24", "brs", v)
    assert h1 == h2
    assert _observation_hash("sec", "2026-09-25", "brs", v) != h1
    assert _observation_hash("sec", "2026-09-24", "brs", dict(v, volume=6)) != h1
