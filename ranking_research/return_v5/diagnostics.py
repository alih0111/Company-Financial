"""Descriptive rank evidence; overlapping outcomes never treated as IID trials."""
import bisect
import hashlib
import json
import numpy as np
import pandas as pd
from .common import V2,V3,V4,read,write,sha
from .prices import valid

def digest(rows,fields):
    records=[{k:r.get(k) for k in fields} for r in rows]
    records.sort(key=lambda r:json.dumps(r,sort_keys=True,default=str))
    return hashlib.sha256(json.dumps(records,sort_keys=True,default=str).encode()).hexdigest()

def primary_summary(p,end):
    from ranking_research.top10_six_month.portfolio import summarize
    daily=[r for r in p['daily_nav'] if r['date']<=end]
    fills=[r for r in p['fills'] if r['date']<=end]
    orders=[r for r in p['orders'] if r['decision_time']<=end]
    s=summarize(daily,1e9,orders,fills)
    h=[r for r in p['holdings'] if r['date']==daily[-1]['date']]
    s.update(stale_price_weight=sum(r['value_rial'] for r in h if r['stale_days']>7)/daily[-1]['nav_rial'],
        book_cash_toman=daily[-1]['cash_rial']/10,settled_cash_toman=None,receivables_toman=None,
        end=daily[-1]['date'],economic_final_toman=None,ledger_type='adjusted_index_proxy',
        assumptions='0.5% each side; inferred calendar; normalized units; no modeled dividend cash; retrospective',actual_account=False)
    return s

def run(out,md,d):
    from ranking_research.return_v3.research import payload,score
    from ranking_research.strategy_search.policy_engine import decision_calendar
    from ranking_research.return_v2.market import TradedPrices
    end=read(out/'evaluation_windows.json')['primary_quality_end'];prices=TradedPrices(md)
    specs=[(V3,'D1_eval_existing_choose','existing_choose'),(V3,'D1_eval_balanced_control','balanced'),
        (V3,'D1_eval_S2_P0','S2_monthly'),(V3,'D1_eval_S2_P3','S2_biweekly'),
        (V4,'old_natural_profit_growth','profit_growth'),(V4,'old_natural_equal_weight_all','equal_weight_all')]
    audits=[];rows=[];blocks=[];concentrations=[]
    from ranking_research.strategy_search.wave2 import policies
    ps=policies();protocol=read(V3/'selection_protocol.json')
    for src,eid,name in specs:
        p=payload(src,eid)
        expected={}
        if name in ['existing_choose','S2_monthly','S2_biweekly','balanced']:
            choices=protocol['old_selector_choices'] if name=='existing_choose' else [('S2_P3' if name=='S2_biweekly' else 'S2_P0' if name=='S2_monthly' else 'S0_P0')]*len(protocol['folds'])
            for choice,fold in zip(choices,protocol['folds']):
                pol=ps[choice.split('_')[1]];lo,hi=fold['evaluate'][0],fold['evaluate'][-1]
                boundary=max(x for x in md.cal if x[:7]<lo)
                dates=sorted(set([boundary]+[x for x in decision_calendar(md,boundary,'2026-04-29',pol['cadence']) if lo<=x[:7]<=hi]))
                expected.update({dt:pol['cadence'] for dt in dates})
        else:expected={dt:'monthly' for dt in decision_calendar(md,'2024-10-30','2026-04-29','monthly')}
        observed=[r['decision_time'] for r in p['decisions']]
        audits.append({'method':name,'source':str(src),'payload_sha256':sha(src/'results'/f'{eid}.payload.pkl.gz'),
            'summary_policy':p['summary'].get('policy'),'actual_decisions':len(observed),'expected_decisions':len(expected),
            'calendar_matches_schedule':observed==sorted(expected),'missing_dates':sorted(set(expected)-set(observed)),
            'extra_dates':sorted(set(observed)-set(expected)),'effective_cadence_by_date':expected,
            'metadata_origin':'outer() passes P0 as base policy to run_policy; policy_schedule overrides each decision; summary copied base policy',
            'metadata_misleading':len(set(expected.values()))>1 or (name=='S2_biweekly' and p['summary'].get('policy',{}).get('cadence')!='biweekly'),
            'maximum_target_members':max(r['target_count'] for r in p['decisions']),
            'portfolio_label':'all eligible securities, not top10' if name=='equal_weight_all' else 'maximum 10; stalled exits retain slot',
            'same_session_fills':sum(r['date']<=r['decision_time'] for r in p['fills'])})
        for scope,endpoint in [('primary_quality',end),('old_V4_reconciliation','2026-04-29')]:
            s=primary_summary(p,endpoint)
            rows.append({'method':name,'scope':scope,'run_id':out.name,'source_run':src.name,'source_experiment':eid,**s})
        nav=pd.DataFrame(p['daily_nav']);previous=1e9
        for lo,hi in read(out/'evaluation_windows.json')['complete_outer_blocks']+[read(out/'evaluation_windows.json')['partial_outer_block']]:
            z=nav[nav.date.ge(lo)&nav.date.le(hi)];value=float(z.iloc[-1].nav_rial)
            blocks.append({'method':name,'start':lo,'end':hi,'initial_toman':previous/10,'final_toman':value/10,'return':value/previous-1,
                'complete':hi<= '2025-10-31','descriptive_used_history':True});previous=value
        # Exact accounting attribution of normalized-index cash flows and terminal marks, no strategy rerun after deleting a name.
        actual_end=max(r['date'] for r in p['daily_nav'] if r['date']<=end)
        fills=pd.DataFrame([r for r in p['fills'] if r['date']<=end]);h=pd.DataFrame([r for r in p['holdings'] if r['date']==actual_end])
        pnl={}
        for r in fills.to_dict('records'):
            pnl[r['symbol']]=pnl.get(r['symbol'],0)+(1 if r['side']=='sell' else -1)*r['gross_rial']-r['fee_rial']
        for r in h.to_dict('records'):pnl[r['symbol']]=pnl.get(r['symbol'],0)+r['value_rial']
        for sym,value in pnl.items():concentrations.append({'method':name,'symbol':sym,'pnl_toman':value/10,'scope':'primary_quality','sector':'not linked to archived dated sector classification'})
        assert abs(sum(pnl.values())/10-primary_summary(p,end)['final_toman']+1e8)<.1
    left=payload(V4,'old_pair_S0_F0');right=payload(V4,'old_pair_S0_S0')
    comparisons={}
    for key,fields in {'weights':('decision_time','symbol','target_weight'),
        'scores':('decision_time','symbol','score','rank'),
        'decisions':('decision_time','nav_rial','cash_rial','target_count'),
        'orders':('decision_time','symbol','side','target_index_units','quantity'),
        'fills':('date','decision_time','symbol','side','index_units','index_price_rial','gross_rial','fee_rial')}.items():
        field='selections' if key in ['weights','scores'] else key
        a,b=digest(left[field],fields),digest(right[field],fields)
        comparisons[key]={'left':a,'right':b,'identical':a==b}
    write(out/'effective_policy_audit.json',{'methods':audits,'identical_pair':comparisons,
        'pair_explanation':'shared cohort can be smaller than 10; different scores may yield identical equal target weights. Compare hashes, not filenames.',
        'policy_change_history':protocol['old_selector_choices'],'calendar_certified':False})
    pd.DataFrame(rows).to_csv(out/'machine_comparison.csv',index=False)
    pd.DataFrame(blocks).to_csv(out/'block_performance.csv',index=False)
    pd.DataFrame(concentrations).to_csv(out/'symbol_pnl.csv',index=False)
    stability=[]
    for name in {r['method'] for r in rows}:
        b=[r for r in blocks if r['method']==name and r['complete']];c=[r for r in concentrations if r['method']==name]
        wealth=float(np.prod([1+r['return'] for r in b]));best=max(b,key=lambda r:r['return'])
        bestsymbol=max(c,key=lambda r:r['pnl_toman'])
        stability.append({'method':name,'complete_blocks':len(b),'wealth_without_best_block':wealth/(1+best['return']),
            'best_block_start':best['start'],'largest_contributor':bestsymbol['symbol'],
            'terminal_pnl_excluding_largest_toman':sum(r['pnl_toman'] for r in c)-bestsymbol['pnl_toman'],
            'not_a_tradable_counterfactual':True})
    pd.DataFrame(stability).to_csv(out/'stability_diagnostics.csv',index=False)
    cohort=[]
    for other in ['S0','profit_growth','equal_weight_all']:
        a=payload(V4,'old_pair_'+other+'_F0');b=payload(V4,'old_pair_'+other+'_'+other)
        for endpoint,scope in [(end,'primary_quality'),('2026-04-29','old_V4_reconciliation')]:
            x,y=primary_summary(a,endpoint),primary_summary(b,endpoint)
            cohort.append({'reference':other,'scope':scope,'S2_common_final_toman':x['final_toman'],'reference_common_final_toman':y['final_toman'],
                'rank_effect_common_toman':x['final_toman']-y['final_toman'],'cadence':'monthly both','re_ranked_inside_intersection':True,
                'note':'natural vs shared path differences are path-dependent eligibility effects, not additive causal attribution'})
    pd.DataFrame(cohort).to_csv(out/'cohort_vs_rank_attribution.csv',index=False)
    # Labels use market sessions passing quality criterion, exact traded endpoints, and a locked cutoff.
    qa=pd.read_csv(out/'price_contract_audit.csv');sessions=qa[qa.vintage.eq('D1_execution') & (qa.valid_ohlc_trade/qa.universe).ge(.5) & qa.date.le(end)].date.tolist()
    dates=[x for x in decision_calendar(md,'2022-05-01',end,'monthly') if x in sessions]
    panel=d[d.decision_time.isin(dates)].reset_index(drop=True)
    allrows=[];boundaries=[];states=[]
    for signal in ['F0','profit_growth','S0']:
        frame=score(panel,signal)
        for day,g in frame.groupby('decision_time'):
            g=g[g.eligible].sort_values(['score','symbol'],ascending=[False,True]);n=len(g)
            if not n:continue
            raw=panel[(panel.decision_time==day)&panel.symbol.isin(g.symbol)].set_index('symbol')
            for i,r in enumerate(g.itertuples()):
                if 8<=i+1<=15:boundaries.append({'signal':signal,'date':day,'symbol':r.symbol,'rank':i+1,'score':r.score,
                    'eligible_count':n,'distance_from_rank10':r.score-g.iloc[min(9,n-1)].score})
                z=raw.loc[r.symbol]
                states.append({'signal':signal,'date':day,'symbol':r.symbol,'rank':i+1,'top10':i<10,'quarter_operating':z.quarter_operating,
                    'prior_quarter_operating':z.quarter_prior_operating,'loss_to_profit':bool(z.quarter_operating>0 and z.quarter_prior_operating<=0),
                    'prior_near_zero_assets_scaled':bool(abs(z.quarter_prior_operating)<abs(z.average_assets)*.001),
                    'financial_period_end':z.financial_period_end,'financial_age_days':z.financial_age_days,'sources':str(z.sources)})
            for horizon in [20,60,120]:
                k=bisect.bisect_right(sessions,day)-1
                maturity=sessions[k+horizon] if k>=0 and k+horizon<len(sessions) else None
                vals=[];rankvals=[];buckets={1:[],2:[],3:[]}
                for i,r in enumerate(g.itertuples()):
                    if maturity is None:continue
                    rec=md.data.get(r.symbol);a=rec['dmap'].get(day) if rec else None;b=rec['dmap'].get(maturity) if rec else None
                    if a is None or b is None or not valid(rec,a) or not valid(rec,b):continue
                    # No stale/missing endpoint becomes zero. Adjustment events through label maturity only.
                    from ranking_research.return_v2.market import traded_return
                    ret=traded_return(md,r.symbol,day,maturity,maturity)
                    if not np.isfinite(ret):continue
                    vals.append(ret);rankvals.append(r.score);buckets[min(3,1+int(i*3/n))].append(ret)
                corr=pd.Series(rankvals).corr(pd.Series(vals),method='spearman') if len(vals)>=5 and len(set(rankvals))>1 else np.nan
                allrows.append({'signal':signal,'date':day,'horizon_sessions':horizon,'maturity':maturity,'eligible_count':n,'valid_labels':len(vals),
                    'missing_or_immature_labels':n-len(vals),'rank_ic':corr,'top_third_return':np.mean(buckets[1]) if buckets[1] else np.nan,
                    'middle_third_return':np.mean(buckets[2]) if buckets[2] else np.nan,'bottom_third_return':np.mean(buckets[3]) if buckets[3] else np.nan,
                    'overlapping_not_independent':True,'label_cutoff':end,'ledger':'adjusted index forward return, no cost; diagnostic only'})
        print('signal diagnostics',signal,flush=True)
    pd.DataFrame(allrows).to_csv(out/'signal_diagnostics.csv',index=False)
    pd.DataFrame(boundaries).to_csv(out/'rank_boundary.csv',index=False)
    pd.DataFrame(states).to_csv(out/'financial_state_diagnostics.csv',index=False)
    write(out/'label_contract.json',{'horizons':[20,60,120],'cutoff':end,'exact_positive_trade_endpoints':True,
        'overlap':'descriptive date-level correlations; no IID p-values or confidence intervals','selection':'none; consumed history diagnostic',
        'future_publication':'shared scorer publication cutoff and original report chains; future label allowed only at maturity',
        'industry':'dated industry crosswalk missing; no present-day classification backfill'})
