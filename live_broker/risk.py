"""Pure preflight for isolated paper execution. Values are integer rial and shares."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from live_broker.contracts import InstrumentRules, OrderRequest, ProviderKey, Side, aware, integer


@dataclass(frozen=True)
class Limits:
    version: str
    order_rial: int | None = None
    account_rial: int | None = None
    instrument_rial: int | None = None
    industry_rial: int | None = None
    aggregate_rial: int | None = None
    turnover_rial: int | None = None
    orders_per_minute: int | None = None
    quote_max_age: timedelta | None = None
    snapshot_max_age: timedelta | None = None


@dataclass(frozen=True)
class Quote:
    key: ProviderKey
    observed_at: datetime
    raw_rial: int

    def __post_init__(self):
        aware(self.observed_at)
        integer(self.raw_rial, minimum=1)


@dataclass(frozen=True)
class Exposure:
    """Scope-specific gross marked exposure including outstanding buy commitments."""

    account_rial: int
    instrument_rial: int
    industry_rial: int
    aggregate_rial: int
    turnover_rial: int
    orders_last_minute: int

    def __post_init__(self):
        for value in (self.account_rial, self.instrument_rial, self.industry_rial, self.aggregate_rial,
                      self.turnover_rial, self.orders_last_minute):
            integer(value)


@dataclass(frozen=True)
class RiskInput:
    request: OrderRequest
    rules: InstrumentRules | None
    quote: Quote | None
    account_observed_at: datetime | None
    exposure: Exposure | None
    strategy_free_rial: int | None
    strategy_sellable_shares: int | None
    estimated_fee_rial: int
    account_stopped: bool
    global_stopped: bool


@dataclass(frozen=True)
class Verdict:
    approved: bool
    reason: str
    policy_version: str


def evaluate(limits: Limits, context: RiskInput, now: datetime) -> Verdict:
    aware(now)

    def result(reason):
        return Verdict(reason == 'approved', reason, limits.version)

    if context.account_stopped or context.global_stopped:
        return result('stopped')
    caps = (limits.order_rial, limits.account_rial, limits.instrument_rial, limits.industry_rial,
            limits.aggregate_rial, limits.turnover_rial, limits.orders_per_minute)
    ages = (limits.quote_max_age, limits.snapshot_max_age)
    if (not limits.version or any(type(cap) is not int or cap <= 0 for cap in caps)
            or any(not isinstance(age, timedelta) or age <= timedelta(0) for age in ages)):
        return result('policy_unset_or_invalid')
    if context.account_observed_at is None or context.exposure is None:
        return result('account_evidence_missing')
    aware(context.account_observed_at)
    if not timedelta(0) <= now - context.account_observed_at <= limits.snapshot_max_age:
        return result('snapshot_stale_or_future')
    request, quote, rules = context.request, context.quote, context.rules
    if quote is None or quote.key != request.instrument.key:
        return result('quote_unverified')
    if not timedelta(0) <= now - quote.observed_at <= limits.quote_max_age:
        return result('quote_stale_or_future')
    if (rules is None or rules.instrument.key != request.instrument.key or rules.tradable is not True
            or not timedelta(0) <= now - rules.observed_at <= limits.snapshot_max_age
            or None in (rules.lower_rial, rules.upper_rial, rules.tick_rial, rules.lot_shares)):
        return result('instrument_rules_unverified_or_halted')
    if (not rules.lower_rial <= request.limit_rial <= rules.upper_rial or request.limit_rial % rules.tick_rial
            or request.shares % rules.lot_shares):
        return result('price_or_quantity_outside_rules')
    integer(context.estimated_fee_rial)
    notional = request.shares * request.limit_rial
    buy = request.side == Side.BUY
    growth = request.shares * max(quote.raw_rial, request.limit_rial) if buy else 0
    if buy:
        if type(context.strategy_free_rial) is not int or context.strategy_free_rial < notional + context.estimated_fee_rial:
            return result('insufficient_strategy_cash')
    elif type(context.strategy_sellable_shares) is not int or context.strategy_sellable_shares < request.shares:
        return result('insufficient_managed_shares')
    exp = context.exposure
    for actual, cap, reason in zip(
        (notional, exp.account_rial + growth, exp.instrument_rial + growth, exp.industry_rial + growth,
         exp.aggregate_rial + growth, exp.turnover_rial + notional, exp.orders_last_minute + 1),
        caps, ('order_limit', 'account_limit', 'instrument_limit', 'industry_limit', 'aggregate_limit',
               'turnover_limit', 'rate_limit'), strict=True,
    ):
        if actual > cap:
            return result(reason)
    return result('approved')
