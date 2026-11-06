"""Replay the frozen new strategy from 1402 without retuning or extrapolation."""
from pathlib import Path
from dataclasses import asdict
import sys,json,hashlib
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np
import pandas as pd
import jdatetime

HERE=Path(__file__).resolve().parent
SEARCH=HERE.parent/'feature_model_search_20261106'
PREV=HERE.parent/'final_strategy_review_20261106'
OUT=HERE/'artifacts';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(PREV))
from engine import Config,Execution,simulate,save_run


def main():
    policy=json.loads((SEARCH/'artifacts/research_decision.json').read_text(encoding='utf8'))
    data=dict(np.load(SEARCH/'artifacts/market_inputs.npz',allow_pickle=False))
    score=np.load(SEARCH/'artifacts/score_cache/GROUP_WEIGHT_033.npz')['score']
    cfg=Config(**policy['portfolio']);execution=Execution(**policy['execution_assumptions'])
    result=simulate({**data,'p1':score},cfg,execution,start='2023-03-21',end='2026-02-24',detail=True)
    base=simulate(data,Config('BASE'),execution,start='2023-03-21',end='2026-02-24',detail=True)
    for label,r in [('candidate',result),('baseline',base)]:save_run(OUT/label,r)
    r=result;periods=[];cal=r['cal'];nav=r['nav']
    jy=np.array([jdatetime.date.fromgregorian(date=pd.Timestamp(str(d)).date()).year for d in cal])
    for year in sorted(set(jy)):
        rows=np.flatnonzero(jy==year);a,b=int(rows[0]),int(rows[-1]);initial=nav[a-1] if a else 1e8
        periods.append(dict(jalali_year=int(year),start=str(cal[a]),end=str(cal[b]),
                            opening_toman=float(initial),closing_toman=float(nav[b]),period_return=float(nav[b]/initial-1)))
    pd.DataFrame(periods).to_csv(OUT/'annual_periods.csv',index=False,encoding='utf-8-sig')
    # Independent cash-flow reconciliation from the recorded fills.
    holdings={};cash=1e8
    for tr in result['trades']:
        s=tr['symbol'];holdings.setdefault(s,0.)
        if tr['side']=='BUY':cash-=tr['gross_toman']+tr['fee_toman'];holdings[s]+=tr['units']
        else:cash+=tr['gross_toman']-tr['fee_toman'];holdings[s]-=tr['units']
    pos={str(s):j for j,s in enumerate(data['syms'])};last=np.searchsorted(data['cal'],r['cal'][-1])
    reconciled=cash+sum(q*data['close'][last,pos[s]] for s,q in holdings.items())
    assert abs(reconciled-result['nav'][-1])<.1
    assert all(t['decision']<t['session'] for t in r['trades'])
    report={'requested_start_jalali':'1402-01-01','requested_end_jalali':'1405-08-15',
            'requested_end_gregorian':'2026-11-06','initial_toman':100000000,
            'available_signal_end':str(data['cal'][-1]),'actual_first_decision':result['decisions'][0]['session'],
            'actual_first_fill':result['trades'][0]['session'],
            'metrics':r['metrics'],'baseline':base['metrics'],'yearly':periods,
            'fees_toman':r['cost_toman'],'slippage_toman':r['slippage_toman'],
            'trades':r['n_trades'],'rebalances':len(r['decisions']),
            'reconciled_terminal_wealth':reconciled,'final_positions':r['terminal_positions'],
            'execution':asdict(execution),'complete_through_today':False,
            'weights_changed':False,'policy_sha256':hashlib.sha256((SEARCH/'artifacts/research_decision.json').read_bytes()).hexdigest()}
    (OUT/'available_replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
