from copy import deepcopy

import pytest

from ranking_research.experimental_risk import check_buy


@pytest.fixture
def example():
    snapshot = {"as_of": "2026-11-05", "cash_toman": 1_000_000, "open_order_count": 0,
                "holdings": [{"company_id": "a", "symbol": "A", "industry": "bank", "shares": 1000}],
                "quotes": {"a": {"symbol": "A", "industry": "bank", "price_toman": 100, "price_date": "2026-11-04"},
                           "b": {"symbol": "B", "industry": "industry", "price_toman": 1000,
                                 "price_date": "2026-11-04", "average_daily_value_toman": 5_000_000,
                                 "liquidity_date": "2026-11-04", "liquidity_sessions": 30}}}
    order = {"side": "BUY", "company_id": "b", "symbol": "B", "industry": "industry", "shares": 100}
    policy = {"policy_id": "test-only/1", "max_symbol_weight": 0.2, "max_industry_weight": 0.3,
              "min_cash_weight": 0.1, "max_daily_value_participation": 0.1,
              "fee_rate": 0.005, "max_price_age_days": 2,
              "max_liquidity_age_days": 2, "min_liquidity_sessions": 20}
    return snapshot, order, policy


def test_buy_gate_reconciles_cash_fee_and_is_reproducible(example):
    snapshot, order, policy = example
    before = deepcopy(example)
    result = check_buy(snapshot, order, policy)
    assert result["decision"] == "ALLOW" and result["reasons"] == []
    assert (result["gross_toman"], result["fee_toman"], result["projected_cash_toman"],
            result["projected_total_toman"]) == (100_000, 500, 899_500, 1_099_500)
    assert result == check_buy(snapshot, order, policy)
    assert example == before
    assert result["liquidity_limitation"] == "DAILY_VALUE_PROXY_DOES_NOT_PROVE_QUEUE_EXECUTION"


def test_buy_gate_enforces_concentration_liquidity_and_cash(example):
    snapshot, order, policy = example
    order["shares"] = 350
    snapshot["quotes"]["b"]["industry"] = order["industry"] = "bank"
    policy["max_daily_value_participation"] = 0.05
    result = check_buy(snapshot, order, policy)
    assert result["decision"] == "REJECT"
    assert {"MAX_SYMBOL_WEIGHT", "MAX_INDUSTRY_WEIGHT", "MAX_DAILY_VALUE_PARTICIPATION"} <= set(result["reasons"])
    order["shares"] = 1100
    result = check_buy(snapshot, order, policy)
    assert {"INSUFFICIENT_CASH", "MIN_CASH_WEIGHT"} <= set(result["reasons"])


@pytest.mark.parametrize("mutation, reason", [
    ("stale", "STALE_PRICE"), ("future", "PRICE_DATE_IN_FUTURE"),
    ("identity", "IDENTITY_OR_INDUSTRY_MISMATCH"), ("missing_turnover", "TURNOVER_NOT_AVAILABLE"),
    ("missing_order_status", "OPEN_ORDER_STATUS_UNKNOWN"), ("open_order", "OPEN_ORDER_EXISTS"),
    ("missing_policy", "POLICY_INCOMPLETE"), ("sell", "UNSUPPORTED_ORDER_SIDE"),
    ("stale_liquidity", "STALE_LIQUIDITY"), ("short_liquidity", "INSUFFICIENT_LIQUIDITY_HISTORY"),
    ("missing_liquidity_date", "LIQUIDITY_FRESHNESS_UNKNOWN"),
    ("missing_quote", "QUOTE_NOT_FOUND"), ("duplicate_symbol", "DUPLICATE_SYMBOL_IDENTITY"),
])
def test_buy_gate_fails_closed_for_unverifiable_inputs(example, mutation, reason):
    snapshot, order, policy = example
    if mutation == "stale": snapshot["quotes"]["a"]["price_date"] = "2026-10-01"
    if mutation == "future": snapshot["quotes"]["b"]["price_date"] = "2026-11-06"
    if mutation == "identity": order["symbol"] = "WRONG"
    if mutation == "missing_turnover": del snapshot["quotes"]["b"]["average_daily_value_toman"]
    if mutation == "missing_order_status": del snapshot["open_order_count"]
    if mutation == "open_order": snapshot["open_order_count"] = 1
    if mutation == "missing_policy": del policy["max_symbol_weight"]
    if mutation == "sell": order["side"] = "SELL"
    if mutation == "stale_liquidity": snapshot["quotes"]["b"]["liquidity_date"] = "2026-10-01"
    if mutation == "short_liquidity": snapshot["quotes"]["b"]["liquidity_sessions"] = 3
    if mutation == "missing_liquidity_date": del snapshot["quotes"]["b"]["liquidity_date"]
    if mutation == "missing_quote": del snapshot["quotes"]["b"]
    if mutation == "duplicate_symbol": order["symbol"] = "A"
    result = check_buy(snapshot, order, policy)
    assert result["decision"] == "REJECT" and reason in result["reasons"]
    assert len(result["input_sha256"]) == 64


def test_zero_limits_are_valid_and_reject_a_positive_buy(example):
    snapshot, order, policy = example
    policy["max_symbol_weight"] = 0
    policy["max_daily_value_participation"] = 0
    result = check_buy(snapshot, order, policy)
    assert result["decision"] == "REJECT"
    assert {"MAX_SYMBOL_WEIGHT", "MAX_DAILY_VALUE_PARTICIPATION"} <= set(result["reasons"])
