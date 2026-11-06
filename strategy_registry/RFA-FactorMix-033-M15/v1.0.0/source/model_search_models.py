"""Frozen feature ablations, group weights and purged expanding models."""
from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
import json,sys
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge,ElasticNet
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits
from features import HERE,ROOT,PREV,OUT,eligible_training_rows

sys.path.insert(0,str(PREV))
from engine import Config
from ranking_research.return_v8.features import FIELDS,ranks,penalties
from ranking_research.return_v8.engine import scores


def registry():
    contract=json.loads((ROOT/'ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json').read_text(encoding='utf-8-sig'))
    base=next(x['weights'] for x in contract['methods'] if x['method_id']=='P1')
    out=[dict(id='REFERENCE_P1',kind='reference')]
    for i,w in enumerate(base):
        if w:
            a=base.copy();a[i]=0
            out.append(dict(id='DROP_'+FIELDS[i],kind='source',weights=a,dq=True,penalties=True))
    out += [dict(id='DQ_OFF',kind='source',weights=base,dq=False,penalties=True),
            dict(id='PENALTIES_OFF',kind='source',weights=base,dq=True,penalties=False)]
    for value in [10,20,30]:
        a=np.array(base)*((100-value)/100);a[[12,13,14]]=value*np.array([.65,.25,.1])
        out.append(dict(id=f'VALUE_{value}',kind='source',weights=a.tolist(),dq=True,penalties=True))
    for label,ix,factor in [('GROWTH',list(range(5)),2),('PROFIT',list(range(5,12)),2),
                           ('SALES_SHORT',[1],3),('STABILITY',[16],3),('MOMENTUM',[20],10)]:
        a=np.array(base);a[ix]*=factor
        out.append(dict(id='BOOST_'+label,kind='source',weights=a.tolist(),dq=True,penalties=True))
    blocks=['growth','profitability','valuation','balance','momentum','risk','acceleration','p1']
    for i,name in enumerate(blocks):
        w=np.zeros(8);w[i]=1
        out.append(dict(id='BLOCK_'+name,kind='blocks',weights=w.tolist()))
    for alpha in [.1,.25,.5,.75]:
        for other in ['momentum','acceleration','valuation']:
            w=np.zeros(8);w[7]=1-alpha;w[blocks.index(other)]=alpha
            out.append(dict(id=f'P1_BLEND_{other}_{alpha:g}',kind='blocks',weights=w.tolist()))
    rng=np.random.default_rng(20261106)
    for k,w in enumerate(rng.dirichlet(np.ones(8)*.7,size=128)):
        out.append(dict(id=f'GROUP_WEIGHT_{k:03}',kind='blocks',weights=w.tolist()))
    for horizon in [63,126]:
        for mask in ['all','fundamental','market','no_value']:
            for alpha in [10.,100.,1000.]:
                out.append(dict(id=f'RIDGE_h{horizon}_{mask}_a{alpha:g}',kind='learned',
                                model='ridge',horizon=horizon,mask=mask,alpha=alpha))
        for mask in ['all','fundamental']:
            for alpha in [.001,.01]:
                out.append(dict(id=f'ELASTIC_h{horizon}_{mask}_a{alpha:g}',kind='learned',
                                model='elastic',horizon=horizon,mask=mask,alpha=alpha))
        for leaves in [7,15]:
            out.append(dict(id=f'TREES_h{horizon}_leaves{leaves}',kind='learned',
                            model='trees',horizon=horizon,mask='all',leaves=leaves))
    assert len({x['id'] for x in out})==len(out)
    return out


def policies():
    out=[]
    for n in [5,7]:
        for d in [35,40,45]:
            for style,buffer in [('equal',1.),('band',1.6)]:
                out.append(Config(f'n{n}_d{d}_{style}',n=n,offset=d,rebalance=style,buffer=buffer))
    out += [Config('n5_sessions63_band',n=5,schedule='sessions63',buffer=1.6,rebalance='band'),
            Config('n5_monthly_band',n=5,schedule='monthly',buffer=1.6,rebalance='band')]
    return out


def source_tensor(feat):
    rows=feat['sample_rows'];x=feat['raw'][rows].astype(float)
    observed=np.isfinite(x)
    for j,limit in [(12,60),(13,100),(14,30)]:observed[:,:,j]&=(x[:,:,j]>0)&(x[:,:,j]<=limit)
    return {'rank':np.stack([ranks(z) for z in x]),'observed':observed,
            'penalty':np.stack([penalties(z,n) for z,n in zip(x,feat['net'][rows])]),'dq':feat['dq'][rows]}


def feature_mask(feat,name):
    groups=feat['groups'];names=feat['names']
    if name=='all':return np.arange(len(names))
    technical=['avg_trade_value_30d','volatility_30d','price_momentum_30d']
    if name=='fundamental':
        excludes=technical+['missing_'+n for n in technical]
        return np.flatnonzero(np.isin(groups,['fundamental','derived','quality','missing'])&~np.isin(names,excludes))
    if name=='market':return np.flatnonzero((groups=='market')|np.isin(names,technical))
    if name=='no_value':return np.flatnonzero(~np.isin(names,['pe','ps','pb','missing_pe','missing_ps','missing_pb']))
    raise ValueError(name)


def training_frame(data,feat,horizon,mask,cutoff):
    rows=eligible_training_rows(data,feat[f'label_end{horizon}'],cutoff,feat['sample_rows'])
    y=feat[f'y{horizon}'][rows]
    valid=np.isfinite(y)&feat['allowed'][rows]&(data['mark_age'][rows]<=10)
    date_counts=np.maximum(valid.sum(axis=1),1)
    weights=np.broadcast_to((1/date_counts)[:,None],valid.shape)[valid]
    if len(weights):weights/=weights.mean()
    X=feat['X'][rows][:,:,mask][valid]
    labels=y[valid]
    assert (feat[f'label_end{horizon}'][rows]<=cutoff).all()
    return X,labels,weights,rows


def build_scores(spec,data,feat,tensor):
    if spec['kind']=='reference':return data['p1'].copy(),[]
    if spec['kind']=='blocks':
        value=feat['blocks']@np.array(spec['weights'])
        value[~feat['allowed']]=np.nan
        return value.astype(np.float32),[]
    if spec['kind']=='source':
        w=np.array(spec['weights']);w=w/w.sum()*100
        cfg=dict(weights=w,vol_direction='lower',missing='defaults',penalties=spec['penalties'],dq=spec['dq'])
        val=scores(tensor,cfg)
        fin=[i for i in range(21) if i not in [15,19,20]]
        coverage=(tensor['observed'][:,:,fin]@w[fin])/w[fin].sum()
        val[coverage<.5]=np.nan
        ix=np.searchsorted(feat['sample_rows'],np.arange(len(data['cal'])),side='right')-1
        daily=val[ix];daily[~feat['allowed']]=np.nan
        return daily.astype(np.float32),[]
    result=np.full(data['p1'].shape,np.nan,dtype=np.float32);audits=[]
    # Fixed expanding schedule. Future labels never enter a historical fit.
    starts=['2022-01-01','2022-07-01','2023-01-01','2023-07-01','2024-01-01',
            '2024-07-01','2025-01-01','2025-07-01','2026-01-01']
    mask=feature_mask(feat,spec['mask'])
    for k,start in enumerate(starts):
        a=int(np.searchsorted(data['cal'],start))
        b=int(np.searchsorted(data['cal'],starts[k+1])) if k+1<len(starts) else len(data['cal'])
        cutoff=a-1
        X,y,sw,rows=training_frame(data,feat,spec['horizon'],mask,cutoff)
        audit=dict(model=spec['id'],prediction_start=str(data['cal'][a]),fit_cutoff=str(data['cal'][cutoff]),
                   samples=len(y),sample_dates=len(rows),max_label_end=None,fallback=False)
        if len(rows):audit['max_label_end']=str(data['cal'][feat[f'label_end{spec["horizon"]}'][rows].max()])
        if len(y)<500 or len(rows)<5:
            result[a:b]=data['p1'][a:b];audit['fallback']=True;audits.append(audit);continue
        if spec['model']=='ridge':model=Ridge(alpha=spec['alpha'],solver='cholesky')
        elif spec['model']=='elastic':model=ElasticNet(alpha=spec['alpha'],l1_ratio=.5,max_iter=3000,tol=1e-5,selection='cyclic')
        else:model=HistGradientBoostingRegressor(max_leaf_nodes=spec['leaves'],max_iter=80,
                    learning_rate=.05,min_samples_leaf=100,l2_regularization=10,early_stopping=False,random_state=20261106)
        with threadpool_limits(limits=4):
            model.fit(X,y,sample_weight=sw)
            pred=model.predict(feat['X'][a:b][:,:,mask].reshape(-1,len(mask))).reshape(b-a,-1)
        pred[~feat['allowed'][a:b]]=np.nan
        result[a:b]=pred
        if hasattr(model,'coef_'):
            audit['coefficients']={str(n):float(v) for n,v in zip(feat['names'][mask],model.coef_)}
        audits.append(audit)
    return result,audits
