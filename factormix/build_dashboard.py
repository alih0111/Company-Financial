"""Publish verified frozen history and the independent forward journal.

This is not a collector or a trading daemon. It refuses changed archive files,
reproduces every historical NAV, reconciles the transaction ledger and writes
only dashboard projections outside the immutable version directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import jdatetime
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factormix import engine
from factormix.journal import tracker, utc_now

ARCHIVE = ROOT / 'strategy_registry/RFA-FactorMix-033/v1.0.0'
PUBLIC = ROOT / 'client/public/strategies/factormix-033'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_archive(archive):
    manifest = json.loads((archive / 'MANIFEST.sha256.json').read_text(encoding='utf8'))
    for item in manifest['files']:
        file = archive / item['path']
        if not file.is_file() or sha(file) != item['sha256']:
            raise RuntimeError('Frozen strategy integrity failed: ' + item['path'])
    return manifest


def ledger_rows(trades, syms, initial):
    """Weighted-average cost incl. fees. Units are adjusted index units, not shares."""
    q = {s: 0.0 for s in syms}
    basis = q.copy()
    realized = q.copy()
    first_buy, last_buy = {}, {}
    cash = float(initial)
    rows = []
    for number, t in enumerate(trades, 1):
        s = t['symbol']; units = t['units']
        released = 0.0
        if t['side'] == 'BUY':
            delta = -t['gross_toman'] - t['fee_toman']
            basis[s] -= delta
            q[s] += units
            first_buy.setdefault(s, t['session']); last_buy[s] = t['session']
        else:
            if units > q[s] + 1e-7:
                raise AssertionError('Sell exceeds position')
            released = basis[s] * min(1, units / q[s])
            delta = t['gross_toman'] - t['fee_toman']
            realized[s] += delta - released
            basis[s] -= released
            q[s] -= units
        cash += delta
        if cash < -0.01:
            raise AssertionError('Negative available cash')
        rows.append(dict(id=f'fill-{number:04d}', **t, cash_delta_toman=delta,
                         cash_after_toman=max(0.0, cash), released_cost_toman=released,
                         realized_pnl_toman=(delta - released) if t['side'] == 'SELL' else None))
    return dict(units=q, basis=basis, realized=realized, cash=cash, trades=rows,
                first_buy=first_buy, last_buy=last_buy)


def next_review(after, offset=40):
    year = jdatetime.date.fromgregorian(date=pd.Timestamp(after).date()).year
    days = []
    for y in [year, year + 1]:
        for m, d in [(3, 31), (6, 31), (9, 30)]:
            days.append(jdatetime.date(y, m, d).togregorian() + timedelta(days=offset))
        days.append(jdatetime.date(y+1, 1, 1).togregorian() + timedelta(days=offset-1))
    return min(d.isoformat() for d in days if d.isoformat() > after)


def ranking_snapshot(data, i, cfg, execution, target_symbols, held_symbols):
    """Exact engine order at a dated cutoff, not the old page's P1 ranking.

    The p1 array is the engine's transport slot for candidate_score. Preserve its
    actual raw weighted score and deterministic tie ordering, without inventing
    a 0-100 score or implying a fresh prospective decision.
    """
    order = engine.order_for(data, i, cfg, execution)
    rows = [dict(rank=rank, symbol=str(data['syms'][j]), score=float(data['candidate_score'][i, j]),
                 selected_in_last_decision=str(data['syms'][j]) in target_symbols,
                 held_at_portfolio_end=str(data['syms'][j]) in held_symbols)
            for rank, j in enumerate(order, 1)]
    return dict(date=str(data['cal'][i]), financial_snapshot_date=str(data['signal_dates'][i]),
                signal_age_days=int(data['score_age'][i]), universe_count=len(data['syms']),
                eligible_count=len(rows), excluded_count=len(data['syms'])-len(rows),
                model='GROUP_WEIGHT_033', basis='historical_reconstruction', rows=rows)


def build_history(archive=ARCHIVE):
    manifest = verify_archive(archive)
    policy = json.loads((archive / 'strategy.locked.json').read_text(encoding='utf8'))
    summary = json.loads((archive / 'results/active_summary.json').read_text(encoding='utf8'))
    data = dict(np.load(archive / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    data['p1'] = data['candidate_score']
    cfg = engine.Config(**policy['portfolio']); execution = engine.Execution(**policy['execution_assumptions'])
    traces = {}

    def observe(state):
        # Keep only the latest state and quarter decisions, never the full matrix in JSON.
        traces['last'] = state
        if state['decision'] == state['session']:
            traces[state['session']] = state

    run = engine.simulate(data, cfg, execution, start=policy['replay']['requested_start'],
                          end=policy['replay']['market_end'], detail=True, observer=observe)
    reference = pd.read_csv(archive / 'results/active_candidate_nav.csv')
    assert run['cal'].tolist() == reference.session.tolist()
    np.testing.assert_allclose(run['nav'], reference.nav_toman.to_numpy(), rtol=0, atol=1)
    np.testing.assert_allclose(run['cash'], reference.cash_toman.to_numpy(), rtol=0, atol=1)
    assert abs(run['nav'][-1] - policy['replay']['expected_final_toman']) < 1
    ledger = ledger_rows(run['trades'], data['syms'].tolist(), summary['initial_toman'])
    assert abs(ledger['cash'] - run['terminal_cash']) < 1
    last = traces['last']; i = last['i']; last_day = str(data['cal'][i])
    decision = traces[last['decision']]; di = decision['i']
    order = engine.order_for(data, di, cfg, execution)
    ranks = {int(j): r for r, j in enumerate(order, 1)}
    latest_targets = set(run['decisions'][-1]['target'].split(';'))
    holdings = []
    for j in np.flatnonzero(last['q'] > 1e-10):
        s = str(data['syms'][j]); units = ledger['units'][s]
        assert abs(units - last['q'][j]) < 1e-6
        value = float(units * data['close'][i, j])
        age = int(data['mark_age'][i, j])
        price_day = (pd.Timestamp(last_day) - pd.Timedelta(days=age)).date().isoformat()
        holdings.append(dict(symbol=s, index_units=units, cost_basis_toman=ledger['basis'][s],
            average_cost_toman=ledger['basis'][s]/units, last_index_price_toman=float(data['close'][i,j]),
            price_date=price_day, price_age_days=age, market_value_toman=value,
            weight=value/run['nav'][-1], unrealized_pnl_toman=value-ledger['basis'][s],
            realized_pnl_toman=ledger['realized'][s], first_buy=ledger['first_buy'][s],
            last_buy=ledger['last_buy'][s], decision_rank=ranks.get(int(j)),
            action='HOLD' if s in latest_targets else 'EXIT_UNFILLED',
            pending_order=bool(last['pending'][j]), target_weight=float(last['target'][j])))
    holdings.sort(key=lambda x: -x['market_value_toman'])
    held_symbols = {h['symbol'] for h in holdings}
    rankings = dict(
        decision=ranking_snapshot(data, di, cfg, execution, latest_targets, held_symbols),
        latest=ranking_snapshot(data, i, cfg, execution, latest_targets, held_symbols))
    unrealized = sum(h['unrealized_pnl_toman'] for h in holdings)
    realized = sum(ledger['realized'].values())
    assert abs(realized + unrealized - (run['nav'][-1] - summary['initial_toman'])) < 1
    assert abs(sum(h['market_value_toman'] for h in holdings) + ledger['cash'] - run['nav'][-1]) < 1
    orders = []
    for j in np.flatnonzero(last['pending']):
        s = str(data['syms'][j]); target = float(last['target'][j])
        expired = i > last['expires']
        side = 'SELL' if target == 0 or last['q'][j]*data['close'][i,j]/last['nav'] > target else 'BUY'
        reason = 'NO_TRADABLE_OPEN' if not np.isfinite(data['opening'][i,j]) else (
            'ONE_PRICE_BAR' if data['locked'][i,j] else 'CAPACITY_OR_CASH_LIMIT')
        orders.append(dict(symbol=s, side=side, status='EXPIRED' if expired else 'PENDING',
            reason=reason, decision_date=last['decision'], target_weight=target,
            eligible_sessions_observed=max(0, i-last['eligible_i']+1),
            lifetime_sessions=execution.order_life,
            partial_units=sum(t['units'] for t in run['trades'] if t['decision']==last['decision'] and t['symbol']==s)))
    baseline = pd.read_csv(archive / 'results/active_baseline_nav.csv')
    assert baseline.session.tolist() == run['cal'].tolist()
    path = [dict(date=str(d), nav_toman=float(n), baseline_toman=float(b), cash_toman=max(0.,float(c)),
                 drawdown=float(n/max(summary['initial_toman'],float(np.max(run['nav'][:k+1])))-1))
            for k,(d,n,b,c) in enumerate(zip(run['cal'],run['nav'],baseline.nav_toman,run['cash']))]
    decisions = []
    for t in run['decisions']:
        d = traces[t['session']]; ordered = engine.order_for(data,d['i'],cfg,execution)
        decision_ranks = {str(data['syms'][j]):r for r,j in enumerate(ordered,1)}
        targets = t['target'].split(';')
        held = [str(data['syms'][j]) for j in np.flatnonzero(d['q']>1e-10)]
        decisions.append(dict(date=t['session'], signal_date=t['signal_date'], nav_toman=t['nav_toman'],
            targets=[dict(symbol=s,rank=decision_ranks.get(s),weight=float(w)) for s,w in zip(targets,t['weights'].split(';'))],
            held=held, entrants=[s for s in targets if s not in held],
            exits=[s for s in held if s not in targets],
            fill_count=sum(x['decision']==t['session'] for x in run['trades'])))
    return dict(schema_version=1, strategy_id=policy['registry_id'], version=policy['registry_version'],
        mode='historical_replay', as_of=last_day, start=summary['start'],
        policy_sha256=sha(archive/'strategy.locked.json'), manifest_sha256=sha(archive/'MANIFEST.sha256.json'),
        initial_toman=summary['initial_toman'], nav_toman=float(run['nav'][-1]),
        cash_toman=max(0.,ledger['cash']), realized_pnl_toman=realized, unrealized_pnl_toman=unrealized,
        fees_toman=run['cost_toman'], slippage_toman=run['slippage_toman'],
        metrics=run['metrics'], baseline=summary['baseline'], holdings=holdings,
        trades=ledger['trades'], decisions=decisions, orders=orders, path=path, rankings=rankings,
        annual=summary['jalali_years'], next_nominal_review=next_review(last_day),
        policy=dict(block_weights=policy['block_weights'], rules=policy['human_rules'], execution=policy['execution_assumptions']),
        integrity=dict(verified_files=len(manifest['files']), daily_nav_reproduced=True, ledger_reconciled=True))


def atomic_json(path, obj):
    raw = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf8')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.factormix-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-tracker', action='store_true')
    args = parser.parse_args()
    history = build_history()
    forward = tracker(ROOT/'factormix/state/tracker.sqlite3', history['policy_sha256'], open_account=args.open_tracker)
    dashboard = dict(**history, generated_at_utc=utc_now(), forward=forward)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    from factormix.performance import publish_performance
    publish_performance(history, PUBLIC, atomic_json)
    # Downloads are derived from the same verified source; no local absolute paths or secrets published.
    for source, target in [('active_candidate_trades.csv','trades.csv'), ('active_candidate_nav.csv','nav.csv'),
                            ('active_candidate_decisions.csv','decisions.csv')]:
        shutil.copyfile(ARCHIVE/'results'/source, PUBLIC/target)
    for source, target in [('STRATEGY.fa.md','strategy.fa.md'), ('strategy.locked.json','strategy.locked.json')]:
        if target.endswith('.json'):
            # Publish only portable rules, never original filesystem locations.
            atomic_json(PUBLIC/target, dict(strategy_id=history['strategy_id'], version=history['version'],
                                          policy=history['policy'], policy_sha256=history['policy_sha256']))
        else:
            # Full recovery guide contains local file paths; keep the public guide portable.
            (PUBLIC/target).write_text('# استراتژی FactorMix-033 — نسخهٔ ۱٫۰٫۰\n\n'
                'سبد هدف ۵ سهم با وزن برابر، نگهداری تا رتبهٔ ۸، بازبینی پایان فصل شمسی +۴۰ روز.\n\n'
                'این خروجی بازپخش تاریخی با واحد شاخصی تعدیل‌شده است. دفتر پیگیری آینده مستقل است.\n'
                'تعریف دقیق، وزن‌ها و فرض‌های اجرا در strategy.locked.json همراه این گزارش قرار دارد.\n', encoding='utf8')
    for name, snapshot in history['rankings'].items():
        pd.DataFrame(snapshot['rows']).assign(
            calculation_date=snapshot['date'], financial_snapshot_date=snapshot['financial_snapshot_date'],
            model=snapshot['model']).to_csv(PUBLIC/f'ranking-{name}.csv',index=False,encoding='utf-8-sig')
    atomic_json(PUBLIC/'dashboard.json', dashboard)
    atomic_json(PUBLIC/'forward.json', forward)
    print(json.dumps(dict(status='PASS', market_date=history['as_of'], trades=len(history['trades']),
                          holdings=len(history['holdings']), tracker=forward['status'])))


if __name__ == '__main__':
    main()
