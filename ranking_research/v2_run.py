"""Execute the registered V2 design; freeze evidence and retain every failure."""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
os.environ['PGOPTIONS']='-c default_transaction_read_only=on'
os.environ.setdefault('CDF_PILOT_DB','company_financial_analytics_shadow_v121')
from v2_inputs import ArchiveSnapshots,feature_row,CM,H
from v2_engine import score_frame
import run as R
import reconstructed_replay as B
from evaluate import diagnostics,paired_ci,forward


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,obj):R.write(Path(path),B.safe_json(obj))
def public(metric):return {k:v for k,v in metric.items() if not k.startswith('_')}


def baseline_common(frame,metric_rows,policy):
    """Both baselines recomputed on identical input population, not old percentiles."""
    factors={'roe_level':('roe',True),'cash_conversion':('cash_conversion',True),
        'leverage':('debt_ratio',False),'pe':('pe',False),'pb':('pb',False),'ps':('ps',False),
        'operating_margin':('operating_margin',True),'net_margin':('net_margin',True),
        'momentum_6m_rel':('qvt_momentum_6m_rel',True),'momentum_3m_rel':('qvt_momentum_3m_rel',True),
        'liquidity':('qvt_liquidity',True),'low_volatility':('qvt_low_volatility',False)}
    complete=frame.eligible.copy()
    for field,_ in factors.values():complete &= np.isfinite(frame[field].to_numpy(dtype=float))
    complete &= (frame[['pe','pb','ps','roe']]>0).all(axis=1)
    groups=[]
    weights=read(ROOT/'qvt_backtest/reconstructed_protocol.json')['weights']
    for date,group in frame.loc[complete].groupby('as_of',sort=True):
        if len(group)<policy['minimum_population']:continue
        eng=CM.Engine(dt.date.fromisoformat(date),B.cutoff_for(date))
        eng.metrics={r['company_id']:copy.deepcopy(metric_rows[(date,r['company_id'])]) for r in group.to_dict('records')}
        eng.rank_and_score()
        group=group.copy()
        group['SCREEN_CORRECTED']=[eng.metrics[cid]['quant_score'] for cid in group.company_id]
        ranks={factor:R.ranked(group[field].to_numpy(dtype=float),higher) for factor,(field,higher) in factors.items()}
        ranks['margins']=.6*ranks['operating_margin']+.4*ranks['net_margin']
        group['QVT76_CORRECTED']=sum(weights[f]*ranks[f] for f in weights)
        for f in weights:group['qvt_p_'+f]=ranks[f]
        groups.append(group)
    return pd.concat(groups,ignore_index=True) if groups else pd.DataFrame()


def prepare(out,policy):
    previous=read(ROOT/'qvt_backtest/output/reconstructed_latest.json')
    baseline=Path(previous['run_path'])
    if read(baseline/'audit.json')['status']!='passed':raise ValueError('old baseline audit missing')
    paths={'reports':H.OUT/'reports.json','shares':H.OUT/'share_intervals.json',
        'panel':ROOT/'score_v2_research/pit_feature_panel.parquet','family':ROOT/'qvt_paper/output/current_ranking.json',
        'qvt_policy':ROOT/'qvt_backtest/reconstructed_protocol.json',
        'old_scores':baseline/'scores.parquet','old_audit':baseline/'audit.json',
        'engine':HERE/'v2_engine.py','inputs':HERE/'v2_inputs.py','runner':Path(__file__),
        'canonical_engine':Path(CM.__file__),'financial_calendar':Path(CM.__file__).with_name('fiscal_calendar.py'),
        'ttm':Path(CM.__file__).with_name('report_chain_ttm.py'),'timing':ROOT/'qvt_backtest/run.py',
        'execution':ROOT/'qvt_backtest/reconstructed_replay.py','diagnostics':HERE/'evaluate.py'}
    manifest={}
    for key,path in paths.items():
        target=out/('input_'+key+path.suffix);shutil.copyfile(path,target)
        manifest[key]={'path':str(path),'frozen':str(target),'sha256':R.sha(target)}
    write(out/'manifest.json',manifest)
    # Finance archive itself must be the audited source, not an unreviewed replacement.
    source_hashes=read(baseline/'input_hashes.json')
    if source_hashes.get('reports.json')!=R.sha(paths['reports']):raise ValueError('financial archive differs from audited history')
    panel=pd.read_parquet(out/'input_panel.parquet')
    panel['as_of']=panel.as_of.astype(str).str[:10]
    dates=sorted(pd.read_parquet(out/'input_old_scores.parquet').as_of.astype(str).str[:10].unique())
    reports=read(out/'input_reports.json')
    identities={r['company_id']:{'symbol':r['symbol']} for r in reports}
    mapping=panel[['symbol','security_id']].drop_duplicates()
    securities=dict(zip(mapping.symbol,mapping.security_id))
    current=read(out/'input_family.json');family={r['symbol']:r for r in current['ranked']+current['unscored']}
    md=R.V.MarketData(R.V.load_reference_data(),symbols=sorted(identities[c]['symbol'] for c in identities))
    for cid,row in identities.items():row['security_id']=md.sym2sid.get(row['symbol']) or securities.get(row['symbol'])
    with CM.pg_pilot_conn() as db:
        monthly=db.execute('''SELECT m.company_id::text, m.period_end_date, m.sales_amount_rial,
            m.quantity_unit, r.published_at, r.source, rv.collected_at
            FROM fundamentals.monthly_activities m JOIN ingestion.reports r ON r.id=m.report_id
            JOIN ingestion.report_versions rv ON rv.id=m.report_version_id
            ORDER BY m.period_end_date, rv.version_no, rv.collected_at, m.id''').fetchall()
    columns=['company_id','period_end_date','sales_amount_rial','quantity_unit','published_at','source','collected_at']
    monthly=[{k:(v.isoformat() if isinstance(v,(dt.date,dt.datetime)) else float(v) if k=='sales_amount_rial' and v is not None else v) for k,v in zip(columns,row)} for row in monthly]
    write(out/'input_monthly.json',monthly)
    source=ArchiveSnapshots(reports,monthly,identities,md,read(out/'input_shares.json')['intervals'])
    features=[];metric_rows={};original_scores=[]
    for date in dates:
        eng,metrics,timing=source.snapshot(date)
        allowed=set(panel.loc[panel.as_of.eq(date),'symbol'])
        symbols=sorted(m['symbol'] for m in metrics.values() if m['symbol'] in allowed)
        raw_t,_=R.historical_timing(md,symbols,date)
        n=0
        for cid,m in metrics.items():
            if m['symbol'] not in allowed:continue
            row=feature_row(eng,cid,m,policy)
            row.update(timing.get(cid,{'momentum':None,'volatility':None,'tradable':False}))
            meta=family.get(m['symbol'],{})
            row.update(model_family=meta.get('model_family','unknown'),industry=meta.get('industry'),industry_pit_valid=False,
                SCREEN_ALL_POPULATION=m['quant_score'],publication_cutoff=eng.cutoff.isoformat(),
                sources=json.dumps(eng.snapshot_source_reports.get(cid,[]),ensure_ascii=False))
            for key in ('roe','cash_conversion','pe','pb','ps','operating_margin','net_margin'):row[key]=m[key]
            for factor in ('momentum_6m_rel','momentum_3m_rel','liquidity','low_volatility'):
                fact=raw_t.get(m['symbol'],{}).get(factor,{})
                row['qvt_'+factor]=fact.get('raw_value') if fact.get('status')=='valid' else None
            features.append(row);metric_rows[(date,cid)]=m
            original_scores.append({'as_of':date,'company_id':cid,**public(m),'dq_flags':json.dumps(m['_dq'].flags)})
            n+=1
        print(f'{date}: rebuilt financial and screen inputs for {n} companies',flush=True)
    frame=pd.DataFrame(features)
    frame.to_parquet(out/'features.parquet',index=False)
    pd.DataFrame(original_scores).to_parquet(out/'corrected_screen_inputs.parquet',index=False)
    scored=score_frame(frame,policy)
    common=baseline_common(scored,metric_rows,policy)
    scored.to_parquet(out/'all_scores.parquet',index=False)
    if not common.empty:common.to_parquet(out/'common_scores.parquet',index=False)
    scored.groupby(['as_of','eligible']).size().unstack(fill_value=0).to_csv(out/'coverage.csv')
    scored.loc[~scored.eligible,['as_of','symbol','refusal_reasons','factor_coverage']].to_csv(out/'refusals.csv',index=False,encoding='utf-8-sig')
    current_cutoff=dt.datetime.now(dt.timezone.utc);current_date=current_cutoff.astimezone(ZoneInfo('Asia/Tehran')).date().isoformat()
    eng,metrics,timing=source.snapshot(current_date,current_cutoff,require_observed=True)
    rows=[]
    for cid,m in metrics.items():
        row=feature_row(eng,cid,m,policy);row.update(timing.get(cid,{'momentum':None,'volatility':None,'tradable':False}))
        meta=family.get(m['symbol'],{})
        row.update(model_family=meta.get('model_family','unknown'),industry=meta.get('industry'),industry_pit_valid=False)
        rows.append(row)
    now=score_frame(pd.DataFrame(rows),policy)
    now.sort_values(['eligible','BALANCED','symbol'],ascending=[False,False,True]).to_csv(out/'current_preview.csv',index=False,encoding='utf-8-sig')
    write(out/'current_snapshot.json',{'as_of':current_date,'cutoff':current_cutoff.isoformat(),'source_policy':'publication_and_actual_observation','rows':len(now),'eligible':int(now.eligible.sum()),'production_changed':False})
    write(out/'raw_financial_manifest.json',source.raw_manifest)
    market={s:{'path':str(R.V.RAW/f"raw_{s}_{rec['ins']}.json.gz"),'sha256':R.sha(R.V.RAW/f"raw_{s}_{rec['ins']}.json.gz")} for s,rec in md.data.items()}
    write(out/'market_manifest.json',market)
    write(out/'prepared.json',{'rows':len(scored),'eligible_rows':int(scored.eligible.sum()),'common_rows':len(common),
        'common_dates':int(common.as_of.nunique()) if not common.empty else 0,'dates':dates,'monthly_proxy_rows':sum(not r['published_at'] for r in monthly),
        'current_eligible':int(now.eligible.sum()),'prepared_at':dt.datetime.now(dt.timezone.utc).isoformat()})
    return common,md


def evaluate(out,policy,common,md):
    models=['SCREEN_CORRECTED','QVT76_CORRECTED',*policy['models']]
    decisions={};portfolio={}
    if common.empty:
        write(out/'summary.json',{'run_path':str(out),'version':policy['version'],'promotion_ready':False,
            'status':'insufficient_common_population','prepared':read(out/'prepared.json'),'real_orders':0})
        return
    common=common.copy()
    common.to_parquet(out/'scores_without_outcomes.parquet',index=False)
    for h in [policy['primary_horizon_sessions'],*policy['sensitivity_horizons']]:
        common[f'ret_{h}']=[forward(md,r.symbol,r.as_of,h) for r in common.itertuples()]
    common.to_parquet(out/'diagnostic_panel.parquet',index=False)
    records=[]
    for model in models:
        for horizon in [policy['primary_horizon_sessions'],*policy['sensitivity_horizons']]:
            records+=diagnostics(common,model,horizon,policy)
    results=pd.DataFrame(records);results.to_csv(out/'per_date_diagnostics.csv',index=False)
    results['year']=results.as_of.str[:4]
    results.groupby(['model','horizon','year'])[['ic','top_excess','quintile_spread']].mean().to_csv(out/'signal_year_diagnostics.csv')
    aggregate=results.groupby(['model','horizon']).agg(mean_ic=('ic','mean'),ic_dates=('ic','count'),top_excess=('top_excess','mean'),top_dates=('top_excess','count'))
    aggregate.to_csv(out/'aggregate.csv')
    changes={}
    for model in models:
        prior=None;turn=[]
        for date,group in common.groupby('as_of',sort=True):
            chosen=set(group.sort_values([model,'symbol'],ascending=[False,True]).head(policy['top_n']).symbol)
            if prior is not None:turn.append(1-len(prior&chosen)/policy['top_n'])
            prior=chosen
        changes[model]=float(np.mean(turn)) if turn else None
    primary=results[results.horizon.eq(policy['primary_horizon_sessions'])]
    cfg=policy['acceptance']
    for model in policy['models']:
        candidate=primary[primary.model.eq(model)];valid=candidate.ic.dropna()
        pairs={b:paired_ci(primary,model,b,policy) for b in models[:2]}
        years=candidate.groupby('year').top_excess.mean().dropna()
        # IC improvement is paired on the same dates, just like top returns.
        pivot=primary.pivot(index='as_of',columns='model',values='ic')
        ic_gain={b:float((pivot[model]-pivot[b]).dropna().mean()) for b in models[:2]}
        checks={'enough_dates':len(valid)>=cfg['minimum_primary_dates'],
            'positive_ic_fraction':bool(len(valid) and (valid>0).mean()>=cfg['minimum_positive_ic_fraction']),
            'ic_gain_over_both':all(np.isfinite(v) and v>=cfg['minimum_mean_ic_gain_over_both_baselines'] for v in ic_gain.values()),
            'enough_paired_dates':all(p['n']>=cfg['minimum_paired_dates'] for p in pairs.values()),
            'top_gain_over_both':all(p['mean'] is not None and p['mean']>=cfg['minimum_top10_excess_gain_over_both_baselines'] for p in pairs.values()),
            'paired_ci_positive':all(p['lower'] is not None and p['lower']>0 for p in pairs.values()),
            'year_stability':bool(len(years)>=cfg['minimum_signal_years'] and (years>0).mean()>=cfg['required_positive_year_fraction']),
            'turnover':changes[model] is not None and changes[model]<=cfg['maximum_monthly_replacement_fraction']}
        decisions[model]={'diagnostic_pass':all(checks.values()),'checks':checks,'paired_top_intervals':pairs,'paired_ic_gain':ic_gain}
    sensitivity=copy.deepcopy(policy);sensitivity['top_n']=policy['top_n_sensitivity']
    pd.DataFrame([r for model in models for r in diagnostics(common,model,policy['primary_horizon_sessions'],sensitivity)]).to_csv(out/'top20_sensitivity.csv',index=False)
    # Fixed weight perturbation is a stability diagnostic; never a fourth model.
    stability=[]
    for model,weights in policy['models'].items():
        for block in weights:
            shift={b:(w+.05 if b==block else w) for b,w in weights.items()}
            total=sum(shift.values());shift={b:w/total for b,w in shift.items()}
            for date,group in common.groupby('as_of'):
                perturbed=sum(group[b]*w for b,w in shift.items())
                original=set(group.nlargest(policy['top_n'],model).symbol)
                altered=set(group.loc[perturbed.nlargest(policy['top_n']).index,'symbol'])
                stability.append({'model':model,'block':block,'as_of':date,'overlap':len(original&altered)/policy['top_n']})
    pd.DataFrame(stability).to_csv(out/'weight_sensitivity.csv',index=False)
    factors=[f for b in policy['blocks'].values() for f in b]
    pd.concat([g[factors].corr(method='spearman').assign(as_of=date) for date,g in common.groupby('as_of')]).to_csv(out/'factor_correlations.csv')
    # Every fixed candidate gets accounting evidence, including failed candidates.
    dates=sorted(common.as_of.unique())
    adj={s:{'dates':r['dates'],'adj':{d:float(c*f) for d,c,f in zip(r['dates'],r['c'],r['cf'])}} for s,r in md.data.items()}
    accounting,keys=R.V.load_portfolio_engine(),R.V.tradability_keys()
    selections={model:common.sort_values(['as_of',model,'symbol'],ascending=[True,False,True]).groupby('as_of').head(policy['top_n']) for model in models}
    selections['MATCHED_EQUAL_WEIGHT']=common
    for name,selected in selections.items():
        for cadence in policy['portfolio']['cadences_months']:
            for cost in policy['portfolio']['cost_rates_per_side']:
                for delay in policy['portfolio']['delay_sessions']:
                    key=f'{name}_{cadence}m_{cost:g}_{delay}d'
                    chosen=selected.assign(ui_score=selected[name] if name in selected else 0)
                    perf,daily,ledger,trades=B.replay(chosen,dates,adj,md.cal,keys,cadence,cost,accounting,execution={'delay_sessions':delay})
                    portfolio[key]=perf
                    pd.DataFrame(daily).to_csv(out/(key+'_daily.csv'),index=False)
                    pd.DataFrame(ledger).to_csv(out/(key+'_ledger.csv'),index=False)
                    pd.DataFrame(trades).to_csv(out/(key+'_trades.csv'),index=False)
        print(f'{name}: fixed portfolio scenarios complete',flush=True)
    write(out/'portfolio.json',portfolio)
    for item in read(out/'manifest.json').values():
        if R.sha(item['path'])!=item['sha256']:raise ValueError('registered source changed')
    for item in read(out/'market_manifest.json').values():
        if R.sha(item['path'])!=item['sha256']:raise ValueError('market source changed')
    summary={'version':policy['version'],'run_path':str(out),'status':'evaluated','promotion_ready':False,
        'production_changed':False,'real_orders':0,'prepared':read(out/'prepared.json'),
        'n_rows':len(common),'n_symbols':int(common.symbol.nunique()),'n_dates':int(common.as_of.nunique()),
        'decisions':decisions,'membership_replacement':changes,'portfolio_scenarios':len(portfolio),
        'limitations':['Previously inspected history; no fresh independent holdout',
            'Current identity/family cohort and survivor bias; no dated historical industry',
            'Legacy monthly rows without publication use period-end proxy; not historical first-seen data',
            'Price series mechanically adjusted; complete cash-dividend/rights total-return accounting absent',
            'No independently investable benchmark or queue/participation-capacity certification',
            'Same canonical formulas on verified archive inputs, but published-history reconstruction differs from original live observations']}
    write(out/'summary.json',summary)
    print(aggregate.to_string(),flush=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--resume',type=Path);args=ap.parse_args()
    policy=read(HERE/'v2_protocol.json')
    if args.resume:
        out=args.resume
        if read(out/'protocol.json')!=policy:raise ValueError('registered protocol changed')
        if (out/'summary.json').exists():raise ValueError('completed experiments are immutable')
        common=pd.read_parquet(out/'common_scores.parquet') if (out/'common_scores.parquet').exists() else pd.DataFrame()
        md=R.V.MarketData(R.V.load_reference_data(),symbols=sorted(read(out/'market_manifest.json')))
    else:
        out=HERE/'output'/('formula_v2_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        out.mkdir(parents=True)
        write(out/'protocol.json',policy)
        write(out/'registration.json',{'registered_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'protocol_sha256':R.sha(HERE/'v2_protocol.json'),'previous_experiment':read(HERE/'output/evaluation_latest.json')['run_path'],
            'plan':str(ROOT/'docs/SCORING_FORMULA_V2_PLAN.fa.md'),'no_weight_search':True})
        write(HERE/'output/formula_v2_running.json',{'run_path':str(out)})
        common,md=prepare(out,policy)
    evaluate(out,policy,common,md)
    print(json.dumps({'output':str(out),'status':read(out/'summary.json')['status']}),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8');main()
