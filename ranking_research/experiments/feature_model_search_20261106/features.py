"""Causal feature bank and delayed/realized forward labels; research only."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import hashlib,json,sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PREV=HERE.parent/'final_strategy_review_20261106'
OUT=HERE/'artifacts'
sys.path[:0]=[str(ROOT),str(PREV),str(HERE.parent/'rank_top5_rebalance_20261105')]
from ranking_research.return_v8.features import FIELDS,LOW


def rank_transform(x,lower=False):
    """Within-date transform only. Missing values are neutral, with explicit flags."""
    x=np.asarray(x,float)
    r=pd.DataFrame(x).rank(axis=1,method='average',pct=True).to_numpy()
    result=2*r-1
    if lower:result=-result
    return np.where(np.isfinite(x),result,0.).astype(np.float32)


def market_features(close,adv):
    c=pd.DataFrame(close).where(np.asarray(close)>0);r=c.pct_change(fill_method=None)
    out={}
    for h in [21,63,126,252]:out[f'mom_{h}']=c.pct_change(h,fill_method=None).to_numpy()
    for h in [126,252]:out[f'mom_{h}_skip21']=(c.shift(21)/c.shift(h)-1).to_numpy()
    for h in [21,63]:out[f'vol_{h}']=r.rolling(h,min_periods=max(10,h//2)).std().to_numpy()
    out['downside_vol63']=r.clip(upper=0).rolling(63,min_periods=40).std().to_numpy()
    for h in [63,126,252]:out[f'near_high_{h}']=(c/c.rolling(h,min_periods=h//2).max()-1).to_numpy()
    out['trend_50_200']=(c.rolling(50,min_periods=40).mean()/c.rolling(200,min_periods=150).mean()-1).to_numpy()
    out['reversal21']=-out['mom_21']
    out['log_adv20']=np.log1p(adv)
    return out


def forward_labels(data,horizon):
    """First available next-session open (<=5 sessions), fixed endpoint after h.

    Label end indexes are returned and MUST be <= each model's fit cutoff.
    Queue capacity at portfolio size is handled by the portfolio simulator.
    """
    T,S=data['close'].shape;y=np.full((T,S),np.nan);end=np.full(T,-1,int)
    for i in range(T-horizon):
        endpoint=i+horizon
        end[i]=endpoint
        op=np.full(S,np.nan)
        for k in range(i+1,min(i+6,endpoint+1)):
            good=np.isnan(op)&np.isfinite(data['opening'][k])&~data['locked'][k]
            op[good]=data['opening'][k,good]
        valid=(op>0)&(data['close'][endpoint]>0)&(data['mark_age'][endpoint]<=10)
        with np.errstate(divide='ignore',invalid='ignore'):
            z=np.log(data['close'][endpoint,valid]/op[valid])
        if valid.sum()>=10:
            z=np.clip(z,-.7,.7)
            y[i,valid]=z-np.median(z)
    return y,end


def eligible_training_rows(data,label_end,cutoff,sample_rows):
    return np.asarray(sample_rows)[(label_end[np.asarray(sample_rows)]>=0)&
                                    (label_end[np.asarray(sample_rows)]<=cutoff)]


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare():
    OUT.mkdir(exist_ok=True)
    prior=PREV/'artifacts_v2/inputs.npz'
    data=dict(np.load(prior,allow_pickle=False))
    end=np.searchsorted(data['cal'],'2026-02-24',side='right')
    T0=len(data['cal'])
    data={k:(v[:end] if v.ndim and v.shape[0]==T0 else v) for k,v in data.items()}
    import backtest_top5 as old
    panel=old.apply_monthly_correction(pd.read_parquet(old.PANEL))
    dates=sorted(panel.decision_time.unique());syms=data['syms'].tolist()
    ix=pd.MultiIndex.from_product([dates,syms],names=['decision_time','symbol'])
    ordered=panel.set_index(['decision_time','symbol']).reindex(ix)
    raw=ordered[FIELDS].to_numpy(float).reshape(len(dates),len(syms),len(FIELDS))
    dateix=np.searchsorted(dates,data['cal'],side='right')-1
    raw_daily=raw[dateix]
    dq=ordered.dq.to_numpy(float).reshape(len(dates),len(syms))[dateix]
    net=ordered.net_profit_ttm.to_numpy(float).reshape(len(dates),len(syms))[dateix]
    # Audit each consumed source's own publication time, separately from receipt.
    publication=np.zeros(len(ordered),bool)
    for i,(sources,cutoff) in enumerate(zip(ordered.sources,ordered.publication_cutoff)):
        try:
            src=json.loads(sources) if isinstance(sources,str) else []
            boundary=datetime.fromisoformat(str(cutoff))
            publication[i]=bool(src) and all(datetime.fromisoformat(str(s['published_at']))<boundary for s in src)
        except (ValueError,TypeError,KeyError):pass
    publication=publication.reshape(len(dates),len(syms))[dateix]
    allowed=np.isfinite(data['p1']) & publication
    # Common candidate universe/coverage guard; no future label affects scoring eligibility.
    columns=[];names=[];groups=[];missing=[]
    for j,f in enumerate(FIELDS):
        x=raw_daily[:,:,j].copy()
        if j==11:x=np.abs(x)
        if j in [12,13,14]:x[(x<=0)|(x>[60,100,30][j-12])]=np.nan
        columns.append(rank_transform(x,j in LOW));names.append(f);groups.append('fundamental')
        missing.append((~np.isfinite(x)).astype(np.float32))
    mf=market_features(data['close'],data['adv'])
    for name,x in mf.items():
        columns.append(rank_transform(x,name.startswith('vol_') or name=='downside_vol63'))
        names.append(name);groups.append('market')
    def add(name,x,group='derived'):
        columns.append(rank_transform(x));names.append(name);groups.append(group)
    lag=np.searchsorted(data['cal'].astype('datetime64[D]'),data['cal'].astype('datetime64[D]')-np.timedelta64(90,'D'),side='right')-1
    lag=np.maximum(lag,0)
    add('sales_accel_3v12',raw_daily[:,:,1]-raw_daily[:,:,0])
    for j,f in [(1,'sales_growth_change90'),(4,'profit_growth_change90'),(8,'margin_trend_change90')]:
        add(f,raw_daily[:,:,j]-raw_daily[lag,:,j])
    add('p1_score',data['p1'],'reference')
    add('p1_score_change90',data['p1']-data['p1'][lag])
    add('data_quality',dq,'quality')
    add('financial_freshness',-data['financial_age'],'quality')
    X=np.stack(columns,axis=2)
    # Explicit missingness is known at the prediction time, not backfilled.
    for j,f in enumerate(FIELDS):
        names.append('missing_'+f);groups.append('missing')
    X=np.concatenate([X,np.stack(missing,axis=2)],axis=2).astype(np.float32)
    idx={n:i for i,n in enumerate(names)}
    def mean(fs):return np.mean(X[:,:,[idx[f] for f in fs]],axis=2)
    bank={
        'growth':mean(FIELDS[:5]),'profitability':mean(FIELDS[5:12]),
        'valuation':mean(['pe','ps','pb']),
        'balance':mean(['leverage','current_ratio','cash_conversion','sales_stability']),
        'momentum':mean(['mom_63','mom_126_skip21','near_high_126','trend_50_200']),
        'risk':mean(['vol_63','downside_vol63','reversal21']),
        'acceleration':mean(['sales_accel_3v12','sales_growth_change90','profit_growth_change90','margin_trend_change90']),
        'p1':X[:,:,idx['p1_score']]}
    np.savez_compressed(OUT/'market_inputs.npz',**data)
    arrays={'X':X,'names':np.array(names),'groups':np.array(groups),'allowed':allowed,
            'raw':raw_daily.astype(np.float32),'dq':dq,'net':net,'publication':publication,
            'sample_rows':np.searchsorted(data['cal'],dates),'block_names':np.array(list(bank)),
            'blocks':np.stack(list(bank.values()),axis=2)}
    for h in [63,126]:
        y,ends=forward_labels(data,h);arrays[f'y{h}']=y.astype(np.float32);arrays[f'label_end{h}']=ends
    np.savez_compressed(OUT/'features.npz',**arrays)
    table=[]
    for i,n in enumerate(names):
        table.append(dict(feature=n,group=groups[i],nonzero_fraction=float(np.mean(X[:,:,i]!=0)),
                          original_missing_fraction=float(np.mean(missing[i])) if i<len(FIELDS) else None))
    pd.DataFrame(table).to_csv(OUT/'feature_inventory.csv',index=False,encoding='utf-8-sig')
    manifest={'features':len(names),'sessions':len(data['cal']),'symbols':len(syms),
        'source_signals_end':str(data['cal'][-1]),'source_market_sha256':sha(prior),
        'source_panel_sha256':sha(old.PANEL),'monthly_events_sha256':sha(old.MONTHLY_EVENTS),
        'publication_valid_cells':int(publication.sum()),'p1_scoreable_but_publication_invalid':int(np.sum(np.isfinite(data['p1'])&~publication)),
        'pit_receipt_time_proven':False,'prior_verification_seen':True,
        'label_rule':'first non-one-price available open in next 5 sessions; endpoint decision+h; only realized ends enter training',
        'sample_dates':len(dates),'feature_names':names}
    (OUT/'feature_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='feature_names'},indent=2),flush=True)


if __name__=='__main__':prepare()
