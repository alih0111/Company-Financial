"""Numba replay for equal/score allocation with persistent, explicitly funded orders."""
import numpy as np
from numba import njit

@njit(cache=True)
def replay(close,opening,values,orders,decision_indices,start,end,n,cadence,exitmult,by_score,anchor,fee):
 s=close.shape[1];cash=100000000.;q=np.zeros(s);target=np.zeros(s);pending=np.zeros(s,np.bool_);cost=0.;peak=cash;dd=0.;nav=cash
 for i in range(start,end):
  op=opening[i];available=np.isfinite(op)&(op>0);marks=np.empty(s);nav_open=cash
  for j in range(s):
   marks[j]=close[max(i-1,0),j]
   if available[j]:marks[j]=op[j]
   nav_open+=q[j]*marks[j]
  if pending.any():
   for j in range(s):
    if pending[j] and available[j]:
     desired=target[j]*nav_open;cur=q[j]*marks[j];amount=max(cur-desired,0.)
     if amount>1e-7:
      units=min(q[j],amount/op[j]);gross=units*op[j];q[j]-=units;cash+=gross*(1-fee);cost+=gross*fee
   needs=np.zeros(s);total=0.
   for j in range(s):
    if pending[j] and available[j]:needs[j]=max(target[j]*nav_open-q[j]*op[j],0.);total+=needs[j]
   fraction=min(1.,max(cash,0.)/(1+fee)/total) if total>0 else 0.
   for j in range(s):
    if pending[j] and available[j] and needs[j]>1e-7:
     gross=needs[j]*fraction;units=gross/op[j];q[j]+=units;cash-=gross*(1+fee);cost+=gross*fee
   remaining_sell=False
   for j in range(s):
    if pending[j] and q[j]*marks[j]>target[j]*nav_open+1e-5:remaining_sell=True
   keep_buys=cash>1e-4 or remaining_sell
   for j in range(s):
    residual=abs(target[j]*nav_open-q[j]*marks[j])>1e-5
    is_sell=q[j]*marks[j]>target[j]*nav_open+1e-5
    pending[j]=pending[j] and residual and (is_sell or keep_buys)
  nav=cash
  for j in range(s):nav+=q[j]*close[i,j]
  peak=max(peak,nav);dd=min(dd,nav/peak-1.)
  d=decision_indices[i]
  if (i-anchor)%cadence==0 and d>=0:
   chosen=np.zeros(s,np.bool_);count=0
   for k in range(s):
    j=orders[d,k]
    if np.isfinite(values[d,j]) and close[i,j]>0 and q[j]>1e-8 and k+1<=n*exitmult and count<n:chosen[j]=True;count+=1
   for k in range(s):
    j=orders[d,k]
    if count<n and np.isfinite(values[d,j]) and close[i,j]>0 and not chosen[j]:chosen[j]=True;count+=1
   denom=0.
   for j in range(s):
    target[j]=max(values[d,j],0.) if chosen[j] and by_score else 1. if chosen[j] else 0.;denom+=target[j]
   if denom==0 and count>0:
    for j in range(s):target[j]=1. if chosen[j] else 0.
    denom=count
   if denom>0:
    for j in range(s):target[j]/=denom
   for j in range(s):pending[j]=q[j]>1e-8 or target[j]>0
 return nav,cash,cost,-dd

def simulate_fast_v10(t,c,values,start,end):
 valid=np.isfinite(values);indices=np.array([t['cal'].index(d) for d in t['dates']]);valid&=t['close'][indices]>0
 order=np.argsort(-np.where(valid,values,-np.inf),axis=1,kind='stable');vals=np.where(valid,values,np.nan)
 lookup={d:i for i,d in enumerate(t['dates'])};di=np.array([lookup.get(d,-1) for d in t['cal']],dtype=np.int64)
 nav,cash,cost,dd=replay(t['close'],t['open'],vals,order,di,start,end,c['n'],c['cadence'],c['exit_mult'],c['allocation']=='score',c['anchor'],.005)
 return dict(final_toman=float(nav),cost_toman=float(cost),max_drawdown=float(dd),initial_toman=100000000.,start=t['cal'][start],end=t['cal'][end-1],cash_toman=float(cash))
