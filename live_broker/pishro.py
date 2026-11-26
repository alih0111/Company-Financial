"""Validate a normalized read-only export supplied by an authorized transport.

The envelope is an internal contract. It is not a claim about Pishro's wire
format, export availability, supported units, or documented API capabilities.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from factormix.decision_readiness import money_to_rial
from live_broker.contracts import (
    Capabilities, Cash, Connection, Instrument, Position, ProviderKey, Read, ReadState, Snapshot,
)


CAPABILITIES = Capabilities()


def parse_snapshot(connection: Connection, document: dict) -> Read[Snapshot]:
    if not isinstance(document, dict):
        return Read(ReadState.INVALID, reason='invalid_envelope')
    state = document.get('state')
    if state == 'session_expired':
        return Read(ReadState.SESSION_EXPIRED, reason='renew_session')
    if state != 'ok' or document.get('error') is not None:
        return Read(ReadState.INVALID, reason='source_error')
    if (connection.account.broker_id != 'pishro' or document.get('broker_id') != 'pishro'
            or document.get('account_id') != connection.account.account_id):
        return Read(ReadState.INVALID, reason='account_mismatch')
    if document.get('positions_complete') is not True:
        return Read(ReadState.PARTIAL, reason='incomplete_pagination')
    if document.get('quantity_unit') != 'SHARE':
        return Read(ReadState.INVALID, reason='unverified_quantity_unit')
    unit = document.get('money_unit')
    if unit not in ('IRR', 'TOMAN'):
        return Read(ReadState.INVALID, reason='unverified_money_unit')
    try:
        positions = document['positions']
        cash = document['cash']
        if not isinstance(positions, list) or not isinstance(cash, dict):
            raise ValueError('unexpected record types')

        def amount(field):
            value = cash.get(field)
            if value is None:
                return None
            if type(value) not in (str, int):
                raise ValueError('money must be a string or integer')
            return money_to_rial(Decimal(value), unit)

        account = connection.account
        items = tuple(Position(Instrument(ProviderKey(account, row['instrument_id']), row.get('isin'),
                                           row.get('display_name', '')),
                               row['shares'], row.get('sellable_shares')) for row in positions)
        snapshot = Snapshot(account, datetime.fromisoformat(document['observed_at']),
                            Cash(amount('free'), amount('reserved'), amount('buying_power')), items)
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        return Read(ReadState.INVALID, reason='invalid_snapshot_fields')
    return Read(ReadState.COMPLETE, snapshot)
