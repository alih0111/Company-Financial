import gzip
import pickle
import bisect
import json
import numpy as np
import pandas as pd
from .common import V2,V3,V4,V5,START,DISPLAY_START,END,read,write,sha,frame_hash,utc
from .model import mature_training,ridge,rank_center

def selector_stress(panel,md,prices,protocol,kwargs=None,end=END):
    """Explicit verified protocol dependency, including the actual selector branch."""
    from ranking_research.return_v3.research import outer
    assert protocol['old_selector_choices'] and protocol['folds']
    return outer(panel,md,prices,protocol['old_selector_choices'],protocol['folds'],end,kwargs)

def schedule(md, protocol):
    from ranking_research.strategy_search.policy_engine import decision_calendar
    from ranking_research.strategy_search.wave2 import policies
    pol=policies()['P3'];dates=[]
    for fold in protocol['folds']:
        lo,hi=fold['evaluate'][0],fold['evaluate'][-1]
        boundary=max(x for x in md.cal if x[:7]<lo)
        dates += [boundary]+[x for x in decision_calendar(md,boundary,END,'biweekly') if lo<=x[:7]<=hi]
    return {day:pol for day in sorted(set(dates)) if day<=END}

def store(out,eid,frame,runner,scope):
    base=out/'results';base.mkdir(exist_ok=True)
    p=base/(eid+'.pkl.gz');contract=base/(eid+'.contract.json')
    sig=frame_hash(frame)
    if p.exists():
        c=read(contract);assert c['frame_sha256']==sig and sha(p)==c['payload_sha256']
        with gzip.open(p,'rb') as f:return pickle.load(f)
    write(contract,{'started_at':utc(),'frame_sha256':sig,'scope':scope,'status':'running'})
    try:r=runner()
    except Exception as e:
        write(contract,{'frame_sha256':sig,'scope':scope,'status':'failed','error':repr(e)});raise
    with gzip.open(p,'wb') as f:pickle.dump(r,f)
    write(contract,{'frame_sha256':sig,'scope':scope,'status':'complete','payload_sha256':sha(p),'completed_at':utc()})
    return r

def run_frame(frame,md,prices,sch,kwargs=None,initial=100000000):
    from ranking_research.strategy_search.policy_engine import run_policy
    from ranking_research.strategy_search.wave2 import policies
    pol={**policies()['P3'],'initial_toman':initial}
    r=run_policy(frame,md,pol,prices=prices,start=START,end=END,policy_schedule={k:{**v,'initial_toman':initial} for k,v in sch.items()},**(kwargs or {}))
    # Keep the complete account, including decision-day NAV. Display clipping is explicit.
    return r

def features(d):
    from ranking_research.return_v2.signals import score
    z=d.copy().reset_index(drop=True);f=score(z,'S2')
    z['op_ttm_assets']=z.operating_profit_ttm/z.total_assets.where(z.total_assets.gt(0))
    z['feature_valid']=f.eligible&np.isfinite(z.momentum_12_1)&np.isfinite(z.op_ttm_assets)
    z['source_max']=[max((s['published_at'] for s in json.loads(raw)),key=lambda s:pd.Timestamp(s)) if isinstance(raw,str) and json.loads(raw) else None for raw in z.sources]
    return z

def train(out,d,md,protocol):
    from ranking_research.strategy_search.policy_engine import decision_calendar
    from ranking_research.return_v2.market import traded_return
    target=out/'model_frames.parquet'
    if target.exists():return pd.read_parquet(target)
    z=features(d);columns=['s2_raw','op_ttm_assets','momentum_12_1']
    # Fixed source-based feature branch before returns. TTM/positive own assets are present.
    write(out/'model_contract.json',{'registered_at':utc(),'before_portfolio_returns':True,'features':columns,
        'formula':{'s2_raw':'same independent-quarter OP change / mean positive comparable assets',
            'op_ttm_assets':'source-verified parent OP TTM / latest positive same-source assets',
            'momentum_12_1':'existing causal adjustment chain at decision, from t-12 months to t-1 month'},
        'target':'cross-sectional percentile rank adjusted-index 60 inferred-session return, centered by .5',
        'objective':'weighted_mean_squared_error + 1.0 * sum(beta**2); intercept unpenalized',
        'alpha':1.,'fit_dates':'monthly, >=24 mature dates, >=20 valid labels per date',
        'weight':'each date 1/N_dates; each name 1/N_names within date','lookback_months':36,
        'refit':'only evaluation block boundary; coefficients fixed through block','fallback':'S2 on SAME feature cohort',
        'model_selection':'no grid, no sign edits, three features chosen on reconstructibility before return observation',
        'horizon_rationale':'fixed design chosen on consumed history, not independent validation','labels_economic_total_return':False})
    months=decision_calendar(md,'2022-04-01',END,'monthly')
    training=z[z.decision_time.isin(months)&z.feature_valid].copy();cal=list(md.cal)
    labels=[]
    for a in training.itertuples():
        i=bisect.bisect_left(cal,a.decision_time)+60
        end=cal[i] if i<len(cal) and cal[i]<=END else None
        value=traded_return(md,a.symbol,a.decision_time,end,end) if end else np.nan
        labels.append((end,value))
    training['label_end']=[v[0] for v in labels];training['label']=[v[1] for v in labels]
    training[['company_id','symbol','decision_time','source_max','label_end','label','feature_valid']].to_csv(out/'training_label_coverage.csv',index=False)
    fits=[];coefs=[];outputs=[]
    sch=schedule(md,protocol)
    for fold in protocol['folds']:
        lo,hi=fold['evaluate'][0],fold['evaluate'][-1]
        cutoff=max(x for x in sch if x[:7]<lo)
        tr=mature_training(training,cutoff);n=tr.decision_time.nunique();fit=n>=24
        beta,evidence=ridge(tr,columns) if fit else (None,{'rows':len(tr),'dates':n})
        fits.append({'block_start':lo,'block_end':hi,'cutoff':cutoff,'training_dates':n,'training_rows':len(tr),
            'minimum_names':int(tr.groupby('decision_time').size().min()) if len(tr) else 0,
            'max_label_end':tr.label_end.max() if len(tr) else None,'max_source_publication':str(pd.to_datetime(tr.source_max,utc=True).max()) if len(tr) else None,
            'status':'trained' if fit else 'not_tested_insufficient_dates','fallback':'none' if fit else 'S2_same_cohort',
            'sum_weights':evidence.get('sum_weights'),'overlapping_labels_not_independent':True})
        if beta is not None:
            for name,b in zip(['intercept']+columns,beta):coefs.append({'block_start':lo,'cutoff':cutoff,'feature':name,'coefficient':b})
        days=[day for day in sch if day==cutoff or lo<=day[:7]<=hi]
        part=z[z.decision_time.isin(days)].copy().reset_index(drop=True)
        valid=part.feature_valid; ranks=rank_center(part.loc[valid],columns)
        part['equal_score']=np.nan;part.loc[valid,'equal_score']=ranks.mean(axis=1)
        part['ridge_score']=np.nan
        part.loc[valid,'ridge_score']=beta[0]+ranks.to_numpy()@beta[1:] if fit else ranks.s2_raw
        part['training_block']=lo;part['learned_model_used']=fit
        outputs.append(part)
    result=pd.concat(outputs).drop_duplicates(['decision_time','company_id'],keep='last').sort_values(['decision_time','company_id']).reset_index(drop=True)
    result.to_parquet(target,index=False)
    pd.DataFrame(fits).to_csv(out/'training_cutoffs.csv',index=False)
    pd.DataFrame(coefs,columns=['block_start','cutoff','feature','coefficient']).to_csv(out/'model_coefficients.csv',index=False)
    return result

def score_frame(d, kind, common=False):
    from ranking_research.return_v2.signals import score
    f=score(d,'S2',d.feature_valid if common else None)
    if kind in ['equal','ridge']:
        f['eligible']=d.feature_valid.to_numpy()
        f['score']=d[kind+'_score'].to_numpy()
    return f

def describe(name,p,frame,scope='natural'):
    from ranking_research.return_v5.diagnostics import primary_summary
    s=primary_summary(p,END)
    nav=pd.DataFrame(p['daily_nav']);display=nav[nav.date.ge(DISPLAY_START)&nav.date.le(END)]
    f=pd.DataFrame(p['fills']);orders=pd.DataFrame(p['orders'])
    counts=frame.groupby('decision_time').eligible.sum()
    initial=p['summary'].get('initial_toman',100000000)
    return {'method':name,'scope':scope,**s,'start':DISPLAY_START,'decision_start':START,'first_nav':nav.date.min(),
        'first_fill':f.date.min() if len(f) else None,'first_display_nav':display.date.min(),
        'initial_toman':initial,'first_account_nav_toman':nav.iloc[0].nav_rial/10,
        'pre_display_cost_toman':f.loc[f.date.lt(DISPLAY_START),'fee_rial'].sum()/10 if len(f) else 0,
        'total_cost_toman':f.fee_rial.sum()/10 if len(f) else 0,'average_candidates':counts.mean(),'minimum_candidates':counts.min(),
        'average_cash_ratio':float((display.cash_rial/display.nav_rial).mean()),
        'incomplete_orders':int((orders.remaining_units>0).sum()) if len(orders) else 0,
        'actual_decision_cadences':'biweekly' if name!='existing_choose' else 'explicit V3 protocol schedule',
        'account_not_reset':True,'economic_final_toman':None}

def blocks(name,p):
    ranges=read(V5/'evaluation_windows.json');nav=pd.DataFrame(p['daily_nav']);prev=1e9;rows=[]
    for lo,hi in ranges['complete_outer_blocks']+[ranges['partial_outer_block']]:
        g=nav[nav.date.between(lo,hi)];value=g.iloc[-1].nav_rial
        rows.append({'method':name,'start':lo,'end':hi,'initial_toman':prev/10,'final_toman':value/10,'return':value/prev-1,'complete':hi<='2025-10-31'})
        prev=value
    return rows
