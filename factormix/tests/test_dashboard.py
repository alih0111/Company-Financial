import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factormix.build_dashboard import ARCHIVE, build_history, ledger_rows, next_review, verify_archive
from factormix.journal import tracker


@pytest.fixture(scope='module')
def history():
    return build_history()


def test_replay_exact_value_and_real_positions(history):
    assert history['as_of'] == '2026-11-04'
    assert history['nav_toman'] == pytest.approx(1_290_465_605.5777485, abs=1)
    assert len(history['trades']) == 120
    assert len(history['decisions']) == 16
    assert {h['symbol'] for h in history['holdings']} == {'شلیا','شمواد','فنورد','فگستر','کهمدا','کیمیا'}
    assert history['integrity']['verified_files'] == 73


def test_every_days_independent_units_and_cash_reconcile(history):
    """Replay published fills independently; price each position from frozen marks."""
    data = dict(np.load(ARCHIVE/'snapshot_data/active_inputs.npz', allow_pickle=False))
    dates = {str(d):i for i,d in enumerate(data['cal'])}
    symbols = {str(s):j for j,s in enumerate(data['syms'])}
    q = np.zeros(len(symbols)); cash = history['initial_toman']
    fills = history['trades']; k = 0
    for point in history['path']:
        while k < len(fills) and fills[k]['session'] == point['date']:
            fill = fills[k]; j = symbols[fill['symbol']]
            q[j] += fill['units'] * (1 if fill['side']=='BUY' else -1)
            cash += fill['cash_delta_toman']
            assert q[j] >= -1e-7 and cash >= -.01
            assert cash == pytest.approx(fill['cash_after_toman'], abs=.01)
            assert fill['decision'] < fill['session']
            k += 1
        assert cash == pytest.approx(point['cash_toman'], abs=.01)
        assert cash + q@data['close'][dates[point['date']]] == pytest.approx(point['nav_toman'], abs=1)
    assert k == len(fills)


def test_cost_basis_and_pnl_reconcile_with_fees(history):
    marked = sum(h['market_value_toman'] for h in history['holdings'])
    assert marked + history['cash_toman'] == pytest.approx(history['nav_toman'], abs=1)
    assert history['realized_pnl_toman'] + history['unrealized_pnl_toman'] == pytest.approx(
        history['nav_toman']-history['initial_toman'], abs=1)
    assert sum(t['fee_toman'] for t in history['trades']) == pytest.approx(history['fees_toman'],abs=1)


def test_pending_sale_is_not_a_sale_or_cash(history):
    h = next(h for h in history['holdings'] if h['symbol']=='شمواد')
    assert h['action']=='EXIT_UNFILLED' and h['pending_order']
    assert h['price_date']=='2026-10-27' and h['price_age_days']==8
    assert h['market_value_toman'] == pytest.approx(259_850_852.43046305,abs=1)
    assert history['orders'] == [dict(symbol='شمواد',side='SELL',status='PENDING',reason='NO_TRADABLE_OPEN',
        decision_date='2026-11-01',target_weight=0.0,eligible_sessions_observed=3,lifetime_sessions=5,partial_units=0)]
    assert not any(t['symbol']=='شمواد' and t['side']=='SELL' and t['decision']=='2026-11-01' for t in history['trades'])


def test_weighted_cost_partial_sale_and_reentry():
    trades = [dict(symbol='X',units=10.,side='BUY',gross_toman=100.,fee_toman=1.,session='2026-01-01'),
              dict(symbol='X',units=4.,side='SELL',gross_toman=60.,fee_toman=.6,session='2026-01-02'),
              dict(symbol='X',units=2.,side='BUY',gross_toman=30.,fee_toman=.3,session='2026-01-03')]
    r = ledger_rows(trades,['X'],1000)
    assert r['units']['X']==8
    assert r['basis']['X']==pytest.approx(90.9)
    assert r['realized']['X']==pytest.approx(19)
    assert r['cash']==pytest.approx(928.1)


def test_changed_archive_refused(tmp_path):
    file = tmp_path/'test.txt'; file.write_text('original',encoding='utf8')
    (tmp_path/'MANIFEST.sha256.json').write_text(json.dumps(dict(files=[dict(path='test.txt',sha256=hashlib.sha256(b'original').hexdigest())])))
    verify_archive(tmp_path)
    file.write_text('changed')
    with pytest.raises(RuntimeError,match='integrity failed'):
        verify_archive(tmp_path)


def test_tracker_opening_is_durable_idempotent_and_never_inherits_history(tmp_path):
    db = tmp_path/'tracker.sqlite3'; policy_hash='a'*64
    assert tracker(db,policy_hash)['status']=='NOT_STARTED'
    assert not db.exists()
    first = tracker(db,policy_hash,open_account=True)
    second = tracker(db,policy_hash,open_account=True)
    assert first==second
    assert first['cash_toman']==first['nav_toman']==100_000_000
    assert not first['holdings'] and not first['trades']
    assert not first['execution_enabled'] and not first['automatic_updates_enabled']
    assert len(first['events'])==1
    # A SQLite backup restores the same account, including its original opening time.
    assert tracker(db.with_suffix('.backup.sqlite3'),policy_hash)==first


def test_tracker_refuses_silent_policy_change_or_unknown_events(tmp_path):
    db = tmp_path/'tracker.sqlite3'; tracker(db,'a'*64,open_account=True)
    with pytest.raises(RuntimeError,match='different policy'):
        tracker(db,'b'*64,open_account=True)
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO events VALUES (?,?,?,?,?)',('unknown','2026-11-07','FILL','{}','x'))
    with pytest.raises(RuntimeError,match='unsupported events'):
        tracker(db,'a'*64)


def test_nominal_reviews_respect_jalali_leap_and_year_transition():
    assert next_review('2026-11-04')=='2027-01-30'
    assert next_review('2025-01-30')=='2025-04-29'  # leap-year Esfand 30
    assert next_review('2026-01-30')=='2026-04-29'


def test_public_projection_has_no_private_paths_or_credentials(history):
    raw = json.dumps(history,ensure_ascii=False)
    for forbidden in ['D:\\', 'D:/', 'C:\\', 'C:/', 'postgresql://', 'password=', 'input_reports.json']:
        assert forbidden not in raw
    assert len(history['policy_sha256'])==64


def test_decision_and_latest_rankings_match_the_exact_engine_inputs(history):
    from factormix import engine
    data = dict(np.load(ARCHIVE/'snapshot_data/active_inputs.npz',allow_pickle=False))
    data['p1'] = data['candidate_score']
    policy = json.loads((ARCHIVE/'strategy.locked.json').read_text(encoding='utf8'))
    cfg = engine.Config(**policy['portfolio']); ex = engine.Execution(**policy['execution_assumptions'])
    for kind,date in [('decision','2026-11-01'),('latest','2026-11-04')]:
        snapshot = history['rankings'][kind]
        assert snapshot['date']==date
        assert snapshot['financial_snapshot_date']=='2026-11-01'
        assert snapshot['model']=='GROUP_WEIGHT_033'
        assert snapshot['eligible_count']==126 and snapshot['excluded_count']==128
        i = data['cal'].tolist().index(date)
        order = engine.order_for(data,i,cfg,ex)
        assert [r['symbol'] for r in snapshot['rows']]==[str(data['syms'][j]) for j in order]
        assert [r['rank'] for r in snapshot['rows']]==list(range(1,len(order)+1))
        np.testing.assert_array_equal([r['score'] for r in snapshot['rows']],data['candidate_score'][i,order])
        scores = [r['score'] for r in snapshot['rows']]
        assert all(a>=b for a,b in zip(scores,scores[1:]))


def test_last_portfolio_was_selected_from_decision_ranks_not_latest_ranks(history):
    decision = history['rankings']['decision']['rows']
    latest = history['rankings']['latest']['rows']
    assert [r['symbol'] for r in decision[:5]]==['شلیا','کیمیا','فگستر','کهمدا','فنورد']
    assert [r['symbol'] for r in latest[:5]]==['شلیا','کهمدا','کیمیا','فگستر','فنورد']
    assert {r['symbol'] for r in decision if r['selected_in_last_decision']}==set(history['decisions'][-1]['entrants'])
    sh_decision = next(r for r in decision if r['symbol']=='شمواد')
    sh_latest = next(r for r in latest if r['symbol']=='شمواد')
    assert sh_decision['rank']==11 and sh_latest['rank']==8
    assert sh_latest['held_at_portfolio_end'] and not sh_latest['selected_in_last_decision']
    assert history['orders'][0]['symbol']=='شمواد' and history['orders'][0]['side']=='SELL'
