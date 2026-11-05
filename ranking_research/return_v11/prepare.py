"""Build immutable V11 monthly-sales panels P0-P3 from source-backed events."""
from __future__ import annotations
import hashlib,json,pickle
from pathlib import Path
import shutil
import numpy as np,pandas as pd,jdatetime
from ranking_research.return_v11.core import ROOT,V9,V10,OUT,sha,WEIGHTS,cfg,score,simulate_v10
from ranking_research.return_v8.features import FIELDS,ranks,penalties

EVENTS=ROOT/'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet'
V8=ROOT/'ranking_research/output/return_v8/v8_20261016T202437867840Z'

def jalali_key(value):
 d=pd.Timestamp(value).date();j=jdatetime.date.fromgregorian(date=d);return f'{j.year:04d}-{j.month:02d}'

def metric_window(months,n):
 if not months:return None
 y,m=map(int,max(months).split('-'));serial=y*12+m-1
 keys=[]
 for i in range(n-1,-1,-1):
  yy,mm=divmod(serial-i,12);keys.append(f'{yy:04d}-{mm+1:02d}')
 if not all(k in months and months[k] is not None for k in keys):return None
 return np.asarray([months[k] for k in keys],float)

def metrics(months):
 out=[np.nan,np.nan,np.nan]
 a=metric_window(months,24)
 if a is not None:
  den=float(a[:12].sum());out[0]=(float(a[12:].sum())-den)/abs(den)*100 if den else np.nan
 a=metric_window(months,6)
 if a is not None:
  den=float(a[:3].sum());out[1]=(float(a[3:].sum())-den)/abs(den)*100 if den else np.nan
 a=metric_window(months,12)
 if a is not None:
  mean=float(a.mean());out[2]=1-float(a.std(ddof=1))/abs(mean) if mean else np.nan
 return out

def timeline(events,cal,*,jalali=False,keep_corrections=False):
 ev=events.copy();ev['company_id']=ev.company_id.astype(str);ev['period_end']=pd.to_datetime(ev.period_end)
 ev['known_date']=pd.to_datetime(ev.signal_entry_date,errors='coerce')
 # Correction notices have no eligible entry date. Their publication becomes known
 # at the first market session strictly after the Tehran publication date.
 corr=ev.is_correction.fillna(False)
 ev['published_at_utc']=pd.to_datetime(ev.published_at,utc=True,errors='coerce')
 published=ev.published_at_utc.dt.tz_convert('Asia/Tehran').dt.tz_localize(None).dt.normalize()
 ev.loc[corr,'known_date']=published[corr]+pd.Timedelta(days=1)
 ev['known_date']=pd.to_datetime(ev.known_date,errors='coerce')
 ev['period_key']=ev.period_end.map(jalali_key) if jalali else ev.period_end.dt.to_period('M').astype(str)
 ev=ev[ev.known_date.notna()].copy()
 # P1 reproduces the old V10 future-correction exclusion, isolating the window fix.
 if not keep_corrections:
  corrected=set(zip(ev.loc[corr.loc[ev.index] if False else ev.is_correction.fillna(False),'company_id'],ev.loc[ev.is_correction.fillna(False),'period_key']))
  ev=ev[~pd.Series(list(zip(ev.company_id,ev.period_key)),index=ev.index).isin(corrected)]
 # Admit original numeric bodies only when their version is verified. A later
 # correction event with no proven number masks the period from its knowledge date.
 ev=ev.sort_values(['known_date','published_at_utc','event_id'],kind='stable')
 lookup={}
 for r in ev.itertuples(index=False):
  value=getattr(r,'CURRENT_PERIOD_SALES');verified=bool(getattr(r,'current_value_version_known')) if pd.notna(getattr(r,'current_value_version_known')) else False
  iscorr=bool(getattr(r,'is_correction'))
  if iscorr:
   if keep_corrections:
    if verified and pd.notna(value):lookup.setdefault(r.company_id,[]).append((r.known_date,r.period_key,float(value),'verified_correction',str(r.event_id)))
    else:lookup.setdefault(r.company_id,[]).append((r.known_date,r.period_key,None,'correction_value_unverified',str(r.event_id)))
  elif verified and pd.notna(value):lookup.setdefault(r.company_id,[]).append((r.known_date,r.period_key,float(value),'verified_original',str(r.event_id)))
 return lookup

def build_monthly(events,feat,cal,syms,*,jalali=False,keep_corrections=False):
 symbols=feat[['symbol','company_id']].drop_duplicates();
 if symbols.symbol.duplicated().any():raise ValueError('Ambiguous symbol-to-company map')
 timelines=timeline(events,cal,jalali=jalali,keep_corrections=keep_corrections)
 rows=[]
 for sr in symbols.itertuples(index=False):
  ev=timelines.get(str(sr.company_id),[]);ix=0;known={};last_status={}
  for day in cal:
   while ix<len(ev) and str(ev[ix][0])[:10]<=str(day)[:10]:
    _,period,value,reason,event_id=ev[ix];known[period]=value;last_status[period]=(reason,event_id);ix+=1
   vals=metrics(known)
   rows.append({'decision_time':day,'symbol':sr.symbol,'company_id':str(sr.company_id),'sales_growth_12m':vals[0],'sales_growth_3m':vals[1],'sales_stability':vals[2],'known_months':sum(v is not None for v in known.values()),'known_periods':len(known),'latest_period':max(known,default=None),'missing_reason_12m':reason_for(known,24),'missing_reason_3m':reason_for(known,6),'missing_reason_stability':reason_for(known,12)})
 return pd.DataFrame(rows)

def reason_for(months,n):
 if not months:return 'no_verified_values'
 a=metric_window(months,n)
 if a is None:return f'insufficient_or_noncontiguous_{n}m'
 if (n==24 and abs(a[:12].sum())==0) or (n==6 and abs(a[:3].sum())==0) or (n==12 and abs(a.mean())==0):return 'zero_denominator'
 return None

def make_tensor(base,monthly,*,rebuild_penalty=False,net=None):
 t={k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in base.items()}
 ix=pd.MultiIndex.from_product([t['dates'],t['syms']],names=['decision_time','symbol'])
 m=monthly.set_index(['decision_time','symbol']).reindex(ix)
 t['raw'][:,:,0]=m.sales_growth_12m.to_numpy(float).reshape(t['raw'].shape[:2]);t['raw'][:,:,1]=m.sales_growth_3m.to_numpy(float).reshape(t['raw'].shape[:2]);t['raw'][:,:,16]=m.sales_stability.to_numpy(float).reshape(t['raw'].shape[:2])
 t['rank']=np.stack([ranks(x) for x in t['raw']]);t['observed']=np.isfinite(t['raw'])
 for j,limit in [(12,60),(13,100),(14,30)]:t['observed'][:,:,j]&=(t['raw'][:,:,j]>0)&(t['raw'][:,:,j]<=limit)
 if rebuild_penalty:
  t['penalty']=np.stack([penalties(t['raw'][i],net[i]) for i in range(len(t['dates']))])
 return t

def run():
 OUT.mkdir(parents=True,exist_ok=True)
 t0=pickle.load((V10/'tensors_v10.pkl').open('rb'));v9t=pickle.load((V9/'tensors_v9.pkl').open('rb'))
 events=pd.read_parquet(EVENTS);feat=pd.read_parquet(V9/'monthly_sales_features_v9.parquet',columns=['decision_time','symbol','company_id'])
 cal=list(t0['cal']);syms=list(t0['syms'])
 # P0 is copied byte-for-byte from V10; sealed run files stay outside this directory.
 shutil.copy2(V10/'monthly_sales_features_v10.parquet',OUT/'panel_P0.parquet');p0=pd.read_parquet(OUT/'panel_P0.parquet')
 p1=build_monthly(events,feat,cal,syms,jalali=False,keep_corrections=False)
 p2=build_monthly(events,feat,cal,syms,jalali=True,keep_corrections=True)
 for name,p in [('P1',p1),('P2',p2)]:p.to_parquet(OUT/f'panel_{name}.parquet',index=False,compression='zstd')
 base=pickle.load((V9/'tensors_v9.pkl').open('rb'))
 tensors={'P0':t0,'P1':make_tensor(base,p1),'P2':make_tensor(base,p2)}
 rawv8=pd.read_parquet(V8/'feature_values_and_ranks.parquet',columns=['decision_time','symbol','net_profit_ttm'])
 net=rawv8.set_index(['decision_time','symbol']).reindex(pd.MultiIndex.from_product([base['dates'],base['syms']],names=['decision_time','symbol'])).net_profit_ttm.to_numpy(float).reshape(base['raw'].shape[:2])
 tensors['P3']=make_tensor(base,p2,rebuild_penalty=True,net=net)
 p3=p2.copy();p3['penalty_source']='recomputed_from_P3_raw_plus_v8_net_profit_ttm';p3.to_parquet(OUT/'panel_P3.parquet',index=False,compression='zstd')
 for k,t in tensors.items():
  if k=='P0':shutil.copy2(V10/'tensors_v10.pkl',OUT/'tensors_P0.pkl')
  else:pickle.dump(t,(OUT/f'tensors_{k}.pkl').open('wb'),protocol=pickle.HIGHEST_PROTOCOL)
 coverage=[]
 for k,p in [('P0',p0),('P1',p1),('P2',p2),('P3',p3)]:
  p=p.copy();p['year']=pd.to_datetime(p.decision_time).dt.year
  for f in ['sales_growth_12m','sales_growth_3m','sales_stability']:
   coverage.extend({'panel':k,'year':int(y),'factor':f,'decision_symbol_cells':int(n),'observed_cells':int(c),'coverage':float(c/n) if n else None} for (y,n,c) in p.groupby('year')[f].agg(['size','count']).reset_index().itertuples(index=False,name=None))
 pd.DataFrame(coverage).to_csv(OUT/'coverage_by_factor_year.csv',index=False)
 missing=[]
 for name,p in [('P1',p1),('P2',p2)]:
  for f,reasoncol in [('sales_growth_12m','missing_reason_12m'),('sales_growth_3m','missing_reason_3m'),('sales_stability','missing_reason_stability')]:
   x=p[p[f].isna()][reasoncol].value_counts(dropna=False)
   missing += [{'panel':name,'factor':f,'reason':str(r),'cells':int(n)} for r,n in x.items()]
 pd.DataFrame(missing).to_csv(OUT/'missing_reasons.csv',index=False)
 # Exact downstream PIT invariance: append an event learned after the entire history,
 # rerun the full monthly panel/scorer input, compare every historical cell.
 synthetic=events.iloc[[0]].copy();synthetic['event_id']='V11_FUTURE_CORRECTION_FIXTURE';synthetic['is_correction']=True;synthetic['publication_role']='correction';synthetic['published_at']=pd.Timestamp(cal[-1]).tz_localize('UTC')+pd.Timedelta(days=365);synthetic['signal_entry_date']=None;synthetic['CURRENT_PERIOD_SALES']=np.nan;synthetic['current_value_version_known']=False
 augmented=build_monthly(pd.concat([events,synthetic],ignore_index=True),feat,cal,syms,jalali=True,keep_corrections=True)
 test_same=bool(p2[['decision_time','symbol','sales_growth_12m','sales_growth_3m','sales_stability']].equals(augmented[['decision_time','symbol','sales_growth_12m','sales_growth_3m','sales_stability']]))
 if not test_same:raise AssertionError('Future event changed historical panel')
 aug_t=make_tensor(base,augmented,rebuild_penalty=True,net=net);control=WEIGHTS.copy();control[15]=0;control=control/control.sum()*100;cc=cfg(control,n=10,cadence=10,exit_mult=1,allocation='equal')
 v0=score(tensors['P3'],cc);v1=score(aug_t,cc);score_same=bool(np.array_equal(v0,v1,equal_nan=True))
 r0,s0,d0=simulate_v10(tensors['P3'],cc,v0,0,len(cal),detail=True);r1,s1,d1=simulate_v10(aug_t,cc,v1,0,len(cal),detail=True)
 trade_same=d0['trades']==d1['trades'];equity_same=d0['equity']==d1['equity'];pipeline_same=score_same and trade_same and equity_same and abs(r0['final_toman']-r1['final_toman'])<1e-8
 if not pipeline_same:raise AssertionError('Future event changed historical scorer, trades, or NAV')
 oldfiles={str(p):sha(Path(p)) for p in [V10/'delivery_manifest.json',V9/'delivery_manifest.json',ROOT/'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet']}
 contract={'panel_semantics':{'P0':'byte-for-byte V10 monthly feature panel and tensor copy','P1':'independent 24m/6m/12m windows with V10 future-correction exclusion and Gregorian period grouping','P2':'P1 window semantics plus Jalali report-month keys and knowledge-time revisions/corrections','P3':'P2 plus rebuilt ranks/observed/penalties; DQ held fixed as independent V8 input.'},'calendar_evidence':'period_end dates convert to Jalali reporting month end; publication dates are separate later dates. Period keys use jdatetime Gregorian-to-Jalali conversion, tested across Esfand/Farvardin.','value_policy':'only verified numeric original versions admitted; unverified correction sets the value null from the next session after Tehran publication; numeric correction is admitted only if source marks the value version verified.','penalty_policy':'V8 penalties(raw,net_profit_ttm) recomputed for P3; independent DQ multiplier unchanged and documented.','calendar_length':len(cal),'factor_names':FIELDS,'future_event_invariance':{'monthly_panel':test_same,'score_and_missing_mask':score_same,'trades':trade_same,'equity':equity_same,'full_pipeline':pipeline_same},'sealed_hashes_before_run':oldfiles,'P0_source_hashes':{'monthly_v10_sha256':sha(V10/'monthly_sales_features_v10.parquet'),'tensor_v10_sha256':sha(V10/'tensors_v10.pkl')}}
 (OUT/'feature_contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'run':str(OUT),'panel_rows':len(p2),'coverage':pd.DataFrame(coverage).to_dict('records')[-6:],'future_invariance':test_same},ensure_ascii=False))

if __name__=='__main__':run()
