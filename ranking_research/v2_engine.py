"""Outcome-free scoring with economic anchors and explicit refusal reasons."""
from __future__ import annotations
import numpy as np
import pandas as pd


def score_frame(frame, policy):
    if frame.duplicated(['as_of','symbol']).any():
        raise ValueError('duplicate company/date')
    factors=list(dict.fromkeys(f for b in policy['blocks'].values() for f in b))
    data=frame.copy()
    for name in factors+['total_assets','total_equity','net_profit_ttm','operating_profit_ttm','market_cap',
                         'financial_age_days','history_windows','maximum_history_gap_days','momentum','volatility']:
        data[name]=pd.to_numeric(data[name],errors='raise')
    missing=~np.isfinite(data[factors].to_numpy(dtype=float)).all(axis=1)
    reasons=[[] for _ in range(len(data))]
    def reject(mask, reason):
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)): reasons[i].append(reason)
    reject(missing,'missing_required_factor')
    essential=['total_assets','total_equity','net_profit_ttm','operating_profit_ttm','market_cap',
               'financial_age_days','history_windows','maximum_history_gap_days']
    reject(~np.isfinite(data[essential].to_numpy(dtype=float)).all(axis=1),'missing_required_evidence')
    reject(~data.model_family.eq('general'),'unsupported_company_family')
    reject(~data.source_valid.fillna(False),'unverified_source')
    reject(data.used_older_income_report.fillna(True),'newer_report_blocks_fallback')
    reject(data.financial_age_days.gt(policy['eligibility']['maximum_financial_age_days']) | data.financial_age_days.lt(0),'stale_or_future_financials')
    reject(data.history_windows.lt(policy['history_windows']) | data.maximum_history_gap_days.gt(policy['maximum_quarter_gap_days']),'insufficient_comparable_history')
    reject(data.net_profit_ttm.le(0) | data.operating_profit_ttm.le(0),'loss_or_turnaround_profile')
    if 'growth_state' in data:
        reject(data.growth_state.eq('turnaround'),'turnaround_requires_separate_profile')
    reject(data.total_assets.le(0) | data.total_equity.div(data.total_assets).lt(policy['eligibility']['minimum_equity_asset_ratio']),'invalid_or_thin_equity')
    reject(~data.debt_ratio.between(0,policy['eligibility']['maximum_debt_ratio']) | data.current_ratio.lt(policy['eligibility']['minimum_current_ratio']),'critical_financial_risk')
    reject(~np.isfinite(data.market_cap) | data.market_cap.le(0),'missing_valuation_identity')
    reject(data.sales_growth_status.ne('comparable'),'low_base_or_uncomparable_sales')
    data['refusal_reasons']=[';'.join(x) for x in reasons]
    data['eligible']=data.refusal_reasons.eq('')
    for f in factors:
        low, high=policy['anchors'][f]
        if not low<high: raise ValueError('invalid anchor')
        value=(data[f]-low)/(high-low)
        if f in policy['lower_better']:value=1-value
        data['s_'+f]=100*value.clip(0,1)
    for block, members in policy['blocks'].items():
        data[block]=data[['s_'+f for f in members]].mean(axis=1,skipna=False)
    for name, weights in policy['models'].items():
        if set(weights)!=set(policy['blocks']) or not np.isclose(sum(weights.values()),1) or any(w<0 for w in weights.values()):
            raise ValueError('invalid model weights')
        score=sum(data[b]*w for b,w in weights.items())
        data[name]=score.where(data.eligible)
    # Coverage is factual completeness, never redistributed into economic score.
    data['factor_coverage']=np.isfinite(data[factors].to_numpy(dtype=float)).mean(axis=1)
    missing_timing=~np.isfinite(data[['momentum','volatility']].to_numpy(dtype=float)).all(axis=1)
    data['entry_state']=np.where(~data.tradable.fillna(False),'blocked',
        np.where(missing_timing,'insufficient_timing',np.where(data.momentum.le(0) | data.volatility.gt(.60),'caution','review')))
    data['confidence']=np.where(data.eligible,'verified_inputs','insufficient')
    # Relative industry scores require dated evidence; never use current labels
    # to fabricate historical sector normalization.
    data['industry_rank']=np.nan
    known=data.eligible & data.industry_pit_valid.fillna(False) & data.industry.notna()
    for _,group in data.loc[known].groupby(['as_of','industry']):
        if len(group)>=policy['industry_minimum_population']:
            data.loc[group.index,'industry_rank']=(group.BALANCED.rank(method='average')-1)/(len(group)-1)*100
    return data


def select_common(scored, policy, baselines=('SCREEN_CORRECTED','QVT76_CORRECTED')):
    complete=scored.eligible & np.isfinite(scored[list(baselines)].to_numpy(dtype=float)).all(axis=1)
    common=scored.loc[complete].copy()
    sizes=common.groupby('as_of').symbol.transform('size')
    return common.loc[sizes>=policy['minimum_population']].copy()
