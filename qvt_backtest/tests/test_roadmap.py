import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execute_roadmap as E
import reconstructed_replay as B


def test_buffer_only_retains_present_incumbents_within_limit():
    a = pd.DataFrame({"as_of": ["2022-01-01"] * 4, "symbol": list("ABCD"), "ui_score": [4, 3, 2, 1]})
    b = pd.DataFrame({"as_of": ["2022-02-01"] * 4, "symbol": list("CBAD"), "ui_score": [4, 3, 2, 1]})
    c = pd.DataFrame({"as_of": ["2022-03-01"] * 3, "symbol": list("CDE"), "ui_score": [4, 3, 2]})
    selected = E.select_buffer(pd.concat([a, b, c]), 2, 3)
    assert set(selected[selected.as_of.eq("2022-02-01")].symbol) == set("AB")
    assert set(selected[selected.as_of.eq("2022-03-01")].symbol) == set("CD")


def test_capacity_and_delay_preserve_cash_and_halted_holdings():
    RA = B.R.V.load_portfolio_engine()
    cal = ["2022-01-02", "2022-01-03", "2022-02-02", "2022-02-03", "2022-03-02"]
    selected = pd.DataFrame({"as_of": ["2022-01-01", "2022-02-01", "2022-03-01"], "symbol": list("ABA"), "ui_score": [10, 20, 30]})
    adj = {s: {"dates": cal, "adj": {d: 10 for d in cal}} for s in "AB"}
    caps = {(cal[1], "A"): .2, (cal[3], "A"): 0, (cal[3], "B"): .1}
    perf, daily, ledger, trades = B.replay(selected, list(selected.as_of), adj, cal,
        {(d, s) for d in cal for s in "AB"}, 1, .005, RA, {"delay_sessions": 1, "capacities": caps})
    assert ledger[0]["exec_date"] == cal[1]
    assert len(ledger) == 2
    assert [r["symbol"] for r in trades] == ["A", "B"]
    assert trades[0]["notional"] <= .2 and trades[1]["notional"] <= .1
    assert min(r["cash_weight"] for r in daily) >= 0
    assert daily[-1]["nav"] == pytest.approx(1 - .3 * .005)
