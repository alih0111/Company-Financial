"""Deterministic in-memory adapters for contract and simulation tests."""
from dataclasses import dataclass, field
from threading import Lock

from live_broker.contracts import (
    BrokerOrder, Capabilities, Capability, Connection, Fill, FillCursor, FillPage,
    InstrumentRules, ProviderKey, Read, ReadState, Snapshot, integer,
)


@dataclass
class FakeBroker:
    connection: Connection
    account_snapshot: Snapshot
    orders: tuple[BrokerOrder, ...] = ()
    executions: tuple[Fill, ...] = ()
    instrument_rules: tuple[InstrumentRules, ...] = ()
    page_size: int = 2
    _lock: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)
    _state: ReadState = field(default=ReadState.COMPLETE, init=False)

    def __post_init__(self):
        integer(self.page_size, minimum=1)
        accounts = {self.account_snapshot.account, *(row.key.account for row in self.orders),
                    *(row.key.account for row in self.executions),
                    *(row.instrument.key.account for row in self.instrument_rules)}
        if accounts != {self.connection.account}:
            raise ValueError('fixture account scope mismatch')

    def capabilities(self):
        yes, no = Capability.VERIFIED, Capability.UNSUPPORTED
        return Capabilities(yes, yes, yes, yes, no, no, no)

    def set_health(self, state: ReadState):
        with self._lock:
            self._state = state

    def _read(self, value):
        if self._state != ReadState.COMPLETE:
            return Read(self._state, reason=self._state.value)
        return Read(ReadState.COMPLETE, value)

    def snapshot(self):
        with self._lock:
            return self._read(self.account_snapshot)

    def open_orders(self):
        with self._lock:
            return self._read(self.orders)

    def _encode(self, offset):
        return f'offset:{offset}'

    def fills(self, after=None):
        with self._lock:
            if self._state != ReadState.COMPLETE:
                return self._read(None)
            start = 0
            if after is not None:
                if after.connection != self.connection:
                    return Read(ReadState.INVALID, reason='cursor_scope_mismatch')
                offsets = {self._encode(i): i for i in range(len(self.executions) + 1)}
                if after.opaque not in offsets:
                    return Read(ReadState.INVALID, reason='unrecognized_cursor')
                start = offsets[after.opaque]
            end = min(start + self.page_size, len(self.executions))
            return self._read(FillPage(self.executions[start:end], FillCursor(self.connection, self._encode(end)),
                                       end < len(self.executions)))

    def rules(self, key: ProviderKey):
        with self._lock:
            if key.account != self.connection.account:
                return Read(ReadState.INVALID, reason='instrument_scope_mismatch')
            value = next((row for row in self.instrument_rules if row.instrument.key == key), None)
            return self._read(value) if value is not None else Read(ReadState.UNKNOWN, reason='unknown_instrument')


class SecondFakeBroker(FakeBroker):
    def _encode(self, offset):
        return f'page-{offset:08x}'
