"""Backtesting v1 tests: PIT safety, determinism, separation, no legacy/oracle/write deps.

Run:
    set CDF_PILOT_DB=company_financial_analytics_shadow_v121
    python -m pytest canonical_postgres_v1_2_1/backtesting_v1/tests -q
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
BT = HERE.parent
BASE = BT.parent
for p in (str(BT), str(BASE / "analytics_canonical_v1"), str(BASE / "migration_tools")):
    sys.path.insert(0, p)

import compute_metrics as CM  # noqa: E402
import report_chain_ttm as RC  # noqa: E402
import forward_returns as FR  # noqa: E402
import universe as UNI  # noqa: E402
from config import BacktestConfig  # noqa: E402
from calendar import TradingCalendar  # noqa: E402


class _FakeStore:
    def __init__(self, m):
        self.m = m

    def close(self, sid, d):
        return self.m.get((sid, d))


def test_pit_future_report_rejected():
    eng = CM.Engine(dt.date(2024, 6, 30), dt.datetime(2024, 6, 30, 23, 59, 59, tzinfo=dt.timezone.utc))
    eng.load()
    for st in eng.stmt:
        assert st["period_end_date"] <= eng.as_of


def test_pit_future_price_rejected_trade_date_mode():
    T = dt.date(2024, 6, 30)
    eng = CM.Engine(T, dt.datetime(2024, 6, 30, 23, 59, 59, tzinfo=dt.timezone.utc),
                    market_pit="trade_date", market_as_of_date=T)
    eng.load()
    assert eng.prices, "expected historical prices"
    for p in eng.prices:
        assert p["trade_date"] <= T


def test_pit_future_correction_rejected():
    eng = CM.Engine(dt.date(2024, 6, 30), dt.datetime(2024, 6, 30, tzinfo=dt.timezone.utc))
    eng.stmt = [
        {"company_id": "c", "statement_type": "income_statement", "period_end_date": dt.date(2024, 3, 20),
         "fiscal_year": 1403, "fiscal_month": 12, "is_restated": False, "version_no": 1, "collected_at": None,
         "metric_code": "operating_profit", "period_order": 1, "canonical_value": 10.0,
         "canonical_unit": "rial", "report_id": "old"},
        {"company_id": "c", "statement_type": "income_statement", "period_end_date": dt.date(2024, 3, 20),
         "fiscal_year": 1403, "fiscal_month": 12, "is_restated": False, "version_no": 2, "collected_at": None,
         "metric_code": "operating_profit", "period_order": 1, "canonical_value": 99.0,
         "canonical_unit": "rial", "report_id": "newcorrection"},
    ]
    eng.superseded = {"old"}
    assert eng.report_index()["c"][(1403, 12)]["operating_profit"][1] == 99.0
    eng.superseded = {"newcorrection"}   # correction not visible at T -> old wins
    assert eng.report_index()["c"][(1403, 12)]["operating_profit"][1] == 10.0


def test_report_chain_pit_safety_no_future_cells():
    rep = {(1405, 6): {"operating_profit": {1: 100.0}}, (1404, 6): {"operating_profit": {1: 40.0}}}
    v, prov = RC.resolve_ttm(rep, "operating_profit", 1405, 6)
    assert v is None and prov == RC.PROV_NO_ANNUAL


def test_no_survivorship_static_universe():
    # universe is built only from provided signals; no global company list is read
    uni = UNI.evaluate_universe(
        [{"company_id": "a", "security_id": "s1"}, {"company_id": "b", "security_id": None}],
        _FakeStore({("s1", dt.date(2024, 1, 2)): 10.0}), dt.date(2024, 1, 2))
    assert uni["eligible"] == 2 and uni["with_security"] == 1
    assert len(uni["tradable"]) == 1
    assert uni["excluded"][0]["company_id"] == "b"


def test_signal_forward_separation_and_execution():
    cal = TradingCalendar([dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 7), dt.date(2024, 1, 8)])
    sig = dt.date(2024, 1, 3)
    exec_ = FR.resolve_execution_date(cal.dates, sig)
    assert exec_ == dt.date(2024, 1, 7) and exec_ > sig
    assert FR.exit_after(cal.dates, exec_, 1) == dt.date(2024, 1, 8)


def test_missing_price_excluded():
    uni = UNI.evaluate_universe([{"company_id": "a", "security_id": "s1"}],
                                _FakeStore({}), dt.date(2024, 1, 2))
    assert len(uni["tradable"]) == 0 and uni["excluded"][0]["reason"] == "no_price_on_execution_date"


def test_missing_factor_neutral_unchanged():
    out = CM.midrank({"a": 1.0, "b": None}, neutral=0.3)
    assert out["b"] == 0.3


def test_deterministic_snapshot_and_scores():
    from snapshot_builder import build_snapshot, snapshot_stable_payload
    import hashlib
    import json
    s1 = build_snapshot(dt.date(2024, 6, 30))
    s2 = build_snapshot(dt.date(2024, 6, 30))
    h1 = hashlib.sha256(json.dumps(snapshot_stable_payload(s1), sort_keys=True, default=str).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(snapshot_stable_payload(s2), sort_keys=True, default=str).encode()).hexdigest()
    assert h1 == h2


def test_deterministic_portfolio_tiny():
    from run_backtest import run
    import tempfile
    cfg = BacktestConfig(start_date="2025-01-01", end_date="2025-03-31")
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        a = run(cfg, outdir=Path(d1))
        b = run(cfg, outdir=Path(d2))
    assert a["hashes"]["summary"] == b["hashes"]["summary"]


def test_no_legacy_or_oracle_or_write_dependency():
    forbidden = ["sqlserver", "Product1", "NPUnitRatio", "compat_v37", "legacy_v37_",
                 "golden", "oracle", "INSERT INTO analytics", "score_runs", "psycopg"]
    for py in BT.glob("*.py"):
        out = []
        with open(py, "r", encoding="utf-8") as fh:
            for tok in tokenize.generate_tokens(fh.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                out.append(tok.string)
        code = " ".join(out)
        for f in forbidden:
            assert f not in code, f"forbidden dependency {f!r} in {py.name}"
        for f in (r"\bOpK\b", r"\bOpAmt\b", r"\bOpAbs\b"):
            assert not re.search(f, code), f"forbidden {f} in {py.name}"
