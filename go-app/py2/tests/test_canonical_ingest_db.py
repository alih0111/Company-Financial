"""DB-backed tests for canonical_ingest.

These run only when a canonical DSN is configured (shadow/test database). They
are idempotent by design and do not create duplicate normalized rows.
"""

from __future__ import annotations

import os
from decimal import Decimal

import jdatetime
import pytest

from canonical_ingest import config
from canonical_ingest.db import transaction
from canonical_ingest.service import dual_write_financial, dual_write_market, dual_write_monthly

COMPANY_MONTHLY = "b88121029d7e973410b008320f8fe378"   # قاسم
COMPANY_FINANCIAL = "6dd3fb203bb12fdd017e1f59fc61b9c6"  # تاصیکو
COMPANY_MARKET = "959eac0c9aaf26d5f523b9008fb87bdf"      # زگلدشت


def _configured() -> bool:
    try:
        config._load_env_files()
        return bool(config.canonical_dsn())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _configured(), reason="canonical DSN not configured")


def _gregorian(jalali: str) -> str:
    y, m, d = (int(x) for x in jalali.split("/"))
    return jdatetime.date(y, m, d).togregorian().isoformat()


def _scalar(sql, params):
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def test_monthly_dual_write_is_idempotent():
    g = _gregorian("1405/06/31")
    kw = dict(legacy_company_id=COMPANY_MONTHLY, period_end_date=g,
              jalali_period_text="1405/06/31", production_quantity=Decimal("0"),
              sales_quantity=Decimal("0"), reported_sales_amount=Decimal("1"),
              sales_amount_rial=Decimal("1000000"))
    r1 = dual_write_monthly(**kw)
    n_after_first = _scalar(
        """SELECT count(*) FROM fundamentals.monthly_activities ma
           JOIN core.legacy_entity_map lem
             ON lem.entity_type='company' AND lem.target_uuid=ma.company_id AND lem.legacy_key=%s
           WHERE ma.period_end_date=%s""", (COMPANY_MONTHLY, g))
    r2 = dual_write_monthly(**kw)
    n_after_second = _scalar(
        """SELECT count(*) FROM fundamentals.monthly_activities ma
           JOIN core.legacy_entity_map lem
             ON lem.entity_type='company' AND lem.target_uuid=ma.company_id AND lem.legacy_key=%s
           WHERE ma.period_end_date=%s""", (COMPANY_MONTHLY, g))
    assert r1.status == "written"
    assert r2.status == "written"
    assert r2.inserted == 0  # second run creates nothing new
    assert n_after_first >= 1
    assert n_after_second == n_after_first  # no duplicate period introduced


def test_financial_dual_write_is_idempotent():
    g = _gregorian("1405/05/31")
    facts = [{
        "statement_type": "income_statement", "metric_code": "revenue", "period_order": 1,
        "comparison_type": "current", "reported_value": Decimal("123"), "reported_unit": "million_rial",
        "canonical_value": Decimal("123000000"), "canonical_unit": "rial", "kind": "m",
    }]
    facts_sql = """SELECT count(*) FROM fundamentals.financial_facts f
                   JOIN fundamentals.financial_statements fs ON fs.id=f.statement_id
                   JOIN core.legacy_entity_map lem
                     ON lem.entity_type='company' AND lem.target_uuid=fs.company_id AND lem.legacy_key=%s
                   WHERE fs.period_end_date=%s AND f.metric_code='revenue' AND f.period_order=1"""
    r1 = dual_write_financial(legacy_company_id=COMPANY_FINANCIAL, period_end_date=g, facts=facts)
    n1 = _scalar(facts_sql, (COMPANY_FINANCIAL, g))
    r2 = dual_write_financial(legacy_company_id=COMPANY_FINANCIAL, period_end_date=g, facts=facts)
    n2 = _scalar(facts_sql, (COMPANY_FINANCIAL, g))
    assert r1.status == "written"
    assert r2.inserted == 0
    assert n1 >= 1
    assert n2 == n1


def test_market_append_only_idempotent_and_collected_at_preserved():
    obs = {
        "trade_date": "2026-09-24", "jalali_date_text": "1405/07/02",
        "closing_price_rial": Decimal("10060"), "volume": 9652539,
        "collected_at": "2026-09-24T17:01:00+03:30", "price_series": "adjusted", "is_adjusted": True,
    }
    count_sql = """SELECT count(*) FROM market.price_observations po
                   JOIN core.legacy_entity_map lem
                     ON lem.entity_type='security' AND lem.target_uuid=po.security_id AND lem.legacy_key=%s
                   WHERE po.trade_date=%s AND po.source='brs'"""
    r1 = dual_write_market(legacy_company_id=COMPANY_MARKET, observations=[obs])
    n1 = _scalar(count_sql, (COMPANY_MARKET, "2026-09-24"))
    r2 = dual_write_market(legacy_company_id=COMPANY_MARKET, observations=[obs])
    n2 = _scalar(count_sql, (COMPANY_MARKET, "2026-09-24"))
    assert r1.status == "written"
    assert r2.inserted == 0  # append-only dedup by observation hash
    assert n2 == n1  # rerunning our writer appends nothing
    preserved = _scalar(
        """SELECT count(*) FROM market.price_observations po
           JOIN core.legacy_entity_map lem
             ON lem.entity_type='security' AND lem.target_uuid=po.security_id AND lem.legacy_key=%s
           WHERE po.trade_date=%s AND po.source='brs'
             AND to_char(po.collected_at, 'YYYY-MM-DD HH24:MI:SS') = '2026-09-24 17:01:00'""",
        (COMPANY_MARKET, "2026-09-24"))
    assert preserved >= 1  # actual collection time preserved, not migration time


def test_unresolved_identity_is_quarantined():
    res = dual_write_monthly(legacy_company_id="__no_such_legacy_id__", period_end_date="2026-01-01")
    assert res.status == "quarantined"
    n = _scalar(
        """SELECT count(*) FROM ingestion.data_quality_issues
           WHERE issue_code='identity_conflict'
             AND details->>'legacy_company_id' = '__no_such_legacy_id__'""", ())
    assert n >= 1


def test_canonical_constraint_failure_rolls_back():
    # Invalid metric_code -> FK violation -> whole transaction rolls back.
    facts = [{
        "statement_type": "income_statement", "metric_code": "__not_a_metric__",
        "period_order": 1, "comparison_type": "current", "reported_value": Decimal("1"),
        "reported_unit": "rial", "canonical_value": Decimal("1"), "canonical_unit": "rial", "kind": "m",
    }]
    res = dual_write_financial(legacy_company_id=COMPANY_FINANCIAL,
                               period_end_date="1990-01-01", facts=facts)
    assert res.status == "canonical_error"
    n = _scalar(
        """SELECT count(*) FROM fundamentals.financial_statements fs
           JOIN core.legacy_entity_map lem
             ON lem.entity_type='company' AND lem.target_uuid=fs.company_id AND lem.legacy_key=%s
           WHERE fs.period_end_date='1990-01-01'""", (COMPANY_FINANCIAL,))
    assert n == 0


def test_postgres_unavailable_is_isolated(monkeypatch):
    monkeypatch.setenv("CDF_CANONICAL_DB", "definitely_production_db")
    monkeypatch.delenv("CDF_ALLOW_NON_TEST_PG", raising=False)
    res = dual_write_monthly(legacy_company_id=COMPANY_MONTHLY, period_end_date="2026-01-01")
    assert res.status == "canonical_error"
