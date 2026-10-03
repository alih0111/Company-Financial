"""Build point-in-time signal snapshots by reusing analytics_canonical_v1.

No formula duplication: the canonical Engine is invoked with the historical
as_of/cutoff. The snapshot is frozen BEFORE any forward return is computed.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
CANON = BASE / "analytics_canonical_v1"
for p in (str(CANON), str(BASE / "migration_tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import compute_metrics as CM  # noqa: E402
from assess_readiness import FACTOR_SOURCE, CATEGORY  # noqa: E402


def end_of_day_utc(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=dt.timezone.utc)


def build_snapshot(as_of_date: dt.date, price_store=None):
    # Historical market PIT uses trade_date as the availability proxy because
    # canonical collected_at is migration metadata, not historical availability.
    # valuation="legacy": canonical share snapshots only start at 2026-09-29, so
    # a historical as_of has no PIT market cap. Reusing today's share count would
    # be look-ahead, so the EPS-based path is kept (and labeled) for history; the
    # direct path applies to live runs.
    eng = CM.Engine(as_of_date, end_of_day_utc(as_of_date),
                    market_pit="trade_date", market_as_of_date=as_of_date,
                    valuation=CM.VAL_LEGACY)
    eng.compute()
    signals = []
    for cid, m in eng.metrics.items():
        factors = {f: (1 if m.get(src) is not None else 0) for f, src in FACTOR_SOURCE.items()}
        ranks = {f: m.get(f) for f in FACTOR_SOURCE}
        n_avail = sum(factors.values())
        cat_avail = {cat: sum(factors[f] for f in fs) for cat, fs in CATEGORY.items()}
        sig_date = as_of_date
        signals.append({
            "company_id": cid,
            "security_id": m.get("security_id"),
            "symbol": m.get("symbol"),
            "signal_date": sig_date,
            "quant_score": m.get("quant_score"),
            "growth_score": m.get("growth_score"),
            "profitability_score": m.get("profitability_score"),
            "valuation_score": m.get("valuation_score"),
            "market_score": m.get("market_score"),
            "data_quality_score": m.get("data_quality_score"),
            "n_factors_available": n_avail,
            "factor_available": factors,
            "factor_rank": ranks,
            "category_available": cat_avail,
            "ttm_prov": m.get("_ttm_prov", {}),
            "valuation_prov": m.get("_valuation_prov", {}),
            "dq_flags": m.get("_dq").flags if m.get("_dq") else [],
            "uses_report_chain": any(v == "REPORT_CHAIN_TTM" for v in (m.get("_ttm_prov") or {}).values()),
        })
    universe_stats = {
        "as_of_date": as_of_date.isoformat(),
        "eligible_universe": len(eng.metrics),
        "profit_report_count": sum(1 for m in eng.metrics.values() if m.get("has_financial")),
        "monthly_available": sum(1 for m in eng.metrics.values() if m.get("has_monthly")),
        "price_available": sum(1 for m in eng.metrics.values() if m.get("has_price")),
    }
    return {"signals": signals, "universe_stats": universe_stats}


def snapshot_stable_payload(snapshot):
    """Deterministic representation for hashing (no volatile ordering)."""
    sigs = sorted(snapshot["signals"], key=lambda s: s["company_id"])
    out = []
    for s in sigs:
        out.append({k: s[k] for k in ("company_id", "security_id", "quant_score", "growth_score",
                                      "profitability_score", "valuation_score", "market_score",
                                      "data_quality_score", "n_factors_available")})
    return {"universe_stats": snapshot["universe_stats"], "signals": out}
