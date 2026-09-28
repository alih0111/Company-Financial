"""Unit tests for the analytics refresh orchestration (no DB required)."""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

import orchestrate_refresh as orf  # noqa: E402


def _run(as_of="2026-09-24", cutoff="2026-09-25T00:11:02+03:30", status="completed"):
    return ("run-1", dt.date.fromisoformat(as_of),
            dt.datetime.fromisoformat(cutoff), dt.datetime.now(dt.timezone.utc), status,
            "canonical-v1-dev+report-chain-ttm")


def test_no_completed_run_is_stale():
    r = orf.evaluate_staleness(None, {"market_latest_trade_date": dt.date(2026, 9, 25)})
    assert r["stale"] is True
    assert "no_completed_run" in r["reasons"]


def test_newer_market_trade_date_is_stale():
    cutoffs = {
        "monthly_latest": dt.date(2026, 9, 22),
        "financial_latest": dt.date(2026, 8, 22),
        "market_latest_trade_date": dt.date(2026, 9, 25),
        "market_latest_collected_at": dt.datetime.fromisoformat("2026-09-25T19:25:02+03:30"),
        "reports_latest_collected_at": dt.datetime.fromisoformat("2026-09-25T20:41:55+03:30"),
    }
    r = orf.evaluate_staleness(_run(), cutoffs)
    assert r["stale"] is True
    assert any("market trade_date" in x for x in r["reasons"])


def test_equal_dates_are_not_stale():
    cutoffs = {
        "monthly_latest": dt.date(2026, 9, 24),
        "financial_latest": dt.date(2026, 9, 24),
        "market_latest_trade_date": dt.date(2026, 9, 24),
        "market_latest_collected_at": dt.datetime.fromisoformat("2026-09-24T20:00:00+03:30"),
        "reports_latest_collected_at": dt.datetime.fromisoformat("2026-09-24T20:00:00+03:30"),
    }
    r = orf.evaluate_staleness(_run(cutoff="2026-09-24T20:41:02+03:30"), cutoffs)
    assert r["stale"] is False, r["reasons"]


def test_newer_collected_at_is_stale_even_if_same_date():
    cutoffs = {
        "monthly_latest": dt.date(2026, 9, 24),
        "financial_latest": dt.date(2026, 9, 24),
        "market_latest_trade_date": dt.date(2026, 9, 24),
        "market_latest_collected_at": dt.datetime.fromisoformat("2026-09-24T23:59:00+03:30"),
        "reports_latest_collected_at": None,
    }
    r = orf.evaluate_staleness(_run(cutoff="2026-09-24T20:41:02+03:30"), cutoffs)
    assert r["stale"] is True
    assert any("collected_at" in x for x in r["reasons"])


def test_choose_as_of_cutoff_prefers_latest_dates():
    cutoffs = {
        "monthly_latest": dt.date(2026, 9, 22),
        "financial_latest": dt.date(2026, 8, 22),
        "market_latest_trade_date": dt.date(2026, 9, 25),
        "market_latest_collected_at": dt.datetime.fromisoformat("2026-09-25T19:25:02+03:30"),
        "reports_latest_collected_at": dt.datetime.fromisoformat("2026-09-25T20:41:55+03:30"),
    }
    as_of, cutoff = orf.choose_as_of_cutoff(cutoffs)
    assert as_of == dt.date(2026, 9, 25)
    assert cutoff == dt.datetime.fromisoformat("2026-09-25T20:41:55+03:30")


def test_ingestion_health_missing_is_not_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr(orf, "INGESTION_STATUS", tmp_path / "missing.json")
    h = orf.read_ingestion_health()
    assert h["available"] is False
    assert h["degraded"] is False


def test_ingestion_health_degrades_on_nonhealthy(tmp_path, monkeypatch):
    p = tmp_path / "status.json"
    p.write_text(
        '{"domains": {"MARKET_PRICE": {"health": "CANONICAL_BEHIND"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(orf, "INGESTION_STATUS", p)
    h = orf.read_ingestion_health()
    assert h["available"] is True
    assert h["degraded"] is True
