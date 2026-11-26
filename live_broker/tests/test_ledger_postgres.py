from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import numpy as np
import pandas as pd
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
import pytest

from live_broker.contracts import (
    AccountKey, Fill, Instrument, InstrumentRules, OrderRequest, ProviderKey, Side, WriteReceipt, WriteState,
)
from live_broker.ledger import Ledger, State, account_values
from live_broker.paper import Bar, simulate, size_order
from live_broker.paper_service import Asset, Market, PaperService
from live_broker.risk import Exposure, Limits, Quote, RiskInput, Verdict, evaluate
from factormix.monthly_paper import POLICY
from factormix.decision_readiness import assess_ranking
from factormix.refresh_ranking import ARCHIVE, rank_rows, read, score_blocks
from factormix.tests.evidence_fixture import controlled_evidence
from ranking_research.return_v8.features import FIELDS, WEIGHTS


@pytest.fixture(scope='module')
def dsn():
    value = os.environ.get('RFA_BROKER_LEDGER_TEST_DSN')
    if not value:
        pytest.skip('RFA_BROKER_LEDGER_TEST_DSN not provided')
    options = conninfo_to_dict(value)
    if (options.get('host') not in {'127.0.0.1', '::1'} or options.get('hostaddr') or options.get('service')
            or not options.get('dbname', '').startswith('company_financial_test_') or not options.get('port')):
        pytest.fail('ledger tests require an explicit loopback-only test database')
    migrations = sorted((Path(__file__).parents[1] / 'sql').glob('*.sql'))
    with psycopg.connect(value, autocommit=True) as db:
        for migration in migrations:
            db.execute(migration.read_text(encoding='utf-8'))
    return value


@pytest.fixture
def account(dsn):
    key = AccountKey('synthetic', uuid4().hex)
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute('INSERT INTO broker_execution.accounts (broker_id,account_id,cash_rial,stopped) VALUES (%s,%s,1000,false)',
                   account_values(key))
        Ledger(db).set_global_stopped(stopped=False)
    return key


def request(account, name):
    return OrderRequest(ProviderKey(account, name), Instrument(ProviderKey(account, 'demo'), None, 'Demo'),
                        Side.BUY, 10, 75)


def record(ledger, order):
    # Low-level crash/fencing fixture. The public paper flow has no injected verdict.
    with ledger.db.transaction(), ledger.db.cursor(row_factory=dict_row) as cur:
        key = order.client_key.account
        balance = ledger._account(cur, key)
        used = cur.execute('''SELECT COALESCE(sum(reserved_rial),0) AS reserved FROM broker_execution.orders
            WHERE broker_id=%s AND account_id=%s''', account_values(key)).fetchone()['reserved']
        approved = (not balance['stopped'] and not ledger._global_stopped(cur)
                    and used + order.shares * order.limit_rial + 10 <= balance['cash_rial'])
        return ledger._insert_intent(cur, order, Verdict(approved, 'fixture', 'synthetic-v1'), 10)


def test_competing_writers_reserve_once_and_conflicting_intent_is_rejected(dsn, account):
    def submit(name):
        with psycopg.connect(dsn, autocommit=True) as db:
            return record(Ledger(db), request(account, name))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ('first', 'second')))
    assert set(results) == {State.APPROVED, State.RISK_REJECTED}
    chosen = request(account, ('first', 'second')[results.index(State.APPROVED)])
    with psycopg.connect(dsn, autocommit=True) as db:
        assert record(Ledger(db), chosen) == State.APPROVED
        with pytest.raises(ValueError, match='different content'):
            record(Ledger(db), replace(chosen, limit_rial=74))
        assert db.execute('SELECT count(*) FROM broker_execution.outbox WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (1,)


def test_crash_fencing_and_fill_after_stop_cancel(dsn, account):
    order = request(account, 'first')
    key = order.client_key
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        assert record(ledger, order) == State.APPROVED
        old = ledger.lease(account, 'old', 30)
        assert ledger.claim(old, key)
        assert not ledger.claim(old, key)
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        assert ledger.lease(account, 'replacement', 30) is None
        db.execute('UPDATE broker_execution.accounts SET lease_until=clock_timestamp() WHERE broker_id=%s AND account_id=%s',
                   account_values(account))
        current = ledger.lease(account, 'replacement', 30)
        assert current.fence > old.fence
        with pytest.raises(ValueError, match='expired lease'):
            ledger.transition(key, State.ACKNOWLEDGED, lease=old)
        assert record(ledger, order) == State.UNKNOWN
        assert not ledger.claim(current, key)
        ledger.transition(key, State.ACKNOWLEDGED, lease=current)
        at = datetime(2026, 11, 13, tzinfo=timezone.utc)
        args = dict(shares=4, price_rial=72, fee_rial=3, executed_at=at)
        callback = ProviderKey(account, 'fill-1')
        assert ledger.fill(key, callback, **args)
        assert record(ledger, order) == State.PARTIALLY_FILLED
        assert not ledger.fill(key, callback, **args)
        with pytest.raises(ValueError, match='different content'):
            ledger.fill(key, callback, **(args | {'shares': 5}))
        ledger.transition(key, State.CANCEL_REQUESTED, lease=current)
        ledger.transition(key, State.CANCELED, lease=current)
        ledger.set_stopped(account, stopped=True)
        assert ledger.fill(key, ProviderKey(account, 'fill-2'), **(args | {'shares': 6}))
        assert record(ledger, order) == State.FILLED
        assert db.execute('SELECT cash_rial,stopped FROM broker_execution.accounts WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (274, True)
        assert db.execute('SELECT shares FROM broker_execution.positions WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (10,)


def test_global_stop_blocks_claim_after_reconnect(dsn, account):
    order = request(account, 'first')
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        assert record(ledger, order) == State.APPROVED
        ledger.set_global_stopped(stopped=True)
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        lease = ledger.lease(account, 'worker', 30)
        assert not ledger.claim(lease, order.client_key)
        assert record(ledger, request(account, 'second')) == State.RISK_REJECTED


def test_broker_receipt_binds_fill_and_replays_without_booking_twice(dsn, account):
    key = request(account, 'first').client_key
    provider_order = ProviderKey(account, 'broker-order-1')
    response = WriteReceipt(WriteState.ACKNOWLEDGED, provider_order)
    fill = Fill(ProviderKey(account, 'broker-fill-1'), provider_order, datetime.now(timezone.utc), 4, 72, 3)
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        assert record(ledger, request(account, key.provider_id)) == State.APPROVED
        lease = ledger.lease(account, 'worker', 30)
        assert ledger.claim(lease, key)
        with pytest.raises(ValueError, match='no matching intent'):
            ledger.record_broker_fill(fill)
        assert ledger.record_submission(key, response, lease=lease) == WriteState.ACKNOWLEDGED

    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        ledger.set_stopped(account, stopped=True)
        assert ledger.record_broker_fill(fill)
        assert not ledger.record_broker_fill(fill)
        assert ledger.record_submission(key, response, lease=lease) == WriteState.ACKNOWLEDGED
        with pytest.raises(ValueError, match='conflicting submission receipt'):
            ledger.record_submission(key, WriteReceipt(WriteState.REJECTED, None), lease=lease)
        with pytest.raises(ValueError, match='reported fee'):
            ledger.record_broker_fill(replace(fill, fee_rial=None))
        assert db.execute('SELECT state,filled_shares FROM broker_execution.orders WHERE account_id=%s AND intent_id=%s',
                          (account.account_id, key.provider_id)).fetchone() == (State.PARTIALLY_FILLED, 4)


@pytest.mark.parametrize('outcome,provider_key,expected,state,reserved', [
    (WriteState.UNKNOWN, None, WriteState.UNKNOWN, State.UNKNOWN, 760),
    (WriteState.ACKNOWLEDGED, 'foreign', WriteState.UNKNOWN, State.UNKNOWN, 760),
    (WriteState.ACKNOWLEDGED, 'duplicate', WriteState.UNKNOWN, State.UNKNOWN, 760),
    (WriteState.REJECTED, None, WriteState.REJECTED, State.REJECTED, 0),
])
def test_unconfirmed_submission_retains_reservation(dsn, account, outcome, provider_key, expected, state, reserved):
    first = request(account, 'first')
    second = request(account, 'second')
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        db.execute('UPDATE broker_execution.accounts SET cash_rial=2000 WHERE account_id=%s', (account.account_id,))
        assert record(ledger, first) == State.APPROVED
        assert record(ledger, second) == State.APPROVED
        lease = ledger.lease(account, 'worker', 30)
        if provider_key == 'duplicate':
            assert ledger.claim(lease, first.client_key)
            provider_order = ProviderKey(account, 'duplicate')
            ledger.record_submission(first.client_key, WriteReceipt(WriteState.ACKNOWLEDGED, provider_order), lease=lease)
        elif provider_key == 'foreign':
            provider_order = ProviderKey(AccountKey(account.broker_id, 'other-account'), 'broker-order')
        else:
            provider_order = None
        assert ledger.claim(lease, second.client_key)
        response = WriteReceipt(outcome, provider_order)
        assert ledger.record_submission(second.client_key, response, lease=lease) == expected
        assert ledger.record_submission(second.client_key, response, lease=lease) == expected
        assert not ledger.claim(lease, second.client_key)
        if expected == WriteState.UNKNOWN and provider_key != 'duplicate':
            assert not ledger.claim(lease, first.client_key)
        assert db.execute('SELECT state,reserved_rial FROM broker_execution.orders WHERE account_id=%s AND intent_id=%s',
                          (account.account_id, second.client_key.provider_id)).fetchone() == (state, reserved)


def test_restore_quarantine_revokes_lease_and_preserves_uncertain_submission(dsn, account):
    order = request(account, 'first')
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        assert record(ledger, order) == State.APPROVED
        worker = ledger.lease(account, 'worker', 30)
        assert ledger.claim(worker, order.client_key)
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        ledger.quarantine_after_restore(account)
        assert record(ledger, order) == State.UNKNOWN
        with pytest.raises(ValueError, match='expired lease'):
            ledger.claim(worker, order.client_key)
        replacement = ledger.lease(account, 'replacement', 30)
        assert not ledger.claim(replacement, order.client_key)


def test_restore_quarantine_blocks_unsent_intent_after_stop_is_cleared(dsn, account):
    order = request(account, 'queued')
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        assert record(ledger, order) == State.APPROVED
        ledger.quarantine_after_restore(account)
        ledger.set_stopped(account, stopped=False)
        assert not ledger.claim(ledger.lease(account, 'worker', 30), order.client_key)


def test_failed_transaction_leaves_no_reservation_and_committed_retry_is_idempotent(dsn, account, monkeypatch):
    order = request(account, 'atomic')
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        original = ledger._event

        def fail_after_reservation(cur, key, event, detail=None):
            original(cur, key, event, detail)
            if event == State.APPROVED:
                raise RuntimeError('simulated process failure before commit')

        with monkeypatch.context() as patch:
            patch.setattr(ledger, '_event', fail_after_reservation)
            with pytest.raises(RuntimeError, match='before commit'):
                record(ledger, order)
        assert db.execute('SELECT count(*) FROM broker_execution.orders WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (0,)
        assert record(ledger, order) == State.APPROVED
    with psycopg.connect(dsn, autocommit=True) as db:
        assert record(Ledger(db), order) == State.APPROVED
        assert db.execute('SELECT count(*) FROM broker_execution.events WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (2,)


def test_offline_paper_plan_through_risk_ledger_and_partial_fill(dsn, account):
    at = datetime(2026, 11, 13, tzinfo=timezone.utc)
    asset = Instrument(ProviderKey(account, 'demo'), None, 'Demo')
    order = size_order(decision_id='synthetic-decision', instrument=asset, side=Side.BUY,
                       notional_rial=500, limit_rial=50, lot_shares=1)
    max_age = timedelta(seconds=30)
    limits = Limits('paper-v1', 500, 1000, 1000, 1000, 1000, 1000, 2, max_age, max_age)
    inputs = RiskInput(order, InstrumentRules(asset, at, 1, 1, 40, 60, True), Quote(asset.key, at, 50),
                       at, Exposure(0, 0, 0, 0, 0, 0), 1000, 0, 5, False, False)
    verdict = evaluate(limits, inputs, at)
    assert verdict.approved
    with psycopg.connect(dsn, autocommit=True) as db:
        ledger = Ledger(db)
        with db.transaction(), db.cursor(row_factory=dict_row) as cur:
            ledger._account(cur, account)
            assert ledger._insert_intent(cur, order, verdict, 5) == State.APPROVED
        lease = ledger.lease(account, 'paper-fixture', 30)
        assert ledger.claim(lease, order.client_key)
        ledger.transition(order.client_key, State.ACKNOWLEDGED, lease=lease)
        later = at + timedelta(days=1)
        partial = simulate(order, Bar(later.date(), 49, 40, False, False), decision_session=at.date(),
                           elapsed_sessions=1, order_life=5, remaining_shares=10, participation=Fraction(1, 10),
                           fee_rate=Fraction(1, 100), lot_shares=1)
        assert partial.shares == 4
        assert ledger.fill(order.client_key, ProviderKey(account, 'synthetic-fill'), shares=partial.shares,
                           price_rial=partial.price_rial, fee_rial=partial.fee_rial, executed_at=later)
        assert db.execute('SELECT state,filled_shares,reserved_rial FROM broker_execution.orders '
                          'WHERE broker_id=%s AND account_id=%s', account_values(account)).fetchone() == (
                              State.PARTIALLY_FILLED, 4, 303)


DECISION = datetime(2026, 11, 13, 15, tzinfo=timezone.utc)
UNIVERSE = tuple(Asset(f'asset-{i}', f'S{i}', 'industry') for i in range(6))
LIMITS = Limits('isolated-factor-mix', 5000, 20000, 5000, 20000, 20000, 20000, 20,
                timedelta(seconds=30), timedelta(seconds=30))


@pytest.fixture(scope='module')
def ranked():
    """Controlled factor panel, real registered scoring, ranking and portfolio code."""
    policy = read(POLICY)
    spec = importlib.util.spec_from_file_location('locked_paper_features', ARCHIVE / 'source/model_search_features.py')
    features = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(features)
    count = len(UNIVERSE)
    dates = np.arange(np.datetime64('2026-02-01'), np.datetime64('2026-11-14'))
    t = np.arange(len(dates))[:, None]
    j = np.arange(count)[None, :]
    adjusted = 1000 + t * (j + 1) + np.sin(t / (j + 3))
    raw = np.broadcast_to((j + 1)[:, :, None] + np.arange(len(FIELDS))[None, None, :] / 20
                          + t[:, :, None] / 10000, (len(dates), count, len(FIELDS))).copy()
    baseline = np.broadcast_to(j / count, adjusted.shape)
    scores = score_blocks(raw, adjusted, np.full_like(adjusted, 1e6), baseline, dates,
                          policy['source_model']['weights'], features)
    day = DECISION.date().isoformat()
    rows = rank_rows([asset.symbol for asset in UNIVERSE], scores[-1], adjusted[-1], np.zeros(count, dtype=int),
                     np.ones(count, dtype=int), np.arange(count), policy['execution_assumptions'], day, {})
    assert len({row['score'] for row in rows}) > 1
    stamps = [(DECISION - timedelta(minutes=offset)).isoformat() for offset in (4, 3, 2, 1)]
    ids = {asset.symbol: asset.instrument_id for asset in UNIVERSE}
    evidence = [dict(symbol=row['symbol'], factor=factor, source_id=ids[row['symbol']],
                     published_at=stamps[0], first_seen_at=stamps[1],
                     received_at=stamps[2], effective_at=stamps[3], identity_verified=True, complete=True)
                for row in rows for factor in ('eod', 'financial', 'sales')]
    return dict(date=day, market_date=day, computed_at_utc=DECISION.isoformat(),
                policy_sha256=policy['parent_policy_sha256'], input_evidence=evidence, rows=rows)


def market(account, at, assets=UNIVERSE):
    result = []
    for row in assets:
        inst = Instrument(ProviderKey(account, row.instrument_id), None, row.symbol)
        result.append(Market(Quote(inst.key, at, 100), InstrumentRules(inst, at, 1, 1, 80, 120, True)))
    return tuple(result)


def provision(db, *, cash=10000, limits=LIMITS, assets=UNIVERSE, pool=None):
    service = PaperService(db)
    account = AccountKey('paper', uuid4().hex)
    service.open_account(account, pool or uuid4().hex, limits, cash, assets)
    service.ledger.set_global_stopped(stopped=False)
    service.ledger.set_stopped(account, stopped=False)
    return service, account


def decide(service, account, ranked):
    return service.decide(account, ranked, market(account, DECISION), at=DECISION,
                          sessions=[DECISION.date().isoformat()], initial_entry=True)


def simulation(service, account, row, *, day=1, volume=1000, mismatch=False, stale=False):
    at = DECISION + timedelta(days=day)
    quotes = market(account, at)
    service.refresh_market(account, quotes, at=at)
    instrument = next(item for item in quotes if item.rules.instrument.display_name == row['symbol'])
    if stale:
        at += timedelta(seconds=31)
    return service.simulate_session(ProviderKey(account, row['order_id']), instrument,
        Bar(at.date(), 99 if mismatch else 100, volume, False, False), at=at,
        sessions=[DECISION.date() + timedelta(days=i) for i in range(day + 1)])


def test_factormix_full_cycle_and_idempotent_replay(dsn, tmp_path, monkeypatch):
    import live_broker.paper_service as module

    monkeypatch.setattr(module, 'ROOT', tmp_path)
    ranked = ranking_from_receipts(tmp_path)
    source = tmp_path / '1-daily.json.gz'
    ranking_file = tmp_path / 'ranking.json'
    ranking_file.write_text(json.dumps(ranked), encoding='utf-8')
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db)
        inputs = dict(at=DECISION, sessions=[DECISION.date().isoformat()], initial_entry=True)
        decision = service.decide_from_ranking_file(account, ranking_file, market(account, DECISION), **inputs)
        assert decision['state'] == 'decided'
        assert {row['symbol'] for row in decision['orders']} == {row['symbol'] for row in ranked['rows'][:5]}
        assert all(row['state'] == State.APPROVED and row['limit_rial'] == 100 and type(row['shares']) is int
                   for row in decision['orders'])
        key = ProviderKey(account, decision['orders'][0]['order_id'])
        with pytest.raises(ValueError, match='transactional preflight'):
            service.ledger.claim(service.ledger.lease(account, 'bypass-check', 30), key)
        with pytest.raises(ValueError, match='persisted simulation receipt'):
            service.ledger.fill(key, ProviderKey(account, 'unproven'), shares=1, price_rial=100,
                                fee_rial=0, executed_at=DECISION)
        links = []
        for row in decision['orders']:
            receipt = simulation(service, account, row)
            assert receipt['reason'] == 'paper_fill', receipt
            assert service.book_receipt(account, receipt['fill_id'])
            assert simulation(service, account, row) == receipt
            assert not service.book_receipt(account, receipt['fill_id'])
            links.append({'order_id': row['order_id'], 'fill_id': receipt['fill_id']})
        assert decide(service, account, ranked) == decision
        reconciliation = service.reconcile(account, decision['decision_id'], at=DECISION + timedelta(days=1))
        assert reconciliation['state'] == 'MATCHED', reconciliation
        assert db.execute('SELECT count(*) FROM broker_execution.fills WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (5,)
        source.write_text('{}', encoding='utf-8')
        with pytest.raises(ValueError, match='checksum mismatch'):
            service.decide_from_ranking_file(account, ranking_file, market(account, DECISION), **inputs)
        print(json.dumps({'decision_id': decision['decision_id'], 'orders_and_fills': links,
                          'reconciliation': reconciliation['state'], 'evidence': 'controlled synthetic inputs'}))


def ranking_from_receipts(root, fault=None):
    from ranking_research.experiments.rank_top5_rebalance_20261105.backtest_top5 import load_scores

    policy = read(POLICY)
    spec = importlib.util.spec_from_file_location('locked_paper_features', ARCHIVE / 'source/model_search_features.py')
    features = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(features)
    symbols = [asset.symbol for asset in UNIVERSE]
    evidence, files, inputs = controlled_evidence(root, symbols, [a.instrument_id for a in UNIVERSE],
                                                  DECISION, fault=fault)
    day = DECISION.date().isoformat()
    ranking = dict(date=day, market_date=day, computed_at_utc=DECISION.isoformat(), evidence_version=2,
                   policy_sha256=policy['parent_policy_sha256'], source_hashes=files.hashes,
                   input_evidence=evidence)
    data = assess_ranking(ranking, symbols, policy['execution_assumptions'], DECISION)
    if data['state'] != 'PASS':
        assert fault, {g['code'] for row in evidence for g in row['evidence_gaps']}
    panels = inputs['snapshots']
    observations = pd.concat([p.assign(decision_time=d).reset_index() for d, p in panels.items()], ignore_index=True)
    # Reconstruct the locked valuation_0 and w0 vectors from the versioned
    # factor weights. The archived contract uses this normalization order.
    base = WEIGHTS.copy()
    base[15] = 0
    base = base / base.sum() * 100
    primary = base.copy()
    primary[12:15] = 0
    primary *= 100 / primary.sum()
    contract = {'methods': [{'method_id': 'P1', 'weights': primary},
                            {'method_id': 'P3', 'weights': base}]}
    p1 = load_scores(observations, contract, symbols)['P1']
    dates = np.array(inputs['score_calendar'], dtype='datetime64[D]')
    older, current = sorted(panels)
    raw = np.repeat(panels[older].loc[symbols, FIELDS].to_numpy()[None, :, :], len(dates), axis=0)
    raw[-1] = panels[current].loc[symbols, FIELDS].to_numpy()
    baseline = np.repeat(p1[older][None, :], len(dates), axis=0)
    baseline[-1] = p1[current]
    adjusted = np.array([inputs['market_trace'][s]['close'] for s in symbols]).T
    scores = score_blocks(raw, adjusted, np.full_like(adjusted, 1e6), baseline, dates,
                          policy['source_model']['weights'], features)
    ranking['rows'] = rank_rows(symbols, scores[-1], adjusted[-1], np.zeros(len(symbols), dtype=int),
                                panels[day].financial_age_days, np.arange(len(symbols)),
                                policy['execution_assumptions'], day, {})
    return ranking


@pytest.mark.parametrize('fault', ['missing', 'revision', 'incomplete', 'future'])
def test_factormix_source_faults_create_no_orders(dsn, tmp_path, fault):
    ranking = ranking_from_receipts(tmp_path, fault)
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db)
        result = decide(service, account, ranking)
        assert result['state'] == 'blocked' and result['orders'] == []
        assert db.execute('SELECT count(*) FROM broker_execution.outbox WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (0,)


def test_factormix_incomplete_data_creates_no_orders(dsn, ranked):
    incomplete = {**ranked, 'input_evidence': [dict(item) for item in ranked['input_evidence']]}
    incomplete['input_evidence'][2]['received_at'] = None
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db)
        decision = decide(service, account, incomplete)
        assert decision['state'] == 'blocked' and decision['orders'] == []
        assert decision['readiness']['data_reasons'][0]['reason'] == 'timestamp_unknown'
        assert db.execute('SELECT count(*) FROM broker_execution.outbox WHERE broker_id=%s AND account_id=%s',
                          account_values(account)).fetchone() == (0,)


def test_factormix_concurrent_accounts_share_one_budget(dsn, ranked):
    with psycopg.connect(dsn, autocommit=True) as db:
        pool = uuid4().hex
        limits = replace(LIMITS, aggregate_rial=2000)
        accounts = [provision(db, pool=pool, limits=limits)[1] for _ in range(2)]

    def run(account):
        with psycopg.connect(dsn, autocommit=True) as db:
            return decide(PaperService(db), account, ranked)['orders']

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [order for batch in executor.map(run, accounts) for order in batch]
    assert sum(row['state'] == State.APPROVED for row in results) == 1
    assert sum(row['reason'] == 'aggregate_limit' for row in results) == 9


def test_factormix_same_account_concurrent_replay_uses_one_cash_reservation(dsn, ranked):
    with psycopg.connect(dsn, autocommit=True) as db:
        _, account = provision(db)

    def run(_):
        with psycopg.connect(dsn, autocommit=True) as db:
            return decide(PaperService(db), account, ranked)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.map(run, range(2))
    assert first == second
    with psycopg.connect(dsn, autocommit=True) as db:
        assert db.execute('SELECT count(*),sum(reserved_rial) FROM broker_execution.orders '
                          'WHERE broker_id=%s AND account_id=%s', account_values(account)).fetchone() == (5, 9595)


def test_factormix_partial_restart_stop_late_fill_and_reconciliation(dsn, ranked):
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db)
        decision = decide(service, account, ranked)
        first, second, *_ = decision['orders']
        partial = simulation(service, account, first, volume=80)
        assert partial['fill_id'] and service.book_receipt(account, partial['fill_id'])
        assert db.execute('SELECT state,filled_shares FROM broker_execution.orders WHERE intent_id=%s',
                          (first['order_id'],)).fetchone() == (State.PARTIALLY_FILLED, 4)
    with psycopg.connect(dsn, autocommit=True) as db:
        service = PaperService(db)
        assert simulation(service, account, first, volume=80) == partial
        next_fill = simulation(service, account, first, day=2)
        assert next_fill['fill_id']
        service.ledger.set_stopped(account, stopped=True)
        assert simulation(service, account, second, day=2)['reason'] == 'stopped'
        assert service.book_receipt(account, next_fill['fill_id'])
        assert simulation(service, account, second, day=2)['reason'] == 'stopped'
        assert service.reconcile(account, decision['decision_id'], at=DECISION + timedelta(days=2))['state'] == 'MATCHED'


def test_factormix_reconciliation_mismatch_and_unmanaged_shares(dsn, ranked):
    with psycopg.connect(dsn, autocommit=True) as db:
        loser = ranked['rows'][-1]['symbol']
        assets = tuple(replace(row, opening_shares=30) if row.symbol == loser else row for row in UNIVERSE)
        service, account = provision(db, assets=assets)
        decision = decide(service, account, ranked)
        assert not any(row['side'] == Side.SELL for row in decision['orders'])
        assert db.execute('''SELECT shares,managed_shares FROM broker_execution.positions
            WHERE broker_id=%s AND account_id=%s AND shares=30''', account_values(account)).fetchone() == (30, 0)
        row = decision['orders'][0]
        assert simulation(service, account, row, mismatch=True)['reason'] == 'bar_quote_mismatch'
        assert simulation(service, account, row, stale=True)['reason'] == 'quote_stale_or_future'
        db.execute('UPDATE broker_execution.accounts SET cash_rial=cash_rial-1 WHERE broker_id=%s AND account_id=%s',
                   account_values(account))
        reconciliation = service.reconcile(account, decision['decision_id'], at=DECISION)
        assert reconciliation['state'] == 'MISMATCH'
        assert simulation(service, account, row)['reason'] == 'reconciliation_blocked'


def test_factormix_unmanaged_shares_are_not_counted_as_managed_sell_capacity(dsn, ranked):
    loser = ranked['rows'][-1]['symbol']
    # The frozen buffer keeps all six eligible names. Make this held name
    # ineligible using the production ranker's mark-age rule.
    score = {row['symbol']: row['score'] for row in ranked['rows']}
    symbols = [row.symbol for row in UNIVERSE]
    rows = rank_rows(symbols, [score[symbol] for symbol in symbols], [1000] * 6,
                     [11 if symbol == loser else 0 for symbol in symbols], [1] * 6, range(6),
                     read(POLICY)['execution_assumptions'], ranked['date'], {})
    ranked = ranked | {'rows': rows}
    assets = tuple(replace(row, opening_shares=30, managed_shares=3) if row.symbol == loser else row
                   for row in UNIVERSE)
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db, assets=assets)
        decision = decide(service, account, ranked)
        sells = [row for row in decision['orders'] if row['side'] == Side.SELL]
        assert len(sells) == 1 and sells[0]['symbol'] == loser and sells[0]['shares'] == 3
        row = sells[0]
        receipt = simulation(service, account, row)
        assert receipt['fill_id'] and service.book_receipt(account, receipt['fill_id'])
        assert db.execute('''SELECT shares,managed_shares FROM broker_execution.positions
            WHERE broker_id=%s AND account_id=%s AND shares>0''', account_values(account)).fetchone() == (27, 0)


def test_factormix_expiry_releases_reservation_even_if_market_evidence_is_stale(dsn, ranked):
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db)
        decision = decide(service, account, ranked)
        row = decision['orders'][0]
        assert simulation(service, account, row, day=6, stale=True)['reason'] == 'expired'
        assert db.execute('SELECT state,reserved_rial FROM broker_execution.orders WHERE intent_id=%s',
                          (row['order_id'],)).fetchone() == (State.EXPIRED, 0)


def test_factormix_fresh_quote_cannot_override_expired_decision_evidence(dsn, ranked):
    effective = (DECISION - timedelta(days=9, hours=12)).isoformat()
    ranked = ranked | {'input_evidence': [row | {'effective_at': effective} if row['factor'] == 'eod' else row
                                           for row in ranked['input_evidence']]}
    with psycopg.connect(dsn, autocommit=True) as db:
        service, account = provision(db)
        decision = decide(service, account, ranked)
        assert decision['state'] == 'decided'
        assert simulation(service, account, decision['orders'][0]) == {
            'reason': 'decision_evidence_stale', 'fill_id': None}
