import bisect
import datetime as dt
import gzip
import json
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
from ranking_research.return_v6.common import ROOT,V2,V3,V4,V5,START,END,DISPLAY_START,read,write,sha,utc,frame_hash

V6=ROOT/'ranking_research/output/return_v6/v6_20261016T144712827439Z'

def register():
    from ranking_research.return_v6.delivery import verify
    verify(V6)
    out=ROOT/'ranking_research/output/return_v7'/('v7_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    sources=[V6/'delivery_manifest.json',V4/'repaired_panel.parquet',V2/'pit_feature_events.parquet',V2/'known_report_gap_events.parquet',V2/'db_securities.parquet',V3/'price_archive_manifest.json',V3/'selection_protocol.json',ROOT/'docs/SOL61_RETURN_V7_EXECUTION.fa.md']
    files=list((ROOT/'ranking_research/return_v7').glob('*.py'))
    write(out/'registration.json',{'registered_at':utc(),'sources':{str(p):sha(p) for p in sources},'code':{str(p):sha(p) for p in files},
      'V6_verified_now':True,'start':START,'end':END,'initial_toman':100000000,'cells':['S2_biweekly_common','momentum_biweekly_common','S2_120_common','momentum_120_common'],
      'features':'existing S2 and momentum_12_1 only','common':'S2 eligible AND finite causal momentum_12_1; cross-sectional ranks recomputed within intersection',
      'calendar':'120 positive-trade inferred market sessions, anchored at V6 start; no fold resets; biweekly exact V6 schedule',
      'execution':'shared frozen V2 policy_engine via V3 snapshot loader; max10 equal target, 0.5% per side, pending orders cancel only at next scheduled decision, same shared timeout/capacity; no new forced exit',
      'terminal':'marked NAV same as S2; separate terminal liquidation diagnostics only on next actual session, no stale-price sales',
      'research_gate':{'wealth_both_controls':'>1','complete_block_wins':2,'complete_blocks':2,'extra_drawdown_max':.05,'max_stale_increase':.05,'minimum_candidates':10},
      'major_gate':'wealth >=1.10 same-conditions previous selector; distinct from research gate',
      'finalist':'largest qualified wealth then method id; natural cohort only this finalist; stress only this finalist plus both controls',
      'stress':['double_cost','delay2','capacity_half','combined'],'no_search':[60,90,180,'ridge alpha','new weights'],
      'network_budget':20,'network_stop':'access barrier or host timeout; no repeated timed-out issuer catalogs',
      'diagnostics':['kaspian two windows','first actual S2 top10 hold','60/120 forward winners and losers'],
      'independent_holdout':False,'production_promotion':False,'brokerage_orders':0})
    return out

def validate(out):
    m=read(out/'registration.json')
    for p,h in {**m['sources'],**m['code']}.items():
        assert sha(p)==h,'Registered input/code changed: '+p

def load():
    from ranking_research.return_v3.common import snapshot
    snapshot(V3)
    from ranking_research.return_v3.market import markets
    _,md,new=markets(V3)
    from ranking_research.return_v2.market import TradedPrices
    return pd.read_parquet(V4/'repaired_panel.parquet'),md,new,TradedPrices(md)

def sessions(md):
    valid=set()
    for r in md.data.values():
        good=(r['vol']>0)&(r['tval']>0)&np.isfinite(r['c'])&(r['c']>0)
        valid.update(np.asarray(r['dates'])[good].tolist())
    return sorted(d for d in valid if START<=d<=END)

def long_dates(md):
    cal=sessions(md)
    assert cal[0]==START
    return cal[::120]

def prepare(out,d,md):
    target=out/'decision_panel.parquet'
    if target.exists():return pd.read_parquet(target)
    from ranking_research.return_v6.experiment import schedule
    dates=sorted(set(schedule(md,read(V3/'selection_protocol.json')))|set(long_dates(md)))
    missing=sorted(set(dates)-set(d.decision_time))
    x=d[d.decision_time.isin(dates)].copy()
    if missing:
        from ranking_research.return_v2.events import panel_asof
        # V4's admitted reports start July 2026; before END, exact V2 event stream is unchanged.
        assert min(r['published_at'] for r in read(V4/'additional_reports.json'))>END
        added=panel_asof(pd.read_parquet(V2/'pit_feature_events.parquet'),md,missing,V2)
        added['s5_raw']=np.nan
        # Same known-release veto as V2 research.prepare, including replacements.
        gaps=pd.read_parquet(V2/'known_report_gap_events.parquet')
        by={c:g for c,g in gaps.groupby('company_id')}
        for idx,a in added.iterrows():
            selected={str(s['period_end']):pd.Timestamp(s['published_at']) for s in json.loads(a.sources)} if isinstance(a.sources,str) else {}
            blocked=[]
            for g in by.get(a.company_id,pd.DataFrame()).itertuples():
                p=g.guard_period
                if p and g.day<=a.decision_time and p<=a.decision_time and (p>str(a.financial_period_end) or p in selected and g.pub>selected[p] and (pd.Timestamp(a.financial_period_end)-pd.Timestamp(p)).days<1000):blocked.append(g.id)
            added.at[idx,'known_report_gap']=bool(blocked)
            added.at[idx,'known_report_gap_reason']='known_unverified_newer_or_replacement' if blocked else ''
            if blocked:added.at[idx,'source_valid']=False;added.at[idx,'used_older_income_report']=True
        x=pd.concat([x,added],ignore_index=True)
    x=x.sort_values(['decision_time','company_id']).reset_index(drop=True)
    x.to_parquet(target,index=False)
    write(out/'schedule_contract.json',{'biweekly':sorted(set(dates)-set(long_dates(md))) if False else sorted(schedule(md,read(V3/'selection_protocol.json'))),
          '120_session':long_dates(md),'valid_session_count':len(sessions(md)),'new_asof_dates':missing,'no_reset_at_block_boundary':True,
          'mandatory_exits':'shared engine has no off-calendar identity/holdability liquidation; no extra forced sale invented',
          'calendar_certified':False})
    # Freeze feature frames before any new portfolio path.
    for kind in ['S2','momentum']:
        for cohort in ['common','natural']:
            f=frame(x,kind,cohort=='common');f.to_parquet(out/f'frame_{kind}_{cohort}.parquet',index=False)
    write(out/'input_freeze.json',{'at':utc(),'panel':sha(target),'frames':{p.name:sha(p) for p in out.glob('frame_*.parquet')},'schedule':sha(out/'schedule_contract.json')})
    return x

def frame(d,kind,common=True):
    from ranking_research.return_v2.signals import score,price_score
    from ranking_research.strategy_search.signals import rank_within
    s=score(d,'S2');mask=s.eligible & np.isfinite(d.momentum_12_1)
    if kind=='S2':return score(d,'S2',mask if common else None)
    f=price_score(d)
    if common:f['eligible']=mask;f['score']=rank_within(d,'momentum_12_1',mask)
    return f

def prior(out,md):
    from ranking_research.return_v3.research import payload
    from ranking_research.return_v6.evaluate import clip
    from ranking_research.strategy_search.policy_engine import decision_calendar
    from ranking_research.return_v6.experiment import schedule
    rows=[]; reuse=[]
    specs=[(V3,'D1_eval_S2_P3','S2_natural','biweekly'),(V3,'D1_eval_existing_choose','existing_choose','protocol'),(V4,'old_natural_profit_growth','profit_growth','monthly'),(V4,'old_natural_equal_weight_all','equal_weight_all','monthly')]
    paths={}
    for src,eid,name,cadence in specs:
        raw=payload(src,eid);p=clip(raw);paths[name]=p
        observed=[a['decision_time'] for a in p['decisions']]
        expected=sorted(schedule(md,read(V3/'selection_protocol.json'))) if cadence=='biweekly' else decision_calendar(md,START, '2026-04-29','monthly') if cadence=='monthly' else None
        if expected is not None:expected=[s for s in expected if s<=END]
        rows.append({'method':name,'actual_cadence':cadence,'decision_dates':';'.join(observed),'matches_expected':observed==expected if expected is not None else None,'V6_generic_csv_cadence_corrected':cadence=='monthly','source_sha256':sha(src/'results'/f'{eid}.payload.pkl.gz')})
        reuse.append({'method':name,'source':str(src/'results'/f'{eid}.payload.pkl.gz'),'sha256':rows[-1]['source_sha256']})
    pd.DataFrame(rows).to_csv(out/'reference_cadence_audit.csv',index=False)
    pd.DataFrame(reuse).to_csv(out/'reused_paths.csv',index=False)
    # Search registries and configuration metadata without replaying known losers.
    found=[]
    for version in ['return_v2','return_v3','return_v4','return_v5','return_v6']:
        for p in (ROOT/'ranking_research/output'/version).rglob('*'):
            if p.is_file() and (('registry' in p.name and p.suffix in ['.json','.jsonl']) or p.name in ['configuration_status.csv','experiment_registry.json']):
                text=p.read_text(encoding='utf-8')
                if any(s in text for s in ['momentum','F4','120']):found.append({'path':str(p),'sha256':sha(p),'mentions_S2_momentum':'F4' in text,'mentions_120':'120' in text,'review':'F4 is 75/25 combination, not pure momentum on same cohort; different horizon/cohort is not exact reuse'})
    write(out/'prior_experiment_search.json',{'files':found,'reuse_rule':'exact frame hash, schedule, prices and initial state only','no_F4_relabeling':True})
    return paths

def replay(out,name,f,md,prices,dates,top=10,start=START,end=END,kwargs=None):
    from ranking_research.strategy_search.policy_engine import run_policy
    from ranking_research.strategy_search.wave2 import policies
    from ranking_research.return_v6.experiment import store
    pol={**policies()['P3'],'top_n':top,'initial_toman':100000000}
    dates=[d for d in dates if start<=d<=end]
    return store(out,name,f,lambda:run_policy(f,md,pol,prices=prices,start=start,end=end,policy_schedule={d:pol for d in dates},**(kwargs or {})),'V7_registered')

def details(name,p,f):
    from ranking_research.return_v6.experiment import describe,blocks
    s=describe(name,p,f)
    h=pd.DataFrame(p['holdings']);nav=pd.DataFrame(p['daily_nav']).set_index('date').nav_rial
    s['maximum_weight']=float((h.value_rial/h.date.map(nav)).max()) if len(h) else 0
    s['maximum_actual_members']=int(h.groupby('date').symbol.nunique().max()) if len(h) else 0
    s['actual_decision_cadences']='120 valid sessions' if '_120_' in name else 'biweekly explicit schedule'
    pnl={}
    for r in p['fills']:pnl[r['symbol']]=pnl.get(r['symbol'],0)+(1 if r['side']=='sell' else -1)*r['gross_rial']-r['fee_rial']
    for r in p['holdings']:
        if r['date']==p['daily_nav'][-1]['date']:pnl[r['symbol']]=pnl.get(r['symbol'],0)+r['value_rial']
    assert abs(sum(pnl.values())/10-s['final_toman']+1e8)<.1
    return s,blocks(name,p),[{'method':name,'symbol':k,'pnl_toman':v/10} for k,v in pnl.items()]

def evaluate(out,d,md,prices,paths):
    from ranking_research.return_v6.experiment import schedule,score_frame,features
    from ranking_research.return_v3.research import score
    bi=sorted(schedule(md,read(V3/'selection_protocol.json')));long=long_dates(md)
    rows=[];br=[];pn=[];fs={};schedules={};counts={'new_matrix':0,'reused_matrix':0}
    for kind in ['S2','momentum']:
        for cadence,dates in [('biweekly',bi),('120',long)]:
            name=f'{kind}_{cadence}_common';f=frame(d[d.decision_time.isin(dates)].reset_index(drop=True),kind)
            fs[name]=f;schedules[name]=dates
            reused=False
            if kind=='S2' and cadence=='biweekly':
                vf=score_frame(features(d[d.decision_time.isin(bi)].reset_index(drop=True)),'s2',True)
                if frame_hash(vf)==frame_hash(f):
                    with gzip.open(V6/'results/S2_common.pkl.gz','rb') as stream:p=pickle.load(stream)
                    write(out/'common_control_reuse.json',{'source':str(V6/'results/S2_common.pkl.gz'),'sha256':sha(V6/'results/S2_common.pkl.gz'),'same_frame_sha256':frame_hash(f),'same_schedule':True,'same_prices':True})
                    reused=True
            if not reused:p=replay(out,name,f,md,prices,dates)
            counts['reused_matrix' if reused else 'new_matrix']+=1
            paths[name]=p;s,b,c=details(name,p,f);rows.append(s);br+=b;pn+=c
            print(name,s['final_toman'],flush=True)
    natural=frame(d[d.decision_time.isin(bi)].reset_index(drop=True),'S2',False)
    for name in ['S2_natural','existing_choose']:
        s,b,c=details(name,paths[name],natural);rows.append(s);br+=b;pn+=c
    pd.DataFrame(rows).to_csv(out/'machine_comparison.csv',index=False);pd.DataFrame(br).to_csv(out/'block_performance.csv',index=False);pd.DataFrame(pn).to_csv(out/'symbol_pnl.csv',index=False)
    by={r['method']:r for r in rows};bdf=pd.DataFrame(br);gates=[]
    for name in fs:
        if name=='S2_biweekly_common':continue
        a=by[name];c=by['S2_biweekly_common'];n=by['S2_natural']
        bb=bdf[bdf.method.eq(name)&bdf.complete]['return'].to_numpy();bc=bdf[bdf.method.eq('S2_biweekly_common')&bdf.complete]['return'].to_numpy();bn=bdf[bdf.method.eq('S2_natural')&bdf.complete]['return'].to_numpy()
        quality=bool(a['minimum_candidates']>=10 and a['stale_price_weight']<=min(c['stale_price_weight'],n['stale_price_weight'])+.05 and a['maximum_actual_members']<=10)
        passed=bool(a['final_toman']>max(c['final_toman'],n['final_toman']) and sum(bb>bc)==2 and sum(bb>bn)==2 and abs(a['max_drawdown'])<=min(abs(c['max_drawdown']),abs(n['max_drawdown']))+.05 and quality)
        gates.append({'method':name,'research_pass':passed,'common_block_wins':int(sum(bb>bc)),'natural_block_wins':int(sum(bb>bn)),'quality_pass':quality,'wealth_ratio_common':a['final_toman']/c['final_toman'],'wealth_ratio_natural':a['final_toman']/n['final_toman'],'wealth_ratio_selector':a['final_toman']/by['existing_choose']['final_toman'],'major_wealth_threshold_met':a['final_toman']/by['existing_choose']['final_toman']>=1.10,'extra_dd_common':abs(a['max_drawdown'])-abs(c['max_drawdown'])})
    qualified=[g for g in gates if g['research_pass']]
    finalist=sorted(qualified,key=lambda g:(-by[g['method']]['final_toman'],g['method']))[0]['method'] if qualified else None
    write(out/'candidate_gate.json',{'candidates':gates,'locked_finalist':finalist,'at':utc(),'independent':False,'promotion':'none'})
    stress=[]
    if finalist:
        from ranking_research.strategy_search.stress import ReducedCapacity
        kind='momentum' if finalist.startswith('momentum') else 'S2'
        dates=schedules[finalist];fn=frame(d[d.decision_time.isin(dates)].reset_index(drop=True),kind,False)
        p=replay(out,'finalist_natural',fn,md,prices,dates);s,b,c=details('finalist_natural',p,fn)
        write(out/'finalist_natural.json',s)
        for scenario,args in [('double_cost',{'cost_mult':2}),('delay2',{'delay':2}),('capacity_half',{'capacity':.5}),('combined',{'cost_mult':2,'delay':2,'capacity':.5})]:
            for name in [finalist,'S2_biweekly_common','S2_natural']:
                cap=args.get('capacity',1);px=ReducedCapacity(prices,cap) if cap!=1 else prices
                f=(natural if name=='S2_natural' else fs[name]).copy();f.capacity_rial*=cap
                p=replay(out,'stress_'+scenario+'_'+name,f,md,px,bi if name=='S2_natural' else schedules[name],kwargs={k:v for k,v in args.items() if k!='capacity'})
                s,_,_=details(name,p,f);stress.append({'scenario':scenario,**s})
        pd.DataFrame(stress).to_csv(out/'stress_comparison.csv',index=False)
    write(out/'path_counts.json',{**counts,'reused_references':4,'failed':0,'stress_paths':len(stress),'natural_paths':int(bool(finalist)),'not_run_stress':0 if finalist else 12})
    return paths
