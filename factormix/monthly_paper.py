"""Forward-only paper ledger for the registered monthly FactorMix policy."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo

import jdatetime
import numpy as np

from factormix.decision_readiness import Gate, assess_ranking, readiness
from factormix.engine import Config, Execution, fill_pending, target_for
from factormix.refresh_ranking import STATE as RANKING_STATE
from factormix.refresh_ranking import (
    MONTHLY_CODAL, MONTHLY_MARKET, ROOT, calculate, latest_factor_codal_manifest,
    market_inputs, market_manifests, publish, ranking_lock, read, sha,
)
from runtime_lock import acquire_file_lock, release_file_lock

TEHRAN = ZoneInfo('Asia/Tehran')
RUN = ROOT / '.runtime/factormix-monthly-paper'
POLICY = ROOT / 'strategy_registry/RFA-FactorMix-033-M15/v1.0.0/strategy.locked.json'
COLLECTORS = ROOT / 'ranking_research/future_eval_v12_30'
SOURCES = ROOT / 'ranking_research/output/paper_cycle'


def now():
    return datetime.now(timezone.utc)


def review_sessions(sessions):
    """The first observed equity session on/after the 15th of each month."""
    if not sessions:
        return {}
    first = jdatetime.date.fromgregorian(date=date.fromisoformat(sessions[0]))
    last = jdatetime.date.fromgregorian(date=date.fromisoformat(sessions[-1]))
    reviews = {}
    for year in range(first.year, last.year + 1):
        for month in range(1, 13):
            nominal = jdatetime.date(year, month, 15).togregorian().isoformat()
            if sessions[0] <= nominal <= sessions[-1]:
                # A prolonged halt can map multiple nominal dates to the
                # same reopening session. Record a single review there.
                reviews[sessions[bisect_left(sessions, nominal)]] = nominal
    return reviews


def collect_market(local):
    day = local.date().isoformat()
    for path in market_manifests():
        if datetime.fromtimestamp(path.stat().st_mtime, TEHRAN).date() != local.date():
            continue
        info = read(path)
        received = datetime.fromisoformat(info['retrieved_at_utc']).astimezone(TEHRAN)
        if (received.date() == local.date() and received.time() >= time(17)
                and info['completed_count'] == 254 and info['failed_count'] == 0
                and day in info['latest_quote_dates']):
            return path.parent
    pack = MONTHLY_MARKET / day
    if (pack / 'manifest.json').exists() and read(pack / 'manifest.json')['completed_count'] == 254:
        # Never overwrite the evidence for a previously completed acquisition.
        pack = pack.with_name(f'{pack.name}-{local:%H%M%S%f}')
    subprocess.run([sys.executable, '-B', str(COLLECTORS / 'acquire_official_tsetmc_v12_35.py'),
                    '--daily-only', '--output-dir', str(pack)], cwd=ROOT, check=True, timeout=5400)
    info = read(pack / 'manifest.json')
    if info['completed_count'] != 254 or info['failed_count'] != 0:
        raise RuntimeError('Incomplete official price package for the 254 FactorMix symbols')
    return pack


def collect_reports(day):
    prefix = f'paper-cycle-factormix-{day}'
    candidates = list(MONTHLY_CODAL.glob(f'{prefix}*/manifest.json'))
    manifest = max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    if manifest is not None:
        prior = read(manifest)
        current = now()
        age = current - datetime.fromisoformat(prior['finished_at_utc'])
        if age >= timedelta(hours=2) and any(
            feed.get('budget_exhausted') or (
                feed.get('next_attempt_at_utc') and datetime.fromisoformat(feed['next_attempt_at_utc']) <= current
            ) for feed in prior['feeds'].values()
        ):
            manifest = None
    # The existing collectors return 1 for partial coverage but retain valid
    # receipts. A missing manifest/output still fails via the reads below.
    if manifest is None:
        run_id = prefix + now().strftime('-%H%M%S%fZ')
        manifest = MONTHLY_CODAL / run_id / 'manifest.json'
        for feed in ('financial', 'sales'):
            for path in (f'archive/{feed}-report-cache.json', f'{feed}-resume.json'):
                old = SOURCES / 'codal' / path
                local = MONTHLY_CODAL / path
                if old.is_file() and not local.exists():
                    local.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(old, local)
        env = dict(os.environ, PAPER_CYCLE_CODAL_OUTPUT=str(MONTHLY_CODAL))
        subprocess.run([sys.executable, '-B', str(COLLECTORS / 'acquire_codal_incremental.py'),
                        run_id, '--feed-budget-seconds', '90'],
                       cwd=ROOT, env=env, timeout=1800)
    info = read(manifest)
    prepared_path = manifest.parent / 'prepared/prepared-inputs.json'
    if not prepared_path.exists():
        subprocess.run([sys.executable, '-B', str(COLLECTORS / 'prepare_codal_inputs.py'), str(manifest)],
                       cwd=ROOT, timeout=1800)
    prepared = read(prepared_path)
    coverage = {key: {field: feed.get(field) for field in ('state', 'pagination_complete',
                                                          'companies_checked', 'companies_failed',
                                                          'budget_exhausted', 'next_attempt_at_utc')}
                for key, feed in info.get('feeds', {}).items()}
    errors = prepared.get('counts', {}).get('parse_errors', 0)
    complete = not errors and set(coverage) == {'financial', 'sales'} and all(
        feed['state'] in ('received', 'empty') and feed['pagination_complete'] and not feed['companies_failed']
        for feed in coverage.values())
    return manifest, {'feeds': coverage, 'parse_errors': errors, 'complete': complete,
                      'manifest_sha256': sha(manifest), 'prepared_sha256': sha(prepared_path)}


def open_ledger(db, policy, policy_hash, opened):
    db.execute('PRAGMA synchronous=FULL')
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), '
                   'policy_sha256 TEXT NOT NULL, opened_at TEXT NOT NULL, initial REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS sessions (day TEXT PRIMARY KEY, snapshot TEXT NOT NULL, '
                   'ranking TEXT)')
        db.execute('INSERT OR IGNORE INTO account VALUES (1,?,?,?)',
                   (policy_hash, opened.isoformat(), policy['replay']['initial_toman']))
        bound, at, initial = db.execute('SELECT policy_sha256, opened_at, initial FROM account').fetchone()
        if bound != policy_hash:
            raise ValueError('Monthly paper account is bound to another strategy policy')
    return datetime.fromisoformat(at), initial


def market_bars(data, md, i):
    session = str(data['cal'][i])
    records = [md.data[str(symbol)] for symbol in data['syms']]
    indices = [rec['dmap'].get(session) for rec in records]
    opening = np.array([rec['o'][k] * rec['cf'][k] if k is not None else np.nan
                        for rec, k in zip(records, indices)])
    locked = np.array([rec['locked'][k] if k is not None else False for rec, k in zip(records, indices)])
    adv = np.where(np.isfinite(opening), data['adv'][i], 0)
    return opening, locked, adv


def unit_factors(md, symbols, session):
    day = date.fromisoformat(session)
    # Persist units in that session's price basis, so a later reference-price
    # adjustment cannot rewrite old marks or change the value of old fills.
    return np.array([np.prod([factor for effective, factor in md.events[md.data[str(symbol)]['sid']]
                              if effective > day]) for symbol in symbols])


def make_review(session, nominal, policy, ranking, coverage, symbols, q, close, nav, superseded, clock):
    if (ranking['date'] != session or ranking['market_date'] != session
            or ranking['policy_sha256'] != policy['parent_policy_sha256']):
        raise ValueError('Review requires ranking based on the same market session')
    recorded = clock()
    if recorded.astimezone(TEHRAN).date().isoformat() != session:
        raise RuntimeError('Review data was not ready before the end of its Tehran date')
    universe = [str(symbol) for symbol in symbols]
    ranked_symbols = [row['symbol'] for row in ranking['rows']]
    ranks = {row['symbol']: row['rank'] for row in ranking['rows'] if row['rank'] is not None}
    rank_values = list(ranks.values())
    valid_strategy = (len(ranked_symbols) == len(universe) == len(set(universe))
                      and set(ranked_symbols) == set(universe) and bool(rank_values)
                      and all(type(value) is int and value > 0 for value in rank_values)
                      and set(rank_values) == set(range(1, len(rank_values) + 1)))
    data = assess_ranking(ranking, universe, policy['execution_assumptions'], recorded)
    gates = readiness(service=Gate.PASS.value, data=data['state'],
                      strategy=(Gate.PASS if valid_strategy else Gate.FAIL).value,
                      broker=Gate.UNKNOWN.value, mode='paper')
    review = dict(nominal_date=nominal, session=session, state='blocked',
                  kind='monthly' if nominal else 'initial_entry', recorded_at_utc=recorded.isoformat(),
                  ranking_computed_at_utc=ranking.get('computed_at_utc'), report_coverage=coverage,
                  readiness={**gates, 'data_reasons': data['reasons'],
                             'strategy_reason': None if valid_strategy else 'invalid_or_empty_rank_universe'})
    if not gates['decision_ready']:
        return review, None, None, None
    signal = np.array([-ranks[str(s)] if str(s) in ranks else np.nan for s in symbols])
    # The published ranking has already enforced both price and financial age.
    ages = np.zeros((1, len(q)))
    score_input = dict(p1=signal[None, :], close=close[None, :], mark_age=ages,
                       financial_age=ages, symbol_index=np.arange(len(q)))
    target, pending, selected = target_for(score_input, 0, Config(**policy['portfolio']),
                                           Execution(**policy['execution_assumptions']), q, nav)
    weights = {str(symbols[j]): float(target[j]) for j in selected}
    orders = []
    for j in np.flatnonzero(pending):
        delta = float(nav * target[j] - q[j] * close[j])
        orders.append(dict(symbol=str(symbols[j]), side='BUY' if delta > 0 else 'SELL',
                           indicative_toman=abs(delta)))
    order = {'session': session, 'elapsed_sessions': 0, 'target_weights': weights,
             'pending': symbols[pending].tolist()} if pending.any() else None
    review.update(state='decided', target_weights=weights, ranks={s: ranks[s] for s in weights},
                  orders=orders, superseded=superseded)
    return review, order, target, pending


def register_initial_entry(db, day, policy, ranking, coverage, clock=now):
    with db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT day,snapshot FROM sessions ORDER BY day DESC LIMIT 1').fetchone()
        if not row or row[0] != day:
            raise ValueError('Initial entry requires a recorded market session for today')
        snapshot = json.loads(row[1])
        prior_review = snapshot['review']
        if ((prior_review and prior_review['state'] != 'blocked') or snapshot['open_batch']
                or snapshot['holdings'] or snapshot['trades'] or db.execute(
                    "SELECT 1 FROM sessions WHERE json_extract(snapshot, '$.review.state') = 'decided' LIMIT 1"
                ).fetchone()):
            raise ValueError('This paper account has already started trading')
        if snapshot['market_sha256'] not in ranking['source_hashes'].values():
            raise ValueError('Initial entry ranking and recorded market package differ')
        symbols = np.array([r['symbol'] for r in ranking['rows']])
        if len(set(symbols)) != len(symbols):
            raise ValueError('Initial entry ranking contains duplicate symbols')
        # With no positions, the plan needs ranks and cash, not an execution price.
        review, batch, _, _ = make_review(day, None, policy, ranking, coverage, symbols,
                                          np.zeros(len(symbols)), np.ones(len(symbols)),
                                          snapshot['nav_toman'], [], clock)
        snapshot.update(review=review, open_batch=batch)
        db.execute('UPDATE sessions SET snapshot=?, ranking=? WHERE day=?',
                   (json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
                    json.dumps(ranking, ensure_ascii=False, allow_nan=False), day))
        return review['state']


def advance(db, data, md, today, opened, initial, policy, market_hash, receipt, build_ranking, clock=now):
    last_row = db.execute('SELECT day,snapshot FROM sessions ORDER BY day DESC LIMIT 1').fetchone()
    last_day, last = (last_row[0], json.loads(last_row[1])) if last_row else ('', {})
    symbols = data['syms']
    q = np.array([last.get('units', {}).get(str(symbol), 0.) for symbol in symbols])
    if last_day:
        q /= unit_factors(md, symbols, last_day)
    cash = last.get('cash_toman', initial)
    order = last.get('open_batch')
    target = np.array([order['target_weights'].get(str(s), 0.) for s in symbols]) if order else np.zeros(len(q))
    pending = np.array([bool(order and str(s) in order['pending']) for s in symbols])
    execution = Execution(**policy['execution_assumptions'])
    cal = data['cal'].tolist()
    opening_day = opened.astimezone(TEHRAN).date().isoformat()
    start = bisect_left(cal, opening_day)
    if last_day and last_day not in cal:
        raise ValueError('Price history no longer contains the last committed session')
    bars = {i: market_bars(data, md, i) for i in range(start, len(cal))}
    active = [i for i, (op, _, _) in bars.items() if np.isfinite(op).any()]
    # Include sessions before account opening when locating this month's first review.
    sessions = [*cal[:start], *(cal[i] for i in active)]
    reviews = review_sessions(sessions)
    for i in active:
        session = cal[i]
        if session <= last_day:
            continue
        factor = unit_factors(md, symbols, session)
        trades, expired = [], []
        if order:
            order['elapsed_sessions'] += 1
            if execution.delay <= order['elapsed_sessions'] < execution.delay + execution.order_life:
                opening, locked, adv = bars[i]
                cash, trades, _ = fill_pending(session, order['session'], symbols, opening, locked,
                                                data['close'][i-1], adv, q, cash, pending, target, execution)
                for fill in trades:
                    j = int(np.flatnonzero(symbols == fill['symbol'])[0])
                    fill['units'] *= float(factor[j])
                    fill['index_price'] /= float(factor[j])
                    fill.pop('base_toman')
            order['pending'] = symbols[pending].tolist()
            if order['elapsed_sessions'] >= execution.delay + execution.order_life - 1:
                expired = order['pending']
                order = None
            elif not pending.any():
                order = None
        value = q * data['close'][i]
        nav = cash + float(value.sum())
        if not np.isfinite(nav) or nav <= 0 or cash < -1e-4 or (q < -1e-7).any():
            raise ValueError('Monthly paper account failed cash/positions reconciliation')
        review = None
        ranking = None
        if session in reviews:
            review = {'nominal_date': reviews[session], 'session': session, 'state': 'missed',
                      'recorded_at_utc': clock().isoformat()}
            if session == today:
                ranking, coverage = build_ranking()
                superseded = order['pending'] if order else []
                review, next_order, next_target, next_pending = make_review(
                    session, reviews[session], policy, ranking, coverage, symbols,
                    q, data['close'][i], nav, superseded, clock)
                if review['state'] == 'decided':
                    order, target, pending = next_order, next_target, next_pending
        last = dict(session=session, cash_toman=cash, nav_toman=nav, review=review, trades=trades,
                    units={str(symbols[j]): float(q[j]*factor[j]) for j in np.flatnonzero(q > 1e-10)},
                    holdings=[dict(symbol=str(symbols[j]), units=float(q[j]*factor[j]),
                                   value_toman=float(value[j]), price_date=str(date.fromisoformat(session)
                                   - timedelta(days=int(data['mark_age'][i, j]))))
                              for j in np.flatnonzero(q > 1e-10)],
                    open_batch=order, expired=expired, market_sha256=market_hash,
                    market_received_at_utc=receipt, recorded_at_utc=clock().isoformat())
        with db:
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (session, json.dumps(last, allow_nan=False),
                       json.dumps(ranking, ensure_ascii=False, allow_nan=False) if ranking else None))


def export_ledger(db, opened, initial, strategy_id):
    rows = [json.loads(row[0]) for row in db.execute('SELECT snapshot FROM sessions ORDER BY day')]
    latest = rows[-1] if rows else {}
    return dict(strategy_id=strategy_id, opened_at_utc=opened.isoformat(), initial_toman=initial,
                session=latest.get('session'), cash_toman=latest.get('cash_toman', initial),
                nav_toman=latest.get('nav_toman', initial), holdings=latest.get('holdings', []),
                open_batch=latest.get('open_batch'), reviews=[row['review'] for row in rows if row['review']],
                trades=[fill for row in rows for fill in row['trades']],
                expired=[dict(session=row['session'], symbols=row['expired']) for row in rows if row['expired']],
                nav=[dict(session=row['session'], nav_toman=row['nav_toman'], cash_toman=row['cash_toman'],
                          market_sha256=row['market_sha256'])
                     for row in rows])


def run(started, *, initial_entry=False, coverage=None):
    policy = read(POLICY)
    local = started.astimezone(TEHRAN)
    today = local.date().isoformat()
    with closing(sqlite3.connect(RUN / 'account.sqlite3')) as db:
        opened, initial = open_ledger(db, policy, sha(POLICY), started)
        try:
            if initial_entry:
                if local.time() < time(17):
                    raise ValueError('Initial entry requires completed market data after 17:00 Tehran time')
                with ranking_lock():
                    ranking = read(RANKING_STATE / 'latest.json')
                    for path, expected in ranking['source_hashes'].items():
                        if sha(ROOT / path) != expected:
                            raise ValueError('Initial entry ranking source checksum mismatch')
                    review_state = register_initial_entry(db, today, policy, ranking, coverage)
                return ('decision_blocked' if review_state == 'blocked' else 'ready'), coverage
            closed = local.weekday() in (3, 4)
            expected = today
            if closed:
                expected = (local.date() - timedelta(days=local.weekday() - 2)).isoformat()
                last = db.execute('SELECT MAX(day) FROM sessions').fetchone()[0]
                if last and last >= expected:
                    return 'weekly_closed', coverage
            elif local.time() < time(17):
                return 'before_cutoff', coverage
            pack = collect_market(local)
            manifest = pack / 'manifest.json'
            market = market_inputs(pack, expected)
            _, _, data, md = market

            op, _, _ = market_bars(data, md, len(data['cal'])-1)
            has_session = bool(np.isfinite(op).any())
            previous_coverage = coverage
            reports, coverage = None, None

            def build_ranking():
                nonlocal reports, coverage
                try:
                    reports, coverage = collect_reports(today)
                except (OSError, ValueError, subprocess.SubprocessError):
                    # A transport failure doesn't erase reports already admitted
                    # to canonical PostgreSQL or received in the local archive.
                    reports = latest_factor_codal_manifest()
                    coverage = {'complete': False, 'used_previous_manifest': True,
                                'manifest_sha256': sha(reports)}
                run_id = 'review-' + started.strftime('%Y%m%dT%H%M%S%fZ')
                with ranking_lock():
                    ranking = calculate(RUN / run_id, today, pack=pack, market=market, codal_manifest=reports)
                coverage['canonical'] = read(RUN / run_id / 'factor-inputs/admission.json').get(
                    'canonical_quick_sync', {}).get('state')
                return ranking, coverage

            advance(db, data, md, today, opened, initial, policy, sha(manifest),
                    read(manifest)['retrieved_at_utc'], build_ranking)
            if not closed and coverage is None:
                _, coverage = collect_reports(today)
            if not has_session:
                return 'no_session_data', coverage or previous_coverage
            review_state = db.execute("SELECT json_extract(snapshot, '$.review.state') FROM sessions WHERE day=?",
                                      (today,)).fetchone()
            if review_state == ('blocked',):
                return 'decision_blocked', coverage or previous_coverage
            return ('weekly_closed' if closed else 'ready'), coverage or previous_coverage
        finally:
            with closing(sqlite3.connect(RUN / 'account.backup.sqlite3')) as backup:
                db.backup(backup)
            publish(RUN / 'account.json', export_ledger(db, opened, initial, policy['registry_id']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initial-entry', action='store_true', help='Record the first paper basket on today’s completed session.')
    parser.add_argument('--reports-only', action='store_true', help='Refresh Codal receipts without processing orders.')
    args = parser.parse_args()
    if args.initial_entry and args.reports_only:
        parser.error('Choose either initial entry or reports only.')
    RUN.mkdir(parents=True, exist_ok=True)
    with (RUN / 'cycle.lock').open('a+b') as lock:
        try:
            acquire_file_lock(lock)
        except OSError:
            if args.initial_entry or args.reports_only:
                raise SystemExit('Monthly paper cycle already running.')
            print('Monthly paper cycle already running', flush=True)
            return
        started = now()
        previous = read(RUN / 'status.json') if (RUN / 'status.json').exists() else {}
        coverage = previous.get('report_coverage')
        publish(RUN / 'status.json', dict(state='running', started_at_utc=started.isoformat()))
        try:
            if args.reports_only:
                _, coverage = collect_reports(started.astimezone(TEHRAN).date().isoformat())
                publish(RUN / 'status.json', {**previous, 'report_coverage': coverage})
                print(json.dumps(coverage), flush=True)
                return
            state, coverage = run(started, initial_entry=args.initial_entry, coverage=coverage)
            publish(RUN / 'status.json', dict(state=state, started_at_utc=started.isoformat(),
                                              finished_at_utc=now().isoformat(), report_coverage=coverage))
            print(state, flush=True)
        except Exception:
            publish(RUN / 'status.json', previous if args.initial_entry or args.reports_only else dict(
                state='failed', started_at_utc=started.isoformat(), finished_at_utc=now().isoformat()))
            raise
        finally:
            release_file_lock(lock)


if __name__ == '__main__':
    main()
