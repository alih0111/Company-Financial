"""Complete publication-reconstructed replay to the latest pinned market day.

Frozen model/policy, no retuning. The already tested historical prefix remains
unchanged. New fundamentals use each report's publication cutoff, never the
current owner feature table. Mechanical reference-price adjustments are a
research extension, not actual-share/cash accounting or live certification.
"""
from pathlib import Path
from dataclasses import asdict
import json,sys,copy
import numpy as np
import pandas as pd
import jdatetime
from extend_market import HERE,ROOT,PREV,OUT,prepare_market

SEARCH=HERE.parent/'feature_model_search_20261106'
sys.path[:0]=[str(ROOT),str(PREV),str(SEARCH),str(HERE.parent/'rank_top5_rebalance_20261105')]
from engine import Config,Execution,simulate,save_run,calendar_schedule
from features import rank_transform,market_features
from ranking_research.return_v8.features import FIELDS,LOW
from ranking_research.return_v11.prepare import build_monthly
from ranking_research.v2_inputs import ArchiveSnapshots,CM,H,resolve_shares
from ranking_research.return_v2.events import cutoff
from ranking_research.future_eval_v12_30.income_statement_selection import income_statement_view
from backtest_top5 import load_scores


class LocalSnapshots(ArchiveSnapshots):
    def parsed(self,record):return {'statements':{},'period_headers':{}}


def ratio(a,b,positive=False,scale=1):
    try:
        a,b=float(a),float(b)
        return a/b*scale if np.isfinite(a) and np.isfinite(b) and (b>0 if positive else b!=0) else np.nan
    except (TypeError,ValueError):return np.nan


def append_financial(data,md,meta,needed):
    reports_path=ROOT/meta['financial']['reports_path']
    records=json.loads(reports_path.read_text(encoding='utf8'))
    comparisons=json.loads((ROOT/meta['financial']['comparatives_path']).read_text(encoding='utf8'))
    monthly_path=reports_path.parent/'monthly_sales_events.parquet'
    events=pd.read_parquet(monthly_path)
    original=pd.read_parquet(ROOT/'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet')
    events=pd.concat([original,events],ignore_index=True).drop_duplicates('event_id',keep='last')
    identities=pd.read_csv(ROOT/'ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv',dtype=str)
    selected_ids={str(r.company_id):{'symbol':str(r.symbol),'security_id':md.sym2sid[str(r.symbol)]} for r in identities.itertuples()}
    intervals=json.loads((ROOT/'qvt_backtest/output/financial_history/share_intervals.json').read_text(encoding='utf8'))['intervals']
    skeleton=pd.concat([identities[['company_id','symbol']].assign(decision_time=d) for d in needed],ignore_index=True)
    monthly=build_monthly(events,skeleton,needed,[],jalali=True,keep_corrections=True).set_index(['decision_time','symbol'])
    all_rows=[];audit=[]
    for day in needed:
        cut=cutoff(day)
        # Comparative facts with explicit later availability are not backdated.
        rcopy=[{**r,'facts':[dict(f) for f in r['facts']]} for r in records]
        bykey={(str(r['company_id']),str(r['tracing_no'])):r for r in rcopy}
        admitted=0
        for comp in comparisons:
            available=comp.get('available_at_utc')
            if available and pd.Timestamp(available)>pd.Timestamp(cut):continue
            rec=bykey.get((str(comp['company_id']),str(comp['tracing_no'])))
            if rec is None:raise RuntimeError('Unmatched comparative identity')
            if pd.Timestamp(rec['published_at'])>=pd.Timestamp(cut):continue
            key=(comp['statement_type'],comp['metric_code'],int(comp['period_order']))
            prior=next((f for f in rec['facts'] if (f['statement_type'],f['metric_code'],int(f['period_order']))==key),None)
            if prior is None:
                rec['facts'].append(dict(statement_type=comp['statement_type'],metric_code=comp['metric_code'],
                    period_order=int(comp['period_order']),value=float(comp['canonical_value']),unit=comp['canonical_unit'],basis='parent'))
                admitted+=1
            elif not np.isclose(float(prior['value']),float(comp['canonical_value']),rtol=1e-12,atol=1):
                raise RuntimeError('Comparative value conflict')
        source=LocalSnapshots(rcopy,[],selected_ids,md,intervals)
        eng,metrics,_=source.snapshot(day,cut)
        full=eng.report_index();income=income_statement_view(full)
        titles=eng.codal_titles
        eligible={(cid,p) for cid,periods in income.items() for p in periods}
        eng.codal_titles=[t for t in titles if (t['company_id'],tuple(CM.fiscal_ym(t['period_end_date']))) in eligible]
        eng.report_index=lambda:income
        imetrics=eng.compute()
        eng.report_index=lambda:full;eng.codal_titles=titles
        rows=[]
        for identity in identities.itertuples():
            cid,sym=str(identity.company_id),str(identity.symbol)
            rep=full.get(cid,{});inc=income.get(cid,{})
            key=max(inc,default=None);cell=inc.get(key,{})
            bk=max(rep,default=None);balance=rep.get(bk,{})
            g=lambda name,order=1:cell.get(name,{}).get(order)
            bg=lambda name:balance.get(name,{}).get(1)
            m=imetrics.get(cid,{})
            net,op,rev=m.get('net_profit_ttm'),m.get('operating_profit_ttm'),m.get('revenue_ttm')
            vals=[m.get(f,np.nan) for f in FIELDS]
            vals=[float(v) if v is not None else np.nan for v in vals]
            vals[5]=ratio(op,abs(rev) if rev else None,scale=100);vals[6]=ratio(net,abs(rev) if rev else None,scale=100)
            for j in [5,6]:
                if abs(vals[j])>200:vals[j]=np.nan
            vals[7]=ratio(net,bg('total_equity'),True,100)
            if abs(vals[7])>300:vals[7]=np.nan
            om=ratio(g('operating_profit'),abs(g('revenue')) if g('revenue') else None,scale=100)
            old=ratio(g('operating_profit',2),abs(g('revenue',2)) if g('revenue',2) else None,scale=100)
            vals[8]=om-old if abs(om)<=200 and abs(old)<=200 else np.nan
            vals[9]=ratio(g('operating_profit'),abs(g('finance_cost')) if g('finance_cost') else None)
            if abs(vals[9])>10000:vals[9]=np.nan
            vals[10]=ratio(m.get('ocf_ttm'),net,True)
            if not -2<=vals[10]<=5:vals[10]=np.nan
            vals[11]=ratio(abs(g('other_non_operating')) if g('other_non_operating') is not None else None,
                           abs(g('operating_profit')) if g('operating_profit') else None,scale=100)
            vals[17]=ratio(bg('total_liabilities'),bg('total_equity'),True)
            vals[18]=ratio(bg('current_assets'),bg('current_liabilities'),True)
            if not 0<=vals[17]<=50:vals[17]=np.nan
            if not 0<=vals[18]<=15:vals[18]=np.nan
            row=monthly.loc[(day,sym)]
            vals[0],vals[1],vals[16]=row.sales_growth_12m,row.sales_growth_3m,row.sales_stability
            market=md.data[sym];dates=np.array(market['dates'])
            good=(dates<=day)&(market['vol']>0)&(market['tval']>0)&(market['c']>0)
            ids=np.flatnonzero(good);tail=ids[-30:]
            factors=md.asof_factors(sym,day);prices=market['c'][tail]*factors[tail]
            vals[15]=float(np.mean(market['tval'][tail])) if len(tail) else np.nan
            vals[19]=float(np.std(-np.diff(prices)/prices[1:]*100,ddof=1)) if len(tail)>2 else np.nan
            vals[20]=float((prices[-1]/prices[0]-1)*100) if len(tail)>=30 else np.nan
            actual=str(dates[ids[-1]]) if len(ids) else None;price=float(market['c'][ids[-1]]) if len(ids) else None
            iv=resolve_shares(source.intervals,sym,cid,md.sym2sid[sym],day,actual) if actual else None
            share_ok=bool(iv and iv.get('evidence')) and not any(str(iv.get('valid_from') or '')<str(d)<=day for d,f in md.events[market['sid']])
            eps=ratio(net,g('net_profit'),True)*g('eps') if g('eps') and g('eps')>0 else np.nan
            vals[12]=ratio(price,eps,True) if share_ok else np.nan
            vals[13]=vals[12]*vals[6]/100 if 0<vals[12]<=60 and vals[6]>0 and vals[12]*vals[6]/100<=100 else np.nan
            vals[14]=vals[12]*vals[7]/100 if 0<vals[12]<=60 and vals[7]>0 and vals[12]*vals[7]/100<=30 else np.nan
            selected=eng.snapshot_source_reports.get(cid,[])
            assert all(pd.Timestamp(s['published_at'])<pd.Timestamp(cut) for s in selected)
            period=cell.get('_period');age=(pd.Timestamp(day)-pd.Timestamp(period)).days if period else 9999
            priceage=(pd.Timestamp(day)-pd.Timestamp(actual)).days if actual else 9999
            count=len(rep);now=pd.Timestamp(day)
            sqljy=now.year-(622 if now.month<3 or now.month==3 and now.day<21 else 621)
            sqljm={1:11,2:12,3:1,4:2,5:3,6:4,7:5,8:6,9:7,10:8,11:9,12:10}[now.month]
            jy,jm=key if key else (0,0);months=sqljy*12+sqljm-jy*12-jm
            dq=(.28 if count>=16 else .16 if count>=8 else .09 if count>=4 else 0)+(.21 if len(ids)>=90 else .13 if len(ids)>=30 else .06 if len(ids)>=10 else 0)+(.09 if price else 0)+(.08 if selected and months<=5 else .045 if selected and months<=8 else 0)+(.06 if priceage<=7 else .035 if priceage<=14 else 0)
            rows.append(dict(decision_time=day,symbol=sym,company_id=cid,**dict(zip(FIELDS,vals)),
                net_profit_ttm=net,dq=dq,financial_age_days=age,blocked=False,
                sources=json.dumps(selected,ensure_ascii=False),publication_cutoff=cut.isoformat(),price_date=actual))
        frame=pd.DataFrame(rows);frame.to_parquet(OUT/f'financial_{day}.parquet',index=False)
        all_rows.extend(rows);audit.append(dict(day=day,companies=len(rows),comparatives_admitted=admitted,
            publication_gate_pass=True,income_statement_selection='latest income period; no future owner table',
            real_historical_receipt_proven=False))
        print('FINANCIAL SNAPSHOT',day,len(rows),'companies',flush=True)
    (OUT/'financial_extension_audit.json').write_text(json.dumps({'snapshots':audit,'reports_path':str(reports_path.relative_to(ROOT)),
        'monthly_path':str(monthly_path.relative_to(ROOT)),'current_owner_features_used':False,
        'source_definitions':'same locked financial ratios; V12.37 income-period selection adapter for new dates only',
        'receipt_limitation':'publication-reconstructed, NOT actual historical receipt evidence'},ensure_ascii=False,indent=2),encoding='utf8')
    return pd.DataFrame(all_rows)


def build_extended_scores(data,frame,policy):
    olddata=dict(np.load(SEARCH/'artifacts/market_inputs.npz'))
    oldfeat=dict(np.load(SEARCH/'artifacts/features.npz'))
    oldlen=len(olddata['cal']);T=len(data['cal']);S=len(data['syms'])
    raw=np.repeat(oldfeat['raw'][-1:],T,axis=0).astype(float);raw[:oldlen]=oldfeat['raw']
    contract=json.loads((ROOT/'ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json').read_text(encoding='utf-8-sig'))
    scoretables=load_scores(frame,contract,data['syms'].tolist())
    arrays={d:g.set_index('symbol').reindex(data['syms']) for d,g in frame.groupby('decision_time')}
    snapdays=sorted(arrays)
    for i in range(oldlen,T):
        day=str(data['cal'][i]);k=np.searchsorted(snapdays,day,side='right')-1
        if k<0:
            for key in ['p1','p3','financial_age','blocked']:data[key][i]=olddata[key][-1]
            data['signal_dates'][i]=olddata['signal_dates'][-1]
        else:
            d=snapdays[k];f=arrays[d];raw[i]=f[FIELDS].to_numpy(float)
            data['p1'][i]=scoretables['P1'][d];data['p3'][i]=scoretables['P3'][d]
            data['financial_age'][i]=f.financial_age_days.to_numpy(float)
            data['blocked'][i]=False;data['signal_dates'][i]=d
        data['score_age'][i]=(pd.Timestamp(day)-pd.Timestamp(str(data['signal_dates'][i]))).days
    cols=[];names=[]
    for j,f in enumerate(FIELDS):
        x=raw[:,:,j].copy()
        if j==11:x=np.abs(x)
        if j in [12,13,14]:x[(x<=0)|(x>[60,100,30][j-12])]=np.nan
        cols.append(rank_transform(x,j in LOW));names.append(f)
    for name,x in market_features(data['close'],data['adv']).items():
        cols.append(rank_transform(x,name.startswith('vol_') or name=='downside_vol63'));names.append(name)
    lag=np.searchsorted(data['cal'].astype('datetime64[D]'),data['cal'].astype('datetime64[D]')-np.timedelta64(90,'D'),side='right')-1
    lag=np.maximum(lag,0)
    for name,x in [('sales_accel_3v12',raw[:,:,1]-raw[:,:,0]),('sales_growth_change90',raw[:,:,1]-raw[lag,:,1]),
                   ('profit_growth_change90',raw[:,:,4]-raw[lag,:,4]),('margin_trend_change90',raw[:,:,8]-raw[lag,:,8]),('p1_score',data['p1'])]:
        cols.append(rank_transform(x));names.append(name)
    X=np.stack(cols,axis=2);idx={n:i for i,n in enumerate(names)}
    def mean(fs):return np.mean(X[:,:,[idx[f] for f in fs]],axis=2)
    blocks=np.stack([mean(FIELDS[:5]),mean(FIELDS[5:12]),mean(['pe','ps','pb']),
        mean(['leverage','current_ratio','cash_conversion','sales_stability']),
        mean(['mom_63','mom_126_skip21','near_high_126','trend_50_200']),
        mean(['vol_63','downside_vol63','reversal21']),
        mean(['sales_accel_3v12','sales_growth_change90','profit_growth_change90','margin_trend_change90']),X[:,:,idx['p1_score']]],axis=2)
    blocks[:oldlen]=oldfeat['blocks']
    values=(blocks@np.array(policy['source_model']['weights'])).astype(np.float32)
    values[~np.isfinite(data['p1'])]=np.nan
    frozen=np.load(SEARCH/'artifacts/score_cache/GROUP_WEIGHT_033.npz')['score']
    np.testing.assert_array_equal(values[:oldlen],frozen)
    return values


def main():
    policy=json.loads((SEARCH/'artifacts/research_decision.json').read_text(encoding='utf8'))
    cfg=Config(**policy['portfolio']);ex=Execution(**policy['execution_assumptions'])
    data,md,meta=prepare_market();cal=data['cal'].tolist()
    scheduled=calendar_schedule(cal,cfg,int(np.searchsorted(cal,'2023-03-21')),len(cal))
    decisions=[i for i in sorted(scheduled) if cal[i]>'2026-02-24']
    needed=set(cal[i] for i in decisions)
    for i in decisions:
        lag=np.searchsorted(data['cal'].astype('datetime64[D]'),np.datetime64(cal[i])-np.timedelta64(90,'D'),side='right')-1
        if cal[lag]>'2026-02-24':needed.add(cal[lag])
    print('REQUIRED NEW SNAPSHOTS',sorted(needed),flush=True)
    frame=append_financial(data,md,meta,sorted(needed))
    values=build_extended_scores(data,frame,policy)
    np.savez_compressed(OUT/'complete_inputs.npz',**data,candidate_score=values)
    candidate=simulate({**data,'p1':values},cfg,ex,start='2023-03-21',end=cal[-1],detail=True)
    baseline=simulate(data,Config('BASE'),ex,start='2023-03-21',end=cal[-1],detail=True)
    prefix=json.loads((OUT/'available_replay.json').read_text(encoding='utf8'))
    k=np.searchsorted(candidate['cal'],'2026-02-24')
    assert abs(candidate['nav'][k]-prefix['metrics']['final_toman'])<1,'Historical NAV prefix changed'
    assert abs(baseline['nav'][k]-prefix['baseline']['final_toman'])<1,'Baseline prefix changed'
    for label,r in [('complete_candidate',candidate),('complete_baseline',baseline)]:save_run(OUT/label,r)
    years=[]
    jy=np.array([jdatetime.date.fromgregorian(date=pd.Timestamp(str(d)).date()).year for d in candidate['cal']])
    for y in sorted(set(jy)):
        ids=np.flatnonzero(jy==y);a,b=int(ids[0]),int(ids[-1]);start=candidate['nav'][a-1] if a else 1e8
        years.append(dict(year=int(y),start=str(candidate['cal'][a]),end=str(candidate['cal'][b]),
            initial_toman=float(start),final_toman=float(candidate['nav'][b]),return_fraction=float(candidate['nav'][b]/start-1)))
    dates=['2026-02-24','2026-09-30',cal[-1]];common=[]
    for day in dates:
        i=np.searchsorted(candidate['cal'],day,side='right')-1
        common.append(dict(date=str(candidate['cal'][i]),candidate_toman=float(candidate['nav'][i]),baseline_toman=float(baseline['nav'][i])))
    summary={'requested_start':'1402-01-01','requested_today':'1405-08-15','latest_available_market_day':cal[-1],
        'latest_market_day_jalali':str(jdatetime.date.fromgregorian(date=pd.Timestamp(cal[-1]).date())),
        'initial_toman':100000000,'candidate':candidate['metrics'],'baseline':baseline['metrics'],
        'same_date_comparison':common,'jalali_years':years,'fees_toman':candidate['cost_toman'],
        'slippage_toman':candidate['slippage_toman'],'trades':candidate['n_trades'],'rebalances':len(candidate['decisions']),
        'first_fill':candidate['trades'][0]['session'],'new_financial_snapshots':sorted(needed),
        'historical_prefix_reproduced':True,'frozen_weights_and_policy_unchanged':True,
        'research_adjustment_extension':True,'historical_receipt_proven':False,
        'data_adapter_note':'existing frozen inputs preserved through 2026-02-24; later dates reconstructed from publication-filtered source reports using current income-period selection, without owner-current values',
        'execution':asdict(ex),'last_positions':candidate['terminal_positions'],'production_changed':False}
    (OUT/'complete_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    pd.DataFrame(years).to_csv(OUT/'complete_annual_periods.csv',index=False,encoding='utf-8-sig')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
