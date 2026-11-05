"""Bounded fixed-candidate diagnostic on a frozen shared financial cohort.

No model fitting, broker calls, DB writes, or promotion. Forward outcomes require
exact global entry/exit sessions and positive traded volume; missing outcomes
are disclosed and never replaced by the next-ranked stock.
"""
from __future__ import annotations
from bisect import bisect_right
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from engine import score_frame

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'qvt_backtest'))
import run as R
import reconstructed_replay as B


def forward(md, symbol, signal, horizon):
    record = md.data.get(symbol)
    start = bisect_right(md.cal, signal)
    if record is None or start + horizon >= len(md.cal):
        return np.nan
    entry, end = md.cal[start], md.cal[start+horizon]
    i, j = record['dmap'].get(entry), record['dmap'].get(end)
    if i is None or j is None:
        return np.nan
    observed=[record['vol'][i],record['vol'][j],record['c'][i],record['c'][j],record['cf'][i],record['cf'][j]]
    if not all(np.isfinite(x) and x>0 for x in observed):
        return np.nan
    a,b = record['c'][i]*record['cf'][i], record['c'][j]*record['cf'][j]
    return float(b/a-1) if a>0 and b>0 else np.nan


def diagnostics(scored, model, horizon, policy):
    records=[]
    for date, group in scored.groupby('as_of',sort=True):
        ordered=group.sort_values([model,'symbol'],ascending=[False,True])
        valid=ordered.dropna(subset=[f'ret_{horizon}',model])
        coverage=len(valid)/len(ordered)
        top=ordered.head(policy['top_n'])
        complete_top=top[f'ret_{horizon}'].notna().all()
        row={'as_of':date,'model':model,'horizon':horizon,'population':len(group),
             'outcome_coverage':coverage,'top_outcome_complete':bool(complete_top),
             'ic':np.nan,'top_excess':np.nan,'quintile_spread':np.nan}
        if coverage>=policy['minimum_outcome_coverage'] and len(valid)>=policy['minimum_population']:
            outcome=valid[f'ret_{horizon}']
            if valid[model].nunique()>1 and outcome.nunique()>1:
                row['ic']=valid[model].rank().corr(outcome.rank())
            if complete_top:
                row['top_excess']=top[f'ret_{horizon}'].mean()-outcome.mean()
            # Quantiles defined from ALL scores, not from future data availability.
            pct=ordered[model].rank(method='average',pct=True)
            high=ordered.loc[pct>=.8,f'ret_{horizon}']
            low=ordered.loc[pct<=.2,f'ret_{horizon}']
            if high.notna().mean()>=.8 and low.notna().mean()>=.8:
                row['quintile_spread']=high.mean()-low.mean()
        records.append(row)
    return records


def paired_ci(frame, candidate, baseline, policy):
    pivot=frame.pivot(index='as_of',columns='model',values='top_excess').sort_index()
    pivot.index=pd.PeriodIndex(pivot.index,freq='M')
    if pivot.index.duplicated().any():
        raise ValueError('multiple observations in a calendar month')
    pivot=pivot.reindex(pd.period_range(pivot.index.min(),pivot.index.max(),freq='M'))
    # Keep the full monthly schedule in blocks; missing labels remain NaN.
    delta=(pivot[candidate]-pivot[baseline]).to_numpy()
    valid=np.isfinite(delta)
    if valid.sum()<2:
        return {'n':int(valid.sum()),'lower':None,'upper':None,'mean':None}
    cfg=policy['bootstrap'];rng=np.random.default_rng(cfg['seed']);n=len(delta)
    values=[]
    for _ in range(cfg['replications']):
        starts=rng.integers(0,n,size=int(np.ceil(n/cfg['block_months'])))
        indices=np.concatenate([(s+np.arange(cfg['block_months']))%n for s in starts])[:n]
        sample=delta[indices]
        if np.isfinite(sample).any(): values.append(float(np.nanmean(sample)))
    return {'n':int(valid.sum()),'mean':float(np.nanmean(delta)),
            'lower':float(np.quantile(values,.025)),'upper':float(np.quantile(values,.975))}


def main():
    here=Path(__file__).resolve().parent
    policy=json.loads((here/'policy.json').read_text())
    baseline=json.loads((ROOT/'qvt_backtest/output/reconstructed_latest.json').read_text())
    base=Path(baseline['run_path'])
    if json.loads((base/'audit.json').read_text())['status']!='passed':
        raise ValueError('unaudited baseline')
    out=here/'output'/('evaluation_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    paths={'policy':here/'policy.json','engine':here/'engine.py','evaluation':Path(__file__),
           'scores':base/'scores.parquet','financial':base/'reconstructed_inputs.parquet',
           'extended':B.HISTORY/'extended_financial_panel.csv','baseline_audit':base/'audit.json'}
    manifest={}
    for key,path in paths.items():
        dest=out/('input_'+key+path.suffix);shutil.copyfile(path,dest)
        manifest[key]={'path':str(path),'frozen':str(dest),'sha256':R.sha(dest)}
    R.write(out/'manifest.json',manifest)
    R.write(out/'registration.json',{'registered_at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'policy_sha256':R.sha(here/'policy.json'),'context':policy['context']})
    core=pd.read_parquet(out/'input_scores.parquet')
    financial=pd.read_parquet(out/'input_financial.parquet')
    extra=pd.read_csv(out/'input_extended.csv')
    for frame in [core,financial]:frame['as_of']=frame.as_of.astype(str).str[:10]
    joined=core[['as_of','symbol','ui_score','baseline_score']].rename(columns={'ui_score':'QVT76','baseline_score':'SCREEN_HISTORICAL'})
    fields=['roe','operating_margin','cash_conversion','debt_ratio','pe','operating_profit_ttm',
            't_mom_120','t_vol_60','financial_period_end','max_source_published_at','used_older_income_report']
    joined=joined.merge(financial[['as_of','symbol',*fields]],on=['as_of','symbol'],validate='one_to_one')
    joined=joined.merge(extra[['date','symbol','revenue_growth','margin_trend','published_at']],left_on=['as_of','symbol'],right_on=['date','symbol'],how='left',validate='one_to_one')
    joined=joined.rename(columns={'t_mom_120':'momentum','t_vol_60':'volatility'})
    if any(pd.Timestamp(r.max_source_published_at).to_pydatetime()>=B.cutoff_for(r.as_of) for r in joined.itertuples()):
        raise ValueError('future fundamental source')
    if any(pd.notna(r.published_at) and pd.Timestamp(r.published_at).to_pydatetime()>=B.cutoff_for(r.as_of) for r in joined.itertuples()):
        raise ValueError('future extended source')
    age=(pd.to_datetime(joined.as_of)-pd.to_datetime(joined.financial_period_end)).dt.days
    eligible=(joined.operating_profit_ttm>0)&age.between(0,365)&~joined.used_older_income_report
    scored,rejected=score_frame(joined.loc[eligible],policy)
    if scored.empty:raise ValueError('insufficient common cohort')
    scored=scored.merge(joined[['as_of','symbol','QVT76','SCREEN_HISTORICAL']],on=['as_of','symbol'],validate='one_to_one')
    if not np.isfinite(scored[['QVT76','SCREEN_HISTORICAL']].to_numpy()).all():raise ValueError('baseline missing')
    scored.to_parquet(out/'scores_without_outcomes.parquet',index=False)
    rejected.to_csv(out/'factor_rejections.csv',index=False)
    joined.loc[~eligible,['as_of','symbol']].to_csv(out/'financial_rejections.csv',index=False)
    print(f'Fixed shared cohort: {len(scored)} rows, {scored.as_of.nunique()} dates, {scored.symbol.nunique()} symbols',flush=True)
    R.write(out/'certified_source_hashes.json',R.V.verify_frozen_shas())
    md=R.V.MarketData(R.V.load_reference_data(),symbols=sorted(scored.symbol.unique()))
    market={s:{'path':str(R.V.RAW/f"raw_{s}_{rec['ins']}.json.gz"),'sha256':R.sha(R.V.RAW/f"raw_{s}_{rec['ins']}.json.gz")} for s,rec in md.data.items()}
    R.write(out/'market_manifest.json',market)
    horizons=[policy['primary_horizon_sessions'],*policy['sensitivity_horizons']]
    for h in horizons:scored[f'ret_{h}']=[forward(md,r.symbol,r.as_of,h) for r in scored.itertuples()]
    scored.to_parquet(out/'diagnostic_panel.parquet',index=False)
    models=['SCREEN_HISTORICAL','QVT76',*policy['models']]
    rows=[r for name in models for h in horizons for r in diagnostics(scored,name,h,policy)]
    results=pd.DataFrame(rows);results.to_csv(out/'per_date_diagnostics.csv',index=False)
    results['year']=results.as_of.str[:4]
    annual=results.groupby(['model','horizon','year'])[['ic','top_excess','quintile_spread']].mean()
    annual.to_csv(out/'signal_year_diagnostics.csv')
    changes={}
    for model in models:
        previous=None;values=[]
        for date,g in scored.groupby('as_of',sort=True):
            chosen=set(g.sort_values([model,'symbol'],ascending=[False,True]).head(policy['top_n']).symbol)
            if previous is not None: values.append(1-len(chosen&previous)/policy['top_n'])
            previous=chosen
        changes[model]=float(np.mean(values))
    primary=results[results.horizon.eq(policy['primary_horizon_sessions'])]
    aggregate=results.groupby(['model','horizon']).agg(mean_ic=('ic','mean'),n_dates=('ic','count'),mean_top_excess=('top_excess','mean'),mean_quintile_spread=('quintile_spread','mean')).reset_index()
    aggregate.to_csv(out/'comparisons.csv',index=False)
    decisions={};gates=policy['acceptance']
    for model in policy['models']:
        own=primary[primary.model.eq(model)]
        pairs={};checks={'sufficient_dates':int(own.ic.count())>=gates['minimum_primary_dates'],
             'positive_ic_fraction':float((own.ic.dropna()>0).mean())>=gates['minimum_positive_ic_fraction'],
             'stable_membership':changes[model]<=gates['maximum_monthly_replacement_fraction']}
        for baseline_name in ['SCREEN_HISTORICAL','QVT76']:
            pair=own.merge(primary[primary.model.eq(baseline_name)],on='as_of',suffixes=('_candidate','_baseline'))
            pairs[baseline_name]=paired_ci(primary,model,baseline_name,policy)
            checks['paired_dates_'+baseline_name]=pairs[baseline_name]['n']>=gates['minimum_primary_dates']
            checks['ic_gain_'+baseline_name]=float((pair.ic_candidate-pair.ic_baseline).mean())>=gates['minimum_mean_ic_gain_over_both_baselines']
            checks['top_gain_'+baseline_name]=(pairs[baseline_name]['mean'] or 0)>=gates['minimum_top10_excess_gain_over_both_baselines']
            checks['uncertainty_'+baseline_name]=pairs[baseline_name]['lower'] is not None and pairs[baseline_name]['lower']>0
            delta=(pair.top_excess_candidate-pair.top_excess_baseline).groupby(pair.as_of.str[:4]).mean().dropna()
            checks['year_consistency_'+baseline_name]=bool(len(delta)>=3 and (delta>0).mean()>=gates['required_positive_year_fraction'])
        decisions[model]={'diagnostic_pass':all(checks.values()),'checks':checks,'paired_top_excess_intervals':pairs}
    # Frozen sources and pure kernel must be identical after observing outcomes.
    repeated,_=score_frame(joined.loc[eligible],policy)
    pd.testing.assert_frame_equal(repeated,scored[repeated.columns],check_dtype=True)
    for record in list(manifest.values())+list(market.values()):
        if R.sha(record['path'])!=record['sha256']:raise ValueError('source changed during evaluation')
    summary={'version':policy['version'],'mode':'research_only','promotion_ready':False,'real_orders':0,
             'run_path':str(out),'baseline_run_path':str(base),'n_rows':len(scored),'n_dates':scored.as_of.nunique(),
             'n_symbols':scored.symbol.nunique(),'primary_horizon_sessions':policy['primary_horizon_sessions'],
             'monthly_membership_replacement':changes,'decisions':decisions,
             'checks':{'source_hashes_unchanged':True,'score_recompute_exact':True,'publication_cutoffs':True},
             'limitations':['Previously analyzed history; not independent validation','Common core-complete general-company subset; historical survivor and industry limitations remain','SCREEN_HISTORICAL is frozen old Score reconstruction, not a recomputation on corrected financial inputs','Overlapping forward returns are not portfolio CAGR; gross before trading costs','Missing exact-date exits remain unobserved; outcome availability may be informative','Corporate-action adjusted price series is not independently certified cash-dividend total return','No production deployment; no complete broker/execution validation']}
    R.write(out/'summary.json',summary);R.write(here/'output/evaluation_latest.json',summary)
    print(aggregate.to_string(index=False),flush=True)
    print(json.dumps({'diagnostic_pass':{k:v['diagnostic_pass'] for k,v in decisions.items()},'output':str(out)}),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
