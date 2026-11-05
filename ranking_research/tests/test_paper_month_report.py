import json

from ranking_research.future_eval_v12_30.paper_month_report import summarize


def account(value, *, price_date="2026-10-28", fee=None):
    events = []
    if fee is not None:
        events.append({"event_id": "buy-1", "type": "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE",
            "at_utc": "2026-10-27T20:00:00+00:00", "details": f"assumed_fee_toman={fee}"})
    return {"cash_toman": 10, "accounting": {"total_value_toman": value, "holdings_value_toman": value - 10},
        "holdings": [{"symbol": "TEST", "last_price_date": price_date}],
        "paper_order": {"symbol": "TEST"}, "event_log": events}


def test_saved_observations_compute_returns_costs_and_snapshot_drawdown(tmp_path):
    home = tmp_path
    runs = home / "runs"
    for index, (v1, v3) in enumerate(((100, 100), (110, 90))):
        folder = runs / f"run-{index}"
        folder.mkdir(parents=True)
        doc = {"updated_at_utc": f"2026-10-2{7+index}T20:00:00+00:00", "accounts": {
            "P1": {"outcome": {"status": "MARK_APPLIED"}, "account": account(v1, fee=5 if index == 0 else None)},
            "P3": {"outcome": {"status": "MARK_APPLIED"}, "account": account(v3)}}}
        (folder / "daily.json").write_text(json.dumps(doc), encoding="utf-8")
    current = {"updated_at_utc": "2026-10-29T20:00:00+00:00", "config": {
        "methods": ["P1", "P3"], "initial_capital_per_method_toman": 100,
        "started_at_utc": "2026-10-27T20:00:00+00:00", "ends_at_utc": "2026-11-26T20:00:00+00:00"},
        "accounts": {"P1": {"outcome": {"status": "MARK_APPLIED"}, "account": account(90)},
                     "P3": {"outcome": {"status": "MARK_APPLIED"}, "account": account(90)}}}
    result = summarize(home, current, ended=False)
    assert result["state"] == "PROVISIONAL"
    assert result["accounts"]["P1"]["net_return_toman"] == -10
    assert result["accounts"]["P1"]["observed_max_drawdown_fraction"] == 2 / 11
    assert result["accounts"]["P1"]["assumed_cost_toman"] == 5
    assert result["comparison"]["benchmark_result"] == "UNKNOWN_NO_ALIGNED_VALID_BENCHMARK"
    assert result["comparison"]["same_symbol_models_are_independent_performance_evidence"] is False
    assert result["period"]["forced_liquidation"] is False


def test_missing_price_is_counted_and_not_filled_from_previous_snapshot(tmp_path):
    current = {"updated_at_utc": "2026-10-28T20:00:00+00:00", "config": {
        "methods": ["P1", "P3"], "initial_capital_per_method_toman": 100},
        "accounts": {"P1": {"outcome": {"status": "NO_NEW_MARK"}, "account": account(90, price_date=None)},
                     "P3": {"outcome": {"status": "NO_NEW_MARK"}, "account": account(100)}}}
    result = summarize(tmp_path, current, ended=True)
    p1 = result["accounts"]["P1"]
    assert result["state"] == "FINAL" and result["period"]["stop_execution"]
    assert p1["unique_days_without_valid_price"] == 1
    assert p1["net_return_toman"] == -10  # equity comes from the saved account, not a fabricated mark
    assert p1["last_price_dates"] == [None]
    assert result["comparison"]["common_decision_symbols"] == ["TEST"]
    assert result["comparison"]["same_symbol_models_are_independent_performance_evidence"] is False
