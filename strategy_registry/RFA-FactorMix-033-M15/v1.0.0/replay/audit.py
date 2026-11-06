"""Replay frozen FactorMix-033 from 1401 with fresh 100m toman; no retuning.

Uses the archived simulator and inputs directly. All outputs stay in this new
analysis directory. Neither the frozen strategy nor frontend/paper accounts are
changed. Raw source availability and real-share accounting limitations persist.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jdatetime
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ARCHIVE = ROOT/'strategy_registry/RFA-FactorMix-033/v1.0.0'
OUT = HERE/'artifacts'
CAPITAL = 100_000_000.0
START = '2022-03-21'
END = '2026-11-04'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')


def jalali(day):
    return str(jdatetime.date.fromgregorian(date=pd.Timestamp(str(day)).date()))


def verify_archive():
    manifest = json.loads((ARCHIVE/'MANIFEST.sha256.json').read_text(encoding='utf8'))
    for row in manifest['files']:
        path = ARCHIVE/row['path']
        if not path.is_file() or sha(path) != row['sha256']:
            raise RuntimeError('Archive changed or missing: '+row['path'])
    return len(manifest['files'])


def load_engine():
    spec = importlib.util.spec_from_file_location('factormix_frozen_1401', ARCHIVE/'replay/engine_snapshot.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def reconcile(data, run, execution):
    """Independent daily cash/units ledger and weighted-average cost attribution."""
    names = data['syms'].tolist(); indexes = {s:j for j,s in enumerate(names)}
    q = np.zeros(len(names)); basis = np.zeros(len(names)); realized = np.zeros(len(names))
    cash = CAPITAL; k = 0; detailed = []
    dates = {str(d):i for i,d in enumerate(data['cal'])}
    for n, day in enumerate(run['cal']):
        i = dates[str(day)]
        while k < len(run['trades']) and run['trades'][k]['session'] == day:
            t = run['trades'][k]; j = indexes[t['symbol']]
            if not t['decision'] < t['session']:
                raise AssertionError('Fill is not after decision')
            assert t['fee_toman'] == t['gross_toman']*execution.fee
            base = t['gross_toman']/(1+execution.slippage if t['side']=='BUY' else 1-execution.slippage)
            assert base <= execution.capacity*t['adv_toman']+1e-5
            released = 0.0
            if t['side']=='BUY':
                delta = -t['gross_toman']-t['fee_toman']
                q[j] += t['units']; basis[j] -= delta
            else:
                assert t['units'] <= q[j]+1e-7
                released = basis[j]*min(1,t['units']/q[j])
                delta = t['gross_toman']-t['fee_toman']
                basis[j] -= released; q[j] -= t['units']; realized[j] += delta-released
            cash += delta
            assert cash >= -.01 and q[j] >= -1e-7
            detailed.append(dict(**t,cash_delta_toman=delta,cash_after_toman=max(0.,cash),
                                 released_cost_toman=released,
                                 realized_pnl_toman=delta-released if t['side']=='SELL' else None))
            k += 1
        np.testing.assert_allclose(cash,run['cash'][n],rtol=0,atol=.01)
        np.testing.assert_allclose(cash+q@data['close'][i],run['nav'][n],rtol=0,atol=1)
        np.testing.assert_allclose(q*data['close'][i],run['holding_values'][n],rtol=0,atol=1)
    assert k==len(run['trades'])
    last_i=dates[str(run['cal'][-1])]
    positions=[]
    last_target=set(run['decisions'][-1]['target'].split(';'))
    for j in np.flatnonzero(q>1e-10):
        value=float(q[j]*data['close'][last_i,j]); age=int(data['mark_age'][last_i,j])
        positions.append(dict(symbol=names[j],index_units=float(q[j]),market_value_toman=value,
            cost_basis_toman=float(basis[j]),average_cost_toman=float(basis[j]/q[j]),
            unrealized_pnl_toman=float(value-basis[j]),weight=value/run['nav'][-1],
            last_index_price_toman=float(data['close'][last_i,j]),price_age_days=age,
            price_date=(pd.Timestamp(str(run['cal'][-1]))-pd.Timedelta(days=age)).date().isoformat(),
            action='HOLD' if names[j] in last_target else 'EXIT_UNFILLED'))
    unrealized=sum(x['unrealized_pnl_toman'] for x in positions)
    np.testing.assert_allclose(float(realized.sum())+unrealized,run['nav'][-1]-CAPITAL,rtol=0,atol=1)
    return dict(daily_reconciliation='PASS',sessions=len(run['cal']),trades_checked=k,
                realized_pnl_toman=float(realized.sum()),unrealized_pnl_toman=unrealized,
                terminal_cash_toman=max(0.,float(cash)),positions=sorted(positions,key=lambda p:-p['market_value_toman'])),detailed


def annual_rows(run):
    years=np.array([int(jalali(d)[:4]) for d in run['cal']]); result=[]
    for year in sorted(set(years)):
        ids=np.flatnonzero(years==year); a,b=int(ids[0]),int(ids[-1])
        initial=CAPITAL if a==0 else float(run['nav'][a-1]); final=float(run['nav'][b])
        result.append(dict(year=int(year),start=str(run['cal'][a]),end=str(run['cal'][b]),
            initial_toman=initial,final_toman=final,return_fraction=final/initial-1))
    np.testing.assert_allclose(np.prod([1+r['return_fraction'] for r in result])*CAPITAL,run['nav'][-1],rtol=0,atol=1)
    return result


def main():
    OUT.mkdir(exist_ok=True)
    count=verify_archive()
    engine=load_engine()
    policy=json.loads((ARCHIVE/'strategy.locked.json').read_text(encoding='utf8'))
    raw=dict(np.load(ARCHIVE/'snapshot_data/active_inputs.npz',allow_pickle=False))
    assert str(raw['cal'][-1])==END
    data={**raw,'p1':raw['candidate_score']}
    cfg=engine.Config(**policy['portfolio']); ex=engine.Execution(**policy['execution_assumptions'])
    protocol=dict(declared_at_utc=datetime.now(timezone.utc).isoformat(),strategy_id=policy['registry_id'],
        requested_start=START,end=END,capital_toman=CAPITAL,selection_or_retuning=False,
        input_sha256=sha(ARCHIVE/'snapshot_data/active_inputs.npz'),
        policy_sha256=sha(ARCHIVE/'strategy.locked.json'),engine_sha256=sha(ARCHIVE/'replay/engine_snapshot.py'),
        primary_calendar=policy['calendar_policy'],portfolio=policy['portfolio'],execution=policy['execution_assumptions'],
        baseline='P1 BASE: same market, capital, start/end and execution; its original fixed policy',
        previous_history_used_only_for_features=True,real_historical_receipt_proven=False,
        performance_is_retrospective_not_unseen_validation=True,all_outputs_outside_frozen_archive=True)
    protocol_path=OUT/'protocol.json'
    if protocol_path.exists():
        old=json.loads(protocol_path.read_text(encoding='utf8'))
        for key in ['requested_start','end','capital_toman','input_sha256','policy_sha256','engine_sha256','portfolio','execution']:
            if old[key]!=protocol[key]:raise RuntimeError('Existing protocol differs: '+key)
    else:
        write_json(protocol_path,protocol)
    # Regression: archived 1402 replay must still reproduce exactly before using
    # the same implementation with the earlier start and a fresh opening cash.
    regression=engine.simulate(data,cfg,ex,start=policy['replay']['requested_start'],end=END,detail=True)
    reference=pd.read_csv(ARCHIVE/'results/active_candidate_nav.csv')
    assert regression['cal'].tolist()==reference.session.tolist()
    np.testing.assert_allclose(regression['nav'],reference.nav_toman.to_numpy(),rtol=0,atol=1)
    runs={}
    accounts={}
    for label,inputs,config in [('candidate',data,cfg),('baseline',raw,engine.Config('BASE'))]:
        run=engine.simulate(inputs,config,ex,start=START,end=END,capital=CAPITAL,detail=True)
        audit,ledger=reconcile(inputs,run,ex)
        engine.save_run(OUT/label,run)
        pd.DataFrame(ledger).to_csv(OUT/f'{label}_ledger.csv',index=False,encoding='utf-8-sig')
        runs[label]=run
        accounts[label]=dict(metrics=run['metrics'],annual=annual_rows(run),
            fees_toman=run['cost_toman'],slippage_toman=run['slippage_toman'],
            fills=run['n_trades'],buy_fills=sum(t['side']=='BUY' for t in run['trades']),
            sell_fills=sum(t['side']=='SELL' for t in run['trades']),decisions=len(run['decisions']),
            first_fill=run['trades'][0]['session'],first_decision=run['decisions'][0],
            expired_orders=run['expired_orders'],stale_decisions_skipped=run['stale_decisions_skipped'],
            maximum_position_count=int(np.max(run['positions'])),ledger=audit)
    # All financial signal dates used to score daily rows are no later than those rows.
    used=(raw['cal']>=START)&(raw['cal']<=END)
    assert np.all(raw['signal_dates'][used]<=raw['cal'][used])
    assert accounts['candidate']['metrics']['start']=='2022-03-26'
    assert verify_archive()==count
    summary=dict(strategy_id=policy['registry_id'],requested_jalali_start='1401-01-01',
        actual_start='2022-03-26',actual_start_jalali='1401-01-06',end=END,end_jalali=jalali(END),
        initial_toman=CAPITAL,accounts=accounts,
        final_difference_toman=accounts['candidate']['metrics']['final_toman']-accounts['baseline']['metrics']['final_toman'],
        previous_1402_result_reproduced=True,previous_1402_result_toman=float(regression['nav'][-1]),
        archive_files_verified=count,frozen_policy_unchanged=True,no_live_or_paper_account_writes=True,
        limitations=['model selected using part of this history; not independent out-of-sample evidence',
            'historical report receipt times unproven; current fixed universe has survivorship risk',
            'fractional adjusted index units and assumed immediate dividend reinvestment',
            'daily-bar fill proxies do not certify actual queue execution',
            'terminal NAV is marked portfolio value, not guaranteed liquidation proceeds'])
    write_json(OUT/'summary.json',summary)
    print(json.dumps(dict(status='PASS',start=summary['actual_start_jalali'],end=summary['end_jalali'],
        candidate=accounts['candidate']['metrics'],baseline=accounts['baseline']['metrics'],
        first_fill=accounts['candidate']['first_fill'],annual=accounts['candidate']['annual'],
        fees_toman=accounts['candidate']['fees_toman'],slippage_toman=accounts['candidate']['slippage_toman'],
        positions=accounts['candidate']['ledger']['positions']),ensure_ascii=True,indent=2),flush=True)


if __name__=='__main__':main()
