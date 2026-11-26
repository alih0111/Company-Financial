"""Deterministic offline sizing and execution proxies in raw rial and integer shares."""
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from hashlib import sha256
import json

from live_broker.contracts import Instrument, OrderRequest, ProviderKey, Side, integer


def size_order(*, decision_id: str, instrument: Instrument, side: Side, notional_rial: int,
               limit_rial: int, lot_shares: int, managed_shares: int = 0) -> OrderRequest | None:
    """Size one already-selected target delta from the strategy's paper plan."""
    integer(notional_rial)
    integer(limit_rial, minimum=1)
    integer(lot_shares, minimum=1)
    integer(managed_shares)
    if not isinstance(side, Side) or not decision_id.strip():
        raise ValueError('explicit decision identity and side required')
    shares = notional_rial // limit_rial
    if side == Side.SELL:
        shares = min(shares, managed_shares)
    shares -= shares % lot_shares
    if shares == 0:
        return None
    identity = json.dumps([decision_id, instrument.key.provider_id, side], separators=(',', ':'))
    return OrderRequest(ProviderKey(instrument.key.account, sha256(identity.encode()).hexdigest()),
                        instrument, side, shares, limit_rial)


@dataclass(frozen=True)
class Bar:
    session: date
    raw_open_rial: int | None
    volume_shares: int | None
    halted: bool | None
    queued: bool | None


@dataclass(frozen=True)
class Simulation:
    reason: str
    shares: int = 0
    price_rial: int | None = None
    fee_rial: int | None = None


def simulate(order: OrderRequest, bar: Bar, *, decision_session: date, elapsed_sessions: int,
             order_life: int, remaining_shares: int, participation: Fraction,
             fee_rate: Fraction, lot_shares: int) -> Simulation:
    """One conservative fill estimate for an already admitted paper order."""
    integer(elapsed_sessions)
    integer(order_life, minimum=1)
    integer(remaining_shares)
    integer(lot_shares, minimum=1)
    if not 0 < participation <= 1 or not 0 <= fee_rate < 1 or remaining_shares > order.shares:
        raise ValueError('invalid simulation settings')
    if remaining_shares == 0:
        return Simulation('filled')
    if bar.session <= decision_session or elapsed_sessions == 0:
        return Simulation('delay')
    if elapsed_sessions > order_life:
        return Simulation('expired')
    if bar.halted is not False or bar.queued is not False or bar.raw_open_rial is None or bar.volume_shares is None:
        return Simulation('no_verified_liquidity')
    integer(bar.raw_open_rial, minimum=1)
    integer(bar.volume_shares)
    if (order.side == Side.BUY and bar.raw_open_rial > order.limit_rial
            or order.side == Side.SELL and bar.raw_open_rial < order.limit_rial):
        return Simulation('limit_not_reached')
    shares = min(remaining_shares, int(bar.volume_shares * participation))
    shares -= shares % lot_shares
    if shares == 0:
        return Simulation('below_lot_capacity')
    # Use the limit price for conservative slippage, and round fees up to rial.
    gross = shares * order.limit_rial
    fee = gross * fee_rate
    fee_rial = -(-fee.numerator // fee.denominator)
    return Simulation('paper_fill', shares, order.limit_rial, fee_rial)
