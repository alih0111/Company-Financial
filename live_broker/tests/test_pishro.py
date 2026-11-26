import pytest

from live_broker.contracts import AccountKey, Capability, Connection, ReadState
from live_broker.pishro import CAPABILITIES, parse_snapshot

CONNECTION = Connection(AccountKey('pishro', 'synthetic-account'), 'synthetic-connection')


@pytest.fixture
def envelope():
    return dict(state='ok', broker_id='pishro', account_id='synthetic-account',
                positions_complete=True, quantity_unit='SHARE', money_unit='TOMAN',
                observed_at='2026-11-13T10:00:00+03:30', cash={'free': '12.5'}, positions=[])


def test_valid_empty_and_unknown_cash_are_distinct(envelope):
    assert CAPABILITIES.snapshot == Capability.UNKNOWN
    read = parse_snapshot(CONNECTION, envelope)
    assert read.state == ReadState.COMPLETE
    assert read.value.positions == ()
    assert read.value.cash.free_rial == 125
    assert read.value.cash.buying_power_rial is None


@pytest.mark.parametrize('update,state,reason', [
    ({'positions_complete': False}, ReadState.PARTIAL, 'incomplete_pagination'),
    ({'account_id': 'different'}, ReadState.INVALID, 'account_mismatch'),
    ({'state': 'session_expired'}, ReadState.SESSION_EXPIRED, 'renew_session'),
    ({'error': 'html_error_under_http_200'}, ReadState.INVALID, 'source_error'),
    ({'money_unit': None}, ReadState.INVALID, 'unverified_money_unit'),
    ({'quantity_unit': 'SYNTHETIC'}, ReadState.INVALID, 'unverified_quantity_unit'),
    ({'cash': {'free': '0.01'}}, ReadState.INVALID, 'invalid_snapshot_fields'),
    ({'positions': [{'instrument_id': 'A', 'shares': 1}] * 2}, ReadState.INVALID, 'invalid_snapshot_fields'),
])
def test_unusable_export_never_returns_an_empty_valid_account(envelope, update, state, reason):
    read = parse_snapshot(CONNECTION, envelope | update)
    assert (read.state, read.reason, read.value) == (state, reason, None)
