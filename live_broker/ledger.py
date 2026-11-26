"""Transactional order journal. Outbox claims model dispatch for paper tests only."""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from live_broker.contracts import AccountKey, Fill, ProviderKey, WriteReceipt, WriteState, aware, identifier, integer


class State(StrEnum):
    CREATED = 'CREATED'
    RISK_REJECTED = 'RISK_REJECTED'
    APPROVED = 'APPROVED'
    SUBMITTING = 'SUBMITTING'
    UNKNOWN = 'UNKNOWN'
    ACKNOWLEDGED = 'ACKNOWLEDGED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCEL_REQUESTED = 'CANCEL_REQUESTED'
    CANCELED = 'CANCELED'
    REJECTED = 'REJECTED'
    EXPIRED = 'EXPIRED'


TRANSITIONS = {
    State.SUBMITTING: {State.ACKNOWLEDGED, State.REJECTED, State.UNKNOWN},
    State.ACKNOWLEDGED: {State.CANCEL_REQUESTED, State.CANCELED, State.EXPIRED},
    State.PARTIALLY_FILLED: {State.CANCEL_REQUESTED, State.CANCELED, State.EXPIRED},
    State.CANCEL_REQUESTED: {State.CANCELED, State.UNKNOWN},
    State.UNKNOWN: {State.ACKNOWLEDGED, State.CANCELED, State.REJECTED, State.EXPIRED},
}


def account_values(key):
    return (key.broker_id, key.account_id)


def order_values(key):
    return (*account_values(key.account), key.provider_id)


@dataclass(frozen=True)
class Lease:
    account: AccountKey
    owner: str
    fence: int


class Ledger:
    """Owns the transaction on a dedicated autocommit connection."""

    def __init__(self, connection):
        if not connection.autocommit:
            raise ValueError('ledger requires a dedicated autocommit connection')
        self.db = connection

    def _account(self, cur, key):
        row = cur.execute('''SELECT * FROM broker_execution.accounts
                             WHERE broker_id=%s AND account_id=%s FOR UPDATE''', account_values(key)).fetchone()
        if row is None:
            raise KeyError('unknown account')
        return row

    def set_stopped(self, account: AccountKey, *, stopped: bool):
        if type(stopped) is not bool:
            raise ValueError('stop state must be explicit')
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._account(cur, account)
            cur.execute('UPDATE broker_execution.accounts SET stopped=%s WHERE broker_id=%s AND account_id=%s',
                        (stopped, *account_values(account)))

    def set_global_stopped(self, *, stopped: bool):
        if type(stopped) is not bool:
            raise ValueError('stop state must be explicit')
        self.db.execute('UPDATE broker_execution.controls SET stopped=%s WHERE singleton', (stopped,))

    def quarantine_after_restore(self, account: AccountKey):
        """Before serving restored data, revoke leases and require reconciliation."""
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._account(cur, account)
            cur.execute('''UPDATE broker_execution.accounts SET stopped=true, reconciliation_required=true, lease_owner=NULL,
                           lease_until=NULL, fence=fence+1 WHERE broker_id=%s AND account_id=%s''',
                        account_values(account))
            self._mark_submissions_unknown(cur, account)

    def _global_stopped(self, cur):
        row = cur.execute('SELECT stopped FROM broker_execution.controls WHERE singleton FOR SHARE').fetchone()
        return row is None or row['stopped']

    def _order(self, cur, key):
        return cur.execute('''SELECT * FROM broker_execution.orders
                              WHERE broker_id=%s AND account_id=%s AND intent_id=%s''', order_values(key)).fetchone()

    def _event(self, cur, key, event, detail=None):
        cur.execute('''INSERT INTO broker_execution.events (broker_id,account_id,intent_id,event,detail)
                       VALUES (%s,%s,%s,%s,%s)''', (*order_values(key), event, Jsonb(detail or {})))

    def _transition(self, cur, key, state, *, release=False):
        cur.execute('''UPDATE broker_execution.orders SET state=%s,
                       reserved_rial=CASE WHEN %s THEN 0 ELSE reserved_rial END,
                       reserved_shares=CASE WHEN %s THEN 0 ELSE reserved_shares END
                       WHERE broker_id=%s AND account_id=%s AND intent_id=%s''',
                    (state, release, release, *order_values(key)))
        self._event(cur, key, state)

    def _insert_intent(self, cur, request, verdict, fee_reserve_rial, *, decision_id=None, admitted_at=None):
        """Persistence only. The paper service evaluates and locks resources before calling this."""
        key = request.client_key
        identifier(verdict.policy_version)
        identifier(verdict.reason)
        integer(fee_reserve_rial)
        intent = (request.instrument.key.provider_id, request.side, request.shares, request.limit_rial,
                  fee_reserve_rial, verdict.policy_version, decision_id)
        existing = self._order(cur, key)
        if existing:
            fields = ('instrument_id', 'side', 'shares', 'limit_rial', 'fee_reserve_rial', 'policy_version', 'decision_id')
            if tuple(existing[field] for field in fields) != intent:
                raise ValueError('intent key reused with different content')
            return State(existing['state'])
        buy = request.side == 'BUY'
        reserve_cash = request.shares * request.limit_rial + fee_reserve_rial if buy else fee_reserve_rial
        reserve_shares = 0 if buy else request.shares
        cur.execute('''INSERT INTO broker_execution.orders
                       (broker_id,account_id,intent_id,instrument_id,side,shares,limit_rial,fee_reserve_rial,
                        policy_version,decision_id,risk_reason,state,reserved_rial,reserved_shares,admitted_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'CREATED',%s,%s,%s)''',
                    (*order_values(key), *intent, verdict.reason, reserve_cash if verdict.approved else 0,
                     reserve_shares if verdict.approved else 0, admitted_at))
        self._event(cur, key, State.CREATED, {'decision_id': decision_id})
        state = State.APPROVED if verdict.approved else State.RISK_REJECTED
        self._transition(cur, key, state)
        if verdict.approved:
            cur.execute('INSERT INTO broker_execution.outbox VALUES (%s,%s,%s)', order_values(key))
        return state

    def lease(self, account: AccountKey, owner: str, seconds: int):
        identifier(owner)
        integer(seconds, minimum=1)
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._account(cur, account)
            row = cur.execute('''UPDATE broker_execution.accounts SET lease_owner=%s,
                                 lease_until=clock_timestamp()+make_interval(secs=>%s), fence=fence+1
                                 WHERE broker_id=%s AND account_id=%s
                                 AND (lease_until IS NULL OR lease_until <= clock_timestamp()) RETURNING fence''',
                              (owner, seconds, *account_values(account))).fetchone()
            if row is None:
                return None
            self._mark_submissions_unknown(cur, account)
            return Lease(account, owner, row['fence'])

    def _mark_submissions_unknown(self, cur, account):
        uncertain = cur.execute('''SELECT intent_id FROM broker_execution.orders
                                  WHERE broker_id=%s AND account_id=%s AND state='SUBMITTING' ''',
                                account_values(account)).fetchall()
        for item in uncertain:
            self._transition(cur, ProviderKey(account, item['intent_id']), State.UNKNOWN)

    def _verify_lease(self, cur, lease):
        self._account(cur, lease.account)
        row = cur.execute('''SELECT stopped,reconciliation_required FROM broker_execution.accounts
                             WHERE broker_id=%s AND account_id=%s AND lease_owner=%s AND fence=%s
                             AND lease_until > clock_timestamp()''',
                          (*account_values(lease.account), lease.owner, lease.fence)).fetchone()
        if row is None:
            raise ValueError('invalid or expired lease')
        return row

    def claim(self, lease: Lease, key: ProviderKey):
        if key.account.broker_id == 'paper':
            raise ValueError('paper execution requires transactional preflight')
        if key.account != lease.account:
            raise ValueError('lease account mismatch')
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            account = self._verify_lease(cur, lease)
            if account['stopped'] or account['reconciliation_required'] or self._global_stopped(cur):
                return False
            if cur.execute('''SELECT 1 FROM broker_execution.orders WHERE broker_id=%s AND account_id=%s
                              AND state IN ('SUBMITTING','UNKNOWN') LIMIT 1''', account_values(key.account)).fetchone():
                return False
            row = self._order(cur, key)
            if row is None or row['state'] != State.APPROVED:
                return False
            if not cur.execute('''DELETE FROM broker_execution.outbox WHERE broker_id=%s AND account_id=%s
                                  AND intent_id=%s RETURNING intent_id''', order_values(key)).fetchone():
                return False
            cur.execute('''UPDATE broker_execution.orders SET submit_fence=%s
                           WHERE broker_id=%s AND account_id=%s AND intent_id=%s''', (lease.fence, *order_values(key)))
            self._transition(cur, key, State.SUBMITTING)
            return True

    def record_submission(self, key: ProviderKey, receipt: WriteReceipt, *, lease: Lease) -> WriteState:
        """Bind a write response to its claimed intent and persist the outcome atomically."""
        if key.account != lease.account or key.account.broker_id == 'paper':
            raise ValueError('invalid submission account')
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._verify_lease(cur, lease)
            row = self._order(cur, key)
            if row is None or row['submit_fence'] != lease.fence:
                raise ValueError('submission fence mismatch')

            outcome, provider_order = receipt.state, receipt.provider_order
            provider_id, reason = None, None
            if provider_order:
                if provider_order.account != key.account:
                    reason = 'broker_order_account_mismatch'
                else:
                    binding = cur.execute('''SELECT intent_id FROM broker_execution.submission_receipts
                        WHERE broker_id=%s AND account_id=%s AND provider_order_id=%s''',
                                          order_values(provider_order)).fetchone()
                    if binding and binding['intent_id'] != key.provider_id:
                        reason = 'broker_order_id_already_bound'
                    else:
                        provider_id = provider_order.provider_id
            elif outcome == WriteState.REJECTED and row['filled_shares']:
                reason = 'rejection_conflicts_with_fill'
            if reason:
                outcome = WriteState.UNKNOWN

            prior = cur.execute('''SELECT outcome,provider_order_id FROM broker_execution.submission_receipts
                WHERE broker_id=%s AND account_id=%s AND intent_id=%s''', order_values(key)).fetchone()
            if prior:
                if (prior['outcome'], prior['provider_order_id']) != (outcome, provider_id):
                    raise ValueError('conflicting submission receipt')
                return outcome
            if row['state'] not in {State.SUBMITTING, State.FILLED}:
                raise ValueError('order is not awaiting a submission receipt')

            cur.execute('''INSERT INTO broker_execution.submission_receipts
                (broker_id,account_id,intent_id,outcome,provider_order_id) VALUES (%s,%s,%s,%s,%s)''',
                        (*order_values(key), outcome, provider_id))
            self._event(cur, key, 'SUBMISSION_RECEIPT',
                        {'outcome': outcome, 'provider_order_id': provider_id, 'reason': reason})
            if row['state'] == State.SUBMITTING:
                state = State[outcome.name]
                if state == State.ACKNOWLEDGED and row['filled_shares']:
                    state = State.PARTIALLY_FILLED
                self._transition(cur, key, state, release=state == State.REJECTED)
            return outcome

    def transition(self, key: ProviderKey, state: State, *, lease: Lease):
        if key.account.broker_id == 'paper':
            raise ValueError('paper transitions belong to the paper service')
        if key.account != lease.account or not isinstance(state, State):
            raise ValueError('lease account mismatch or invalid transition')
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._verify_lease(cur, lease)
            row = self._order(cur, key)
            if row is None or state not in TRANSITIONS.get(row['state'], ()):
                raise ValueError('invalid order transition')
            if row['state'] == State.SUBMITTING and row['submit_fence'] != lease.fence:
                raise ValueError('submission fence mismatch')
            if state == State.REJECTED and row['filled_shares']:
                raise ValueError('cannot reject an order with recorded fills')
            if state == State.ACKNOWLEDGED and row['filled_shares']:
                state = State.PARTIALLY_FILLED
            self._transition(cur, key, state, release=state in {State.CANCELED, State.REJECTED, State.EXPIRED})

    def fill(self, key: ProviderKey, fill_id: ProviderKey, *, shares: int, price_rial: int,
             fee_rial: int, executed_at: datetime):
        if key.account.broker_id == 'paper':
            raise ValueError('paper fill must reference a persisted simulation receipt')
        if key.account != fill_id.account:
            raise ValueError('fill account mismatch')
        integer(shares, minimum=1)
        integer(price_rial, minimum=1)
        integer(fee_rial)
        aware(executed_at)
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._account(cur, key.account)
            return self._book_fill(cur, key, fill_id, shares, price_rial, fee_rial, executed_at)

    def record_broker_fill(self, fill: Fill) -> bool:
        """Book a fill against the broker's order ID and a known, reported fee."""
        account = fill.order.account
        if account.broker_id == 'paper' or fill.fee_rial is None:
            raise ValueError('broker fill requires a real account and a reported fee')
        with self.db.transaction(), self.db.cursor(row_factory=dict_row) as cur:
            self._account(cur, account)
            binding = cur.execute('''SELECT intent_id FROM broker_execution.submission_receipts
                WHERE broker_id=%s AND account_id=%s AND provider_order_id=%s''',
                                  order_values(fill.order)).fetchone()
            if binding is None:
                raise ValueError('broker order ID has no matching intent')
            return self._book_fill(cur, ProviderKey(account, binding['intent_id']), fill.key,
                                   fill.shares, fill.price_rial, fill.fee_rial, fill.executed_at)

    def _book_fill(self, cur, key, fill_id, shares, price_rial, fee_rial, executed_at):
        managed = key.account.broker_id == 'paper'
        event = (key.provider_id, executed_at, shares, price_rial, fee_rial)
        previous = cur.execute('''SELECT intent_id,executed_at,shares,price_rial,fee_rial
                                  FROM broker_execution.fills WHERE broker_id=%s AND account_id=%s AND fill_id=%s''',
                               order_values(fill_id)).fetchone()
        if previous:
            if tuple(previous.values()) != event:
                raise ValueError('fill key reused with different content')
            return False
        row = self._order(cur, key)
        fillable = {State.SUBMITTING, State.UNKNOWN, State.ACKNOWLEDGED, State.PARTIALLY_FILLED,
                    State.CANCEL_REQUESTED, State.CANCELED, State.EXPIRED}
        if row is None or row['state'] not in fillable or row['filled_shares'] + shares > row['shares']:
            raise ValueError('fill conflicts with order history')
        cur.execute('INSERT INTO broker_execution.fills VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                    (*order_values(fill_id), *event))
        buy = row['side'] == 'BUY'
        signed = shares if buy else -shares
        cash = cur.execute('''UPDATE broker_execution.accounts SET cash_rial=cash_rial+%s
                              WHERE broker_id=%s AND account_id=%s RETURNING cash_rial''',
                           (-signed * price_rial - fee_rial, *account_values(key.account))).fetchone()
        position = cur.execute('''INSERT INTO broker_execution.positions
                       (broker_id,account_id,instrument_id,shares,managed_shares) VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (broker_id,account_id,instrument_id) DO UPDATE
                       SET shares=broker_execution.positions.shares+excluded.shares,
                           managed_shares=broker_execution.positions.managed_shares+excluded.managed_shares
                       RETURNING shares,managed_shares''',
                               (*account_values(key.account), row['instrument_id'], signed, signed if managed else 0)).fetchone()
        total = row['filled_shares'] + shares
        terminal = row['state'] in {State.CANCELED, State.EXPIRED}
        if total == row['shares']:
            state = State.FILLED
        elif terminal or row['state'] in {State.UNKNOWN, State.CANCEL_REQUESTED, State.SUBMITTING}:
            state = State(row['state'])
        else:
            state = State.PARTIALLY_FILLED
        release = terminal or state == State.FILLED
        used_reserve = (shares * row['limit_rial'] if buy else 0) + fee_rial
        cur.execute('''UPDATE broker_execution.orders SET state=%s,filled_shares=%s,reserved_rial=%s,reserved_shares=%s
                       WHERE broker_id=%s AND account_id=%s AND intent_id=%s''',
                    (state, total, 0 if release else max(0, row['reserved_rial'] - used_reserve),
                     0 if release else max(0, row['reserved_shares'] - (0 if buy else shares)), *order_values(key)))
        self._event(cur, key, 'FILL', {'fill_id': fill_id.provider_id, 'state': state})
        if cash['cash_rial'] < 0 or position['shares'] < 0 or position['managed_shares'] < 0:
            cur.execute('UPDATE broker_execution.accounts SET stopped=true WHERE broker_id=%s AND account_id=%s',
                        account_values(key.account))
            self._event(cur, key, 'RESOURCE_DEFICIT')
        return True
