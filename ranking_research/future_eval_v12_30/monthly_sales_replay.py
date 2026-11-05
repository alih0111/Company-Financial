"""Local monthly-sales correction replay extracted unchanged from V11 prepare.

Kept dependency-light so current ranking preparation does not import the historical
backtest/scoring stack merely to calculate three monthly factors.
"""
import numpy as np
import pandas as pd
import jdatetime

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
