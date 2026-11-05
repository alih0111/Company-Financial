"""V11 repaired stateful engine and PIT panel contract."""
from __future__ import annotations
import hashlib, json, pickle, os
from pathlib import Path
from itertools import product
import numpy as np
import pandas as pd
from ranking_research.return_v8.features import FIELDS, WEIGHTS, GROUPS, ranks, penalties, NEUTRAL
from ranking_research.return_v8.engine import scores as v8_scores
from ranking_research.return_v10.fast import simulate_fast_v10

ROOT=Path(__file__).resolve().parents[2]
V9=ROOT/'ranking_research/output/return_v9/v9_20261017T120500Z'
V10=ROOT/'ranking_research/output/return_v10/v10_20261018T090000Z'
OUT=ROOT/'ranking_research/output/return_v11'/os.environ.get('RETURN_V11_RUN_ID','v11_20261018T120000Z')
SEED=20261018
POLICY=dict(n=10,cadence=10,exit_mult=1,allocation='equal',anchor=0)

def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def calendar_month_metrics(months):
 """Independent, contiguous requirements: 24m YoY, 6m sequential, 12m stability."""
 if not months:return (np.nan,np.nan,np.nan)
 last=max(pd.Period(k,freq='M') for k in months)
 def tail(n):
  ks=[str(last-i) for i in range(n-1,-1,-1)]
  return np.asarray([float(months[k]) for k in ks],float) if all(k in months for k in ks) else None
 vals=[np.nan,np.nan,np.nan]
 a24=tail(24)
 if a24 is not None:
  den=float(a24[:12].sum()); vals[0]=(float(a24[12:].sum())-den)/abs(den)*100 if abs(den)>0 else np.nan
 a6=tail(6)
 if a6 is not None:
  den=float(a6[:3].sum()); vals[1]=(float(a6[3:].sum())-den)/abs(den)*100 if abs(den)>0 else np.nan
 a12=tail(12)
 if a12 is not None:
  mean=float(a12.mean()); vals[2]=1-float(a12.std(ddof=1))/abs(mean) if abs(mean)>0 else np.nan
 return tuple(vals)

def admit_asof_month_version(months,period,value,entry_date,cutoff):
 """Apply one event version only after its publication/signal-entry date is known."""
 if pd.Timestamp(entry_date).date()<=pd.Timestamp(cutoff).date():months[str(pd.Period(period,freq='M'))]=float(value)

def score(t,c):
 """Shared scorer. No caching: values depend on every score-affecting choice."""
 return v8_scores(t,c)

def evaluate_stateless(t,c,a,b):
 values=score(t,c)
 if c.get('allocation')=='hold': return simulate_v10(t,c,values,a,b)[0]
 return simulate_fast_v10(t,c,values,a,b)

def replay_stateful(t,c,a,b,state=None,detail=False):
 values=score(t,c)
 return simulate_v10(t,c,values,a,b,detail=detail,state=state)

def replay(t,c,a,b,detail=False,state=None):
 """Compatibility wrapper that always preserves state on the stateful path."""
 if state is None and not detail:return evaluate_stateless(t,c,a,b)
 return replay_stateful(t,c,a,b,state=state,detail=detail)

def simulate_v10(t,c,values,start,end=None,state=None,detail=False,fee=.005):
 """Order-aware accounting. Residual orders persist until filled or explicitly replaced."""
 end=len(t['cal']) if end is None else end;S=len(t['syms'])
 cash=100_000_000. if state is None else float(state['cash']);q=np.zeros(S) if state is None else state['q'].copy()
 target=np.zeros(S) if state is None else state.get('target',np.zeros(S)).copy()
 target_q=np.zeros(S) if state is None else state.get('target_q',np.zeros(S)).copy()
 pending=np.zeros(S,bool) if state is None else state.get('pending',np.zeros(S,bool)).copy()
 mode=None if state is None else state.get('pending_mode');decision=None if state is None else state.get('decision');owner=None if state is None else state.get('model_id');dranks=None if state is None else state.get('ranks')
 order_ids=list(state.get('order_ids',[None]*S)) if state is not None else [None]*S;order_models=list(state.get('order_models',[None]*S)) if state is not None else [None]*S
 lookup={d:i for i,d in enumerate(t['dates'])};equity=[];trades=[];decisions=[];orders=[];cost=0.;peak=cash+q@t['close'][start];maxdd=0.;anchor=c.get('anchor',0);model_id=config_id(c)
 for i in range(start,end):
  day=t['cal'][i];op=t['open'][i];available=np.isfinite(op)&(op>0)
  if mode and pending.any():
   pending_before=pending.copy()
   mark=t['close'][max(i-1,0)].copy();mark[available]=op[available];nav=max(cash+q@mark,1e-12)
   if mode=='hold_units':
    for j in np.flatnonzero(pending&available&(target_q<q-1e-8)):
     units=min(q[j],q[j]-target_q[j]);gross=units*op[j];q[j]-=units;cash+=gross*(1-fee);cost+=gross*fee
     if detail:
      trades.append(dict(date=day,decision_time=decision,model_id=order_models[j] or owner,order_id=order_ids[j],symbol=t['syms'][j],side='sell',index_units=units,index_price_toman=op[j],gross_toman=gross,fee_toman=gross*fee,rank=int(dranks[j]),reason='rank_exit',target_weight=0.))
      orders.append(dict(order_id=order_ids[j],event_type='fill',event_date=day,symbol=t['syms'][j],side='sell',decision_model_id=order_models[j] or owner,execution_model_id=model_id,filled_units=units,index_price_toman=op[j],fee_toman=gross*fee))
    need=np.where(pending&available,np.maximum(target_q-q,0)*op,0.);total=float(need.sum());fraction=min(1.,max(cash,0.)/(1+fee)/total) if total else 0.
    for j in np.flatnonzero(need>1e-7):
     gross=need[j]*fraction
     if gross<=1e-7:continue
     units=gross/op[j];q[j]+=units;cash-=gross*(1+fee);cost+=gross*fee
     if detail:
      trades.append(dict(date=day,decision_time=decision,model_id=order_models[j] or owner,order_id=order_ids[j],symbol=t['syms'][j],side='buy',index_units=units,index_price_toman=op[j],gross_toman=gross,fee_toman=gross*fee,rank=int(dranks[j]),reason='replacement_entry',target_weight=None))
      orders.append(dict(order_id=order_ids[j],event_type='fill',event_date=day,symbol=t['syms'][j],side='buy',decision_model_id=order_models[j] or owner,execution_model_id=model_id,filled_units=units,index_price_toman=op[j],fee_toman=gross*fee))
    residual=np.abs(target_q-q)>1e-7;remaining_sell=bool(np.any(pending&(q>target_q+1e-7)));keep_buys=cash>1e-4 or remaining_sell
    for j in range(S):pending[j]=pending[j] and residual[j] and (q[j]>target_q[j]+1e-7 or keep_buys)
   else:
    desired=target*nav;current=q*mark;sells=np.where(pending&available,np.maximum(current-desired,0),0.)
    for j in np.flatnonzero(sells>1e-7):
     units=min(q[j],sells[j]/op[j]);gross=units*op[j];q[j]-=units;cash+=gross*(1-fee);cost+=gross*fee
     if detail:
      trades.append(dict(date=day,decision_time=decision,model_id=order_models[j] or owner,order_id=order_ids[j],symbol=t['syms'][j],side='sell',index_units=units,index_price_toman=op[j],gross_toman=gross,fee_toman=gross*fee,rank=int(dranks[j]),reason='rank_exit' if target[j]<=0 else 'rebalance',target_weight=float(target[j])))
      orders.append(dict(order_id=order_ids[j],event_type='fill',event_date=day,symbol=t['syms'][j],side='sell',decision_model_id=order_models[j] or owner,execution_model_id=model_id,filled_units=units,index_price_toman=op[j],fee_toman=gross*fee))
    need=np.where(pending&available,np.maximum(desired-q*op,0),0.);total=float(need.sum());fraction=min(1.,max(cash,0.)/(1+fee)/total) if total else 0.
    for j in np.flatnonzero(need>1e-7):
     gross=need[j]*fraction
     if gross<=1e-7:continue
     units=gross/op[j];q[j]+=units;cash-=gross*(1+fee);cost+=gross*fee
     if detail:
      trades.append(dict(date=day,decision_time=decision,model_id=order_models[j] or owner,order_id=order_ids[j],symbol=t['syms'][j],side='buy',index_units=units,index_price_toman=op[j],gross_toman=gross,fee_toman=gross*fee,rank=int(dranks[j]),reason='rank_entry_or_rebalance',target_weight=float(target[j])))
      orders.append(dict(order_id=order_ids[j],event_type='fill',event_date=day,symbol=t['syms'][j],side='buy',decision_model_id=order_models[j] or owner,execution_model_id=model_id,filled_units=units,index_price_toman=op[j],fee_toman=gross*fee))
    residual=np.abs(target*nav-q*mark)>1e-7;remaining_sell=bool(np.any(pending&(q*mark>target*nav+1e-7)));keep_buys=cash>1e-4 or remaining_sell
    for j in range(S):pending[j]=pending[j] and residual[j] and (q[j]*mark[j]>target[j]*nav+1e-7 or keep_buys)
   if detail:
    for j in np.flatnonzero(pending_before & (np.array([x is not None for x in order_ids]))):
     oid=order_ids[j];remaining=float(abs(target_q[j]-q[j])) if mode=='hold_units' else float(abs(target[j]*nav-q[j]*mark[j]))/max(mark[j],1e-12)
     status='residual' if pending[j] else 'completed'
     orders.append(dict(order_id=oid,event_type=status,event_date=day,symbol=t['syms'][j],side='buy_or_sell',decision_model_id=order_models[j],execution_model_id=model_id,remaining_units=remaining))
     if not pending[j]:order_ids[j]=None;order_models[j]=None
   if cash < -1e-4:raise AssertionError('Unfunded V10 order created negative cash')
  nav=float(cash+q@t['close'][i]);peak=max(peak,nav);maxdd=min(maxdd,nav/peak-1.)
  if detail:equity.append(dict(date=day,nav_toman=nav,cash_toman=cash,positions=int((q>1e-8).sum()),holdings=';'.join(t['syms'][j] for j in np.flatnonzero(q>1e-8))))
  if (i-anchor)%c['cadence']==0 and day in lookup:
   d=lookup[day];vals=values[d].copy();valid=np.isfinite(vals)&(t['close'][i]>0);order=np.lexsort((np.arange(S),-np.where(valid,vals,-np.inf)));dranks=np.empty(S,int);dranks[order]=np.arange(1,S+1)
   retained=[j for j in order if valid[j] and q[j]>1e-8 and dranks[j]<=c['n']*c['exit_mult']][:c['n']]
   chosen=list(retained)+[j for j in order if valid[j] and j not in retained][:max(0,c['n']-len(retained))]
   old_ids=order_ids.copy();old_pending=pending.copy();old_mode=mode;old_target=target.copy();old_target_q=target_q.copy()
   if c['allocation']=='hold':
    target_q=q.copy();keep=np.zeros(S,bool);keep[retained]=True;target_q[~keep]=0.
    exits=[j for j in range(S) if q[j]>1e-8 and not keep[j]];entrants=[j for j in chosen if q[j]<=1e-8]
    mark=t['close'][i];budget=max(0.,cash+sum(q[j]*mark[j]*(1-fee) for j in exits));each=budget/max(1+fee,1e-9)/len(entrants) if entrants else 0.
    for j in entrants:target_q[j]=each/max(mark[j],1e-12)
    pending=np.abs(target_q-q)>1e-7;mode='hold_units'
   else:
    target=np.zeros(S)
    if chosen:
     ww=np.maximum(vals[chosen],0) if c['allocation']=='score' else np.ones(len(chosen))
     if ww.sum()<=0:ww=np.ones(len(chosen))
     target[chosen]=ww/ww.sum()
    pending=(q>1e-8)|(target>0);mode='weights';target_q=np.zeros(S)
   decision=day;owner=model_id;dranks=dranks
   if detail:
    for j,oid in enumerate(old_ids):
     if oid is not None and old_pending[j]:
      orders.append(dict(order_id=oid,event_type='replaced' if pending[j] else 'canceled',event_date=day,symbol=t['syms'][j],side='buy_or_sell',decision_model_id=order_models[j],execution_model_id=model_id,remaining_units=None))
      order_ids[j]=None;order_models[j]=None
    for j in range(S):
     if not pending[j]:continue
     closemark=max(float(t['close'][i,j]),1e-12)
     delta=float(target_q[j]-q[j]) if mode=='hold_units' else float((target[j]*(cash+q@t['close'][i])-q[j]*closemark)/closemark)
     if abs(delta)<=1e-7:continue
     oid=f'{day}|{model_id}|{t["syms"][j]}'
     order_ids[j]=oid;order_models[j]=model_id
     orders.append(dict(order_id=oid,event_type='created',event_date=day,symbol=t['syms'][j],side='buy' if delta>0 else 'sell',decision_model_id=model_id,execution_model_id=model_id,target_units=float(abs(delta)),remaining_units=float(abs(delta))))
   if detail:decisions.extend(dict(date=day,symbol=t['syms'][j],rank=int(dranks[j]),score=float(vals[j]),target_weight=float(target[j]) if mode=='weights' else None,model_id=model_id) for j in chosen)
 result=dict(final_toman=float(cash+q@t['close'][end-1]),cost_toman=float(cost),max_drawdown=float(-maxdd),initial_toman=100_000_000.,start=t['cal'][start],end=t['cal'][end-1],cash_toman=float(cash))
 newstate=dict(cash=cash,q=q,target=target,target_q=target_q,pending=pending,pending_mode=mode,decision=decision,model_id=owner,ranks=dranks,order_ids=order_ids,order_models=order_models)
 if detail:
  for j,oid in enumerate(order_ids):
   if oid is not None and pending[j]:
    if mode=='hold_units':remaining=float(abs(target_q[j]-q[j]))
    else:
     mark=float(t['close'][end-1,j]);navend=float(cash+q@t['close'][end-1]);remaining=float(abs(target[j]*navend-q[j]*mark)/max(mark,1e-12))
    orders.append(dict(order_id=oid,event_type='open_at_block_end',event_date=t['cal'][end-1],symbol=t['syms'][j],side='buy_or_sell',decision_model_id=order_models[j],execution_model_id=model_id,remaining_units=remaining))
 return result,newstate,dict(equity=equity,trades=trades,decisions=decisions,orders=orders)

def monthly_v10():
 """Strict calendar-month growth from numerically present, provable original events."""
 ev=pd.read_parquet(ROOT/'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet')
 ev['company_id']=ev.company_id.astype(str);ev['period_end']=pd.to_datetime(ev.period_end,errors='coerce')
 ev['signal_entry_date']=pd.to_datetime(ev.signal_entry_date,errors='coerce')
 ev=ev[(~ev.is_correction.fillna(False))&ev.current_value_version_known.fillna(False)&ev.CURRENT_PERIOD_SALES.notna()&ev.signal_entry_date.notna()].copy()
 # If the period is flagged as corrected anywhere, the original value is not a valid V10 fact.
 allv=pd.read_parquet(ROOT/'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet',columns=['company_id','period_end','is_correction'])
 corr=set(zip(allv.loc[allv.is_correction.fillna(False),'company_id'].astype(str),pd.to_datetime(allv.loc[allv.is_correction.fillna(False),'period_end'],errors='coerce').dt.to_period('M')))
 ev['month']=ev.period_end.dt.to_period('M')
 ev=ev[~pd.Series(list(zip(ev.company_id,ev.month)),index=ev.index).isin(corr)]
 # Retain versions and apply them in knowledge-time order inside each as-of snapshot.
 ev=ev.sort_values(['company_id','signal_entry_date','published_at','event_id'])
 feat=pd.read_parquet(V9/'monthly_sales_features_v9.parquet',columns=['decision_time','symbol','company_id'])
 days=sorted(feat.decision_time.astype(str).unique()); symbols=feat[['symbol','company_id']].drop_duplicates()
 if symbols.symbol.duplicated().any():raise ValueError('Ambiguous ticker to company mapping')
 by={cid:g.sort_values('month') for cid,g in ev.groupby('company_id')};rows=[]
 for row in symbols.itertuples(index=False):
  g=by.get(str(row.company_id),ev.iloc[:0]);entries=list(g.itertuples(index=False));months={};cursor=0
  for day in days:
   while cursor<len(entries) and entries[cursor].signal_entry_date.strftime('%Y-%m-%d')<=day:
    x=entries[cursor];admit_asof_month_version(months,x.month,x.CURRENT_PERIOD_SALES,x.signal_entry_date,day);cursor+=1
   mkeys=sorted(months);vals=calendar_month_metrics(months)
   rows.append(dict(decision_time=day,symbol=row.symbol,sales_growth_12m=vals[0],sales_growth_3m=vals[1],sales_stability=vals[2],known_calendar_months=len(months),latest_period=str(max(months)) if months else None))
 return pd.DataFrame(rows)

def make_v10_tensor(monthly):
 t=pickle.load(open(V9/'tensors_v9.pkl','rb'));t={k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in t.items()}
 m=monthly.set_index(['decision_time','symbol']).reindex(pd.MultiIndex.from_product([t['dates'],t['syms']]))
 raw=t['raw'];raw[:,:,0]=m.sales_growth_12m.to_numpy(float).reshape(raw.shape[:2]);raw[:,:,1]=m.sales_growth_3m.to_numpy(float).reshape(raw.shape[:2]);raw[:,:,16]=m.sales_stability.to_numpy(float).reshape(raw.shape[:2])
 t['rank']=np.stack([ranks(x) for x in raw]);t['observed']=np.isfinite(raw)
 for j,limit in [(12,60),(13,100),(14,30)]:t['observed'][:,:,j]&=(raw[:,:,j]>0)&(raw[:,:,j]<=limit)
 return t

def cfg(weights,**over):
 c=dict(weights=list(map(float,weights)),missing='defaults',penalties=True,dq=True,vol_direction='lower',**POLICY);c.update(over);return c

def config_id(c):return hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

def validate_config(c):
 if any(type(c[k]) is not int for k in ['n','cadence','exit_mult']):raise TypeError('n, cadence and exit_mult must be integers')
 if any(type(c[k]) is not bool for k in ['penalties','dq']):raise TypeError('penalties and dq must be booleans')
 if len(c['weights'])!=21 or not np.isclose(sum(c['weights']),100) or c['weights'][15]!=0:raise ValueError('Invalid normalized V10 weights')

def candidates(t,a,b):
 rng=np.random.default_rng(SEED);tested=np.flatnonzero(t['observed'].any(axis=(0,1)));tested=tested[tested!=15]
 base=WEIGHTS.copy();base[15]=0;base=base/base.sum()*100
 seen={};configs=[];phase_ids={'weight':[],'trade':[],'joint':[]}
 def add(c,stage):
  k=config_id(c)
  if k not in seen:seen[k]=stage;configs.append(c)
  if k not in phase_ids[stage]:phase_ids[stage].append(k);return True
  return False
 fixed=cfg(base)
 add(fixed,'weight')
 for j in tested:
  w=np.zeros(21);w[j]=100;add(cfg(w),'weight')
 attempts=0
 while len(configs)<500 and attempts<10000:
  attempts+=1;subset=rng.choice(tested,size=int(rng.integers(1,len(tested)+1)),replace=False);v=rng.dirichlet(np.ones(len(subset))*.55)*100
  w=np.zeros(21);w[subset]=np.floor(v);left=100-int(w.sum())
  if left:w[subset[np.argsort(-(v-np.floor(v)))[:left]]]+=1
  add(cfg(w),'weight')
 # All 150 trade policies: N*cadence*exit*allocation.
 for n in [1,3,5,10,20]:
  for cadence in [5,10,21,63,126]:
   for ex in [1,2]:
    for al in ['equal','score','hold']:add(cfg(base,n=n,cadence=cadence,exit_mult=ex,allocation=al),'trade')
 # Pair-balanced randomized common settings. The full cross-product is never truncated.
 opts={'missing':['defaults','available'],'penalties':[False,True],'dq':[False,True],'vol_direction':['lower','higher']}
 joint_options=list(product(opts['missing'],opts['penalties'],opts['dq'],opts['vol_direction']))
 i=0;tries=0
 while len(phase_ids['joint'])<600 and tries<12000:
  tries+=1
  w=np.zeros(21)
  if i%4==0:w[tested]=base[tested]
  elif i%4==1:w[int(rng.choice(tested))]=100
  else:
   sub=rng.choice(tested,size=int(rng.integers(1,len(tested)+1)),replace=False);z=rng.dirichlet(np.ones(len(sub))*.7)*100;w[sub]=np.floor(z);left=100-int(w.sum());w[sub[np.argsort(-(z-np.floor(z)))[:left]]]+=1
  c=cfg(w)
  # Every one of the 16 combinations is cycled evenly, ensuring balanced pairs.
  for (k,_),v in zip(opts.items(),joint_options[i%len(joint_options)]):c[k]=v
  add(c,'joint')
  i+=1
 # Top-20 neighbors, unique and capped. Fill from registered candidates if collisions occur.
 return configs,seen,tested,phase_ids

def evaluate_search(t,label,a,b):
 folder=OUT/'searches'/label;folder.mkdir(parents=True,exist_ok=True)
 cs,stages,tested,phase_ids=candidates(t,a,b)
 for c in cs:validate_config(c)
 registration={'seed':SEED,'window':[t['cal'][a],t['cal'][b-1]],'objective':'max final net wealth','budget':1500,'planned_stage_count':{x:len(v) for x,v in phase_ids.items()},'unique_evaluations_initial':len(cs),'tested_factors':[FIELDS[i] for i in tested],'configs_sha256':hashlib.sha256(json.dumps(cs,sort_keys=True).encode()).hexdigest()}
 rp=folder/'registration.json'
 if rp.exists() and json.loads(rp.read_text(encoding='utf8'))!=registration:raise RuntimeError('Existing checkpoint registration differs: '+label)
 if not rp.exists():rp.write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf8')
 candidate_file=folder/'candidate_configs.json'
 candidate_payload={'stage_ids':phase_ids,'configs':cs,'generated_before_training_outcomes':True,'adaptive_neighbors':'generated later from top twenty training-only starts'}
 if candidate_file.exists() and candidate_file.read_text(encoding='utf8')!=json.dumps(candidate_payload,ensure_ascii=False,indent=2):raise RuntimeError('Candidate registry differs from checkpoint')
 if not candidate_file.exists():candidate_file.write_text(json.dumps(candidate_payload,ensure_ascii=False,indent=2),encoding='utf8')
 config_byid={config_id(c):c for c in cs};coverage=[]
 dimensions={'trade':['n','cadence','exit_mult','allocation'],'joint':['missing','penalties','dq','vol_direction']}
 for phase,fields in dimensions.items():
  entries=[config_byid[k] for k in phase_ids[phase] if k in config_byid]
  for field in fields:
   counts=pd.Series([str(c[field]) for c in entries]).value_counts().to_dict()
   for value,count in sorted(counts.items()):coverage.append({'stage':phase,'dimension':field,'value':value,'count':count,'stage_candidates':len(entries)})
  if phase=='joint':
   for i,f1 in enumerate(fields):
    for f2 in fields[i+1:]:
     pairs=pd.Series([str(c[f1])+' | '+str(c[f2]) for c in entries]).value_counts().to_dict()
     for value,count in sorted(pairs.items()):coverage.append({'stage':phase,'dimension':f1+' x '+f2,'value':value,'count':count,'stage_candidates':len(entries)})
 pd.DataFrame(coverage).to_csv(folder/'search_coverage.csv',index=False,encoding='utf-8-sig')
 # Fill 250 unique local candidates around top-20 without consuming slots on duplicates.
 attempts=0
 records=[];record_byid={};log=folder/'experiments.jsonl'
 if log.exists():
  for line in log.read_text(encoding='utf8').splitlines():
   if line.strip():
    item=json.loads(line);record_byid[item['id']]=item
 records=list(record_byid.values());scorecache={};pathcache={}
 for idx,c in enumerate(cs):
  key=config_id(c)
  if key in record_byid:continue
  sk=json.dumps({k:c[k] for k in ['weights','missing','penalties','dq','vol_direction']},sort_keys=True);values=scorecache.get(sk)
  if values is None:values=score(t,c);scorecache[sk]=values
  valid=np.isfinite(values);sig=hashlib.sha256(np.nan_to_num(values,nan=-1e99).tobytes()+valid.tobytes()+json.dumps({k:c[k] for k in ['n','cadence','exit_mult','allocation','anchor']},sort_keys=True).encode()).hexdigest()
  if sig not in pathcache:pathcache[sig]=simulate_v10(t,c,values,a,b)[0] if c.get('allocation')=='hold' else simulate_fast_v10(t,c,values,a,b)
  r=pathcache[sig];item={'id':key,'stage':stages[key],'config':c,**r};records.append(item);record_byid[key]=item
  with log.open('a',encoding='utf8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
  if idx==len(cs)-1:
   top=sorted([x for x in records if x['stage']!='neighbor'],key=lambda x:(-x['final_toman'],x['id']))[:20];rng=np.random.default_rng(SEED+1);local_seen=set(stages)|set(record_byid)
   while len(records)<1500 and attempts<30000:
    attempts+=1;parent=top[(attempts-1)%20];c=json.loads(json.dumps(parent['config']))
    if attempts%2:
     aa,bb=rng.choice(tested,2,replace=False);amount=int(rng.choice([1,2,5,10]))
     if c['weights'][aa]<amount:
      donors=[j for j in tested if c['weights'][j]>=amount]
      if not donors:continue
      aa=int(rng.choice(donors))
     c['weights'][aa]-=amount;c['weights'][bb]+=amount
    else:
     k=str(rng.choice(['missing','penalties','dq','vol_direction','n','cadence','exit_mult','allocation']))
     opts={'missing':['defaults','available'],'penalties':[False,True],'dq':[False,True],'vol_direction':['lower','higher'],'n':[1,3,5,10,20],'cadence':[5,10,21,63,126],'exit_mult':[1,2],'allocation':['equal','score','hold']}
     c[k]=rng.choice([x for x in opts[k] if x!=c[k]]).item() if k in ['n','cadence','exit_mult','penalties','dq'] else str(rng.choice([x for x in opts[k] if x!=c[k]]))
     if k in ['penalties','dq']:c[k]=bool(c[k])
    key=config_id(c)
    validate_config(c)
    if key in local_seen:continue
    local_seen.add(key);sk=json.dumps({k:c[k] for k in ['weights','missing','penalties','dq','vol_direction']},sort_keys=True);values=scorecache.get(sk)
    if values is None:values=score(t,c);scorecache[sk]=values
    valid=np.isfinite(values);sig=hashlib.sha256(np.nan_to_num(values,nan=-1e99).tobytes()+valid.tobytes()+json.dumps({k:c[k] for k in ['n','cadence','exit_mult','allocation','anchor']},sort_keys=True).encode()).hexdigest()
    if sig not in pathcache:pathcache[sig]=simulate_v10(t,c,values,a,b)[0] if c.get('allocation')=='hold' else simulate_fast_v10(t,c,values,a,b)
    item={'id':key,'stage':'neighbor','config':c,**pathcache[sig]};records.append(item);record_byid[key]=item
    with log.open('a',encoding='utf8') as f:f.write(json.dumps(item,ensure_ascii=False)+'\n')
   break
 pd.DataFrame([{k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()} for row in records]).to_csv(folder/'experiments.csv',index=False,encoding='utf-8-sig')
 best=sorted(records,key=lambda x:(-x['final_toman'],x['id']))[0]
 (folder/'best.json').write_text(json.dumps(best,ensure_ascii=False,indent=2),encoding='utf8')
 (folder/'timing.json').write_text(json.dumps({'distinct_evaluated':len(records),'errors':0,'checkpoint_resumable':True,'planned_unique_candidate_count':len(cs),'candidate_generation_attempt_limit':20*1500},ensure_ascii=False,indent=2),encoding='utf8')
 return best,records
