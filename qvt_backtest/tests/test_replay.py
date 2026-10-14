import datetime as dt
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("qvt_replay", Path(__file__).parents[1] / "run.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_ranking_direction_and_missing_not_neutral():
    values = np.array(list(range(10)) + [np.nan])
    high = replay.ranked(values)
    low = replay.ranked(values, False)
    assert high[9] == 1 and high[0] == 0
    assert low[0] == 1 and low[9] == 0
    assert np.isnan(high[-1])


def test_annualization_uses_actual_time_and_includes_entry_cost():
    rows = [{"exec_date": "2021-01-01", "value_post_trade": .99, "cash_weight": 0,
             "turnover": 1, "failed_targets": 0},
            {"exec_date": "2023-01-01", "value_post_trade": 1.21, "cash_weight": 0,
             "turnover": .1, "failed_targets": 0}]
    result = replay.performance(rows)
    assert abs(result["cumulative_return_pct"] - 21) < 1e-9
    assert 9.9 < result["annualized_return_pct"] < 10.1
    assert abs(result["max_drawdown_pct"] + 1) < 1e-9


def test_future_prices_never_reach_timing_raw(monkeypatch):
    seen = {}
    class Market:
        data = {"one": {"dates": ["2021-01-01", "2021-01-02", "2021-01-03"],
                         "c": np.array([100, 110, 10000]), "tval": np.array([1, 2, 999999])}}
        def idx_at(self, sym, date): return 1
        def asof_factors(self, sym, date): return np.ones(3)
    def capture(histories, *_args, **_kwargs):
        seen.update(histories)
        return {}
    monkeypatch.setattr(replay.TR, "build_t_raw", capture)
    monkeypatch.setattr(replay, "align_returns", lambda *_: {})
    replay.historical_timing(Market(), ["one"], "2021-01-02")
    assert [r["date"] for r in seen["one"]] == [dt.date(2021, 1, 1), dt.date(2021, 1, 2)]
    assert all(r["collected_at"] is None for r in seen["one"])


def test_outcomes_cannot_change_selection_scores(monkeypatch):
    size = 30
    panel = pd.DataFrame({"as_of": ["2021-01-31"] * size,
        "knowledge_cutoff": ["2021-01-31T23:59:59Z"] * size,
        "symbol": [str(i) for i in range(size)], "ui_score": range(size),
        **{f: np.arange(size, dtype=float) + 1 for f in ("roe", "cash_conversion", "debt_ratio", "pe", "pb", "ps", "operating_margin", "net_margin", "net_profit_ttm", "revenue_ttm")},
        "ret_21": np.arange(size), "ret_63": np.arange(size)})
    current = {"ranked": [{"symbol": str(i), "model_family": "general"} for i in range(size)], "unscored": []}
    fields = ("momentum_6m_rel", "momentum_3m_rel", "liquidity", "low_volatility")
    monkeypatch.setattr(replay, "historical_timing", lambda *_: (
        {str(i): {f: {"raw_value": i + 1, "status": "valid"} for f in fields} for i in range(size)}, {}))
    weights = replay.json.loads((Path(__file__).parents[1] / "protocol.json").read_text())["weights"]
    first = replay.build_scores(panel, None, current, weights)[1]
    panel["ret_21"] *= -999
    panel["ret_63"] *= 777
    second = replay.build_scores(panel, None, current, weights)[1]
    assert list(first.ui_score) == list(second.ui_score)
