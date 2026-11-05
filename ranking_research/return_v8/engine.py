"""Self-financing fractional index-unit replay, no capacity or liquidity gates."""
import numpy as np
import pandas as pd
from .features import FIELDS,WEIGHTS,GROUPS,NEUTRAL,ranks,penalties

def tensors(panel,cal,syms,md):
    dates=sorted(panel.decision_time.unique());D=len(dates);S=len(syms)
    raw=panel.set_index(['decision_time','symbol']).reindex(pd.MultiIndex.from_product([dates,syms]))
    x=raw[FIELDS].to_numpy(float).reshape(D,S,21)
    rank=np.stack([ranks(v) for v in x]);observed=np.isfinite(x)
    for j,limit in [(12,60),(13,100),(14,30)]:observed[:,:,j]&=(x[:,:,j]>0)&(x[:,:,j]<=limit)
    net=pd.to_numeric(raw.net_profit_ttm,errors='coerce').to_numpy().reshape(D,S)
    pen=np.stack([penalties(x[i],net[i]) for i in range(D)])
    dq=raw.dq.to_numpy(float).reshape(D,S)
    s2=raw.s2_raw.to_numpy(float).reshape(D,S)
    close=np.zeros((len(cal),S));opening=np.full_like(close,np.nan);markdate=np.empty(close.shape,dtype=object)
    for j,sym in enumerate(syms):
        r=md.data[sym];good=(r['vol']>0)&(r['tval']>0)&np.isfinite(r['c'])&(r['c']>0)
        ids=np.flatnonzero(good);gd=np.asarray(r['dates'])[ids]
        # Existing V2/V7 event-normalized index. Constant initial scale cancels in returns.
        scale=r['cf']/r['cf'][0]/1000000
        for i,day in enumerate(cal):
            k=np.searchsorted(gd,day,side='right')-1
            if k>=0:close[i,j]=r['c'][ids[k]]*scale[ids[k]]/10;markdate[i,j]=str(gd[k])
            else:markdate[i,j]=None
            z=r['dmap'].get(day)
            if z is not None and good[z] and np.isfinite(r['o'][z]) and r['o'][z]>0:
                opening[i,j]=r['o'][z]*scale[z]/10
    return dict(dates=dates,syms=syms,cal=cal,raw=x,rank=rank,observed=observed,penalty=pen,dq=dq,s2=s2,close=close,open=opening,markdate=markdate)

def scores(t,c):
    if c.get('kind')=='equal':return np.ones(t['rank'].shape[:2])
    if c.get('kind')=='S2':return t['s2'].copy()
    w=np.array(c['weights']);r=t['rank'].copy()
    if c['vol_direction']=='higher':r[:,:,19]=1-r[:,:,19];r[:,:,19][~t['observed'][:,:,19]]=NEUTRAL[19]
    if c['missing']=='available':
        seen=t['observed']@w
        r=np.where(t['observed'],r,0)
        r=r*np.divide(100,seen,out=np.zeros_like(seen),where=seen>0)[:,:,None]
    else:seen=np.full(r.shape[:2],100.)
    value=np.zeros(r.shape[:2])
    for g,ix in enumerate(GROUPS):
        v=r[:,:,ix]@w[ix]
        if c['penalties']:v-=t['penalty'][:,:,g]*(1 if c.get('kind')=='current' else 100/89)
        value+=np.maximum(v,0)
    if c['dq']:value*=t['dq']
    if c.get('kind')=='current':value=np.floor(value*100+.5)/100
    value[seen<50]=np.nan
    return value

def simulate(t,c,start=0,end=None,detail=False,state=None,fee=.005,precomputed=None):
    end=len(t['cal']) if end is None else end;S=len(t['syms']);v=scores(t,c) if precomputed is None else precomputed
    dateix={d:i for i,d in enumerate(t['dates'])}
    cash=100000000. if state is None else float(state['cash']);q=np.zeros(S) if state is None else state['q'].copy()
    target=None if state is None else state.get('target');pending=np.zeros(S,bool) if state is None else state.get('pending',np.zeros(S,bool)).copy();decision=None if state is None else state.get('decision');dranks=None if state is None else state.get('ranks');equity=[];trades=[];decisions=[];peak=cash+q@t['close'][start];dd=0.;cost=0
    anchor=c.get('anchor',start);n=c['n'];cad=c['cadence'];exitmult=c['exit_mult'];allocation=c['allocation']
    for i in range(start,end):
        day=t['cal'][i];op=t['open'][i];ex=np.isfinite(op)&(op>0)
        if target is not None and pending.any():
            active=pending&ex
            # Hold unavailable positions. Invest only available wealth; sell before buy.
            marks=t['close'][max(i-1,0)].copy();marks[ex]=op[ex]
            nav=cash+q@marks
            desired=np.zeros(S)
            desired[active]=target[active]*nav
            current=q*marks
            sells=np.where(active,np.maximum(current-desired,0),0)
            for j in np.flatnonzero(sells>1e-7):
                units=min(q[j],sells[j]/op[j]);gross=units*op[j];q[j]-=units;cash+=gross*(1-fee);cost+=gross*fee
                if detail:trades.append(dict(date=day,decision_time=decision,symbol=t['syms'][j],side='sell',index_units=units,index_price_toman=op[j],raw_open_rial=None,gross_toman=gross,fee_toman=gross*fee,rank=int(dranks[j]),reason='rank_exit' if target[j]==0 else 'rebalance',target_weight=target[j]))
            need=np.where(active,np.maximum(desired-q*marks,0),0)
            total=need.sum();budget=max(cash,0)/(1+fee);fraction=min(1,budget/total) if total>0 else 0
            for j in np.flatnonzero(need>1e-7):
                gross=need[j]*fraction;units=gross/op[j];q[j]+=units;cash-=gross*(1+fee);cost+=gross*fee
                if detail:trades.append(dict(date=day,decision_time=decision,symbol=t['syms'][j],side='buy',index_units=units,index_price_toman=op[j],raw_open_rial=None,gross_toman=gross,fee_toman=gross*fee,rank=int(dranks[j]),reason='rank_entry_or_rebalance',target_weight=target[j]))
            # Orders for traded names completed. Pending halted names retry until next decision.
            pending[active]=False
            assert cash>-1e-4
        nav=cash+q@t['close'][i];peak=max(peak,nav);dd=min(dd,nav/peak-1)
        if detail:equity.append(dict(date=day,nav_toman=nav,cash_toman=cash,positions=int((q>1e-8).sum()),holdings=';'.join(t['syms'][j] for j in np.flatnonzero(q>1e-8))))
        if (i-anchor)%cad==0 and day in dateix:
            vals=v[dateix[day]].copy();valid=np.isfinite(vals)&(t['close'][i]>0)
            order=np.lexsort((np.arange(S),-np.where(valid,vals,-np.inf)))
            dranks=np.empty(S,int);dranks[order]=np.arange(1,S+1)
            chosen=[j for j in order if valid[j] and q[j]>1e-8 and dranks[j]<=n*exitmult][:n]
            chosen += [j for j in order if valid[j] and j not in chosen][:max(0,n-len(chosen))]
            target=np.zeros(S)
            if chosen:
                weights=np.maximum(vals[chosen],0) if allocation=='score' else np.ones(len(chosen))
                if weights.sum()==0:weights=np.ones(len(chosen))
                target[chosen]=weights/weights.sum()
            pending=(q>1e-8)|(target>0);decision=day
            if detail:decisions.extend(dict(date=day,symbol=t['syms'][j],rank=int(dranks[j]),score=float(vals[j]),target_weight=float(target[j])) for j in chosen)
    result=dict(final_toman=float(cash+q@t['close'][end-1]),cost_toman=float(cost),max_drawdown=float(-dd),initial_toman=100000000,start=t['cal'][start],end=t['cal'][end-1],cash_toman=float(cash))
    return result,dict(cash=cash,q=q,target=target,pending=pending,decision=decision,ranks=dranks),dict(equity=equity,trades=trades,decisions=decisions)
