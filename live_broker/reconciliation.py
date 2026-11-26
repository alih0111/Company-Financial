"""Compare complete broker evidence with an immutable ledger projection."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from live_broker.contracts import (
    AccountKey, BrokerOrder, Cash, Fill, Position, ProviderKey, Read, ReadState, Snapshot, aware,
)


class Result(StrEnum):
    MATCHED = 'MATCHED'
    MISMATCH = 'MISMATCH'
    UNKNOWN = 'UNKNOWN'


class ExternalKind(StrEnum):
    MANUAL_TRADE = 'manual_trade'
    DEPOSIT = 'deposit'
    WITHDRAWAL = 'withdrawal'
    DIVIDEND = 'dividend'
    CORPORATE_ACTION = 'corporate_action'
    TRADE_CORRECTION = 'trade_correction'


@dataclass(frozen=True)
class ExternalEvent:
    key: ProviderKey
    kind: ExternalKind
    occurred_at: datetime

    def __post_init__(self):
        aware(self.occurred_at)


@dataclass(frozen=True)
class Projection:
    account: AccountKey
    cash: Cash
    positions: tuple[Position, ...]
    orders: tuple[BrokerOrder, ...]
    fills: tuple[Fill, ...]


@dataclass(frozen=True)
class Reconciliation:
    state: Result
    reasons: tuple[str, ...]


def compare(expected: Projection, snapshot: Read[Snapshot], orders: Read[tuple[BrokerOrder, ...]],
            fills: Read[tuple[Fill, ...]], *, now: datetime, max_snapshot_age: timedelta,
            pending_external: tuple[ExternalEvent, ...] = ()) -> Reconciliation:
    aware(now)
    if max_snapshot_age <= timedelta(0):
        raise ValueError('snapshot age must be positive')
    missing = tuple(f'{name}:{read.state}' for name, read in (
        ('snapshot', snapshot), ('orders', orders), ('fills', fills)) if read.state != ReadState.COMPLETE)
    if missing:
        return Reconciliation(Result.UNKNOWN, missing)
    actual = snapshot.value
    if actual.account != expected.account:
        return Reconciliation(Result.UNKNOWN, ('account_mismatch',))
    if not timedelta(0) <= now - actual.observed_at <= max_snapshot_age:
        return Reconciliation(Result.UNKNOWN, ('snapshot_stale_or_future',))
    if pending_external:
        return Reconciliation(Result.UNKNOWN, ('unresolved_external_event',))
    reasons = []
    unknown = []
    for field in ('free_rial', 'reserved_rial', 'buying_power_rial'):
        left, right = getattr(expected.cash, field), getattr(actual.cash, field)
        if left is None or right is None:
            unknown.append(f'{field}:missing')
        elif left != right:
            reasons.append(f'{field}:difference')

    def positions(rows):
        return [(row.instrument.key, (row.shares, row.sellable_shares)) for row in rows]

    def open_orders(rows):
        return [(row.key, (row.instrument.key, row.side, row.shares, row.filled_shares, row.limit_rial))
                for row in rows]

    def executions(rows):
        return [(row.key, (row.order, row.executed_at, row.shares, row.price_rial, row.fee_rial)) for row in rows]

    if any(row.fee_rial is None for row in (*expected.fills, *fills.value)):
        unknown.append('fills:fee_missing')
    if any(row.sellable_shares is None for row in (*expected.positions, *actual.positions)):
        unknown.append('positions:sellable_missing')
    for label, left, right in (
        ('positions', positions(expected.positions), positions(actual.positions)),
        ('orders', open_orders(expected.orders), open_orders(orders.value)),
        ('fills', executions(expected.fills), executions(fills.value)),
    ):
        if any(len(dict(rows)) != len(rows) or any(key.account != expected.account for key, _ in rows)
               for rows in (left, right)):
            return Reconciliation(Result.UNKNOWN, (f'{label}:duplicate_or_wrong_account',))
        before, after = dict(left), dict(right)
        if before.keys() != after.keys() or any(
            a is not None and b is not None and a != b
            for key in before.keys() & after.keys() for a, b in zip(before[key], after[key], strict=True)
        ):
            reasons.append(f'{label}:difference')
    state = Result.MISMATCH if reasons else Result.UNKNOWN if unknown else Result.MATCHED
    return Reconciliation(state, tuple(reasons + unknown))
