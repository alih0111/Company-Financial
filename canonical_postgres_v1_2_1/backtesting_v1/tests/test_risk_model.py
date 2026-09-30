"""Deterministic checks for the PIT risk weighting (no DB, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import risk_model  # noqa: E402


def test_cap_and_sum():
    w = risk_model.apply_cap([0.9, 0.05, 0.05], 0.5)
    assert all(0 <= x <= 0.5 + 1e-12 for x in w), w
    assert abs(sum(w) - 1) < 1e-9, w
    # incompatible cap → equal weights
    w2 = risk_model.apply_cap([0.5, 0.5, 0.0], 0.2)
    assert abs(w2[0] - 1 / 3) < 1e-9, w2


def test_inverse_vol_is_proportional_to_one_over_sigma():
    cov = [[0.0001, 0.0], [0.0, 0.0004]]  # σ = 1% and 2%
    w = risk_model.inverse_vol(cov, cap=0.9)
    assert abs(w[0] - 2 / 3) < 1e-9, w
    assert abs(sum(w) - 1) < 1e-12, w


def test_min_variance_matches_analytic_solution():
    # Analytic two-asset (uncorrelated) min-variance: w1 = σ2² / (σ1² + σ2²)
    cov = [[0.0004, 0.0], [0.0, 0.0025]]
    w = risk_model.min_variance(cov, cap=0.95, iterations=3000)
    want = 0.0025 / (0.0004 + 0.0025)
    assert abs(w[0] - want) < 5e-3, (w, want)
    assert abs(sum(w) - 1) < 1e-9, w


def test_shrinkage_preserves_diagonal():
    cov = [[0.04, 0.02], [0.02, 0.09]]
    s = risk_model.shrink(cov, 0.5)
    assert abs(s[0][0] - 0.04) < 1e-12
    assert abs(s[0][1] - 0.01) < 1e-12


def test_pit_window_excludes_future_dates():
    import datetime as dt
    from market_data import PriceStore

    rows = []
    for i, d in enumerate(["2024-01-02", "2024-01-03", "2024-01-04", "2025-06-01"]):
        rows.append(("sec1", dt.date.fromisoformat(d), 100.0 + i))
    store = PriceStore(rows)

    # window ending before the future date must not see it
    closes = store.window_closes("sec1", dt.date(2024, 12, 31), 10)
    assert closes == [100.0, 101.0, 102.0], closes
    dates = store.window_dates("sec1", dt.date(2024, 12, 31), 10)
    assert dates[-1] == dt.date(2024, 1, 4), dates
    # and the future date is visible once the as-of date allows it
    assert store.window_closes("sec1", dt.date(2025, 12, 31), 10)[-1] == 103.0


def test_weights_cover_members_and_sum_to_one():
    import datetime as dt
    from market_data import PriceStore

    rows = []
    days = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(200)]
    # three securities with different volatilities but deterministic paths
    for k, vol in enumerate([0.005, 0.02, 0.01]):
        px = 1000.0
        for i, d in enumerate(days):
            swing = 1 + (vol if i % 2 == 0 else -vol) * (1 + k * 0.1)
            px *= swing
            rows.append((f"sec{k}", d, px))
    store = PriceStore(rows)
    members = [{"company_id": f"c{k}", "security_id": f"sec{k}"} for k in range(3)]

    for method in ("equal", "inverse_vol", "min_variance"):
        w, info = risk_model.weights_for(store, members, days[-1], method, window=150, cap=0.6)
        assert set(w) == {"c0", "c1", "c2"}, (method, w, info)
        assert abs(sum(w.values()) - 1) < 1e-9, (method, w)
        assert all(0 <= v <= 0.6 + 1e-12 for v in w.values()), (method, w)


def test_missing_history_is_dropped_not_fabricated():
    import datetime as dt
    from market_data import PriceStore

    days = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(200)]
    rows = [(f"sec{k}", d, 100.0 + i) for k in range(2) for i, d in enumerate(days)]
    rows.append(("sec_thin", days[-1], 100.0))  # only one observation
    store = PriceStore(rows)
    members = [{"company_id": "c0", "security_id": "sec0"},
               {"company_id": "c1", "security_id": "sec1"},
               {"company_id": "c_thin", "security_id": "sec_thin"}]
    w, info = risk_model.weights_for(store, members, days[-1], "min_variance", window=150, cap=0.6)
    # fewer than three usable series → no weights at all, and the reason is reported
    assert w == {}, (w, info)
    assert "c_thin" in info["dropped"] or info.get("reason"), info
