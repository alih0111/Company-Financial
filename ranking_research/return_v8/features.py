import json
from pathlib import Path
import numpy as np
import pandas as pd
from ranking_research.return_v6.common import ROOT,V2,V3,V4,read,write,sha,utc

FIELDS=['sales_growth_12m','sales_growth_3m','revenue_growth','operating_profit_growth','net_profit_growth','operating_margin','net_margin','roe','margin_trend','interest_coverage','cash_conversion','earnings_quality','pe','ps','pb','avg_trade_value_30d','sales_stability','leverage','current_ratio','volatility_30d','price_momentum_30d']
WEIGHTS=np.array([10,6,5,5,10,4,4,6,3,3,2,4,11,3,2,3,1,2,2,2,1],float)
GROUPS=[list(range(5)),list(range(5,12)),list(range(12,15)),list(range(15,21))]
NEUTRAL=np.array([.3]*9+[.5,.3,.5,0,0,0,0,.3,.3,.3,.3,.3])
LOW={11,12,13,14,17,19}
CLIPS={0:(-150,150),1:(-150,150),2:(-200,200),3:(-250,250),4:(-300,300),5:(-80,80),6:(-60,60),7:(-150,150),8:(-25,25),10:(-2,5),20:(-50,40)}
START='2021-04-01'
END='2026-02-25'

def ranks(raw):
    r=np.empty_like(raw,dtype=float)
    for j in range(21):
        v=raw[:,j].copy()
        if j in CLIPS:v=np.clip(v,*CLIPS[j])
        if j==9:v=np.where(v<=0,-999999,np.minimum(v,20))
        if j==11:v=np.minimum(abs(v),150)
        if j==17:v=np.minimum(v,50)
        if j==18:v=np.minimum(v,15)
        invalid=~np.isfinite(v)
        if j in (12,13,14):
            invalid |= (v<=0)|(v>[60,100,30][j-12]);v[invalid]=999999
        valid=np.isfinite(v);n=valid.sum()
        s=pd.Series(v).rank(method='average').to_numpy()
        pct=(s-1)/(n-1) if n>1 else np.full(len(v),.5)
        if j in LOW:pct=1-pct
        pct[~valid]=NEUTRAL[j]
        if j in (12,13,14):pct[invalid]=0
        r[:,j]=pct
    return r

def penalties(raw,net):
    p=np.zeros((len(raw),4))
    p[:,0]=6*(raw[:,0]<-20)+5*(raw[:,3]<-25)
    p[:,1]=10*(net<0)+4*(raw[:,9]<1.5)+3*(raw[:,8]<-2)+np.nan_to_num(np.clip((raw[:,11]-20)/80,0,1))*8
    p[:,2]=8*((~np.isfinite(raw[:,12]))|(raw[:,12]<=0)|(raw[:,12]>60))
    return p

def build(out,md,worker_range=None):
    from ranking_research.return_v2.events import source_inputs,cutoff
    from ranking_research.strategy_search.features import causal_factors
    from ranking_research.return_v7.core import sessions
    # Same source-backed financial stream as V2--V7; do not trust legacy PIT label.
    source,records,policy,_=source_inputs(pd.DataFrame(),md)
    md.asof_factors=lambda s,t:causal_factors(md,s,t)
    cal=sorted({d for r in md.data.values() for i,d in enumerate(r['dates']) if START<=d<=END and r['vol'][i]>0 and r['tval'][i]>0 and np.isfinite(r['c'][i]) and r['c'][i]>0})
    dates=sorted(set(d for k in [5,10,21,63,126] for d in cal[::k]))
    if worker_range:dates=[d for d in dates if worker_range[0]<=d<=worker_range[1]]
    syms=sorted(md.data);cids={v['symbol']:k for k,v in source.identities.items()}
    events=pd.read_parquet(V2/'pit_feature_events.parquet')
    gaps=pd.read_parquet(V2/'known_report_gap_events.parquet')
    shards=out/'feature_shards';shards.mkdir(exist_ok=True)
    identities=dict(source.identities);allreports=list(source.reports)
    metrics_cache={};index_cache={};selected_cache={};signatures={}
    for ix,day in enumerate(dates):
        path=shards/(day+'.parquet')
        if path.exists():continue
        from ranking_research.v2_inputs import H
        known=H.select_asof(allreports,cutoff(day));by={}
        for rec in known:by.setdefault(rec['company_id'],[]).append(rec)
        current={cid:tuple(sorted((str(r['tracing_no']),r['sha256']) for r in by.get(cid,[]))) for cid in identities}
        changed=[cid for cid in identities if cid not in signatures or current[cid]!=signatures[cid]]
        if changed:
            source.identities={cid:identities[cid] for cid in changed}
            source.reports=[r for r in allreports if r['company_id'] in source.identities]
            eng,newmetrics,_=source.snapshot(day,cutoff(day))
            metrics_cache.update(newmetrics);index_cache.update(eng.report_index())
            for cid in changed:selected_cache[cid]=eng.snapshot_source_reports.get(cid,[])
        signatures=current;metrics=metrics_cache;idx=index_cache;rows=[]
        for sym in syms:
            cid=cids.get(sym);m=metrics.get(cid,{});rep=idx.get(cid,{})
            latest=max(rep,default=None);cell=rep.get(latest,{})
            def g(k,order=1):return cell.get(k,{}).get(order)
            def ratio(a,b,positive=False,scale=1):
                return a/b*scale if a is not None and b is not None and np.isfinite(a) and np.isfinite(b) and (b>0 if positive else b!=0) else np.nan
            vals=[m.get(f,np.nan) for f in FIELDS];vals=[float(v) if v is not None else np.nan for v in vals]
            # No proven monthly chain in the V4--V7 admitted input stream.
            for j in [0,1,16]:vals[j]=np.nan
            net=m.get('net_profit_ttm');op=m.get('operating_profit_ttm');rev=m.get('revenue_ttm')
            vals[5]=ratio(op,abs(rev) if rev else None,scale=100);vals[6]=ratio(net,abs(rev) if rev else None,scale=100)
            for j in [5,6]:
                if abs(vals[j])>200:vals[j]=np.nan
            vals[7]=ratio(net,g('total_equity'),True,100)
            if abs(vals[7])>300:vals[7]=np.nan
            om=ratio(g('operating_profit'),abs(g('revenue')) if g('revenue') else None,scale=100)
            old=ratio(g('operating_profit',2),abs(g('revenue',2)) if g('revenue',2) else None,scale=100)
            vals[8]=om-old if abs(om)<=200 and abs(old)<=200 else np.nan
            vals[9]=ratio(g('operating_profit'),abs(g('finance_cost')) if g('finance_cost') else None)
            if abs(vals[9])>10000:vals[9]=np.nan
            vals[10]=ratio(m.get('ocf_ttm'),net,True)
            if not -2<=vals[10]<=5:vals[10]=np.nan
            vals[11]=ratio(abs(g('other_non_operating')) if g('other_non_operating') is not None else None,abs(g('operating_profit')) if g('operating_profit') else None,scale=100)
            vals[17]=ratio(g('total_liabilities'),g('total_equity'),True)
            if not 0<=vals[17]<=50:vals[17]=np.nan
            vals[18]=ratio(g('current_assets'),g('current_liabilities'),True)
            if not 0<=vals[18]<=15:vals[18]=np.nan
            r=md.data[sym];ids=np.flatnonzero((np.asarray(r['dates'])<=day)&(r['vol']>0)&(r['tval']>0)&np.isfinite(r['c'])&(r['c']>0))
            tail=ids[-30:];f=causal_factors(md,sym,day);prices=r['c'][tail]*f[tail]
            vals[15]=float(np.mean(r['tval'][tail])) if len(tail) else np.nan
            # SQL LAG in DESC order: older minus newer, divided by newer.
            vals[19]=float(np.std(-np.diff(prices)/prices[1:]*100,ddof=1)) if len(tail)>2 else np.nan
            vals[20]=float((prices[-1]/prices[0]-1)*100) if len(tail)>=30 else np.nan
            price=float(r['c'][ids[-1]]) if len(ids) else None
            # SQL-equivalent EPS method; require dated share identity as additional validity proof.
            from ranking_research.v2_inputs import resolve_shares
            actual_day=str(r['dates'][ids[-1]]) if len(ids) else None
            dated_iv=resolve_shares(source.intervals,sym,cid,md.sym2sid.get(sym),day,actual_day) if actual_day else None
            iv={'share_evidence':dated_iv.get('evidence') if dated_iv else None,'share_knowledge_from':dated_iv.get('knowledge_from') if dated_iv else None,'valid_from':dated_iv.get('valid_from') if dated_iv else None,'price_date':actual_day}
            share=iv.get('share_evidence')
            sid=md.sym2sid.get(sym)
            share_ok=bool(share) and not any(str(iv.get('valid_from') or '')<str(e[0])<=day for e in md.events.get(sid,[]))
            eps=ratio(net,g('net_profit'),True)*g('eps') if g('eps') and g('eps')>0 else np.nan
            vals[12]=ratio(price,eps,True) if share_ok else np.nan
            vals[13]=vals[12]*vals[6]/100 if 0<vals[12]<=60 and vals[6]>0 and vals[12]*vals[6]/100<=100 else np.nan
            vals[14]=vals[12]*vals[7]/100 if 0<vals[12]<=60 and vals[7]>0 and vals[12]*vals[7]/100<=30 else np.nan
            selected=selected_cache.get(cid,[])
            assert all(pd.Timestamp(s['published_at'])<pd.Timestamp(cutoff(day)) for s in selected)
            ev=events[(events.company_id==cid)&(events.decision_time<=day)]
            last=ev.iloc[-1] if len(ev) else None
            # Same known-publication replacement/new-report veto as V7.
            chosen={str(s['period_end']):pd.Timestamp(s['published_at']) for s in selected}
            gp=gaps[(gaps.company_id==cid)&(gaps.day<=day)]
            latest_period=max(chosen,default='0000')
            blocked=any(a.guard_period and a.guard_period<=day and (a.guard_period>latest_period or a.guard_period in chosen and a.pub>chosen[a.guard_period] and (pd.Timestamp(latest_period)-pd.Timestamp(a.guard_period)).days<1000) for a in gp.itertuples())
            if blocked:
                for j in list(range(2,15))+[17,18]:vals[j]=np.nan
            # DQ production SQL, historical GETDATE substituted by decision date.
            count=len(rep);age=(pd.Timestamp(day)-pd.Timestamp(latest_period)).days if chosen else 9999
            priceage=(pd.Timestamp(day)-pd.Timestamp(r['dates'][ids[-1]])).days if len(ids) else 9999
            nmarket=len(ids)
            jy,jm=latest if latest else (0,0)
            now=pd.Timestamp(day);sqljy=now.year-(622 if now.month<3 or now.month==3 and now.day<21 else 621)
            sqljm={1:11,2:12,3:1,4:2,5:3,6:4,7:5,8:6,9:7,10:8,11:9,12:10}[now.month]
            months=sqljy*12+sqljm-jy*12-jm
            dq=(.28 if count>=16 else .16 if count>=8 else .09 if count>=4 else 0)+(.21 if nmarket>=90 else .13 if nmarket>=30 else .06 if nmarket>=10 else 0)+(.09 if price else 0)+(.08 if chosen and months<=5 else .045 if chosen and months<=8 else 0)+(.06 if priceage<=7 else .035 if priceage<=14 else 0)
            s2ok=last is not None and not blocked and bool(last.source_valid) and bool(last.publication_valid) and last.historical_family=='general' and 0<=age<=365
            rows.append(dict(decision_time=day,symbol=sym,company_id=cid,**dict(zip(FIELDS,vals)),net_profit_ttm=net,s2_raw=last.s2_raw if s2ok else np.nan,sources=json.dumps(selected),publication_cutoff=cutoff(day).isoformat(),blocked=blocked,dq=dq,financial_age_days=age,price_date=r['dates'][ids[-1]] if len(ids) else None,share_proof=json.dumps(iv,default=str)))
        pd.DataFrame(rows).to_parquet(path,index=False)
        manifest_name='raw_financial_manifest_'+worker_range[0]+'.json' if worker_range else 'raw_financial_manifest.json'
        write(out/manifest_name,source.raw_manifest)
        print('features',ix+1,'/',len(dates),day,flush=True)
    if worker_range:return None
    d=pd.concat([pd.read_parquet(shards/(day+'.parquet')) for day in dates],ignore_index=True)
    d.to_parquet(out/'feature_panel.parquet',index=False)
    contract=[];coverage=[]
    for j,fld in enumerate(FIELDS):
        available=np.isfinite(d[fld]);tested=bool(available.any()) and j!=15
        contract.append(dict(factor=fld,old_weight=WEIGHTS[j],direction='lower' if j in LOW else 'higher',tested=tested,status='tested' if tested else 'excluded_by_user' if j==15 else 'not_reconstructable',source='dated original-report chain / SQL formula; actual historical price observations',raw_adapter='CorrectedSnapshots plus SQL-specific current-period ratios; monthly input withheld',missing_default=NEUTRAL[j]))
        for day,gp in d.groupby('decision_time'):
            coverage.append(dict(date=day,year=day[:4],factor=fld,observed=int(np.isfinite(gp[fld]).sum()),rows=len(gp),coverage=float(np.isfinite(gp[fld]).mean())))
    pd.DataFrame(contract).to_csv(out/'feature_contract.csv',index=False)
    pd.DataFrame(coverage).to_csv(out/'feature_coverage.csv',index=False)
    pd.DataFrame(coverage).groupby(['year','factor'])[['observed','rows']].sum().assign(coverage=lambda x:x.observed/x.rows).to_csv(out/'feature_coverage_year.csv')
    write(out/'panel_contract.json',dict(start=cal[0],end=cal[-1],sessions=cal,dates=dates,symbols=syms,monthly='not tested: historical proxy rejected, no admitted local monthly publication chain',universe='254 local identities, not survivor-free historical entire market',calendar='inferred positive volume AND value, not official calendar',economic_return='adjusted price index; no extra dividend cash; complete corporate-action economics unknown',independent_holdout=False))
    return d,cal,syms
