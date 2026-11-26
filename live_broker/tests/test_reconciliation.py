from dataclasses import replace
from datetime import datetime, timedelta, timezone

from live_broker.contracts import AccountKey, Cash, Instrument, Position, ProviderKey, Read, ReadState, Snapshot
from live_broker.reconciliation import ExternalEvent, ExternalKind, Projection, Result, compare


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
ACCOUNT = AccountKey('fake', 'paper')
CASH = Cash(200, 10, 200)
POSITION = Position(Instrument(ProviderKey(ACCOUNT, 'asset'), None, 'Sample'), 5, 4)
EXPECTED = Projection(ACCOUNT, CASH, (POSITION,), (), ())
SNAPSHOT = Snapshot(ACCOUNT, NOW, CASH, (POSITION,))


def reconcile(snapshot, **kwargs):
    empty = Read(ReadState.COMPLETE, ())
    return compare(EXPECTED, snapshot, empty, empty, now=NOW, max_snapshot_age=timedelta(seconds=30), **kwargs)


def test_partial_snapshot_is_quarantined_but_valid_missing_position_is_a_difference():
    assert reconcile(Read(ReadState.COMPLETE, SNAPSHOT)).state == Result.MATCHED
    empty = replace(SNAPSHOT, positions=())
    assert reconcile(Read(ReadState.PARTIAL, empty, 'page_missing')).state == Result.UNKNOWN
    assert reconcile(Read(ReadState.COMPLETE, empty)).reasons == ('positions:difference',)
    assert EXPECTED.positions == (POSITION,)


def test_unknown_cash_staleness_and_unresolved_external_event_block_reconciliation():
    incomplete = replace(SNAPSHOT, cash=Cash(None, 10, 200))
    assert reconcile(Read(ReadState.COMPLETE, incomplete)).state == Result.UNKNOWN
    stale = replace(SNAPSHOT, observed_at=NOW - timedelta(seconds=31))
    assert reconcile(Read(ReadState.COMPLETE, stale)).reasons == ('snapshot_stale_or_future',)
    event = ExternalEvent(ProviderKey(ACCOUNT, 'event'), ExternalKind.TRADE_CORRECTION, NOW)
    assert reconcile(Read(ReadState.COMPLETE, SNAPSHOT), pending_external=(event,)).state == Result.UNKNOWN
