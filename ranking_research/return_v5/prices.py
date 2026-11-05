"""Source quality, not portfolio PnL, determines the primary endpoint."""
import bisect
import datetime as dt
import gzip
import json
import time
import numpy as np
import pandas as pd
import requests
from .common import V2,V3,read,write,sha

def valid(r,i):
    return (all(np.isfinite(r[k][i]) and r[k][i]>0 for k in ['o','h','l','c','vol','tval'])
            and r['l'][i]<=min(r['o'][i],r['c'][i])<=max(r['o'][i],r['c'][i])<=r['h'][i])

def run(out,md,new):
    if (out/'evaluation_windows.json').exists():return
    rows=[];detail=[]
    cov=pd.read_csv(V3/'economic_event_coverage.csv')
    ref=set(cov[cov.method.isin(['balanced_control','existing_choose'])].symbol)
    inv=pd.read_csv(V2/'new_market_archive/inventory.csv',dtype={'ins_code':str})
    # Exposure-first then lexicographic fixed sample, never selected on returns.
    sample=list(cov[cov.method.isin(['balanced_control','existing_choose'])].symbol.value_counts().head(4).index)
    sample+= [s for s in sorted(md.data) if s not in sample][:4]
    days=sorted(set(md.cal)|set(d for r in new.data.values() for d in r['dates']))
    for vintage,market in [('D1_execution',md),('latest_raw_unspliced',new)]:
        trade_dates={sym:[r['dates'][i] for i in np.flatnonzero((r['vol']>0)&(r['tval']>0)&(r['c']>0))] for sym,r in market.data.items()}
        ordinals={d:pd.Timestamp(d).toordinal() for d in days}
        selected=set(sample)|ref
        for day in days:
            if day<'2022-05-01':continue
            n=dict(present=0,positive_trade=0,valid_ohlc_trade=0,zero_volume=0,invalid_ohlc=0,missing=0,stale_over_7d=0)
            refpos=0
            for sym,r in market.data.items():
                i=r['dmap'].get(day)
                if i is None:n['missing']+=1
                else:
                    n['present']+=1
                    pos=bool(r['vol'][i]>0 and r['tval'][i]>0 and np.isfinite(r['c'][i]) and r['c'][i]>0)
                    n['positive_trade']+=int(pos);refpos+=int(pos and sym in ref)
                    n['valid_ohlc_trade']+=int(valid(r,i));n['zero_volume']+=int(not pos)
                    n['invalid_ohlc']+=int(pos and not valid(r,i))
                j=bisect.bisect_right(trade_dates[sym],day)-1
                last=trade_dates[sym][j] if j>=0 else None
                stale=last is not None and ordinals[day]-pd.Timestamp(last).toordinal()>7
                n['stale_over_7d']+=int(stale)
                if sym in selected and day>='2026-02-01':
                    detail.append({'vintage':vintage,'symbol':sym,'date':day,'reference_exposure':sym in ref,'fixed_sample':sym in sample,
                        'record_present':i is not None,'positive_trade':bool(i is not None and r['vol'][i]>0 and r['tval'][i]>0 and r['c'][i]>0),
                        'last_positive_trade':last,'stale_over_7d':stale,'cause':'unknown_source_or_halt_or_calendar; no status notice'})
            rows.append({'vintage':vintage,'date':day,'universe':len(market.data),**n,'reference_symbols':len(ref),'reference_positive':refpos,
                'market_open_status':'inferred_if_positive_else_unknown','price_unit':'rial','price_type':'unadjusted pClosing; execution priceFirst',
                'candle':'daily instrument history /0; not minute or adjusted candle','date_contract':'DEven Gregorian YYYYMMDD converted once',
                'endpoint':'cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{insCode}/0','pagination':'whole returned history; no pagination parameter; archive earliest/latest retained',
                'identity_contract':'inventory insCode exact match to response; symbol mapped security_id'})
    table=pd.DataFrame(rows);table.to_csv(out/'price_contract_audit.csv',index=False)
    pd.DataFrame(detail).to_csv(out/'price_sample_daily.csv',index=False)
    q=table[table.vintage.eq('D1_execution') & (table.valid_ohlc_trade/table.universe).ge(.5)]
    end=q[q.date.le('2026-04-29')].date.max()
    write(out/'evaluation_windows.json',{'quality_rule_registered_before_returns':read(out/'registration.json')['quality_rule'],
        'primary_quality_end':end,'last_quality_row_full_archive':q.date.max(),'full_exploratory':['2022-05-01','2026-09-30'],
        'old_V4_reconciliation':['2024-11-02','2026-04-29'],
        'primary_evaluation':['2024-11-02',end],
        'complete_outer_blocks':[['2024-11-02','2025-04-30'],['2025-05-01','2025-10-31']],
        'partial_outer_block':['2025-11-01',end],'block_months':6,'protocol':[24,6,6],
        'independent_holdout':False,'extension_admitted':False,'reason':'new raw tail not spliced onto old adjustment factors; unresolved event/calendar provenance',
        'positive_trade_is_not_executable_guarantee':True})
    target=out/'price_probes';target.mkdir(exist_ok=True)
    attempts=[]
    for sym in sample:
        x=inv[inv.symbol.eq(sym)].iloc[0];url=f'https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{x.ins_code}/0'
        p=target/(str(x.ins_code)+'.json');row={'symbol':sym,'ins_code':str(x.ins_code),'security_id':x.security_id,'url':url,'received_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            r=requests.get(url,timeout=(5,15));p.write_bytes(r.content);row.update(status=r.status_code,source_path=str(p),sha256=sha(p))
            if r.status_code in [401,402,403,429] or 'captcha' in r.text.lower():row['stop']='access/rate';attempts.append(row);break
            if r.ok:
                z=r.json()['closingPriceDaily'];assert all(str(a.get('insCode',x.ins_code))==str(x.ins_code) for a in z)
                pos=[str(a['dEven']) for a in z if a.get('qTotTran5J',0)>0 and a.get('qTotCap',0)>0 and a.get('pClosing',0)>0]
                row.update(rows=len(z),last_positive=max(pos,default=None),positive_after_feb25=sum(d>'20260225' for d in pos),
                    corroboration='new retrieval of same official endpoint; NOT independent status evidence')
        except (requests.RequestException,ValueError,KeyError,AssertionError) as e:row['error']=type(e).__name__
        attempts.append(row);pd.DataFrame(attempts).to_csv(target/'attempts.csv',index=False);time.sleep(1.5)
    pd.DataFrame(attempts).to_csv(target/'attempts.csv',index=False)
    write(target/'checkpoint.json',{'sample':sample,'requests':len(attempts),'same_source_only':True,'independent_status_evidence':False})
