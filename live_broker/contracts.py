"""Shared contracts for broker reads and future order operations."""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Generic, Protocol, TypeVar


class Capability(StrEnum):
    VERIFIED = 'verified'
    UNKNOWN = 'unknown'
    UNSUPPORTED = 'unsupported'


class ReadState(StrEnum):
    COMPLETE = 'complete'
    PARTIAL = 'partial'
    UNKNOWN = 'unknown'
    SESSION_EXPIRED = 'session_expired'
    INVALID = 'invalid'


class Side(StrEnum):
    BUY = 'BUY'
    SELL = 'SELL'


def identifier(value: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError('expected a nonempty canonical identifier')


def integer(value: int, *, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError('expected an integer in the supported range')


def aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('expected a timezone-aware timestamp')


@dataclass(frozen=True, order=True)
class AccountKey:
    broker_id: str
    account_id: str

    def __post_init__(self):
        identifier(self.broker_id)
        identifier(self.account_id)


@dataclass(frozen=True)
class ProviderKey:
    account: AccountKey
    provider_id: str

    def __post_init__(self):
        identifier(self.provider_id)


@dataclass(frozen=True)
class Connection:
    account: AccountKey
    connection_id: str

    def __post_init__(self):
        identifier(self.connection_id)


@dataclass(frozen=True)
class Capabilities:
    snapshot: Capability = Capability.UNKNOWN
    open_orders: Capability = Capability.UNKNOWN
    fills: Capability = Capability.UNKNOWN
    instrument_rules: Capability = Capability.UNKNOWN
    submit: Capability = Capability.UNKNOWN
    search: Capability = Capability.UNKNOWN
    cancel: Capability = Capability.UNKNOWN


@dataclass(frozen=True)
class Instrument:
    key: ProviderKey
    isin: str | None
    display_name: str

    def __post_init__(self):
        if self.isin is not None:
            identifier(self.isin)


@dataclass(frozen=True)
class Position:
    instrument: Instrument
    shares: int
    sellable_shares: int | None

    def __post_init__(self):
        integer(self.shares)
        if self.sellable_shares is not None:
            integer(self.sellable_shares)
            if self.sellable_shares > self.shares:
                raise ValueError('sellable shares exceed held shares')


@dataclass(frozen=True)
class Cash:
    """Integer rial. Missing values stay None, including in otherwise valid reads."""

    free_rial: int | None
    reserved_rial: int | None
    buying_power_rial: int | None

    def __post_init__(self):
        for value in (self.free_rial, self.reserved_rial, self.buying_power_rial):
            if value is not None:
                integer(value)


@dataclass(frozen=True)
class Snapshot:
    account: AccountKey
    observed_at: datetime
    cash: Cash
    positions: tuple[Position, ...]

    def __post_init__(self):
        aware(self.observed_at)
        keys = tuple(row.instrument.key for row in self.positions)
        if any(key.account != self.account for key in keys) or len(set(keys)) != len(keys):
            raise ValueError('positions must be unique and belong to the snapshot account')


@dataclass(frozen=True)
class InstrumentRules:
    instrument: Instrument
    observed_at: datetime
    tick_rial: int | None
    lot_shares: int | None
    lower_rial: int | None
    upper_rial: int | None
    tradable: bool | None

    def __post_init__(self):
        aware(self.observed_at)
        for value in (self.tick_rial, self.lot_shares, self.lower_rial, self.upper_rial):
            if value is not None:
                integer(value, minimum=1)
        if self.lower_rial is not None and self.upper_rial is not None and self.lower_rial > self.upper_rial:
            raise ValueError('inverted price bounds')


@dataclass(frozen=True)
class OrderRequest:
    client_key: ProviderKey
    instrument: Instrument
    side: Side
    shares: int
    limit_rial: int

    def __post_init__(self):
        integer(self.shares, minimum=1)
        integer(self.limit_rial, minimum=1)
        if not isinstance(self.side, Side) or self.client_key.account != self.instrument.key.account:
            raise ValueError('invalid side or order account')


@dataclass(frozen=True)
class BrokerOrder:
    key: ProviderKey
    instrument: Instrument
    side: Side
    shares: int
    filled_shares: int
    limit_rial: int
    observed_at: datetime

    def __post_init__(self):
        aware(self.observed_at)
        integer(self.shares, minimum=1)
        integer(self.filled_shares)
        integer(self.limit_rial, minimum=1)
        if (self.key.account != self.instrument.key.account or self.filled_shares > self.shares
                or not isinstance(self.side, Side)):
            raise ValueError('invalid order account, quantity or side')


@dataclass(frozen=True)
class Fill:
    key: ProviderKey
    order: ProviderKey
    executed_at: datetime
    shares: int
    price_rial: int
    fee_rial: int | None

    def __post_init__(self):
        aware(self.executed_at)
        integer(self.shares, minimum=1)
        integer(self.price_rial, minimum=1)
        if self.fee_rial is not None:
            integer(self.fee_rial)
        if self.key.account != self.order.account:
            raise ValueError('fill belongs to another account')


@dataclass(frozen=True)
class FillCursor:
    connection: Connection
    opaque: str

    def __post_init__(self):
        identifier(self.opaque)


@dataclass(frozen=True)
class FillPage:
    fills: tuple[Fill, ...]
    checkpoint: FillCursor
    has_more: bool

    def __post_init__(self):
        keys = tuple(row.key for row in self.fills)
        if any(key.account != self.checkpoint.connection.account for key in keys) or len(set(keys)) != len(keys):
            raise ValueError('fills must be unique and belong to the cursor account')


T = TypeVar('T')


@dataclass(frozen=True)
class Read(Generic[T]):
    state: ReadState
    value: T | None = None
    reason: str | None = None

    def __post_init__(self):
        if self.state == ReadState.COMPLETE:
            if self.value is None or self.reason is not None:
                raise ValueError('complete reads require a value and no error')
        elif not self.reason or (self.state != ReadState.PARTIAL and self.value is not None):
            raise ValueError('unusable reads require an error and cannot carry data')


class BrokerAdapter(Protocol):
    @property
    def connection(self) -> Connection: ...
    def capabilities(self) -> Capabilities: ...
    def snapshot(self) -> Read[Snapshot]: ...
    def open_orders(self) -> Read[tuple[BrokerOrder, ...]]: ...
    def fills(self, after: FillCursor | None = None) -> Read[FillPage]: ...
    def rules(self, key: ProviderKey) -> Read[InstrumentRules]: ...


class WriteState(StrEnum):
    ACKNOWLEDGED = 'acknowledged'
    REJECTED = 'rejected'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class WriteReceipt:
    state: WriteState
    provider_order: ProviderKey | None

    def __post_init__(self):
        if not isinstance(self.state, WriteState):
            raise ValueError('invalid write state')
        if self.state == WriteState.ACKNOWLEDGED:
            if not isinstance(self.provider_order, ProviderKey):
                raise ValueError('acknowledgment requires a broker order ID')
        elif self.provider_order is not None:
            raise ValueError('only an acknowledgment can bind a broker order ID')


class BrokerOrderOperations(Protocol):
    """Future protocol. No implementation is registered with the application."""

    def submit(self, order: OrderRequest) -> WriteReceipt: ...
    def search(self, client_key: ProviderKey) -> Read[tuple[BrokerOrder, ...]]: ...
    def cancel(self, order: ProviderKey) -> WriteReceipt: ...
