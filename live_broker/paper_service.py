"""Offline FactorMix admission, simulation receipts, and reconciliation on PostgreSQL."""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from hashlib import sha256
import json

import numpy as np
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from factormix.decision_readiness import ranking_deadline
from factormix.monthly_paper import POLICY, TEHRAN, make_review, review_sessions
from factormix.refresh_ranking import ROOT, read, sha
from live_broker.contracts import (
    AccountKey, BrokerOrder, Cash, Fill, Instrument, InstrumentRules, OrderRequest,
    Position, ProviderKey, Read, ReadState, Side, Snapshot, aware, identifier, integer,
)
from live_broker.ledger import Ledger, State, account_values, order_values
from live_broker.paper import Bar, simulate, size_order
from live_broker.reconciliation import Projection, Result, compare
from live_broker.risk import Exposure, Limits, Quote, RiskInput, Verdict, evaluate


OPEN = (State.APPROVED, State.ACKNOWLEDGED, State.PARTIALLY_FILLED)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def policy_document(limits):
    value = asdict(limits)
    for name in ('quote_max_age', 'snapshot_max_age'):
        if value[name] is not None:
            value[name] = value[name].total_seconds()
    return value


def limits_from(document):
    value = dict(document)
    for name in ('quote_max_age', 'snapshot_max_age'):
        if value[name] is not None:
            value[name] = timedelta(seconds=value[name])
    return Limits(**value)


@dataclass(frozen=True)
class Asset:
    instrument_id: str
    symbol: str
    industry: str
    opening_shares: int = 0
    managed_shares: int = 0

    def __post_init__(self):
        for value in (self.instrument_id, self.symbol, self.industry):
            identifier(value)
        integer(self.opening_shares)
        integer(self.managed_shares)
        if self.managed_shares > self.opening_shares:
            raise ValueError('managed shares exceed opening holdings')


@dataclass(frozen=True)
class Market:
    quote: Quote
    rules: InstrumentRules

    def __post_init__(self):
        if self.quote.key != self.rules.instrument.key:
            raise ValueError('quote and rules instrument mismatch')


class PaperService:
    def __init__(self, connection):
        self.ledger = Ledger(connection)
        self.db = connection
        with connection.cursor(row_factory=dict_row) as cur:
            isolation = cur.execute('SHOW transaction_isolation').fetchone()['transaction_isolation']
        if isolation != 'read committed':
            raise ValueError('pooled paper reservations require READ COMMITTED')
        self.strategy = read(POLICY)
        self.policy_hash = sha(POLICY)
        self.execution = self.strategy['execution_assumptions']
        self.fee_rate = Fraction(str(self.execution['fee']))

    def open_account(self, account: AccountKey, pool_id: str, limits: Limits, cash_rial: int, assets: tuple[Asset, ...]):
        if account.broker_id != 'paper':
            raise ValueError('only separate paper accounts are supported')
        identifier(pool_id)
        identifier(limits.version)
        integer(cash_rial)
        if not assets:
            raise ValueError('explicit paper universe required')
        policy = policy_document(limits)
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            cur.execute('INSERT INTO broker_execution.paper_pools VALUES (%s,%s) ON CONFLICT DO NOTHING',
                        (pool_id, Jsonb(policy)))
            stored = cur.execute('SELECT policy FROM broker_execution.paper_pools WHERE pool_id=%s FOR UPDATE',
                                 (pool_id,)).fetchone()
            if stored['policy'] != policy:
                raise ValueError('pool already has a different policy')
            key = account_values(account)
            cur.execute('INSERT INTO broker_execution.accounts (broker_id,account_id,cash_rial) VALUES (%s,%s,%s)',
                        (*key, cash_rial))
            cur.execute('''INSERT INTO broker_execution.paper_accounts (broker_id,account_id,pool_id,opening_cash_rial)
                           VALUES (%s,%s,%s,%s)''', (*key, pool_id, cash_rial))
            for asset in assets:
                cur.execute('''INSERT INTO broker_execution.paper_assets
                    (broker_id,account_id,instrument_id,symbol,industry,opening_shares,opening_managed)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''', (*key, asset.instrument_id, asset.symbol, asset.industry,
                                                    asset.opening_shares, asset.managed_shares))
                cur.execute('''INSERT INTO broker_execution.positions
                    (broker_id,account_id,instrument_id,shares,managed_shares) VALUES (%s,%s,%s,%s,%s)''',
                            (*key, asset.instrument_id, asset.opening_shares, asset.managed_shares))

    def _lock(self, cur, account):
        if account.broker_id != 'paper':
            raise ValueError('only separate paper accounts are supported')
        balance = self.ledger._account(cur, account)
        paper = cur.execute('SELECT * FROM broker_execution.paper_accounts WHERE broker_id=%s AND account_id=%s',
                            account_values(account)).fetchone()
        if paper is None:
            raise ValueError('account is not provisioned for this paper service')
        pool = cur.execute('SELECT policy FROM broker_execution.paper_pools WHERE pool_id=%s FOR UPDATE',
                           (paper['pool_id'],)).fetchone()
        return balance, paper, limits_from(pool['policy'])

    def _assets(self, cur, account):
        rows = cur.execute('''SELECT a.*,p.shares,p.managed_shares FROM broker_execution.paper_assets a
            JOIN broker_execution.positions p USING (broker_id,account_id,instrument_id)
            WHERE a.broker_id=%s AND a.account_id=%s ORDER BY a.symbol''', account_values(account)).fetchall()
        return {row['instrument_id']: row for row in rows}

    def _instrument(self, account, asset):
        return Instrument(ProviderKey(account, asset['instrument_id']), None, asset['symbol'])

    def _store_market(self, cur, account, markets, now):
        for market in markets:
            key = market.quote.key
            if key.account != account or max(market.quote.observed_at, market.rules.observed_at) > now:
                raise ValueError('future or cross-account market evidence')
            quote = {'at': market.quote.observed_at.astimezone(timezone.utc).isoformat(), 'raw_rial': market.quote.raw_rial}
            rules = {name: getattr(market.rules, name) for name in
                     ('tick_rial', 'lot_shares', 'lower_rial', 'upper_rial', 'tradable')}
            rules['at'] = market.rules.observed_at.astimezone(timezone.utc).isoformat()
            previous = cur.execute('''SELECT quote,rules FROM broker_execution.paper_assets
                WHERE broker_id=%s AND account_id=%s AND instrument_id=%s''', order_values(key)).fetchone()
            if previous is None:
                raise ValueError('instrument outside paper universe')
            for name, item in (('quote', quote), ('rules', rules)):
                old = previous[name]
                if old and (datetime.fromisoformat(old['at']) > datetime.fromisoformat(item['at'])
                            or datetime.fromisoformat(old['at']) == datetime.fromisoformat(item['at']) and old != item):
                    raise ValueError('regressed or conflicting market evidence')
            cur.execute('''UPDATE broker_execution.paper_assets SET quote=%s,rules=%s
                           WHERE broker_id=%s AND account_id=%s AND instrument_id=%s''',
                        (Jsonb(quote), Jsonb(rules), *order_values(key)))

    def _orders(self, cur, account):
        return cur.execute('SELECT * FROM broker_execution.orders WHERE broker_id=%s AND account_id=%s',
                           account_values(account)).fetchall()

    def _preflight(self, cur, balance, paper, limits, request, fee, now, *, replacing=None):
        key = request.client_key.account
        asset = self._assets(cur, key).get(request.instrument.key.provider_id)
        if asset is None:
            return Verdict(False, 'unregistered_instrument', limits.version)
        if paper['reconciliation_blocked'] or balance['reconciliation_required']:
            return Verdict(False, 'reconciliation_blocked', limits.version)
        if balance['stopped'] or self.ledger._global_stopped(cur):
            return Verdict(False, 'stopped', limits.version)
        if cur.execute('''SELECT 1 FROM broker_execution.orders WHERE broker_id=%s AND account_id=%s
                AND state IN ('SUBMITTING','UNKNOWN','CANCEL_REQUESTED') LIMIT 1''', account_values(key)).fetchone():
            return Verdict(False, 'order_state_uncertain', limits.version)
        if cur.execute('''SELECT 1 FROM broker_execution.paper_attempts
                WHERE broker_id=%s AND account_id=%s AND fill_id IS NOT NULL AND NOT booked LIMIT 1''',
                       account_values(key)).fetchone():
            return Verdict(False, 'unbooked_simulation_receipt', limits.version)
        instrument = self._instrument(key, asset)
        q, r = asset['quote'], asset['rules']
        quote = Quote(instrument.key, datetime.fromisoformat(q['at']), q['raw_rial']) if q else None
        rules = InstrumentRules(instrument, datetime.fromisoformat(r['at']), r['tick_rial'], r['lot_shares'],
                                r['lower_rial'], r['upper_rial'], r['tradable']) if r else None
        if quote is None or limits.quote_max_age is None:
            return Verdict(False, 'quote_unverified', limits.version)
        if not timedelta(0) <= now - quote.observed_at <= limits.quote_max_age:
            return Verdict(False, 'quote_stale_or_future', limits.version)
        # All writes that alter pooled commitments or holdings take the same pool row lock.
        assets = cur.execute('''SELECT a.account_id,a.instrument_id,a.industry,a.quote,p.shares
            FROM broker_execution.paper_assets a JOIN broker_execution.positions p USING (broker_id,account_id,instrument_id)
            JOIN broker_execution.paper_accounts b USING (broker_id,account_id) WHERE b.pool_id=%s''',
                             (paper['pool_id'],)).fetchall()
        orders = cur.execute('''SELECT o.* FROM broker_execution.orders o
            JOIN broker_execution.paper_accounts a USING (broker_id,account_id) WHERE a.pool_id=%s''',
                             (paper['pool_id'],)).fetchall()
        local = [row for row in orders if row['account_id'] == key.account_id and row['intent_id'] != replacing]
        open_orders = [row for row in orders if row['state'] in OPEN and
                       (row['account_id'], row['intent_id']) != (key.account_id, replacing)]
        by_asset = {(row['account_id'], row['instrument_id']): row for row in assets}
        exposure = [0, 0, 0, 0]

        def accumulate(row, amount):
            exposure[3] += amount
            if row['account_id'] == key.account_id:
                exposure[0] += amount
                if row['instrument_id'] == asset['instrument_id']:
                    exposure[1] += amount
                if row['industry'] == asset['industry']:
                    exposure[2] += amount

        def usable_mark(row):
            mark = row['quote']
            if mark is None or limits.quote_max_age is None:
                return None
            age = now - datetime.fromisoformat(mark['at'])
            return mark['raw_rial'] if timedelta(0) <= age <= limits.quote_max_age else None

        for row in assets:
            if row['shares']:
                mark = usable_mark(row)
                if mark is None or row['shares'] < 0:
                    return Verdict(False, 'pooled_position_mark_unverified', limits.version)
                accumulate(row, row['shares'] * mark)
        for row in open_orders:
            if row['side'] == Side.BUY:
                scope = by_asset[(row['account_id'], row['instrument_id'])]
                mark = usable_mark(scope)
                if mark is None:
                    return Verdict(False, 'pooled_commitment_mark_unverified', limits.version)
                accumulate(scope, (row['shares'] - row['filled_shares']) * max(row['limit_rial'], mark))
        turnover = sum(row['shares'] * row['limit_rial'] for row in local if row['admitted_at']
                       and row['admitted_at'].astimezone(TEHRAN).date() == now.astimezone(TEHRAN).date()
                       and row['state'] != State.RISK_REJECTED)
        rate = sum(row['admitted_at'] is not None and timedelta(0) <= now - row['admitted_at'] < timedelta(minutes=1)
                   and row['state'] != State.RISK_REJECTED for row in local)
        free = balance['cash_rial'] - sum(row['reserved_rial'] for row in local)
        sellable = asset['managed_shares'] - sum(row['reserved_shares'] for row in local
                                                 if row['instrument_id'] == asset['instrument_id'])
        if free < fee:
            return Verdict(False, 'insufficient_strategy_cash', limits.version)
        return evaluate(limits, RiskInput(request, rules, quote, now, Exposure(*exposure, turnover, rate),
                                          free, sellable, fee, False, False), now)

    def _fee_reserve(self, order):
        per_share = order.limit_rial * self.fee_rate
        return order.shares * (-(-per_share.numerator // per_share.denominator))

    def refresh_market(self, account, markets, *, at):
        aware(at)
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._lock(cur, account)
            self._store_market(cur, account, markets, at)

    def decide_from_ranking_file(self, account, ranking_file, markets, **decision):
        """Admit a published local ranking after verifying its declared artifacts."""
        ranking = read(ranking_file)
        sources = ranking.get('source_hashes')
        if not isinstance(sources, dict) or not sources:
            raise ValueError('ranking has no source receipts')
        for name, expected in sources.items():
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file() or sha(path) != expected:
                raise ValueError('ranking source checksum mismatch')
        return self.decide(account, ranking, markets, **decision)

    def decide(self, account, ranking, markets, *, at, sessions, initial_entry=False):
        aware(at)
        local = at.astimezone(TEHRAN)
        session = local.date().isoformat()
        if local.hour < 17:
            raise ValueError('paper review requires after-close evidence')
        if not sessions or sessions[-1] != session or list(sessions) != sorted(set(sessions)):
            raise ValueError('ordered observed trading sessions through the decision are required')
        nominal = None if initial_entry else review_sessions(list(sessions)).get(session)
        if not initial_entry and nominal is None:
            raise ValueError('session is not a registered monthly review')
        ranking_digest = digest(ranking)
        decision_id = digest([account.broker_id, account.account_id, session, self.policy_hash])
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            balance, paper, limits = self._lock(cur, account)
            key = (*account_values(account), decision_id)
            prior = cur.execute('''SELECT ranking_digest,result FROM broker_execution.paper_decisions
                WHERE broker_id=%s AND account_id=%s AND decision_id=%s''', key).fetchone()
            if prior:
                if prior['ranking_digest'] != ranking_digest:
                    raise ValueError('different ranking for existing paper decision')
                return prior['result']
            if cur.execute('''SELECT 1 FROM broker_execution.paper_decisions
                    WHERE broker_id=%s AND account_id=%s AND session>=%s LIMIT 1''',
                           (*account_values(account), session)).fetchone():
                raise ValueError('paper decisions must advance by session')
            if initial_entry and cur.execute('''SELECT 1 FROM broker_execution.paper_decisions
                    WHERE broker_id=%s AND account_id=%s LIMIT 1''', account_values(account)).fetchone():
                raise ValueError('initial entry is only available for a new paper account')
            self._store_market(cur, account, markets, at)
            assets = list(self._assets(cur, account).values())
            quotes = {row['symbol']: row['quote'] for row in assets}
            raw = [row['quote']['raw_rial'] if row['quote'] else 0 for row in assets]
            managed = [row['managed_shares'] for row in assets]
            nav = balance['cash_rial'] + sum(shares * price for shares, price in zip(managed, raw, strict=True))
            if nav <= 0:
                raise ValueError('paper strategy NAV is not positive')
            review, _, _, _ = make_review(session, nominal, self.strategy, ranking, {},
                np.array([row['symbol'] for row in assets]), np.array(managed, dtype=float),
                np.array(raw, dtype=float) / 10, nav / 10, [], lambda: at)
            valid_until = None
            if review['state'] == 'decided':
                ages = {'eod': self.execution['max_mark_age'], 'financial': self.execution['max_financial_age'],
                        'sales': self.execution['max_financial_age']}
                valid_until = min(datetime.fromisoformat(ranking['computed_at_utc']) +
                                  timedelta(days=self.execution['max_signal_age']), *(
                    ranking_deadline(item, ages[item['factor']])
                    for item in ranking['input_evidence'] if item['symbol'] in quotes and item['factor'] in ages))
                quote_max_age = limits.quote_max_age
                identifiers = {item['symbol']: item.get('source_id') for item in ranking['input_evidence']
                               if item['factor'] == 'eod'}
                wrong_identity = [row['symbol'] for row in assets
                                  if identifiers.get(row['symbol']) != row['instrument_id']]
                invalid_quote = [symbol for symbol, quote in quotes.items() if quote is None or quote_max_age is None or
                                 not timedelta(0) <= at - datetime.fromisoformat(quote['at']) <= quote_max_age]
                if valid_until < at or invalid_quote or wrong_identity:
                    review['state'] = 'blocked'
                    review['readiness']['data'] = 'FAIL'
                    review['readiness']['decision_ready'] = False
                    review['readiness']['data_reasons'].extend(
                        {'input': [symbol, 'quote'], 'state': 'FAIL', 'reason': 'raw_quote_missing_or_stale'}
                        for symbol in invalid_quote)
                    review['readiness']['data_reasons'].extend(
                        {'input': [symbol, 'eod'], 'state': 'FAIL', 'reason': 'raw_instrument_identity_mismatch'}
                        for symbol in wrong_identity)
                    if valid_until < at:
                        review['readiness']['data_reasons'].append({'input': None, 'state': 'FAIL', 'reason': 'signal_stale'})
            result = dict(decision_id=decision_id, state=review['state'], readiness=review['readiness'], orders=[])
            cur.execute('''INSERT INTO broker_execution.paper_decisions
                (broker_id,account_id,decision_id,session,decided_at,valid_until,ranking_digest,result)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (*key, session, at, valid_until, ranking_digest, Jsonb(result)))
            if review['state'] != 'decided':
                return result
            by_symbol = {row['symbol']: row for row in assets}
            for item in review['orders']:
                asset = by_symbol[item['symbol']]
                rules = asset['rules'] or {}
                lot = rules.get('lot_shares')
                if not lot:
                    result['orders'].append(dict(symbol=item['symbol'], state='RISK_REJECTED', reason='lot_unverified'))
                    continue
                side = Side(item['side'])
                price = asset['quote']['raw_rial']
                # The locked equal-weight rule allocates one slot per selected name.
                # Recompute the monetary delta exactly before flooring to whole shares.
                slots = self.strategy['portfolio']['n']
                weight = Fraction(1, slots) if item['symbol'] in review['target_weights'] else Fraction(0)
                delta = nav * weight - asset['managed_shares'] * price
                if not delta or (delta > 0) != (side == Side.BUY):
                    continue
                notional = int(abs(delta))
                if side == Side.BUY:
                    fee_per_share = self._fee_reserve(OrderRequest(ProviderKey(account, 'sizing'),
                        self._instrument(account, asset), side, 1, price))
                    notional = (notional // (price + fee_per_share)) * price
                order = size_order(decision_id=decision_id, instrument=self._instrument(account, asset), side=side,
                                   notional_rial=notional, limit_rial=price, lot_shares=lot,
                                   managed_shares=asset['managed_shares'])
                if order is None:
                    continue
                fee = self._fee_reserve(order)
                verdict = self._preflight(cur, balance, paper, limits, order, fee, at)
                state = self.ledger._insert_intent(cur, order, verdict, fee, decision_id=decision_id, admitted_at=at)
                result['orders'].append(dict(symbol=item['symbol'], order_id=order.client_key.provider_id, state=state,
                                             reason=verdict.reason, side=side, shares=order.shares, limit_rial=order.limit_rial))
            cur.execute('''UPDATE broker_execution.paper_decisions SET result=%s
                           WHERE broker_id=%s AND account_id=%s AND decision_id=%s''', (Jsonb(result), *key))
            return result

    def _request(self, account, row, asset, shares=None):
        return OrderRequest(ProviderKey(account, row['intent_id']), self._instrument(account, asset),
                            Side(row['side']), row['shares'] if shares is None else shares, row['limit_rial'])

    def simulate_session(self, key, market, bar: Bar, *, at, sessions):
        """Record a deterministic simulator receipt. Booking is replayable after restart."""
        aware(at)
        if (market.quote.key.account != key.account or bar.session != at.astimezone(TEHRAN).date()
                or not sessions or sessions[-1] != bar.session or list(sessions) != sorted(set(sessions))):
            raise ValueError('execution evidence must match the observed session and account')
        event_digest = digest([asdict(bar) | {'session': bar.session.isoformat()}, market.quote.raw_rial,
                               market.quote.observed_at.isoformat(), market.rules.observed_at.isoformat(),
                               market.rules.tick_rial, market.rules.lot_shares, market.rules.lower_rial,
                               market.rules.upper_rial, market.rules.tradable, market.quote.key.provider_id,
                               at.isoformat(), [day.isoformat() for day in sessions]])
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            balance, paper, limits = self._lock(cur, key.account)
            row = self.ledger._order(cur, key)
            if row is None or row['decision_id'] is None:
                raise KeyError('unknown paper order')
            if row['instrument_id'] != market.quote.key.provider_id:
                raise ValueError('execution evidence instrument mismatch')
            previous = cur.execute('''SELECT reason,fill_id,event_digest FROM broker_execution.paper_attempts
                WHERE broker_id=%s AND account_id=%s AND intent_id=%s AND session=%s''',
                                   (*order_values(key), bar.session)).fetchone()
            if previous:
                if previous.pop('event_digest') != event_digest:
                    raise ValueError('session evidence differs from the persisted simulation')
                return previous
            if row['state'] not in OPEN:
                return {'reason': 'order_not_executable', 'fill_id': None}
            decision = cur.execute('''SELECT session,decided_at,valid_until FROM broker_execution.paper_decisions
                WHERE broker_id=%s AND account_id=%s AND decision_id=%s''',
                                   (*account_values(key.account), row['decision_id'])).fetchone()
            if sessions[0] != decision['session']:
                raise ValueError('execution calendar must start with the decision session')
            elapsed_sessions = len(sessions) - 1
            if elapsed_sessions < self.execution['delay'] or at <= decision['decided_at']:
                return {'reason': 'delay', 'fill_id': None}
            last = cur.execute('''SELECT max(session) AS day FROM broker_execution.paper_attempts
                WHERE broker_id=%s AND account_id=%s AND intent_id=%s''', order_values(key)).fetchone()['day']
            if last is not None and bar.session <= last:
                raise ValueError('execution session precedes an existing simulation')
            if elapsed_sessions >= self.execution['delay'] + self.execution['order_life']:
                if cur.execute('''SELECT 1 FROM broker_execution.paper_attempts WHERE broker_id=%s AND account_id=%s
                    AND intent_id=%s AND fill_id IS NOT NULL AND NOT booked LIMIT 1''', order_values(key)).fetchone():
                    return {'reason': 'unbooked_simulation_receipt', 'fill_id': None}
                cur.execute('''DELETE FROM broker_execution.outbox WHERE broker_id=%s AND account_id=%s AND intent_id=%s''',
                            order_values(key))
                cur.execute('''UPDATE broker_execution.paper_tickets SET expired=true
                               WHERE broker_id=%s AND account_id=%s AND intent_id=%s''', order_values(key))
                self.ledger._transition(cur, key, State.EXPIRED, release=True)
                return {'reason': 'expired', 'fill_id': None}
            if decision['valid_until'] is None or at > decision['valid_until']:
                return {'reason': 'decision_evidence_stale', 'fill_id': None}
            # Validate bars on the same evidence clock as quote and instrument rules.
            if (market.quote.observed_at.astimezone(TEHRAN).date() != bar.session or
                    market.rules.observed_at.astimezone(TEHRAN).date() != bar.session or
                    (bar.raw_open_rial is not None and bar.raw_open_rial != market.quote.raw_rial)):
                return {'reason': 'bar_quote_mismatch', 'fill_id': None}
            self._store_market(cur, key.account, (market,), at)
            asset = self._assets(cur, key.account)[row['instrument_id']]
            remaining = row['shares'] - row['filled_shares']
            request = self._request(key.account, row, asset, remaining)
            fee = self._fee_reserve(request)
            verdict = self._preflight(cur, balance, paper, limits, request, fee, at, replacing=key.provider_id)
            if not verdict.approved or verdict.policy_version != row['policy_version']:
                return {'reason': verdict.reason if not verdict.approved else 'policy_changed', 'fill_id': None}
            needed = fee + (remaining * row['limit_rial'] if row['side'] == Side.BUY else 0)
            if row['reserved_rial'] < needed or (row['side'] == Side.SELL and row['reserved_shares'] < remaining):
                return {'reason': 'reservation_incomplete', 'fill_id': None}
            participation = Fraction(str(self.execution['capacity']))
            simulation = simulate(request, bar, decision_session=decision['session'],
                                  elapsed_sessions=elapsed_sessions - self.execution['delay'] + 1,
                                  order_life=self.execution['order_life'], remaining_shares=remaining,
                                  participation=participation, fee_rate=self.fee_rate, lot_shares=market.rules.lot_shares)
            if row['state'] == State.APPROVED:
                claimed = cur.execute('''DELETE FROM broker_execution.outbox WHERE broker_id=%s AND account_id=%s
                                       AND intent_id=%s RETURNING intent_id''', order_values(key)).fetchone()
                if claimed is None:
                    raise ValueError('approved paper order is missing its outbox entry')
                self.ledger._transition(cur, key, State.SUBMITTING)
                self.ledger._transition(cur, key, State.ACKNOWLEDGED)
                cur.execute('''INSERT INTO broker_execution.paper_tickets
                    (broker_id,account_id,intent_id,instrument_id,side,shares,limit_rial,fee_reserve_rial)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (*order_values(key), row['instrument_id'], row['side'],
                        row['shares'], row['limit_rial'], row['fee_reserve_rial']))
            fill_id = digest([key.provider_id, bar.session.isoformat()]) if simulation.shares else None
            cur.execute('''INSERT INTO broker_execution.paper_attempts
                (broker_id,account_id,intent_id,session,elapsed_sessions,event_digest,reason,fill_id,
                 executed_at,shares,price_rial,fee_rial) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                        (*order_values(key), bar.session, elapsed_sessions, event_digest, simulation.reason, fill_id,
                         at if fill_id else None, simulation.shares, simulation.price_rial, simulation.fee_rial))
            return {'reason': simulation.reason, 'fill_id': fill_id}

    def book_receipt(self, account, fill_id):
        """Only an existing simulator receipt can move cash and shares, even after stop."""
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._lock(cur, account)
            row = cur.execute('''SELECT * FROM broker_execution.paper_attempts
                                  WHERE broker_id=%s AND account_id=%s AND fill_id=%s''',
                              (*account_values(account), fill_id)).fetchone()
            if row is None:
                raise KeyError('unknown paper receipt')
            changed = self.ledger._book_fill(cur, ProviderKey(account, row['intent_id']), ProviderKey(account, fill_id),
                                             row['shares'], row['price_rial'], row['fee_rial'], row['executed_at'])
            cur.execute('UPDATE broker_execution.paper_attempts SET booked=true WHERE broker_id=%s AND account_id=%s AND fill_id=%s',
                        (*account_values(account), fill_id))
            return changed

    def reconcile(self, account, decision_id, *, at):
        """Rebuild the simulator account independently of ledger fills and balances."""
        aware(at)
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            balance, paper, limits = self._lock(cur, account)
            scoped = account_values(account)
            assets = self._assets(cur, account)
            orders = self._orders(cur, account)
            tickets = cur.execute('SELECT * FROM broker_execution.paper_tickets WHERE broker_id=%s AND account_id=%s',
                                  scoped).fetchall()
            sim = cur.execute('''SELECT * FROM broker_execution.paper_attempts
                WHERE broker_id=%s AND account_id=%s AND fill_id IS NOT NULL''', scoped).fetchall()
            fills = cur.execute('SELECT * FROM broker_execution.fills WHERE broker_id=%s AND account_id=%s',
                                scoped).fetchall()

            def fill(row):
                return Fill(ProviderKey(account, row['fill_id']), ProviderKey(account, row['intent_id']),
                            row['executed_at'], row['shares'], row['price_rial'], row['fee_rial'])

            def broker_order(row, filled):
                return BrokerOrder(ProviderKey(account, row['intent_id']), self._instrument(account, assets[row['instrument_id']]),
                                   Side(row['side']), row['shares'], filled, row['limit_rial'], at)

            actual_cash = paper['opening_cash_rial']
            actual_shares = {key: row['opening_shares'] for key, row in assets.items()}
            actual_managed = {key: row['opening_managed'] for key, row in assets.items()}
            tickets_by_id = {row['intent_id']: row for row in tickets}
            filled = {row['intent_id']: 0 for row in tickets}
            paid = dict(filled)
            for row in sim:
                order = tickets_by_id[row['intent_id']]
                signed = row['shares'] if order['side'] == Side.BUY else -row['shares']
                actual_cash -= signed * row['price_rial'] + row['fee_rial']
                actual_shares[order['instrument_id']] += signed
                actual_managed[order['instrument_id']] += signed
                filled[row['intent_id']] += row['shares']
                paid[row['intent_id']] += row['fee_rial']
            actual_orders, actual_reserve, actual_reserved_shares = [], 0, {}
            for row in tickets:
                done = filled[row['intent_id']]
                if row['expired'] or done == row['shares']:
                    continue
                actual_orders.append(broker_order(row, done))
                remaining = row['shares'] - done
                actual_reserve += row['fee_reserve_rial'] - paid[row['intent_id']]
                if row['side'] == Side.BUY:
                    actual_reserve += remaining * row['limit_rial']
                else:
                    inst = row['instrument_id']
                    actual_reserved_shares[inst] = actual_reserved_shares.get(inst, 0) + remaining
            # Local approved orders are reservations but do not exist on the simulator yet.
            for row in orders:
                if row['state'] == State.APPROVED:
                    actual_reserve += row['fee_reserve_rial']
                    inst = row['instrument_id']
                    if row['side'] == Side.BUY:
                        actual_reserve += row['shares'] * row['limit_rial']
                    else:
                        actual_reserved_shares[inst] = actual_reserved_shares.get(inst, 0) + row['shares']
            ledger_reserved = sum(row['reserved_rial'] for row in orders)
            ledger_reserved_shares = {key: sum(row['reserved_shares'] for row in orders if row['instrument_id'] == key)
                                      for key in assets}
            reasons = []
            if any(row['executed_at'] > at for row in (*sim, *fills)):
                reasons.append('reconciliation_precedes_execution')
            if any(row['managed_shares'] != actual_managed[key] for key, row in assets.items()):
                reasons.append('managed_positions:difference')
            if any(row['state'] in (State.SUBMITTING, State.UNKNOWN, State.CANCEL_REQUESTED) for row in orders):
                reasons.append('order_state_uncertain')
            try:
                expected = Projection(account, Cash(balance['cash_rial'] - ledger_reserved, ledger_reserved,
                                                     balance['cash_rial'] - ledger_reserved),
                    tuple(Position(self._instrument(account, row), row['shares'], row['managed_shares'] - ledger_reserved_shares[key])
                          for key, row in assets.items()),
                    tuple(broker_order(row, row['filled_shares']) for row in orders
                          if row['state'] in (State.ACKNOWLEDGED, State.PARTIALLY_FILLED)), tuple(map(fill, fills)))
                snapshot = Snapshot(account, at, Cash(actual_cash - actual_reserve, actual_reserve, actual_cash - actual_reserve),
                    tuple(Position(self._instrument(account, row), actual_shares[key],
                                   actual_managed[key] - actual_reserved_shares.get(key, 0)) for key, row in assets.items()))
                result = compare(expected, Read(ReadState.COMPLETE, snapshot), Read(ReadState.COMPLETE, tuple(actual_orders)),
                                 Read(ReadState.COMPLETE, tuple(map(fill, sim))), now=at,
                                 max_snapshot_age=limits.snapshot_max_age or timedelta(seconds=1))
                reasons.extend(result.reasons)
                state = Result.MISMATCH if reasons else result.state
            except ValueError:
                reasons.append('invalid_ledger_or_simulator_projection')
                state = Result.MISMATCH
            cur.execute('''INSERT INTO broker_execution.paper_reconciliations
                (broker_id,account_id,decision_id,observed_at,state,reasons) VALUES (%s,%s,%s,%s,%s,%s)''',
                        (*scoped, decision_id, at, state, Jsonb(reasons)))
            if state != Result.MATCHED:
                cur.execute('''UPDATE broker_execution.paper_accounts SET reconciliation_blocked=true
                               WHERE broker_id=%s AND account_id=%s''', scoped)
            elif balance['reconciliation_required']:
                cur.execute('''UPDATE broker_execution.accounts SET reconciliation_required=false
                               WHERE broker_id=%s AND account_id=%s''', scoped)
            return {'decision_id': decision_id, 'state': state, 'reasons': reasons}
