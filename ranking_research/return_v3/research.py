"""Frozen V2 controls first, at most twelve interpretable candidates second."""
import copy
import numpy as np
import pandas as pd
from .common import SOURCE,read,write,sha,done,checkpoint,seal_code

def data(out):return pd.read_parquet(out/'D1_panel.parquet')

def prepare(out,md):
    if (out/'D1_panel.parquet').exists():return data(out)
    from ranking_research.return_v2.market import fresh
    d=pd.read_parquet(SOURCE/'decision_panel.parquet')
    d=d[d.decision_time.ge('2022-04-01')].copy().reset_index(drop=True)
    # Pure market values recomputed on revised OHLC, volume and value; fundamentals unchanged.
    updates=[]
    for i,r in enumerate(d.itertuples()):
        updates.append(fresh(md,r.symbol,r.decision_time))
        if i and i%20000==0:print('D1 market features',i,'/',len(d),flush=True)
    u=pd.DataFrame(updates,index=d.index)
    for c in u:d[c]=u[c]
    d['market_cap']=d.shares_outstanding*d.decision_price
    d['operating_yield']=d.operating_profit_ttm/d.market_cap.where(d.market_cap.gt(0))
    d.to_parquet(out/'D1_panel.parquet',index=False)
    write(out/'financial_inputs.json',{'panel_sha256':sha(out/'D1_panel.parquet'),
        'data_packages_sha256':sha(out/'data_packages.json'),'price_revision_sha256':sha(out/'price_row_revisions.csv'),
        'calendar':'V2 archive calendar; official validity unproved',
        'economic_contract':'normalized adjusted index, no cash dividend or real share accounting',
        'start':'2022-05-01','end':'2026-09-30','old_evaluation':['2024-11-02','2026-04-29'],
        'D2_status':'not admitted: missing complete new event/economic/lifecycle evidence',
        'longest_jointly_certified_economic_interval':None,
        'retrospective':True,'new_fundamental_versions_admitted':0})
    return d

def execute(out,eid,config,runner):
    from ranking_research.strategy_search.harness import _record
    from ranking_research.strategy_search.registry import Registry
    config={**config,'v3_code_freeze_sha256':sha(out/'financial_code_freeze.json')}
    return _record(Registry(out),eid,eid,config,'V3 registered research; uncertified adjusted-index execution',
        config.get('scope','control'),sha(out/'financial_inputs.json'),out/'results',runner,out/'financial_inputs.json')

def payload(out,eid):
    from ranking_research.strategy_search.stages import load_payload
    return load_payload(out,eid)

def score(d,name,cohort=None):
    from ranking_research.return_v2.signals import score as prior,price_score
    from ranking_research.strategy_search.signals import baseline_frame,rank_within,base_masks
    if name.startswith('S'):return prior(d,name,cohort)
    if name=='profit_growth':return baseline_frame(d,name)
    if name=='price_momentum':return price_score(d)
    if name=='equal_weight_all':
        f=price_score(d);f['eligible']=base_masks(d)[0];f['score']=0.;return f
    if name=='F0':return prior(d,'S2',cohort)
    base=prior(d,'S2',cohort);mask=base.eligible.copy()
    if name=='F1':mask &= d.quarter_operating.gt(0)
    elif name=='F2':mask &= np.isfinite(d.previous_quarter_s2_raw)
    elif name=='F3':mask &= np.isfinite(d.cash_asset_quality)
    elif name=='F4':mask &= np.isfinite(d.momentum_12_1)
    elif name=='F5':mask &= np.isfinite(d.s5_raw)
    else:raise ValueError(name)
    value=rank_within(d,'s2_raw',mask)
    if name=='F2':value=(value+rank_within(d,'previous_quarter_s2_raw',mask))/2
    if name in ('F3','F4','F5'):
        c={'F3':'cash_asset_quality','F4':'momentum_12_1','F5':'s5_raw'}[name]
        value=.75*value+.25*rank_within(d,c,mask)
    base['eligible']=mask & np.isfinite(value);base['score']=value.where(base.eligible)
    return base

def outer(d,md,prices,choices,fs,end,kwargs=None,initial=100000000):
    from ranking_research.strategy_search.policy_engine import decision_calendar,run_policy
    from ranking_research.strategy_search.wave2 import policies
    from ranking_research.top10_six_month.portfolio import summarize
    from ranking_research.strategy_search.stages import reblock
    frames=[];schedule={};ps=policies()
    for eid,fold in zip(choices,fs):
        s,pid=eid.split('_',1);pol=ps[pid]
        lo,hi=fold['evaluate'][0],fold['evaluate'][-1]
        boundary=max(x for x in md.cal if x[:7]<lo)
        dates=sorted(set([boundary]+[x for x in decision_calendar(md,boundary,end,pol['cadence']) if lo<=x[:7]<=hi]))
        frames.append(score(d[d.decision_time.isin(dates)].reset_index(drop=True),s))
        schedule.update({day:pol for day in dates})
    frame=pd.concat(frames,ignore_index=True).drop_duplicates(['decision_time','company_id'],keep='last')
    first=fs[0]['evaluate'][0];start=max(x for x in md.cal if x[:7]<first)
    r=run_policy(frame,md,{**ps['P0'],'initial_toman':initial},prices=prices,start=start,end=end,policy_schedule=schedule,**(kwargs or {}))
    r['daily_nav']=[v for v in r['daily_nav'] if v['date'][:7]>=first]
    r['holdings']=[v for v in r['holdings'] if v['date'][:7]>=first]
    r['summary'].update(summarize(r['daily_nav'],initial*10,r['orders'],r['fills']))
    r['selection_history']=choices
    return reblock(r)

def metric(p,months):
    lo,hi=months[0],months[-1];nav=p['daily_nav']
    prior=[r for r in nav if r['date'][:7]<lo]
    initial=prior[-1]['nav_rial'] if prior else p['summary']['initial_toman']*10
    vals=[initial]+[r['nav_rial'] for r in nav if lo<=r['date'][:7]<=hi]
    n=np.array(vals);assert len(n)>1
    return {'wealth':float(n[-1]/n[0]),'dd':float((n/np.maximum.accumulate(n)-1).min()),
        'turnover':sum(r['gross_rial'] for r in p['fills'] if lo<=r['date'][:7]<=hi)/initial}

def choose(paths,configs,fs,baseline='S0_P0'):
    choices=[];evidence=[]
    for i,fold in enumerate(fs):
        bt=metric(paths[baseline],fold['train']);bs=metric(paths[baseline],fold['select'])
        rows=[]
        for eid in sorted(configs):
            tr=metric(paths[eid],fold['train']);se=metric(paths[eid],fold['select'])
            passed=tr['wealth']>1 and abs(tr['dd'])<=abs(bt['dd'])+.05 and abs(se['dd'])<=abs(bs['dd'])+.05
            rows.append({'fold':i,'configuration':eid,'train_wealth':tr['wealth'],'train_dd':tr['dd'],
                'selection_wealth':se['wealth'],'selection_dd':se['dd'],'selection_turnover':se['turnover'],
                'cutoff_month':fold['select'][-1],'pass':passed})
        valid=sorted([r for r in rows if r['pass']],key=lambda r:(-r['selection_wealth'],r['selection_turnover'],r['configuration']))
        selected=valid[0]['configuration'] if valid else baseline;choices.append(selected)
        evidence.extend([{**r,'chosen':selected} for r in rows])
    return choices,evidence

def summary(eid,p,**extra):
    end=p['daily_nav'][-1];h=[r for r in p['holdings'] if r['date']==end['date']]
    return {'experiment_id':eid,**p['summary'],'book_cash_toman':end['cash_rial']/10,
        'stale_price_weight':sum(r['value_rial'] for r in h if r['stale_days']>7)/end['nav_rial'],
        'unsold_positions':len(h),'settled_cash_toman':None,'receivables_toman':None,
        'economic_final_toman':None,'accounting_status':'adjusted_index_proxy_not_economic_wealth',**extra}

def fixed(out,md,d):
    if done(out,'D'):return
    from ranking_research.return_v2.market import TradedPrices
    from ranking_research.strategy_search.policy_engine import run_policy,decision_calendar
    from ranking_research.strategy_search.wave2 import policies
    ps=policies();prices=TradedPrices(md)
    protocol=read(SOURCE/'selection_protocol.json');fs=protocol['folds'];end=protocol['outer_end']
    names=pd.read_csv(SOURCE/'configuration_status.csv').query('status == "tested"').configuration.tolist()
    paths={};rows=[]
    for eid in names:
        s,pid=eid.split('_');pol=ps[pid]
        dates=decision_calendar(md,'2022-05-01','2026-09-30',pol['cadence'])
        f=score(d[d.decision_time.isin(dates)].reset_index(drop=True),s)
        p=execute(out,'D1_'+eid,{'scope':'fixed_v2','signal':s,'policy':pol,'periods':{'start':'2022-05-01','end':'2026-09-30'}},
            lambda f=f,pol=pol:run_policy(f,md,pol,prices=prices,start='2022-05-01',end='2026-09-30'))
        paths[eid]=p;rows.append(summary('D1_'+eid,p,scope='fixed_v2'))
        print('D fixed',eid,flush=True)
    choices,evidence=choose(paths,names,fs)
    newprotocol={'folds':fs,'old_selector_choices':choices,'old_counterfactual_choices':protocol['choices']['existing_choose'],
        'outer_end':end,'continuous_account':True,'retrospective':True,'independent_holdout':False}
    write(out/'selection_protocol.json',newprotocol)
    pd.DataFrame(evidence).to_csv(out/'old_selector_evidence.csv',index=False)
    compare=[];effects=[]
    # Two identical V2 selectors count as one reference; prove identity from trajectories.
    a=pd.read_csv(SOURCE/'results/eval_existing_choose.nav.csv');b=pd.read_csv(SOURCE/'results/eval_two_of_three.nav.csv')
    assert a.equals(b)
    write(out/'old_selector_identity.json',{'same_values':True,'existing_nav_sha256':sha(SOURCE/'results/eval_existing_choose.nav.csv'),
        'alternative_nav_sha256':sha(SOURCE/'results/eval_two_of_three.nav.csv'),'independent_evidence_count':1})
    for name,ch in {'balanced_control':['S0_P0']*len(fs),'S2_P0':['S2_P0']*len(fs),
        'S2_P3':['S2_P3']*len(fs),'S1_P3':['S1_P3']*len(fs),'existing_choose':choices,
        'old_choices_counterfactual':protocol['choices']['existing_choose']}.items():
        eid='D1_eval_'+name
        p=execute(out,eid,{'scope':'old_period','choices':ch,'periods':{'start':'2024-11-02','end':end}},
            lambda ch=ch:outer(d,md,prices,ch,fs,end))
        compare.append(summary(eid,p,method=name,data_package='D1'))
        oldeid='eval_'+name
        if (SOURCE/'results'/f'{oldeid}.json').exists():
            old=read(SOURCE/'results'/f'{oldeid}.json')['summary']
            compare.append({**old,'method':name,'data_package':'D0','accounting_status':'adjusted_index_proxy_not_economic_wealth'})
            effects.append({'method':name,'start':old['start'],'end':end,'D0_final_toman':old['final_toman'],
                'D1_final_toman':p['summary']['final_toman'],'price_revision_effect_toman':p['summary']['final_toman']-old['final_toman'],
                'selector_reselected':name=='existing_choose'})
    pd.DataFrame(rows).to_csv(out/'fixed_v2_paths.csv',index=False)
    pd.DataFrame(compare).to_csv(out/'same_period_100m_comparison.csv',index=False)
    pd.DataFrame(effects).to_csv(out/'price_revision_effect.csv',index=False)
    checkpoint(out,'D',[out/n for n in ['fixed_v2_paths.csv','same_period_100m_comparison.csv','price_revision_effect.csv','selection_protocol.json','old_selector_evidence.csv','old_selector_identity.json']])
    print('D complete; corrected comparison available; no new weights searched yet',flush=True)

def variants(out,md,d):
    if done(out,'E'):return
    assert done(out,'D'),'corrected comparison must precede new formula search'
    from .features import augment
    d=augment(out,d)
    from ranking_research.return_v2.market import TradedPrices
    from ranking_research.strategy_search.policy_engine import run_policy,decision_calendar
    from ranking_research.strategy_search.wave2 import policies
    from ranking_research.strategy_search.harness import assert_cohorts_equal
    ps=policies();prices=TradedPrices(md);protocol=read(out/'selection_protocol.json');fs=protocol['folds'];end=protocol['outer_end']
    preg={'before_first_new_candidate_performance':True,'features':{
        'F0':'S2 unchanged','F1':'S2 rank with latest independent OP quarter >0',
        'F2':'mean ranks S2 latest and prior independent quarter; reconstruct same source versions/positive mean assets; require exact current S2 reproduction',
        'F3':'.75 rank S2 + .25 rank (OCF_TTM - NI_TTM)/positive mean assets',
        'F4':'.75 rank S2 + .25 rank momentum12to1',
        'F5':'.75 rank S2 + .25 rank same-season 3monthly sales growth; missing six body/unit/version chains'},
        'policies':['P0','P3'],'maximum_configurations':12,'missing':'not_tested, no replacement or zero fill',
        'tie_break':'score descending, company_id ascending','pairwise':'rerank F0 and candidate within per-date intersection',
        'selection':'V2 train wealth>1, DD<=balanced+5pp on train and selection, select wealth descending then turnover then id; fallback S0_P0',
        'folds':fs,'financial_inputs_sha256':sha(out/'financial_inputs.json'),'variant_panel_sha256':sha(out/'variant_panel.parquet'),'v3_code_sha256':sha(out/'financial_code_freeze.json'),
        'acceptance':{'wealth_vs_S2_selector':1.1,'wealth_vs_balanced':1.1,'block_majority':True,'extra_dd_max':.05,
            'remove_best_log_block_positive':True,'combined_advantage_positive':True},
        'stress':['double_cost','delay2','capacity_half','combined','capital5x','unknown_event_factors'],
        'retrospective':True,'independent_holdout':False,'weight_changes_after_results':False}
    p=out/'v3_preregistration.json'
    if p.exists():assert read(p)==preg
    else:write(p,preg)
    rows=[];coverage=[];status=[];paths={'S0_P0':payload(out,'D1_S0_P0')};names=[]
    for pid in ['P0','P3']:
        dates=decision_calendar(md,'2022-05-01','2026-09-30',ps[pid]['cadence'])
        panel=d[d.decision_time.isin(dates)].reset_index(drop=True)
        for s in ['F0','F1','F2','F3','F4','F5']:
            f=score(panel,s);eid=s+'_'+pid
            usable=int(f.groupby('decision_time').eligible.sum().ge(2).sum())
            status.append({'configuration':eid,'status':'tested' if usable else 'not_tested','usable_dates':usable,
                'reason':'' if usable else ('prior_quarter_versioned_average_assets_not_materialized' if s=='F2' else 'six_monthly_bodies_versions_units_not_verified')})
            for day,g in f.groupby('decision_time'):
                coverage.append({'configuration':eid,'decision_time':day,'universe':len(g),'eligible':int(g.eligible.sum()),'scope':'natural'})
            if not usable:continue
            pay=execute(out,eid,{'scope':'variant','signal':s,'policy':ps[pid],'preregistration_sha256':sha(p),
                'periods':{'start':'2022-05-01','end':'2026-09-30'}},lambda f=f,pid=pid:run_policy(f,md,ps[pid],prices=prices,start='2022-05-01',end='2026-09-30'))
            paths[eid]=pay;names.append(eid);rows.append(summary(eid,pay,scope='natural',method=s,policy_id=pid))
            if s!='F0':
                base=score(panel,'F0');common=f.eligible.to_numpy()&base.eligible.to_numpy()
                cf,bf=score(panel,s,common),score(panel,'F0',common);assert_cohorts_equal(cf,bf,eid)
                for suffix,ff in [('pair',cf),('pair_reference',bf)]:
                    peid=eid+'_'+suffix
                    pay=execute(out,peid,{'scope':suffix,'signal':s,'policy':ps[pid],'preregistration_sha256':sha(p),
                        'periods':{'start':'2022-05-01','end':'2026-09-30'}},lambda ff=ff,pid=pid:run_policy(ff,md,ps[pid],prices=prices,start='2022-05-01',end='2026-09-30'))
                    rows.append(summary(peid,pay,scope=suffix,method=s,policy_id=pid))
            print('E',eid,flush=True)
    for s in ['profit_growth','price_momentum','equal_weight_all']:
        dates=decision_calendar(md,'2022-05-01','2026-09-30','monthly');panel=d[d.decision_time.isin(dates)].reset_index(drop=True)
        f=score(panel,s);pol={**ps['P0'],'model':'equal_weight'} if s=='equal_weight_all' else ps['P0']
        pay=execute(out,s,{'scope':'benchmark','policy':pol,'periods':{'start':'2022-05-01','end':'2026-09-30'}},
            lambda f=f,pol=pol:run_policy(f,md,pol,prices=prices,start='2022-05-01',end='2026-09-30'))
        rows.append(summary(s,pay,scope='benchmark',method=s,policy_id='P0'))
    choices,evidence=choose(paths,names,fs)
    write(out/'new_selector_choices.json',{'choices':choices,'old_choices':protocol['old_selector_choices'],'folds':fs})
    pd.DataFrame(evidence).to_csv(out/'walk_forward_selection.csv',index=False)
    pay=execute(out,'new_selector',{'scope':'evaluation','choices':choices,'periods':{'start':'2024-11-02','end':end}},
        lambda:outer(d,md,prices,choices,fs,end))
    rows.append(summary('new_selector',pay,scope='evaluation',method='new_selector'))
    pd.DataFrame(rows).to_csv(out/'variant_comparison.csv',index=False)
    pd.DataFrame(coverage).to_csv(out/'coverage_before_after.csv',index=False)
    pd.DataFrame(status).to_csv(out/'configuration_status.csv',index=False)
    # Reproducible per-symbol entry/exit traces are retained in every order and selection artifact.
    checkpoint(out,'E',[out/n for n in ['variant_comparison.csv','coverage_before_after.csv','configuration_status.csv','walk_forward_selection.csv','new_selector_choices.json','v3_preregistration.json']])
