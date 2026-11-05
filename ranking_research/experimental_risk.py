"""Deterministic buy-side risk gate for explicitly configured paper experiments.

This module has no account, network, scheduler or order-writing side effects.
Daily turnover is only a capacity proxy; it does not establish queue execution.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _fraction(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or number > 1 or (positive and number == 0):
        raise ValueError
    return number


def _integer(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or (positive and value == 0):
        raise ValueError
    return value


def _identity(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value


def check_buy(snapshot: dict, order: dict, policy: dict) -> dict:
    """Evaluate one proposed BUY against a versioned, explicitly supplied policy.

    Monetary values and quoted turnover are whole toman, shares are integers,
    and all weight/fee/participation limits are fractions in [0, 1]. The
    caller owns order execution and must independently check market/queue data.
    """
    fingerprint = None
    try:
        if not all(isinstance(x, dict) for x in (snapshot, order, policy)):
            raise ValueError("INVALID_INPUT")
        fingerprint = hashlib.sha256(json.dumps({"snapshot": snapshot, "order": order, "policy": policy},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        required_policy = {"policy_id", "max_symbol_weight", "max_industry_weight", "min_cash_weight",
                           "max_daily_value_participation", "fee_rate", "max_price_age_days",
                           "max_liquidity_age_days", "min_liquidity_sessions"}
        if not required_policy.issubset(policy):
            raise ValueError("POLICY_INCOMPLETE")
        policy_id = _identity(policy["policy_id"])
        max_symbol = _fraction(policy["max_symbol_weight"])
        max_industry = _fraction(policy["max_industry_weight"])
        min_cash = _fraction(policy["min_cash_weight"])
        participation = _fraction(policy["max_daily_value_participation"])
        fee_rate = _fraction(policy["fee_rate"])
        max_age = _integer(policy["max_price_age_days"])
        max_liquidity_age = _integer(policy["max_liquidity_age_days"])
        min_liquidity_sessions = _integer(policy["min_liquidity_sessions"], positive=True)
        as_of = date.fromisoformat(_identity(snapshot["as_of"]))
        cash = _integer(snapshot["cash_toman"])
        if "open_order_count" not in snapshot or snapshot["open_order_count"] is None:
            raise ValueError("OPEN_ORDER_STATUS_UNKNOWN")
        open_orders = _integer(snapshot["open_order_count"])
        holdings, quotes = snapshot["holdings"], snapshot["quotes"]
        if not isinstance(holdings, list) or not isinstance(quotes, dict):
            raise ValueError("INVALID_SNAPSHOT")
        if order["side"] != "BUY":
            raise ValueError("UNSUPPORTED_ORDER_SIDE")
        cid, symbol, industry = (_identity(order[key]) for key in ("company_id", "symbol", "industry"))
        shares = _integer(order["shares"], positive=True)
        if open_orders:
            return {"decision": "REJECT", "reasons": ["OPEN_ORDER_EXISTS"], "policy_id": policy_id, "input_sha256": fingerprint}

        def quote_for(company_id, expected_symbol, expected_industry):
            if company_id not in quotes:
                raise ValueError("QUOTE_NOT_FOUND")
            quote = quotes[company_id]
            if not isinstance(quote, dict) or quote.get("symbol") != expected_symbol or quote.get("industry") != expected_industry:
                raise ValueError("IDENTITY_OR_INDUSTRY_MISMATCH")
            if "price_toman" not in quote or "price_date" not in quote:
                raise ValueError("QUOTE_INCOMPLETE")
            price = _integer(quote["price_toman"], positive=True)
            price_date = date.fromisoformat(_identity(quote["price_date"]))
            age = (as_of - price_date).days
            if age < 0:
                raise ValueError("PRICE_DATE_IN_FUTURE")
            if age > max_age:
                raise ValueError("STALE_PRICE")
            return quote, price

        seen, symbols, current_total, industry_total, symbol_total = set(), {}, 0, 0, 0
        for holding in holdings:
            if not isinstance(holding, dict):
                raise ValueError("INVALID_HOLDING")
            h_id, h_symbol, h_industry = (_identity(holding[key]) for key in ("company_id", "symbol", "industry"))
            units = _integer(holding["shares"], positive=True)
            if h_id in seen:
                raise ValueError("DUPLICATE_HOLDING_IDENTITY")
            if h_symbol in symbols and symbols[h_symbol] != h_id:
                raise ValueError("DUPLICATE_SYMBOL_IDENTITY")
            seen.add(h_id)
            symbols[h_symbol] = h_id
            _, price = quote_for(h_id, h_symbol, h_industry)
            value = units * price
            current_total += value
            if h_industry == industry:
                industry_total += value
            if h_id == cid:
                if h_symbol != symbol or h_industry != industry:
                    raise ValueError("IDENTITY_OR_INDUSTRY_MISMATCH")
                symbol_total = value
        if symbol in symbols and symbols[symbol] != cid:
            raise ValueError("DUPLICATE_SYMBOL_IDENTITY")
        quote, target_price = quote_for(cid, symbol, industry)
        if "average_daily_value_toman" not in quote or quote["average_daily_value_toman"] is None:
            raise ValueError("TURNOVER_NOT_AVAILABLE")
        if not quote.get("liquidity_date") or "liquidity_sessions" not in quote:
            raise ValueError("LIQUIDITY_FRESHNESS_UNKNOWN")
        liquidity_date = date.fromisoformat(_identity(quote["liquidity_date"]))
        liquidity_age = (as_of - liquidity_date).days
        if liquidity_age < 0:
            raise ValueError("LIQUIDITY_DATE_IN_FUTURE")
        if liquidity_age > max_liquidity_age:
            raise ValueError("STALE_LIQUIDITY")
        if _integer(quote["liquidity_sessions"]) < min_liquidity_sessions:
            raise ValueError("INSUFFICIENT_LIQUIDITY_HISTORY")
        daily_value = _integer(quote["average_daily_value_toman"], positive=True)
        gross = shares * target_price
        fee = int((Decimal(gross) * fee_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        new_cash = cash - gross - fee
        new_total = cash + current_total - fee
        if new_total <= 0:
            return {"decision": "REJECT", "reasons": ["NONPOSITIVE_PORTFOLIO_VALUE"], "policy_id": policy_id, "input_sha256": fingerprint}
        symbol_weight = Decimal(symbol_total + gross) / Decimal(new_total)
        industry_weight = Decimal(industry_total + gross) / Decimal(new_total)
        cash_weight = Decimal(new_cash) / Decimal(new_total)
        reasons = []
        if new_cash < 0:
            reasons.append("INSUFFICIENT_CASH")
        if cash_weight < min_cash:
            reasons.append("MIN_CASH_WEIGHT")
        if symbol_weight > max_symbol:
            reasons.append("MAX_SYMBOL_WEIGHT")
        if industry_weight > max_industry:
            reasons.append("MAX_INDUSTRY_WEIGHT")
        if Decimal(gross) > Decimal(daily_value) * participation:
            reasons.append("MAX_DAILY_VALUE_PARTICIPATION")
        return {"decision": "REJECT" if reasons else "ALLOW", "reasons": reasons, "policy_id": policy_id,
                "input_sha256": fingerprint, "gross_toman": gross, "fee_toman": fee,
                "projected_cash_toman": new_cash, "projected_total_toman": new_total,
                "projected_symbol_weight": str(symbol_weight), "projected_industry_weight": str(industry_weight),
                "projected_cash_weight": str(cash_weight),
                "liquidity_limitation": "DAILY_VALUE_PROXY_DOES_NOT_PROVE_QUEUE_EXECUTION"}
    except (KeyError, TypeError, InvalidOperation, ValueError, OverflowError) as error:
        reason = str(error) if isinstance(error, ValueError) and str(error) in {
            "UNSUPPORTED_ORDER_SIDE", "IDENTITY_OR_INDUSTRY_MISMATCH", "PRICE_DATE_IN_FUTURE", "STALE_PRICE",
            "DUPLICATE_HOLDING_IDENTITY", "DUPLICATE_SYMBOL_IDENTITY", "INVALID_HOLDING", "INVALID_SNAPSHOT",
            "POLICY_INCOMPLETE", "OPEN_ORDER_STATUS_UNKNOWN", "QUOTE_NOT_FOUND", "QUOTE_INCOMPLETE", "TURNOVER_NOT_AVAILABLE",
            "LIQUIDITY_FRESHNESS_UNKNOWN", "LIQUIDITY_DATE_IN_FUTURE", "STALE_LIQUIDITY", "INSUFFICIENT_LIQUIDITY_HISTORY"} else "INVALID_OR_MISSING_RISK_INPUT"
        result = {"decision": "REJECT", "reasons": [reason]}
        if fingerprint is not None:
            result["input_sha256"] = fingerprint
        return result
