"""Pre-registered retrospective selection, frozen verification and stresses."""
from __future__ import annotations
from dataclasses import asdict, replace
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,time,os
import numpy as np
import pandas as pd
from engine import Config,Execution,configurations,simulate,window_metrics,save_run

HERE=Path(__file__).resolve().parent
OUT=HERE/os.environ.get('RFA_RESEARCH_ARTIFACTS','artifacts')
FOLDS=[('2023-01-01','2023-06-30'),('2023-07-01','2023-12-31'),
       ('2024-01-01','2024-06-30'),('2024-07-01','2024-12-31')]
BASE=Config('BASE')
EXEC=Execution()
END_TRAIN='2024-12-31'
END_VERIFY='2026-02-24'


def dump(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def freeze():
    protocol={'registered_at_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'retrospective research, NOT pristine out-of-sample; source scores/weights/universe were already researched',
        'search_start':'2021-04-03','selection_end':END_TRAIN,'validation_folds':FOLDS,
        'locked_verification':['2025-01-01',END_VERIFY],
        'stale_price_extension':['2026-02-25','2026-09-30'],
        'execution':asdict(EXEC),'initial_toman':100e6,
        'configs':[asdict(c) for c in configurations()],
        'selection_rule':{'eligible':'n>=3, not EW254/MOM_ONLY/TOP1_CONTROL; profitable through selection end; DD <= max(25%, baseline DD+5pp); worst six-month relative wealth >= 0.75',
            'score':'0.6*median(fold log relative wealth) + 0.4*mean(fold log relative wealth) - 0.25*abs(selection DD)',
            'ties':'lower n_trades then config id',
            'fallback':'BASE if no eligible contender or if chosen fails verification improvement, DD or stress gates'},
        'promotion_gate':{'verify_return':'chosen > BASE net final wealth',
            'verify_dd':'chosen absolute DD <= BASE absolute DD + 5pp',
            'stress':'chosen beats BASE under 1% fee + 0.3% slippage, and 3-session delay',
            'uncertainty':'paired 21-session block bootstrap log-relative-wealth 95% CI lower > 0 to claim statistically supported superiority',
            'production':'never enabled; receipt-time, corporate-action cash timing, survivorship and actual queue evidence remain unresolved'},
        'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [HERE/'engine.py',OUT/'input_manifest.json',OUT/'inputs.npz']}}
    protocol['data_revision_note']=json.loads((OUT/'input_manifest.json').read_text(encoding='utf8')).get('data_revision_note','original normalization')
    path=OUT/'protocol.locked.json'
    if path.exists():
        prev=json.loads(path.read_text(encoding='utf8'))
        assert prev['configs']==protocol['configs'] and prev['source_hashes']==protocol['source_hashes'], 'Frozen protocol changed'
        return prev
    dump(path,protocol)
    return protocol


def selection_row(cfg,run,base,folds=FOLDS):
    m=run['metrics'];bm=base['metrics'];logs=[];row={'id':cfg.id,**asdict(cfg),**m,
        'n_trades':run['n_trades'],'cost_toman':run['cost_toman'],'expired_orders':run['expired_orders']}
    for k,(a,b) in enumerate(folds):
        x=window_metrics(run,a,b);y=window_metrics(base,a,b)
        rel=(1+x['total_return'])/(1+y['total_return']);logs.append(np.log(rel))
        row[f'fold{k+1}_return']=x['total_return'];row[f'fold{k+1}_relative_wealth']=rel
    row['worst_relative_wealth']=float(np.exp(min(logs)))
    row['score']=float(.6*np.median(logs)+.4*np.mean(logs)-.25*abs(m['max_drawdown']))
    row['eligible']=bool(cfg.n>=3 and cfg.id not in ['EW254','MOM_ONLY','TOP1_CONTROL']
        and m['total_return']>0 and abs(m['max_drawdown'])<=max(.25,abs(bm['max_drawdown'])+.05)
        and min(logs)>=np.log(.75))
    return row


def bootstrap(chosen,base,B=3000):
    assert np.array_equal(chosen['cal'],base['cal'])
    x=np.diff(np.log(chosen['nav']))-np.diff(np.log(base['nav']))
    rng=np.random.default_rng(20261106)
    block=21;n=len(x);draw=[]
    for _ in range(B):
        starts=rng.integers(0,n,size=(n+block-1)//block)
        ix=np.concatenate([(s+np.arange(block))%n for s in starts])[:n]
        draw.append(float(x[ix].sum()))
    q=np.quantile(draw,[.025,.5,.975])
    return {'block_sessions':block,'replications':B,'observed_relative_wealth':float(chosen['nav'][-1]/base['nav'][-1]),
            'ci95_relative_wealth':[float(np.exp(q[0])),float(np.exp(q[2]))],
            'bootstrap_fraction_relative_wealth_le1':float(np.mean(np.array(draw)<=0)),
            'note':'conditional on frozen chosen policy; does not remove prior model/universe selection bias'}


def main():
    t=time.time();protocol=freeze()
    data=dict(np.load(OUT/'inputs.npz',allow_pickle=False))
    configs=configurations();byid={c.id:c for c in configs}
    base=simulate(data,BASE,EXEC,end=END_TRAIN)
    train={};rows=[]
    for k,c in enumerate(configs,1):
        r=base if c.id=='BASE' else simulate(data,c,EXEC,end=END_TRAIN)
        train[c.id]=r;rows.append(selection_row(c,r,base))
        if k%20==0:print(f'TRAIN {k}/{len(configs)} completed ({time.time()-t:.1f}s)',flush=True)
    table=pd.DataFrame(rows).sort_values(['eligible','score','n_trades','id'],ascending=[False,False,True,True])
    table.to_csv(OUT/'selection_all_configs.csv',index=False,encoding='utf-8-sig')
    eligible=table[table.eligible & table.id.ne('BASE')]
    chosen=byid[eligible.iloc[0].id] if len(eligible) else BASE
    locked={'chosen_before_verification':asdict(chosen),'selection_end':END_TRAIN,
            'locked_at_utc':datetime.now(timezone.utc).isoformat(),
            'protocol_sha256':hashlib.sha256((OUT/'protocol.locked.json').read_bytes()).hexdigest(),
            'selection_table_sha256':hashlib.sha256((OUT/'selection_all_configs.csv').read_bytes()).hexdigest()}
    # Verification has not been simulated or inspected before this file is written.
    if (OUT/'chosen.before_verification.json').exists():
        assert json.loads((OUT/'chosen.before_verification.json').read_text(encoding='utf8'))['chosen_before_verification']==asdict(chosen)
    else:dump(OUT/'chosen.before_verification.json',locked)
    print('LOCKED CHOICE',chosen.id,flush=True)
    # A genuine chronological policy selection audit, using only each fold's past.
    wfchoices={};wfhistory=[]
    for a,b in FOLDS:
        past_end=(pd.Timestamp(a)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        years=(pd.Timestamp(past_end)-pd.Timestamp('2021-04-03')).days/365.25
        base_p=window_metrics(base,'2021-04-03',past_end)
        records=[]
        for c in configs:
            if c.id in ['EW254','MOM_ONLY','TOP1_CONTROL'] or c.n<3:continue
            m=window_metrics(train[c.id],'2021-04-03',past_end)
            if abs(m['max_drawdown'])>max(.25,abs(base_p['max_drawdown'])+.05):continue
            logrel=np.log((1+m['total_return'])/(1+base_p['total_return']))/years
            records.append((logrel-.25*abs(m['max_drawdown']),c.id))
        winner=max(records)[1] if records else 'BASE'
        boundary=data['cal'][np.searchsorted(data['cal'],a)-1]
        wfchoices[str(boundary)]=byid[winner]
        wfhistory.append(dict(evaluation_start=a,evaluation_end=b,past_data_end=past_end,decision=str(boundary),chosen=winner))
    wf=simulate(data,BASE,EXEC,start=wfhistory[0]['decision'],end=END_TRAIN,detail=True,choice_schedule=wfchoices)
    save_run(OUT/'walk_forward',wf);dump(OUT/'walk_forward_choices.json',wfhistory)
    comparisons=[];runs={}
    for label,c in [('chosen',chosen),('baseline',BASE),('equal_universe',byid['EW254']),('momentum_control',byid['MOM_ONLY'])]:
        r=simulate(data,c,EXEC,start='2025-01-01',end=END_VERIFY,detail=True)
        runs[label]=r;save_run(OUT/f'verify_{label}',r)
        comparisons.append({'label':label,'id':c.id,**r['metrics'],'n_trades':r['n_trades'],
                            'expired_orders':r['expired_orders'],'cost_toman':r['cost_toman'],
                            'slippage_toman':r['slippage_toman']})
    pd.DataFrame(comparisons).to_csv(OUT/'verification.csv',index=False,encoding='utf-8-sig')
    print('VERIFICATION',json.dumps(comparisons[:2]),flush=True)
    stress_rows=[]
    scenarios={'default':EXEC,'fee1pct_slip03pct':replace(EXEC,fee=.01,slippage=.003),
        'delay3sessions':replace(EXEC,delay=3),'capacity1pct':replace(EXEC,capacity=.01),
        'zero_capacity_constraint':replace(EXEC,capacity=None,skip_one_price=False),
        'financial_age180':replace(EXEC,max_financial_age=180),'signal_age14':replace(EXEC,max_signal_age=14)}
    for name,e in scenarios.items():
        for label,c in [('chosen',chosen),('baseline',BASE)]:
            r=simulate(data,c,e,start='2025-01-01',end=END_VERIFY)
            stress_rows.append(dict(scenario=name,label=label,**r['metrics'],n_trades=r['n_trades'],expired_orders=r['expired_orders']))
    for start in ['2022-01-01','2023-03-21','2024-01-01']:
        for label,c in [('chosen',chosen),('baseline',BASE)]:
            r=simulate(data,c,EXEC,start=start,end=END_VERIFY,detail=True)
            save_run(OUT/f'start_{start}_{label}',r)
            stress_rows.append(dict(scenario=f'start_{start}',label=label,**r['metrics'],n_trades=r['n_trades'],expired_orders=r['expired_orders']))
    # Known stale-score extension; explicitly excluded from selection/promotion.
    for label,c in [('chosen',chosen),('baseline',BASE)]:
        r=simulate(data,c,replace(EXEC,max_signal_age=99999),start='2023-03-21',end='2026-09-30',detail=True)
        save_run(OUT/f'stale_extension_{label}',r)
        stress_rows.append(dict(scenario='STALE_SCORE_EXTENSION_NOT_VALIDATION',label=label,**r['metrics'],n_trades=r['n_trades'],expired_orders=r['expired_orders']))
    stresses=pd.DataFrame(stress_rows);stresses.to_csv(OUT/'stress_results.csv',index=False,encoding='utf-8-sig')
    ci=bootstrap(runs['chosen'],runs['baseline']);dump(OUT/'paired_bootstrap.json',ci)
    m=runs['chosen']['metrics'];b=runs['baseline']['metrics']
    def wins(s):
        x=stresses[stresses.scenario.eq(s)].set_index('label')
        return bool(x.loc['chosen','final_toman']>x.loc['baseline','final_toman'])
    gates={'verification_return':m['final_toman']>b['final_toman'],
           'verification_drawdown':abs(m['max_drawdown'])<=abs(b['max_drawdown'])+.05,
           'cost_stress':wins('fee1pct_slip03pct'),'delay_stress':wins('delay3sessions'),
           'statistical_support':ci['ci95_relative_wealth'][0]>1}
    recommended=chosen if all(gates.values()) else BASE
    # Symbol attribution reconciles costs and terminal NAV for verification.
    for label in ['chosen','baseline']:
        r=runs[label];pnl={}
        for tr in r['trades']:
            s=tr['symbol'];pnl.setdefault(s,{'symbol':s,'buy_cash':0.,'sell_cash':0.,'fees':0.})
            pnl[s]['fees']+=tr['fee_toman']
            if tr['side']=='BUY':pnl[s]['buy_cash']+=tr['gross_toman']+tr['fee_toman']
            else:pnl[s]['sell_cash']+=tr['gross_toman']-tr['fee_toman']
        for s,row in pnl.items():
            row['terminal_value']=r['terminal_positions'].get(s,0.)
            row['pnl_toman']=row['terminal_value']+row['sell_cash']-row['buy_cash']
        assert abs(sum(x['pnl_toman'] for x in pnl.values())-(r['nav'][-1]-100e6))<.1
        pd.DataFrame(pnl.values()).sort_values('pnl_toman',ascending=False).to_csv(OUT/f'verify_{label}_attribution.csv',index=False,encoding='utf-8-sig')
    summary={'searched_configurations':len(configs),'frozen_challenger':asdict(chosen),
        'research_recommendation':asdict(recommended),'gates':gates,'verification':comparisons,
        'paired_bootstrap':ci,'production_ready':False,
        'conclusion':'CHALLENGER_SUPPORTED_RETROSPECTIVELY' if all(gates.values()) else 'NO_SUFFICIENT_EVIDENCE_TO_REPLACE_BASELINE',
        'input_quality_limits':['unproven historical receipt time','fixed current universe and survivorship',
            'adjusted index units and immediate dividend reinvestment','daily bars do not prove opening queue fills',
            'previously researched historical data; no untouched prospective holdout'],
        'elapsed_seconds':round(time.time()-t,1)}
    dump(OUT/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
