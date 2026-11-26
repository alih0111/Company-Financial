from dataclasses import replace
from datetime import datetime, timedelta, timezone

from live_broker.contracts import AccountKey, Instrument, InstrumentRules, OrderRequest, ProviderKey, Side
from live_broker.risk import Exposure, Limits, Quote, RiskInput, evaluate

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
ACCOUNT = AccountKey('sample', 'paper')
INSTRUMENT = Instrument(ProviderKey(ACCOUNT, 'one'), None, 'Sample')
ORDER = OrderRequest(ProviderKey(ACCOUNT, 'order'), INSTRUMENT, Side.BUY, 10, 100)
AGE = timedelta(seconds=30)
POLICY = Limits('paper-v1', 1000, 3000, 3000, 3000, 4000, 5000, 5, AGE, AGE)
CONTEXT = RiskInput(ORDER, InstrumentRules(INSTRUMENT, NOW, 5, 5, 90, 110, True),
                    Quote(INSTRUMENT.key, NOW, 100), NOW, Exposure(1000, 500, 1000, 2500, 2000, 2),
                    1010, 0, 10, False, False)


def test_preflight_blocks_unknown_evidence_and_checks_exact_boundaries():
    assert evaluate(POLICY, CONTEXT, NOW).approved
    assert evaluate(replace(POLICY, aggregate_rial=None), CONTEXT, NOW).reason == 'policy_unset_or_invalid'
    assert evaluate(POLICY, replace(CONTEXT, strategy_free_rial=1009), NOW).reason == 'insufficient_strategy_cash'
    assert evaluate(POLICY, CONTEXT, NOW + AGE + timedelta(microseconds=1)).reason == 'snapshot_stale_or_future'
    stale = replace(CONTEXT, quote=replace(CONTEXT.quote, observed_at=NOW - 2 * AGE))
    assert evaluate(POLICY, stale, NOW).reason == 'quote_stale_or_future'
    assert evaluate(POLICY, replace(CONTEXT, global_stopped=True), NOW).reason == 'stopped'


def test_unmanaged_sale_limits_and_aggregate_exposure():
    sell = replace(CONTEXT, request=replace(ORDER, side=Side.SELL))
    assert evaluate(POLICY, sell, NOW).reason == 'insufficient_managed_shares'
    assert evaluate(POLICY, replace(sell, strategy_sellable_shares=10), NOW).approved
    larger = replace(CONTEXT, exposure=replace(CONTEXT.exposure, aggregate_rial=3001))
    assert evaluate(POLICY, larger, NOW).reason == 'aggregate_limit'
    off_tick = replace(CONTEXT, request=replace(ORDER, limit_rial=99))
    assert evaluate(POLICY, off_tick, NOW).reason == 'price_or_quantity_outside_rules'
