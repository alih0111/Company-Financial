import numpy as np
import pandas as pd
from ranking_research.strategy_search.signals import base_masks, rank_within, baseline_frame
from ranking_research.strategy_search.wave2 import frame_for

SIGNALS = ['S0','S1','S2','S3','S4','S5','S6','S7']


def score(d, name, cohort=None):
    d = d.copy().reset_index(drop=True)
    if name in ['S0', 'S1']:
        return frame_for(d, 'balanced' if name == 'S0' else 'garp_yield_quality', cohort)
    trade, family, financial = base_masks(d)
    mask = trade & family & financial
    extra = pd.Series(True, index=d.index) if cohort is None else pd.Series(np.asarray(cohort), index=d.index)
    mask &= extra
    def good(cols):
        return np.isfinite(d[cols].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)).all(axis=1)
    if name == 'S2':
        mask &= good(['s2_raw'])
        value = rank_within(d, 's2_raw', mask)
    elif name == 'S3':
        mask &= good(['s2_raw', 'operating_yield', 'cash_asset_quality']) & d.operating_yield.gt(0)
        value = sum(rank_within(d,c,mask) for c in ['s2_raw', 'operating_yield', 'cash_asset_quality']) / 3
    elif name == 'S4':
        mask &= good(['s4_raw'])
        value = rank_within(d, 's4_raw', mask)
    elif name == 'S5':
        mask &= good(['s5_raw'])
        value = rank_within(d, 's5_raw', mask)
    elif name == 'S6':
        mask &= good(['s2_raw','post_report_return']) & d.s2_raw.gt(0) & d.post_report_sessions.between(3,20) & d.post_report_valid_observations.ge(3)
        value = (rank_within(d,'s2_raw',mask)+rank_within(d,'post_report_return',mask))/2
    elif name == 'S7':
        initial = frame_for(d, 'garp_yield_quality')
        mask &= initial.eligible & good(['momentum_12_1'])
        quality = frame_for(d, 'garp_yield_quality', mask)
        mask &= quality.eligible
        value = (quality.score + rank_within(d, 'momentum_12_1', mask)) / 2
    else:
        raise ValueError(name)
    f = d[['decision_time','company_id','symbol','capacity_rial']].copy()
    f['eligible'] = mask & np.isfinite(value)
    f['score'] = value.where(f.eligible)
    return f


def price_score(d):
    # Price-only comparison includes specialized and unknown issuers without
    # implicitly requiring a report or a present-day sector classification.
    trade, _, _ = base_masks(d)
    mask = trade & np.isfinite(d.momentum_12_1)
    value = rank_within(d,'momentum_12_1',mask)
    f = d[['decision_time','company_id','symbol','capacity_rial']].copy()
    f['eligible'] = mask & np.isfinite(value)
    f['score'] = value.where(f.eligible)
    return f


def refusal(d, f, name):
    out = []
    for i, r in d.iterrows():
        reasons = []
        if not bool(r.source_valid) or not bool(r.publication_valid): reasons.append('missing_source')
        if not 0 <= r.financial_age_days <= 365: reasons.append('stale_source')
        if r.historical_family != 'general': reasons.append('specialized_or_unknown_family')
        if not r.capacity_rial > 0 or r.positive_volume_sessions < 15: reasons.append('capacity_or_halt')
        if name in ['S2','S3','S4','S6'] and not bool(r.get('independent_quarter_comparable',False)): reasons.append('non_comparable_period')
        if name in ['S2','S3','S6'] and not r.get('average_assets',np.nan) > 0: reasons.append('invalid_denominator')
        if name in ['S1','S3','S7'] and not r.get('market_cap',np.nan) > 0: reasons.append('missing_share_or_valuation_source')
        if name == 'S5': reasons.append('missing_six_versioned_monthly_sales_sources')
        if not f.eligible.iloc[i] and not reasons: reasons.append('required_signal_inputs')
        out.append(';'.join(reasons) if not f.eligible.iloc[i] else '')
    return out
