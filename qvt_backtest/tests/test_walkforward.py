import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from walkforward_research import choose_schedule, audit_schedule


def example():
    policy = json.loads((Path(__file__).resolve().parents[1] / "walkforward_policy.json").read_text())
    dates = pd.date_range("2022-01-01", "2024-06-30").strftime("%Y-%m-%d")
    frames = {name: pd.DataFrame({"date": dates, "nav": np.exp(np.arange(len(dates)) * rate / 365)})
              for name, rate in [("QVT", .05), ("QVT_BUFFER", .15), ("Q", .1)]}
    return policy, frames


def test_future_and_signal_day_outcomes_cannot_change_prior_choices():
    policy, frames = example()
    signals = ["2022-01-31", "2022-12-31", "2023-01-31", "2023-08-31", "2024-01-31"]
    schedule, choices, metrics = choose_schedule(signals, frames, policy)
    assert schedule["2022-12-31"] == "QVT"  # no midyear update
    assert schedule["2023-01-31"] == "QVT_BUFFER"
    poisoned = {name: frame.copy() for name, frame in frames.items()}
    poisoned["QVT"].loc[poisoned["QVT"].date.ge("2024-01-31"), "nav"] = 1e12
    assert choose_schedule(signals, poisoned, policy)[0] == schedule
    assert audit_schedule(schedule, choices, metrics, frames, policy)["status"] == "passed"
    metrics[-1]["training_end"] = "2024-01-31"
    with pytest.raises(ValueError, match="training_trace"):
        audit_schedule(schedule, choices, metrics, frames, policy)


def test_equal_training_performance_has_fixed_name_tie_break():
    policy, frames = example()
    equal = {name: frames["QVT"].copy() for name in policy["candidates"]}
    schedule, _, _ = choose_schedule(["2022-01-31", "2023-01-31"], equal, policy)
    assert schedule["2022-01-31"] == "QVT"
    assert schedule["2023-01-31"] == "Q"
