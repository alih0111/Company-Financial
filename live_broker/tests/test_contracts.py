from datetime import datetime, timezone

import pytest

from live_broker.contracts import (
    AccountKey, BrokerAdapter, BrokerOrder, Capabilities, Capability, Cash, Connection,
    Fill, Instrument, InstrumentRules, Position, ProviderKey, ReadState, Side, Snapshot,
)
from live_broker.fake import FakeBroker, SecondFakeBroker

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


def adapter(implementation, broker_id, account_id='sample', connection_id='session') -> BrokerAdapter:
    account = AccountKey(broker_id, account_id)
    connection = Connection(account, connection_id)
    instrument = Instrument(ProviderKey(account, 'symbol-1'), 'IR-DEMO', 'Demo')
    order = BrokerOrder(ProviderKey(account, '123'), instrument, Side.BUY, 10, 5, 1000, NOW)
    fills = tuple(Fill(ProviderKey(account, f'fill-{i}'), order.key, NOW, 1, 1000, None) for i in range(5))
    rules = InstrumentRules(instrument, NOW, 1, 1, 900, 1100, True)
    return implementation(connection, Snapshot(account, NOW, Cash(None, 0, None), ()),
                          (order,), fills, (rules,))


@pytest.mark.parametrize('implementation', [FakeBroker, SecondFakeBroker])
def test_read_contract_and_pagination(implementation):
    broker = adapter(implementation, 'demo')
    assert broker.capabilities().snapshot == Capability.VERIFIED
    assert broker.capabilities().submit == Capability.UNSUPPORTED
    assert Capabilities().snapshot == Capability.UNKNOWN
    empty = broker.snapshot()
    assert empty.state == ReadState.COMPLETE
    assert empty.value.positions == ()
    assert empty.value.cash.buying_power_rial is None
    assert empty.value.cash.reserved_rial == 0
    order, = broker.open_orders().value
    assert broker.rules(order.instrument.key).value.lot_shares == 1
    cursor = None
    seen = []
    while True:
        page = broker.fills(cursor).value
        seen.extend(fill.key for fill in page.fills)
        cursor = page.checkpoint
        if not page.has_more:
            break
    assert len(seen) == len(set(seen)) == 5
    assert broker.fills(cursor).value.fills == ()
    broker.set_health(ReadState.SESSION_EXPIRED)
    failed = broker.snapshot()
    assert failed.state == ReadState.SESSION_EXPIRED and failed.value is None


def test_cross_broker_account_and_session_are_independent():
    first = adapter(FakeBroker, 'first')
    same_broker = adapter(FakeBroker, 'first', 'other-account')
    new_session = adapter(FakeBroker, 'first', connection_id='replacement')
    second = adapter(SecondFakeBroker, 'second')
    orders = [broker.open_orders().value[0].key for broker in (first, second)]
    assert orders[0].provider_id == orders[1].provider_id
    assert len(set(orders)) == 2
    cursor = first.fills().value.checkpoint
    first.set_health(ReadState.INVALID)
    for broker in (same_broker, new_session, second):
        assert broker.snapshot().state == ReadState.COMPLETE
        assert broker.fills(cursor).reason == 'cursor_scope_mismatch'


def test_nonintegral_or_cross_account_positions_are_rejected():
    first = adapter(FakeBroker, 'first')
    second = adapter(SecondFakeBroker, 'second')
    instrument = first.open_orders().value[0].instrument
    with pytest.raises(ValueError, match='integer'):
        Position(instrument, 1.5, None)
    with pytest.raises(ValueError, match='snapshot account'):
        Snapshot(second.connection.account, NOW, Cash(0, 0, 0), (Position(instrument, 1, 1),))
