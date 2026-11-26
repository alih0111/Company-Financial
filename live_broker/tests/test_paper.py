from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction

from live_broker.contracts import AccountKey, Instrument, ProviderKey, Side
from live_broker.paper import Bar, simulate, size_order

DAY = date(2026, 11, 13)
ASSET = Instrument(ProviderKey(AccountKey('paper', 'sample'), 'asset'), None, 'Sample')
PLAN = dict(decision_id='decision', instrument=ASSET, side=Side.BUY, notional_rial=1049,
            limit_rial=100, lot_shares=2)


def test_sizing_is_deterministic_and_preserves_integer_managed_shares():
    order = size_order(**PLAN)
    assert order == size_order(**PLAN)
    assert order.shares == 10
    assert size_order(**(PLAN | {'side': Side.SELL})) is None
    assert size_order(**(PLAN | {'side': Side.SELL, 'managed_shares': 5})).shares == 4


def test_paper_fill_requires_later_liquidity_and_respects_expiry_and_capacity():
    order = size_order(**PLAN)
    bar = Bar(DAY + timedelta(days=1), 90, 50, False, False)
    args = dict(decision_session=DAY, elapsed_sessions=1, order_life=5, remaining_shares=order.shares,
                participation=Fraction(1, 10), fee_rate=Fraction(3, 1000), lot_shares=2)
    assert simulate(order, replace(bar, session=DAY), **args).reason == 'delay'
    assert simulate(order, replace(bar, queued=True), **args).reason == 'no_verified_liquidity'
    assert simulate(order, replace(bar, raw_open_rial=101), **args).reason == 'limit_not_reached'
    assert simulate(order, bar, **(args | {'elapsed_sessions': 6})).reason == 'expired'
    fill = simulate(order, bar, **args)
    assert (fill.reason, fill.shares, fill.price_rial, fill.fee_rial) == ('paper_fill', 4, 100, 2)
