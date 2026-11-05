import copy
import json
import numpy as np
import pandas as pd
from .common import V3,V4,V5,START,DISPLAY_START,END,read,write,sha,utc,frame_hash
from .experiment import schedule,store,run_frame,score_frame,describe,blocks,selector_stress

def clip(p):
    r=copy.deepcopy(p)
    for key in ['daily_nav','holdings','fills','ledger']:
        if key in r:r[key]=[a for a in r[key] if a.get('date','')<=END]
    for key in ['decisions','orders','selections']:
        if key in r:r[key]=[a for a in r[key] if a.get('decision_time','')<=END]
    return r

def run(out,d,md):
    if (out/'candidate_gate.json').exists():return
    from ranking_research.return_v2.market import TradedPrices
    from ranking_research.return_v3.research import payload,score
    from ranking_research.strategy_search.policy_engine import run_policy,decision_calendar
    from ranking_research.strategy_search.wave2 import policies
    prices=TradedPrices(md);protocol=read(V3/'selection_protocol.json');sch=schedule(md,protocol)
    write(out/'effective_protocol.json',{'path':str(V3/'selection_protocol.json'),'sha256':sha(V3/'selection_protocol.json'),
        'protocol':protocol,'S2_actual_schedule':{k:v['cadence'] for k,v in sch.items()},
        'start_contract':{'initial_toman':100000000,'decision_start':START,'display_start':DISPLAY_START,
            'all_V6_account_nav_retained':True,'source_V5_nav_clipping_disclosed':True,'no_reset_at_blocks':True}})
    m=pd.read_parquet(out/'model_frames.parquet')
    paths={};frames={};rows=[];blockrows=[];reuse=[]
    base=score(d[d.decision_time.isin(sch)].reset_index(drop=True),'F0')
    ref=clip(payload(V3,'D1_eval_S2_P3'));paths['S2_publication']=ref;frames['S2_publication']=base
    old=clip(payload(V3,'D1_eval_existing_choose'));paths['existing_choose']=old;frames['existing_choose']=base
    refs=[(V3,'D1_eval_S2_P3','S2_publication'),(V3,'D1_eval_existing_choose','existing_choose'),
          (V4,'old_natural_profit_growth','profit_growth'),(V4,'old_natural_equal_weight_all','equal_weight_all')]
    for src,eid,name in refs:
        p=clip(payload(src,eid));paths[name]=p
        if name in ['profit_growth','equal_weight_all']:
            dates=decision_calendar(md,START,'2026-04-29','monthly')
            ff=score(d[d.decision_time.isin(dates)&d.decision_time.le(END)].reset_index(drop=True),name)
        else:ff=base
        frames[name]=ff
        rows.append(describe(name,p,ff));blockrows+=blocks(name,p)
        reuse.append({'method':name,'source_run':str(src),'experiment':eid,'sha256':sha(src/'results'/f'{eid}.payload.pkl.gz'),'reuse':'exact frozen data/source contract'})
    monthly=pd.read_parquet(out/'monthly_counterfactual.parquet')
    monthly=monthly[monthly.decision_time.isin(sch)].reset_index(drop=True)
    mf=score(monthly,'F0')
    pp=store(out,'D1_monthly_counterfactual',mf,lambda:run_frame(mf,md,prices,sch),'data_ablation')
    paths['D1_monthly_counterfactual']=pp;frames['D1_monthly_counterfactual']=mf
    rows.append(describe('D1_monthly_counterfactual',pp,mf,'data_ablation'));blockrows+=blocks('D1_monthly_counterfactual',pp)
    trained=pd.read_csv(out/'training_cutoffs.csv').status.eq('trained').any()
    specs=[('S2_common','s2'),('equal_feature_ranks','equal')]+([('ridge_rank','ridge')] if trained else [])
    for name,kind in specs:
        f=score_frame(m,kind,True);frames[name]=f
        p=store(out,name,f,lambda f=f:run_frame(f,md,prices,sch),'same_feature_cohort')
        paths[name]=p;rows.append(describe(name,p,f,'common'));blockrows+=blocks(name,p)
        print(name,rows[-1]['final_toman'],flush=True)
    pd.DataFrame(reuse).to_csv(out/'reused_paths.csv',index=False)
    pd.DataFrame(rows).to_csv(out/'machine_comparison.csv',index=False)
    pd.DataFrame(blockrows).to_csv(out/'block_performance.csv',index=False)
    ablation=[]
    for name,f,p in [('D0_V5_actual',base,ref),('D1_recovered_monthly',mf,pp),('D2_recovered_publication',base,ref)]:
        s=describe(name,p,f);ablation.append({'data_state':name,'input_frame_sha256':frame_hash(f),
            'input_differs_from_D0':frame_hash(f)!=frame_hash(base),'target_differs_from_D0':p['selections']!=ref['selections'],
            'final_toman':s['final_toman'],'difference_from_D0_toman':s['final_toman']-rows[0]['final_toman'],
            'wealth_ratio_to_D0':s['final_toman']/rows[0]['final_toman'],'historical_reports_recovered':0,
            'interpretation':'monthly counterfactual, not previous V5 behavior' if name.startswith('D1') else 'actual publication-aware input; unchanged S2 formula',
            'financial_replay':'new' if name.startswith('D1') else 'reused'})
    pd.DataFrame(ablation).to_csv(out/'data_ablation.csv',index=False)
    by={r['method']:r for r in rows};bdf=pd.DataFrame(blockrows);gates=[]
    for name in ['equal_feature_ranks','ridge_rank']:
        if name not in paths:
            gates.append({'method':name,'status':'not_tested_insufficient_dates','research_pass':False});continue
        candidate=by[name];common=by['S2_common'];natural=by['S2_publication']
        cb=bdf[bdf.method.eq(name)&bdf.complete]['return'].to_numpy()
        rb=bdf[bdf.method.eq('S2_common')&bdf.complete]['return'].to_numpy()
        nb=bdf[bdf.method.eq('S2_publication')&bdf.complete]['return'].to_numpy()
        q=bool(candidate['stale_price_weight']<=common['stale_price_weight']+.05 and candidate['minimum_candidates']>=10)
        same=bool(candidate['final_toman']>common['final_toman'] and sum(cb>rb)>len(cb)/2 and abs(candidate['max_drawdown'])<=abs(common['max_drawdown'])+.05 and q)
        total=bool(candidate['final_toman']>natural['final_toman'] and sum(cb>nb)>len(cb)/2 and abs(candidate['max_drawdown'])<=abs(natural['max_drawdown'])+.05 and q)
        best=int(np.argmax(cb));without=np.prod(1+np.delete(cb,best));refwithout=np.prod(1+np.delete(rb,best))
        nav=pd.DataFrame(paths[name]['daily_nav']);fills=pd.DataFrame(paths[name]['fills']);h=pd.DataFrame(paths[name]['holdings']);last=nav.date.max()
        pnl={}
        for a in fills.to_dict('records'):pnl[a['symbol']]=pnl.get(a['symbol'],0)+(1 if a['side']=='sell' else -1)*a['gross_rial']-a['fee_rial']
        for a in h[h.date.eq(last)].to_dict('records'):pnl[a['symbol']]=pnl.get(a['symbol'],0)+a['value_rial']
        pd.DataFrame([{'symbol':s,'pnl_toman':v/10} for s,v in pnl.items()]).to_csv(out/(name+'_concentration.csv'),index=False)
        largest=max(pnl.values(),default=0)/10;adv=candidate['final_toman']-common['final_toman']
        gates.append({'method':name,'same_cohort_research_pass':same,'natural_total_research_pass':total,'research_pass':same and total,
            'wealth_ratio_same_cohort_S2':candidate['final_toman']/common['final_toman'],
            'wealth_ratio_natural_S2':candidate['final_toman']/natural['final_toman'],
            'wealth_ratio_same_conditions_selector':candidate['final_toman']/by['existing_choose']['final_toman'],
            'wealth_ratio_frozen_V5_selector':candidate['final_toman']/by['existing_choose']['final_toman'],
            'complete_blocks':len(cb),'common_block_wins':int(sum(cb>rb)),'natural_block_wins':int(sum(cb>nb)),
            'extra_drawdown_same_cohort':abs(candidate['max_drawdown'])-abs(common['max_drawdown']),
            'remove_best_block_wealth':float(without),'reference_same_removed_block_wealth':float(refwithout),
            'largest_contributor_pnl_toman':largest,'largest_contributor_to_advantage':largest/adv if adv else None,
            'data_quality_pass':q,'status':'research_candidate_needs_stress' if same and total else 'no_qualified_winner',
            'independent_evidence':False,'stress_pass':None,'major_improvement_pass':False})
    qualified=[g for g in gates if g['research_pass']]
    stressrows=[]
    if qualified:
        finalist=max(qualified,key=lambda g:(by[g['method']]['final_toman'],g['method']))['method']
        from ranking_research.strategy_search.stress import ReducedCapacity
        scenarios={'double_cost':{'cost_mult':2},'delay2':{'delay':2},'capacity_half':{'capacity':.5},'combined':{'cost_mult':2,'delay':2,'capacity':.5}}
        for label,args in scenarios.items():
            cap=args.get('capacity',1);px=ReducedCapacity(prices,cap) if cap!=1 else prices
            kw={k:v for k,v in args.items() if k!='capacity'}
            for name in [finalist,'S2_common','S2_publication','existing_choose']:
                frame=frames[name].copy();frame['capacity_rial']*=cap
                if name=='existing_choose':
                    panel=d.copy();panel['capacity_rial']*=cap
                    runner=lambda panel=panel,px=px,kw=kw:selector_stress(panel,md,px,protocol,kw)
                else:runner=lambda frame=frame,px=px,kw=kw:run_frame(frame,md,px,sch,kw)
                p=clip(store(out,'stress_'+name+'_'+label,frame,runner,'stress'))
                stressrows.append({'scenario':label,**describe(name,p,frame,'stress')})
        sd=pd.DataFrame(stressrows);sd.to_csv(out/'stress_comparison.csv',index=False)
        g=next(g for g in gates if g['method']==finalist)
        stresspass=all(float(sd[sd.method.eq(finalist)&sd.scenario.eq(s)].final_toman.iloc[0])>
                       float(sd[sd.method.eq('S2_common')&sd.scenario.eq(s)].final_toman.iloc[0]) for s in scenarios)
        g['stress_pass']=stresspass
        g['major_improvement_pass']=bool(stresspass and g['wealth_ratio_same_conditions_selector']>=1.10)
        g['status']='research_improvement' if stresspass else 'no_qualified_winner'
        if stresspass:
            for name in [finalist,'S2_common']:
                frame=frames[name];p=store(out,'capital500m_'+name,frame,lambda frame=frame:run_frame(frame,md,prices,sch,initial=500000000),'capacity_500m')
                # primary_summary is a 100m helper: scale account metrics independently for this test.
                write(out/('capital500m_'+name+'.json'),{'initial_toman':500000000,'final_toman':p['daily_nav'][-1]['nav_rial']/10,'purpose':'capacity only; not candidate selection'})
    write(out/'candidate_gate.json',{'candidates':gates,'promotion':'none; S2 preserved; no economic/real-account validation',
        'stress':'executed for one finalist' if qualified else 'not_tested; no research-qualified finalist',
        'capital500m':'see capacity artifacts' if any(g.get('stress_pass') for g in gates) else 'not_tested; no stress-passing finalist',
        'data_recovered':False,'selector_reselection':'same data => locked V3 choices reused, no redundant financial paths',
        'limitations':['consumed history','two complete blocks','overlapping training labels','local 254 identities; not survivor-free market']})
