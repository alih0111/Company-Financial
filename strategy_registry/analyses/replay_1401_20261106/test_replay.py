"""Check exported artifacts independently of the simulator implementation."""
import hashlib
import json
from pathlib import Path

import jdatetime
import numpy as np
import pandas as pd
import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'artifacts'
ARCHIVE=ROOT/'strategy_registry/RFA-FactorMix-033/v1.0.0'


@pytest.fixture(scope='module')
def summary():
    return json.loads((OUT/'summary.json').read_text(encoding='utf8'))


def test_source_integrity_and_exact_locked_policy(summary):
    protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf8'))
    policy=json.loads((ARCHIVE/'strategy.locked.json').read_text(encoding='utf8'))
    for field,relative in [('input_sha256','snapshot_data/active_inputs.npz'),
                           ('policy_sha256','strategy.locked.json'),('engine_sha256','replay/engine_snapshot.py')]:
        assert hashlib.sha256((ARCHIVE/relative).read_bytes()).hexdigest()==protocol[field]
    assert protocol['portfolio']==policy['portfolio']
    assert protocol['execution']==policy['execution_assumptions']
    assert protocol['selection_or_retuning'] is False
    assert summary['previous_1402_result_reproduced']
    assert summary['previous_1402_result_toman']==pytest.approx(1_290_465_605.5777485,abs=1)


@pytest.mark.parametrize('label',['candidate','baseline'])
def test_every_saved_daily_nav_from_independent_transaction_ledger(label,summary):
    data=np.load(ARCHIVE/'snapshot_data/active_inputs.npz',allow_pickle=False)
    names={str(s):i for i,s in enumerate(data['syms'])}
    dates={str(s):i for i,s in enumerate(data['cal'])}
    nav=pd.read_csv(OUT/f'{label}_nav.csv')
    fills=pd.read_csv(OUT/f'{label}_trades.csv').to_dict('records')
    q=np.zeros(len(names));cash=100_000_000.;k=0
    for row in nav.itertuples():
        while k<len(fills) and fills[k]['session']==row.session:
            t=fills[k];j=names[t['symbol']]
            assert t['decision']<t['session']
            assert t['fee_toman']==pytest.approx(t['gross_toman']*.005,abs=.01)
            assert t['units']>0 and t['index_price']>0
            if t['side']=='BUY':
                q[j]+=t['units'];cash-=t['gross_toman']+t['fee_toman']
                base=t['gross_toman']/1.001
            else:
                q[j]-=t['units'];cash+=t['gross_toman']-t['fee_toman']
                base=t['gross_toman']/.999
            assert q[j]>=-1e-6 and cash>=-.01
            assert base<=.05*t['adv_toman']+.01
            k+=1
        assert cash==pytest.approx(row.cash_toman,abs=.01)
        assert cash+q@data['close'][dates[row.session]]==pytest.approx(row.nav_toman,abs=1)
    assert k==len(fills)
    assert nav.nav_toman.iloc[-1]==pytest.approx(summary['accounts'][label]['metrics']['final_toman'],abs=1)


def test_initial_capital_start_fill_timing_and_same_comparison_window(summary):
    a=pd.read_csv(OUT/'candidate_nav.csv');b=pd.read_csv(OUT/'baseline_nav.csv')
    assert a.session.tolist()==b.session.tolist()
    assert a.session.iloc[0]=='2022-03-26' and a.session.iloc[-1]=='2026-11-04'
    for nav,label in [(a,'candidate'),(b,'baseline')]:
        assert nav.nav_toman.iloc[0]==100_000_000
        assert nav.cash_toman.iloc[0]==100_000_000 and nav.n_positions.iloc[0]==0
        assert summary['accounts'][label]['first_fill']=='2022-03-27'
        decisions=pd.read_csv(OUT/f'{label}_decisions.csv')
        assert (decisions.signal_date<=decisions.session).all()
        assert (decisions.signal_age<=45).all()


@pytest.mark.parametrize('label',['candidate','baseline'])
def test_annual_balances_compound_and_match_daily_drawdown(label,summary):
    account=summary['accounts'][label];nav=pd.read_csv(OUT/f'{label}_nav.csv')
    years=[jdatetime.date.fromgregorian(date=pd.Timestamp(d).date()).year for d in nav.session]
    for row in account['annual']:
        group=nav[np.array(years)==row['year']]
        assert row['final_toman']==pytest.approx(group.nav_toman.iloc[-1],abs=1)
    ratio=np.prod([1+r['return_fraction'] for r in account['annual']])
    assert ratio*100_000_000==pytest.approx(nav.nav_toman.iloc[-1],abs=1)
    values=np.r_[100_000_000,nav.nav_toman.to_numpy()]
    dd=float(np.min(values/np.maximum.accumulate(values)-1))
    assert dd==pytest.approx(account['metrics']['max_drawdown'],abs=1e-12)


def test_final_marked_value_and_pnl_do_not_treat_unfilled_sale_as_cash(summary):
    account=summary['accounts']['candidate'];ledger=account['ledger']
    assert ledger['terminal_cash_toman']+sum(p['market_value_toman'] for p in ledger['positions'])==pytest.approx(account['metrics']['final_toman'],abs=1)
    assert ledger['realized_pnl_toman']+ledger['unrealized_pnl_toman']==pytest.approx(account['metrics']['final_toman']-100_000_000,abs=1)
    position=next(p for p in ledger['positions'] if p['symbol']=='شمواد')
    assert position['action']=='EXIT_UNFILLED' and position['price_age_days']==8
    assert position['price_date']=='2026-10-27'
    fills=pd.read_csv(OUT/'candidate_trades.csv')
    assert not ((fills.symbol=='شمواد')&(fills.side=='SELL')&(fills.decision=='2026-11-01')).any()
    assert fills.fee_toman.sum()==pytest.approx(account['fees_toman'],abs=1)
    assert fills.slippage_toman.sum()==pytest.approx(account['slippage_toman'],abs=1)
