"""SHADOW V1 — deterministic accounting engine.

Byte-faithful port of the certified repaired engine
`portfolio_research/repair_accounting_v1.rebalance_accounts` (the certified artifact is
imported for parity testing but never modified), with ONE engineering change required by
SHADOW_V1_SPEC §13: every dict/set iteration over security names is replaced by SORTED
iteration, removing the cross-process float nondeterminism that unordered set iteration
caused (observed magnitude ≤ 5e-16, summation order only; economics identical).

Parity proof against the certified engine runs in portfolio_shadow/tests/.
Invariants (asserted by callers at every rebalance):
  cash_post + sum(new_position_values) == cash_pre + sum(current_values) - cost
  cash_post >= 0
"""
from __future__ import annotations


def rebalance_accounts(cash_pre, current_values, target_values, tradable, cost_rate):
    """Pure rebalance accounting with delta-scaled buy financing (deterministic order).

    current_values: {sym: market value at the execution date} for HELD names
    target_values:  {sym: equal-weight target value} for SELECTED+EXECUTABLE names
    tradable:       {sym: bool} executability on the execution date
    Returns (cash_post, new_position_values, cost, buys_executed, sells_executed, buy_scale).
    """
    sells = buys = 0.0
    new_pos = {}
    for sym in sorted(set(current_values) | set(target_values)):
        cur = current_values.get(sym, 0.0)
        if sym in target_values and tradable.get(sym, False):
            d = target_values[sym] - cur
            if d > 0:
                buys += d
            elif d < 0:
                sells += -d
            new_pos[sym] = target_values[sym]          # executed at exact target (f=1 path)
        elif cur > 0 and not tradable.get(sym, False):
            new_pos[sym] = cur                          # carried: held but not executable
        elif cur > 0:
            sells += cur                                # held, not re-selected, tradable -> full exit
        # not held, not targeted -> stays cash (failed target handled by caller)
    cost = cost_rate * (buys + sells)
    avail = cash_pre + sells - cost_rate * sells
    buy_scale = 1.0
    if buys > 0 and avail < buys * (1 + cost_rate):
        buy_scale = max(0.0, avail / (buys * (1 + cost_rate)))
        buys = buys * buy_scale                          # executed buys shrink
        cost = cost_rate * (buys + sells)
        for sym in sorted(new_pos):
            if sym in target_values and tradable.get(sym, False) and target_values[sym] > current_values.get(sym, 0.0):
                cur = current_values.get(sym, 0.0)
                new_pos[sym] = cur + buy_scale * (target_values[sym] - cur)  # scale the DELTA
    cash_post = cash_pre + sells - buys - cost
    return cash_post, new_pos, cost, buys, sells, buy_scale


def assert_invariants(cash_pre, current_values, result, tol=1e-9):
    """Assert the certified invariants on a rebalance_accounts result tuple."""
    cash_post, new_pos, cost, buys, sells, buy_scale = result
    nav_pre = cash_pre + sum(current_values.values())
    nav_post = cash_post + sum(new_pos.values())
    assert abs(nav_post - (nav_pre - cost)) <= tol, f"NAV identity violated: {nav_post} vs {nav_pre - cost}"
    assert cash_post >= -tol, f"negative cash: {cash_post}"
    return True
