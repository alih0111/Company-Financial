"""Unit tests for the analytics refresh orchestration (no DB required).

The staleness contract is *input-watermark* based: a run records the fingerprint of
everything it consumed, and staleness is "the fingerprint moved". That replaced a
date-comparison rule which could not see a report that arrived for a period older
than the run's as_of (a backfill) — the exact failure these tests guard.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

import orchestrate_refresh as orf  # noqa: E402


def _run(as_of="2026-10-06", cutoff="2026-10-06T11:32:00+03:30", status="completed",
         watermark=None, run_seq=24):
    """A score_runs row shaped like latest_serving_run(): index 7 is input_watermark."""
    return ("run-1", dt.date.fromisoformat(as_of),
            dt.datetime.fromisoformat(cutoff), dt.datetime.now(dt.timezone.utc), status,
            "canonical-v1-dev+report-chain-ttm", run_seq, watermark)


def _wm(rows=100, date="2026-09-22", arrival="2026-10-05T18:35:00+03:30", digest="d1"):
    """A one-domain watermark; the shape mirrors compute_metrics.input_watermark()."""
    return {"v": 1, "domains": {
        "monthly": {"date": date, "arrival": arrival, "rows": rows, "digest": digest}}}


def test_no_completed_run_is_stale():
    r = orf.evaluate_staleness(None, _wm())
    assert r["stale"] is True
    assert "no_completed_run" in r["reasons"]


def test_run_without_watermark_is_stale():
    """Pre-migration runs carry '{}'; they must never read as fresh."""
    r = orf.evaluate_staleness(_run(watermark={}), _wm())
    assert r["stale"] is True
    assert any("watermark" in x for x in r["reasons"])


def test_identical_watermark_is_not_stale():
    wm = _wm()
    r = orf.evaluate_staleness(_run(watermark=wm), wm)
    assert r["stale"] is False, r["reasons"]


def test_backfilled_older_period_is_stale():
    """THE regression: a report for a period OLDER than the run's as_of.

    The old rule compared `monthly_latest.period_end_date > run.as_of_date`, which is
    False here (2026-09-22 < 2026-10-06), so a backfilled month was invisible. The
    watermark sees it: the row count grew even though the data date did not advance.
    """
    run_wm = _wm(rows=100, date="2026-09-22")
    current = _wm(rows=103, date="2026-09-22",
                  arrival="2026-10-08T17:50:00+03:30", digest="d2")
    r = orf.evaluate_staleness(_run(as_of="2026-10-06", watermark=run_wm), current)
    assert r["stale"] is True
    assert any(x.startswith("monthly") for x in r["reasons"])


def test_data_date_beyond_as_of_is_stale():
    run_wm = _wm(rows=100, date="2026-09-22")
    current = _wm(rows=101, date="2026-10-22")  # a genuinely new month
    r = orf.evaluate_staleness(_run(as_of="2026-10-06", watermark=run_wm), current)
    assert r["stale"] is True
    assert any("data date" in x for x in r["reasons"])


def test_in_place_content_change_is_stale():
    """Same row count and arrival, different content: only the digest moves."""
    run_wm = _wm(rows=100, digest="d1")
    current = _wm(rows=100, digest="d2")
    r = orf.evaluate_staleness(_run(watermark=run_wm), current)
    assert r["stale"] is True
    assert any("content changed" in x for x in r["reasons"])


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
