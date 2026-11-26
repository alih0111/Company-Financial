from datetime import datetime
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from factormix import monthly_paper
from factormix.monthly_paper import (
    POLICY, TEHRAN, advance, export_ledger, open_ledger, register_initial_entry, review_sessions,
)
from factormix.refresh_ranking import read, sha


def sample(sessions, locked=None):
    symbols = np.array(list('ABCDEF'))
    cal = np.array(sessions)
    close = np.full((len(cal), len(symbols)), 100.)
    data = dict(cal=cal, syms=symbols, close=close, mark_age=np.zeros_like(close, dtype=int),
                adv=np.full_like(close, 1e9))
    md = SimpleNamespace(data={}, events={})
    for symbol in symbols:
        md.data[symbol] = dict(sid=symbol, dmap={day: i for i, day in enumerate(cal)},
                               o=close[:, 0], cf=np.ones(len(cal)),
                               locked=np.array([symbol == locked for _ in cal]))
        md.events[symbol] = []
    return data, md


def signal(day, symbols):
    at = day + 'T17:30:00+03:30'
    evidence = [dict(symbol=s, factor=factor, published_at=at, first_seen_at=at,
                     received_at=at, effective_at=at, identity_verified=True, complete=True)
                for s in symbols for factor in ('eod', 'financial', 'sales')]
    return dict(date=day, market_date=day, computed_at_utc=at, input_evidence=evidence,
                policy_sha256=read(POLICY)['parent_policy_sha256'],
                rows=[dict(symbol=s, rank=i) for i, s in enumerate(symbols, 1)]), {}


def run(db, policy, opened, sessions, symbols='ABCDEF', locked=None):
    day = sessions[-1]
    data, md = sample(sessions, locked)
    instant = datetime.fromisoformat(day + 'T18:00:00').replace(tzinfo=TEHRAN)
    advance(db, data, md, day, opened, 100_000_000, policy, 'market-hash',
            instant.isoformat(), lambda: signal(day, symbols), clock=lambda: instant)
    return export_ledger(db, opened, 100_000_000, policy['registry_id'])


def test_monthly_decision_executes_next_session_and_carries_positions(tmp_path):
    policy = read(POLICY)
    db_path = tmp_path / 'account.sqlite3'
    start = datetime(2026, 12, 5, 18, tzinfo=TEHRAN)
    with sqlite3.connect(db_path) as db:
        opened, _ = open_ledger(db, policy, sha(POLICY), start)
        cal = ['2026-12-05', '2026-12-06']
        first = run(db, policy, opened, cal)
        assert first['trades'] == []
        assert first['open_batch']['pending'] == list('ABCDE')
        assert run(db, policy, opened, cal) == first
    with sqlite3.connect(db_path) as db:
        opened, _ = open_ledger(db, policy, sha(POLICY), datetime(2026, 12, 7, 18, tzinfo=TEHRAN))
        assert opened == start
        cal.append('2026-12-07')
        second = run(db, policy, opened, cal)
        assert len(second['trades']) == 5
        assert {trade['session'] for trade in second['trades']} == {'2026-12-07'}
        assert second['cash_toman'] == pytest.approx(0, abs=1e-6)
        assert sum(row['value_toman'] for row in second['holdings']) == pytest.approx(second['nav_toman'])
        assert run(db, policy, opened, cal) == second
        # 15 Dey is January 5. Existing positions keep priority even when F is ranked first.
        cal.append('2027-01-05')
        third = run(db, policy, opened, cal, symbols='FABCDE')
        assert third['reviews'][-1]['session'] == '2027-01-05'
        assert set(third['reviews'][-1]['target_weights']) == set('ABCDE')
        assert third['open_batch'] is None


def test_missed_date_is_not_recreated_and_blocked_order_expires(tmp_path):
    policy = read(POLICY)
    with sqlite3.connect(tmp_path / 'account.sqlite3') as db:
        start = datetime(2026, 12, 5, 18, tzinfo=TEHRAN)
        opened, _ = open_ledger(db, policy, sha(POLICY), start)
        cal = ['2026-12-05', '2026-12-07', '2026-12-08']
        assert review_sessions(cal) == {'2026-12-07': '2026-12-06'}
        assert review_sessions(['2026-12-05', '2026-12-26']) == {'2026-12-26': '2026-12-06'}
        missed = run(db, policy, opened, cal)
        assert [review['state'] for review in missed['reviews']] == ['missed']
        assert not missed['trades']
        cal.append('2027-01-05')
        run(db, policy, opened, cal)
        cal.extend(['2027-01-06', '2027-01-09', '2027-01-10', '2027-01-11', '2027-01-12'])
        result = run(db, policy, opened, cal, locked='A')
        assert {trade['symbol'] for trade in result['trades']} == set('BCDE')
        assert result['expired'] == [{'session': '2027-01-12', 'symbols': ['A']}]
        assert result['open_batch'] is None


def test_initial_entry_preserves_the_session_and_executes_from_the_next_one(tmp_path):
    policy = read(POLICY)
    with sqlite3.connect(tmp_path / 'account.sqlite3') as db:
        start = datetime(2026, 11, 9, 18, tzinfo=TEHRAN)
        opened, _ = open_ledger(db, policy, sha(POLICY), start)
        cal = ['2026-11-09']
        before = run(db, policy, opened, cal)
        ranking, coverage = signal(cal[0], 'ABCDEF')
        ranking['source_hashes'] = {'manifest.json': 'market-hash'}
        register_initial_entry(db, cal[0], policy, ranking, coverage, clock=lambda: start)
        after = export_ledger(db, opened, 100_000_000, policy['registry_id'])
        assert after['nav'] == before['nav']
        assert after['reviews'][0]['kind'] == 'initial_entry'
        assert after['open_batch']['pending'] == list('ABCDE')
        assert after['trades'] == []
        with pytest.raises(ValueError, match='already started'):
            register_initial_entry(db, cal[0], policy, ranking, coverage, clock=lambda: start)
        cal.append('2026-11-10')
        result = run(db, policy, opened, cal)
        assert len(result['trades']) == 5
        assert all(t['session'] == cal[1] and t['decision'] == cal[0] for t in result['trades'])


def test_weekly_closure_recovers_delayed_wednesday_data(tmp_path, monkeypatch):
    monday = datetime(2026, 11, 9, 18, tzinfo=TEHRAN)
    thursday = datetime(2026, 11, 12, 15, tzinfo=TEHRAN)
    policy = read(POLICY)
    with sqlite3.connect(tmp_path / 'account.sqlite3') as db:
        opened, _ = open_ledger(db, policy, sha(POLICY), monday)
        run(db, policy, opened, ['2026-11-09', '2026-11-10'])
    (tmp_path / 'manifest.json').write_text('{"retrieved_at_utc":"2026-11-12T11:30:00Z"}')
    calls = []

    def load_market(pack, day):
        calls.append((pack, day))
        data, md = sample(['2026-11-09', '2026-11-10', day])
        return None, None, data, md

    monkeypatch.setattr(monthly_paper, 'RUN', tmp_path)
    monkeypatch.setattr(monthly_paper, 'collect_market', lambda _: tmp_path)
    monkeypatch.setattr(monthly_paper, 'market_inputs', load_market)
    assert monthly_paper.run(thursday) == ('weekly_closed', None)
    assert read(tmp_path / 'account.json')['session'] == '2026-11-11'
    assert monthly_paper.run(thursday) == ('weekly_closed', None)
    assert calls == [(tmp_path, '2026-11-11')]


def test_codal_refresh_still_runs_when_today_has_no_price_bars(tmp_path, monkeypatch):
    started = datetime(2026, 11, 11, 18, tzinfo=TEHRAN)
    (tmp_path / 'manifest.json').write_text('{"retrieved_at_utc":"2026-11-11T14:30:00Z"}')
    data, md = sample(['2026-11-10', '2026-11-11'])
    for rec in md.data.values():
        rec['o'] = np.array([100., np.nan])
    monkeypatch.setattr(monthly_paper, 'RUN', tmp_path)
    monkeypatch.setattr(monthly_paper, 'collect_market', lambda _: tmp_path)
    monkeypatch.setattr(monthly_paper, 'market_inputs', lambda *_: (None, None, data, md))
    calls = []

    def collect(day):
        calls.append(day)
        return tmp_path / 'manifest.json', {'complete': False}

    monkeypatch.setattr(monthly_paper, 'collect_reports', collect)
    assert monthly_paper.run(started) == ('no_session_data', {'complete': False})
    assert calls == ['2026-11-11']


def test_incomplete_required_evidence_blocks_both_decision_paths(tmp_path):
    policy = read(POLICY)
    opened = datetime(2026, 12, 5, 18, tzinfo=TEHRAN)
    with sqlite3.connect(tmp_path / 'account.sqlite3') as db:
        open_ledger(db, policy, sha(POLICY), opened)
        run(db, policy, opened, ['2026-12-05'])
        ranking, _ = signal('2026-12-05', 'ABCDEF')
        ranking['source_hashes'] = {'manifest.json': 'market-hash'}
        del ranking['input_evidence']
        assert register_initial_entry(db, '2026-12-05', policy, ranking, {}, clock=lambda: opened) == 'blocked'
        first = export_ledger(db, opened, 100_000_000, policy['registry_id'])
        assert first['open_batch'] is None
        assert first['reviews'][0]['readiness']['data'] == 'UNKNOWN'

        sessions = ['2026-12-05', '2026-12-06']
        data, md = sample(sessions)
        at = datetime(2026, 12, 6, 18, tzinfo=TEHRAN)
        ranking, _ = signal(sessions[-1], 'ABCDEF')
        # F is outside the target but can alter ranks if its sales evidence changes.
        ranking['input_evidence'][-1]['complete'] = False
        advance(db, data, md, sessions[-1], opened, 100_000_000, policy, 'market-hash',
                at.isoformat(), lambda: (ranking, {'complete': False}), clock=lambda: at)
        result = export_ledger(db, opened, 100_000_000, policy['registry_id'])
        assert result['open_batch'] is None
        assert result['trades'] == []
        assert result['reviews'][-1]['state'] == 'blocked'
        assert result['reviews'][-1]['readiness']['data_reasons'] == [
            {'input': ['F', 'sales'], 'state': 'FAIL', 'reason': 'identity_or_input_invalid'}]
