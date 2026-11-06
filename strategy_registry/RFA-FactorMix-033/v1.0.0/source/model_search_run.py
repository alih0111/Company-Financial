"""Broad authorized model research; prior history exposure remains explicit."""
from dataclasses import asdict,replace
from datetime import datetime,timezone
from pathlib import Path
import json,time,hashlib,sys
import numpy as np
import pandas as pd
from features import HERE,OUT,PREV,sha
from models import registry,policies,source_tensor,build_scores
sys.path.insert(0,str(PREV))
from engine import Config,Execution,simulate,window_metrics,save_run
from run_research import bootstrap,dump

E=Execution();BASE=Config('BASE');FOLDS=[('2023-01-01','2023-06-30'),('2023-07-01','2023-12-31'),
                                        ('2024-01-01','2024-06-30'),('2024-07-01','2024-12-31')]


def select_row(model,policy,run,base):
    m=run['metrics'];logrel=[]
    row={'model':model['id'],'kind':model['kind'],'policy':policy.id,'id':model['id']+'__'+policy.id,
         **m,'n_trades':run['n_trades'],'expired_orders':run['expired_orders']}
    for k,(a,b) in enumerate(FOLDS):
        x=window_metrics(run,a,b);y=window_metrics(base,a,b)
        rel=(1+x['total_return'])/(1+y['total_return']);logrel.append(np.log(rel))
        row[f'fold{k+1}_return']=x['total_return'];row[f'fold{k+1}_relative']=rel
    row['score']=float(np.mean(logrel)-.25*np.std(logrel)-.25*abs(m['max_drawdown']))
    row['eligible']=bool(m['total_return']>0 and
        abs(m['max_drawdown'])<=max(.25,abs(base['metrics']['max_drawdown'])+.05) and min(logrel)>=np.log(.75))
    return row


def main():
    t=time.time();OUT.mkdir(exist_ok=True);(OUT/'score_cache').mkdir(exist_ok=True)
    data=dict(np.load(OUT/'market_inputs.npz',allow_pickle=False));feat=dict(np.load(OUT/'features.npz',allow_pickle=False))
    specs=registry();ps=policies();specmap={x['id']:x for x in specs};pmap={c.id:c for c in ps}
    protocol={'registered_at_utc':datetime.now(timezone.utc).isoformat(),
        'prior_verification_seen':True,'status':'RETROSPECTIVE_EXPLORATORY_MODEL_SEARCH_NOT_PRISTINE_OOS',
        'objective':'higher net return with drawdown and cross-period stability gates; not maximum in-sample NAV',
        'selection':['2022-01-01','2024-12-31'],'selection_folds':FOLDS,
        'reused_verification':['2025-01-01','2026-02-24'],
        'selection_score':'mean six-month log relative wealth - .25 * std of log relative wealth - .25 * absolute DD',
        'selection_gate':'positive return, DD <= max(25%, BASE DD+5pp), each fold relative wealth >= .75',
        'learned_model_retrain':'January and July boundaries; only sample label_end <= previous session cutoff; equal-date sample weights',
        'minimum_fit':'500 labels and 5 completed source dates, else P1 fallback explicitly recorded',
        'execution':asdict(E),'models':specs,'policies':[asdict(p) for p in ps],
        'source_hashes':{p.name:sha(p) for p in [OUT/'features.npz',OUT/'market_inputs.npz',HERE/'features.py',HERE/'models.py',HERE/'run.py']},
        'promotion_gate':'verification relative wealth >1, DD <= BASE DD+5pp, win cost and delay stresses, paired 95% CI lower >1; prospective evidence still required'}
    path=OUT/'protocol.locked.json'
    if path.exists():
        prev=json.loads(path.read_text(encoding='utf8'))
        assert prev['source_hashes']==protocol['source_hashes'] and prev['models']==specs
    else:dump(path,protocol)
    tensor=source_tensor(feat)
    baseline=simulate(data,BASE,E,start='2022-01-01',end='2024-12-31')
    rows=[];fit_audits=[]
    for k,spec in enumerate(specs,1):
        cache=OUT/'score_cache'/f"{spec['id']}.npz"
        auditfile=OUT/'score_cache'/f"{spec['id']}.fits.json"
        if cache.exists():
            values=np.load(cache)['score'];audits=json.loads(auditfile.read_text(encoding='utf8'))
        else:
            values,audits=build_scores(spec,data,feat,tensor)
            np.savez_compressed(cache,score=values);dump(auditfile,audits)
        fit_audits.extend(audits)
        for p in ps:
            r=simulate({**data,'p1':values},p,E,start='2022-01-01',end='2024-12-31')
            rows.append(select_row(spec,p,r,baseline))
        if k%10==0 or spec['kind']=='learned':
            print(f'MODELS {k}/{len(specs)}; portfolios {len(rows)}; elapsed {time.time()-t:.1f}s; {spec["id"]}',flush=True)
    table=pd.DataFrame(rows).sort_values(['eligible','score','n_trades','id'],ascending=[False,False,True,True])
    table.to_csv(OUT/'selection_all.csv',index=False,encoding='utf-8-sig')
    dump(OUT/'fit_audits.json',fit_audits)
    assert all(x['max_label_end'] is None or x['max_label_end']<=x['fit_cutoff'] for x in fit_audits)
    winner=table[table.eligible].iloc[0]
    spec=specmap[winner.model];p=pmap[winner.policy]
    locked={'selected_model':spec,'selected_policy':asdict(p),'selected_training_row':winner.to_dict(),
            'selection_end':'2024-12-31','prior_verification_seen':True,
            'locked_at_utc':datetime.now(timezone.utc).isoformat(),'selection_table_sha256':sha(OUT/'selection_all.csv')}
    lockpath=OUT/'chosen.before_reused_verification.json'
    if lockpath.exists():
        assert json.loads(lockpath.read_text(encoding='utf8'))['selected_training_row']['id']==winner.id
    else:dump(lockpath,locked)
    print('LOCKED MODEL/POLICY',winner.id,flush=True)
    values=np.load(OUT/'score_cache'/f"{spec['id']}.npz")['score']
    candidate={**data,'p1':values}
    verify={};comparison=[]
    for label,d,c in [('candidate',candidate,p),('baseline',data,BASE)]:
        r=simulate(d,c,E,start='2025-01-01',end='2026-02-24',detail=True)
        verify[label]=r;save_run(OUT/f'verify_{label}',r)
        comparison.append({'label':label,**r['metrics'],'n_trades':r['n_trades'],'expired_orders':r['expired_orders']})
    stress=[]
    cases={'fee1pct_slip03pct':replace(E,fee=.01,slippage=.003),'delay3sessions':replace(E,delay=3),
           'capacity1pct':replace(E,capacity=.01),'order_life10':replace(E,order_life=10),
           'fresh_price1':replace(E,max_mark_age=1)}
    for case,ex in cases.items():
        for label,d,c in [('candidate',candidate,p),('baseline',data,BASE)]:
            r=simulate(d,c,ex,start='2025-01-01',end='2026-02-24')
            stress.append(dict(case=case,label=label,**r['metrics']))
    monthly=[]
    for start in pd.date_range('2023-01-01','2024-12-01',freq='MS').strftime('%Y-%m-%d'):
        for label,d,c in [('candidate',candidate,p),('baseline',data,BASE)]:
            r=simulate(d,c,E,start=start,end='2026-02-24')
            monthly.append(dict(start_date=start,label=label,**r['metrics']))
    pd.DataFrame(stress).to_csv(OUT/'stress.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(monthly).to_csv(OUT/'monthly_starts.csv',index=False,encoding='utf-8-sig')
    ci=bootstrap(verify['candidate'],verify['baseline'])
    def wins(case):
        z=[r for r in stress if r['case']==case]
        return next(r['final_toman'] for r in z if r['label']=='candidate')>next(r['final_toman'] for r in z if r['label']=='baseline')
    cm=verify['candidate']['metrics'];bm=verify['baseline']['metrics']
    gates={'verification_return':cm['final_toman']>bm['final_toman'],
        'verification_drawdown':abs(cm['max_drawdown'])<=abs(bm['max_drawdown'])+.05,
        'cost_stress':wins('fee1pct_slip03pct'),'delay_stress':wins('delay3sessions'),
        'paired_ci_lower_above_one':ci['ci95_relative_wealth'][0]>1}
    # Full chronology for the frozen choice; verification already declared reused.
    for label,d,c in [('candidate',candidate,p),('baseline',data,BASE)]:
        r=simulate(d,c,E,start='2022-01-01',end='2026-02-24',detail=True)
        save_run(OUT/f'full_{label}',r)
    monthly=pd.DataFrame(monthly).pivot(index='start_date',columns='label',values='final_toman')
    result={'model_specifications':len(specs),'portfolio_configurations_per_model':len(ps),
        'selection_portfolio_runs':len(rows),'input_features':feat['X'].shape[-1],
        'learned_models':sum(x['kind']=='learned' for x in specs),'fit_audit_records':len(fit_audits),
        'all_training_labels_realized_at_fit':True,'winner':locked,'verification':comparison,
        'paired_bootstrap':ci,'gates':gates,'all_gates_pass':all(gates.values()),
        'monthly_start_wins':int((monthly.candidate>monthly.baseline).sum()),'monthly_start_pairs':len(monthly),
        'prior_verification_seen':True,'production_activated':False,'elapsed_seconds':round(time.time()-t,1)}
    dump(OUT/'summary.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='winner'},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
