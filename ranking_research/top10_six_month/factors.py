"""Outcome-free four-factor scoring. Missing facts are never imputed."""
import numpy as np
import pandas as pd

FORBIDDEN = ('ret_', 'forward_', 'outcome', 'future_')


def score(frame, protocol):
    if any(str(c).startswith(FORBIDDEN) for c in frame.columns):
        raise ValueError('outcomes are forbidden in the scoring input')
    if frame.duplicated(['decision_time', 'company_id']).any():
        raise ValueError('duplicate_company_decision')
    d = frame.copy()
    d['V_raw'] = d[['net_profit_ttm', 'operating_profit_ttm']].min(axis=1, skipna=False) / d.market_cap
    d['Q_cash_raw'] = d.ocf_ttm / d.net_profit_ttm
    d['Q_roa_raw'] = d.operating_profit_ttm / d.total_assets
    den = d.operating_profit_ttm.abs() + d.prior_operating_profit_ttm.abs()
    d['G_raw'] = (d.operating_profit_ttm - d.prior_operating_profit_ttm) / den.where(den.ne(0))
    d['M_raw'] = d.momentum_12_1
    essentials = ['net_profit_ttm', 'operating_profit_ttm', 'ocf_ttm', 'market_cap',
                  'total_assets', 'total_equity', 'prior_operating_profit_ttm', 'M_raw',
                  'capacity_rial', 'decision_price', 'financial_age_days']
    reasons = [[] for _ in range(len(d))]

    def reject(mask, reason):
        for i in np.flatnonzero(np.asarray(mask.fillna(True), dtype=bool)):
            reasons[i].append(reason)

    reject(pd.Series(~np.isfinite(d[essentials].to_numpy(dtype=float)).all(axis=1), index=d.index), 'missing_factor')
    reject(d.net_profit_ttm.le(0) | d.operating_profit_ttm.le(0), 'nonpositive_profit')
    reject(d.market_cap.le(0) | d.total_assets.le(0) | d.total_equity.le(0), 'nonpositive_capital')
    reject(~d.financial_age_days.between(0, protocol['maximum_financial_age_days']), 'financial_age')
    fam_scope = protocol.get('family_scope', 'general')
    fam_ok = (d.historical_family.eq('general') if fam_scope == 'general'
              else d.historical_family.isin(('general', 'unknown')))
    reject(~fam_ok, 'historical_family_not_operating')
    reject(~d.source_valid | d.used_older_income_report, 'source_or_newer_report_failure')
    reject(~d.publication_valid, 'publication_after_decision_or_unknown')
    reject(~d.growth_window_valid, 'unmatched_growth_window')
    reject(d.positive_volume_sessions.lt(protocol['minimum_positive_volume_sessions']) |
           d.liquidity_observations.lt(protocol['liquidity_sessions']), 'insufficient_liquidity')
    reject(d.capacity_rial.le(0) | d.decision_price.le(0), 'missing_decision_market')
    d['refusals'] = [';'.join(r) for r in reasons]
    d['eligible'] = d.refusals.eq('')
    for column in ['V', 'Q', 'G', 'M', *protocol['weights']]:
        d[column] = np.nan
    for _, group in d[d.eligible].groupby('decision_time'):
        if len(group) < 2:
            d.loc[group.index, 'eligible'] = False
            d.loc[group.index, 'refusals'] = 'fewer_than_two'
            continue
        def rank(field):
            return 100 * (group[field].rank(method='average') - 1) / (len(group) - 1)
        for name in ['V', 'G', 'M']:
            d.loc[group.index, name] = rank(name + '_raw')
        d.loc[group.index, 'Q'] = (rank('Q_cash_raw') + rank('Q_roa_raw')) / 2
        for name, weights in protocol['weights'].items():
            d.loc[group.index, name] = d.loc[group.index, ['V', 'Q', 'G', 'M']].to_numpy() @ weights
    return d
