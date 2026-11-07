"""Economic and information-timing checks, independent of reported returns."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from reportflow import engine
from reportflow.build_inputs import ARCHIVE, HERE, OUT, effective_session, read, sha


def toy(cal, scores, *, tradable=None):
    scores = np.asarray(scores, float)
    T, S = scores.shape
    return dict(cal=np.asarray(cal), syms=np.array(['A', 'B'][:S]),
                close=np.full((T, S), 100.), opening=np.full((T, S), 100.),
                locked=np.zeros((T, S), bool), adv=np.full((T, S), 1e10),
                p1=scores, symbol_index=np.arange(S), mark_age=np.zeros((T, S)),
                financial_age=np.zeros((T, S)), score_age=np.zeros(T), signal_dates=np.asarray(cal),
                trading_sessions=np.ones(T, bool) if tradable is None else np.asarray(tradable))


def test_market_rank_change_without_new_report_does_not_rebalance():
    data = toy(['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04'], [[2, 1], [1, 3], [1, 3], [1, 3]])
    cfg = engine.Config('test', n=1, buffer=1, rebalance='band')
    r = engine.simulate(data, cfg, start='2026-01-01', end='2026-01-04', detail=True, review_dates=['2026-01-01'])
    assert [t['symbol'] for t in r['trades']] == ['A']
    assert len(r['decisions']) == 1


def test_identical_daily_reports_do_not_extend_blocked_order_expiry():
    cal = pd.date_range('2026-01-01', periods=9).strftime('%Y-%m-%d').tolist()
    data = toy(cal, np.ones((9, 1)))
    data['opening'][:] = np.nan
    cfg = engine.Config('test', n=1, rebalance='band')
    r = engine.simulate(data, cfg, start=cal[0], end=cal[-1], detail=True, review_dates=cal)
    assert r['expired_orders'] >= 1
    assert r['decisions'][0]['session'] == cal[0]
    assert r['decisions'][1]['session'] == cal[6]
    assert len(r['decisions']) == 2


def test_weekend_receipt_does_not_consume_order_life_or_allow_same_day_fill():
    cal = ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04']
    data = toy(cal, [[1], [1], [1], [1]], tradable=[False, False, True, True])
    r = engine.simulate(data, engine.Config('test', n=1), start=cal[0], end=cal[-1],
                        detail=True, review_dates=[cal[0]])
    assert r['trades'][0]['session'] == cal[2]
    assert r['trades'][0]['decision'] == cal[0]


def test_unfilled_exit_remains_an_asset_and_never_finances_fake_buys():
    cal = pd.date_range('2026-01-01', periods=5).strftime('%Y-%m-%d').tolist()
    data = toy(cal, [[2, 1], [2, 1], [1, 3], [1, 3], [1, 3]])
    data['opening'][3:, 0] = np.nan
    r = engine.simulate(data, engine.Config('test', n=1, buffer=1), start=cal[0], end=cal[-1],
                        detail=True, review_dates=[cal[0], cal[2]])
    assert not any(t['side'] == 'SELL' for t in r['trades'])
    assert not any(t['symbol'] == 'B' for t in r['trades'])
    assert r['terminal_positions']['A'] > 0
    assert r['terminal_cash'] >= -.01


def test_publication_timezone_and_next_actual_session():
    cal = np.array(['2026-11-04', '2026-11-07', '2026-11-08'])
    assert effective_session(cal, '2026-11-04T22:00:00Z') == '2026-11-07'
    assert effective_session(cal, '2026-11-07T08:00:00+03:30', following_day=True) == '2026-11-08'
    with pytest.raises(ValueError):
        effective_session(cal, '2026-11-04')


def test_paper_account_initialization_is_idempotent(tmp_path, monkeypatch):
    from reportflow import service
    from datetime import datetime, timezone
    monkeypatch.setattr(service, 'STATE', tmp_path)
    first = service.initialize(datetime(2026, 11, 6, tzinfo=timezone.utc))
    again = service.initialize(datetime(2026, 11, 7, tzinfo=timezone.utc))
    assert first == again
    assert again['initial_toman'] == 100_000_000


def test_retired_strategy_cannot_initialize_or_update_paper_account(tmp_path, monkeypatch):
    from reportflow import service
    retired = tmp_path / 'model'
    retired.mkdir()
    (retired / 'retired.json').write_text('{}')
    state = tmp_path / 'state'
    monkeypatch.setattr(service, 'HERE', retired)
    monkeypatch.setattr(service, 'STATE', state)
    result = service.cycle(init=True)
    assert result['state'] == 'ARCHIVED'
    assert result['automatic_enabled'] is False
    assert not state.exists()
    state.mkdir()
    original = b'{"cash_toman":100000000,"holdings":{}}'
    (state / 'portfolio.json').write_bytes(original)
    assert service.cycle()['state'] == 'ARCHIVED'
    assert (state / 'portfolio.json').read_bytes() == original


def test_new_sales_trigger_waits_until_the_report_is_usable(tmp_path):
    from reportflow.service import report_fingerprint
    (tmp_path / 'input_reports.json').write_text('[]')
    (tmp_path / 'comparative_lineage.json').write_text('[]')
    pd.DataFrame([dict(event_id='new-sale', CURRENT_PERIOD_SALES=100., current_value_version_known=True,
                       signal_entry_date='2026-11-08', is_correction=False,
                       published_at='2026-11-07T08:00:00Z')]).to_parquet(tmp_path / 'monthly_sales_events.parquet')
    before = report_fingerprint(tmp_path, '2026-11-07')
    after = report_fingerprint(tmp_path, '2026-11-08')
    assert before != after
    assert after == report_fingerprint(tmp_path, '2026-11-09')


@pytest.mark.skipif(not (OUT / 'summary.json').exists(), reason='Run reportflow.run first')
def test_saved_backtest_cash_ledger_prices_costs_and_report_triggers():
    summary = read(OUT / 'summary.json')
    data = dict(np.load(OUT / 'event_inputs.npz', allow_pickle=False))
    date_ix = {str(day): i for i, day in enumerate(data['cal'])}
    symbols = {str(s): i for i, s in enumerate(data['syms'])}
    events = pd.read_csv(OUT / 'report_events.csv')
    for label in ['reportflow', 'same_information_quarterly', 'original_factormix', 'double_cost', 'delay_2_sessions']:
        trades = pd.read_csv(OUT / f'{label}_trades.csv').to_dict('records')
        nav = pd.read_csv(OUT / f'{label}_nav.csv')
        q = np.zeros(len(symbols)); cash = 1e8; k = 0
        ex = summary['accounts'][label]['execution']
        decisions = pd.read_csv(OUT / f'{label}_decisions.csv')
        if label in ['reportflow', 'double_cost', 'delay_2_sessions']:
            assert set(decisions.session) <= set(events.session) | {nav.session.iloc[0]}
        for row in nav.itertuples():
            i = date_ix[row.session]
            while k < len(trades) and trades[k]['session'] == row.session:
                t = trades[k]; j = symbols[t['symbol']]
                assert t['decision'] < t['session']
                assert i - date_ix[t['decision']] >= ex['delay']
                assert not data['locked'][i, j]
                assert t['index_price'] == pytest.approx(data['opening'][i, j])
                assert t['fee_toman'] == pytest.approx(t['gross_toman'] * ex['fee'])
                base = t['gross_toman'] / (1 + ex['slippage'] if t['side'] == 'BUY' else 1 - ex['slippage'])
                assert base <= ex['capacity'] * data['adv'][i, j] + .01
                if t['side'] == 'BUY':
                    q[j] += t['units']; cash -= t['gross_toman'] + t['fee_toman']
                else:
                    q[j] -= t['units']; cash += t['gross_toman'] - t['fee_toman']
                assert cash >= -.01 and q[j] >= -1e-6
                k += 1
            assert cash == pytest.approx(row.cash_toman, abs=.01)
            assert cash + q @ data['close'][i] == pytest.approx(row.nav_toman, abs=1)
        assert k == len(trades)
        assert nav.nav_toman.iloc[-1] == pytest.approx(summary['accounts'][label]['metrics']['final_toman'], abs=1)
    policy = read(ARCHIVE / 'strategy.locked.json')
    assert read(HERE / 'strategy.json')['weights'] == policy['source_model']['weights']
    assert sha(HERE / 'strategy.json') == summary['strategy_sha256']
    assert summary['original_result_reproduced']


@pytest.mark.skipif(not (OUT / 'input_manifest.json').exists(), reason='Build inputs first')
def test_source_and_receipt_chronology():
    data = np.load(OUT / 'event_inputs.npz', allow_pickle=False)
    events = pd.read_csv(OUT / 'report_events.csv')
    for r in events.itertuples():
        published_day = pd.Timestamp(r.published_at).tz_convert('Asia/Tehran').date().isoformat()
        assert published_day <= r.session
        if r.kind.startswith('sales'):
            assert published_day < r.session
    for name, checksum in read(OUT / 'input_manifest.json')['source_hashes'].items():
        assert sha(HERE.parent / name) == checksum
    assert str(data['cal'][-1]) == '2026-11-04'
