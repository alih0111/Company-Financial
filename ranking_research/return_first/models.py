"""Only historical features; eligibility is specific to each model."""
import numpy as np
import pandas as pd
from ranking_research.top10_six_month.factors import score as old_score

MODELS = ('profit_growth', 'operating_growth', 'price_momentum', 'balanced',
          'growth_value', 'growth_quality')


def score(frame, policy, common=False):
    if any(str(c).startswith(('ret_', 'forward_', 'outcome', 'future_')) for c in frame):
        raise ValueError('future_outcomes_in_features')
    if frame.duplicated(['decision_time', 'company_id']).any():
        raise ValueError('duplicate_company_date')
    d = frame.copy().reset_index(drop=True)
    old = old_score(d, policy)
    financial = (d.source_valid.eq(True) & d.publication_valid.eq(True)
                 & d.used_older_income_report.eq(False)
                 & d.financial_age_days.between(0, policy['maximum_financial_age_days']))
    scope = policy.get('family_scope', 'general')
    fams = ('general',) if scope == 'general' else ('general', 'unknown')
    trade = (d.historical_family.isin(fams) & d.capacity_rial.gt(0)
             & d.decision_price.gt(0) & np.isfinite(d.capacity_rial) & np.isfinite(d.decision_price)
             & d.positive_volume_sessions.ge(policy['minimum_positive_volume_sessions'])
             & d.liquidity_observations.ge(policy['liquidity_sessions']))
    comparable = d.growth_window_valid.eq(True) & d.net_growth_verified.eq(True)
    def finite(*cols):
        return pd.Series(np.isfinite(d[list(cols)].to_numpy(dtype=float)).all(axis=1), index=d.index)
    # Input reports are rounded to million rial. Smaller denominators are below
    # the source resolution; loss-to-profit transitions are a separate hypothesis.
    np_ok = financial & comparable & finite('net_profit_ttm', 'prior_net_profit_ttm') & d.prior_net_profit_ttm.ge(1e6)
    op_ok = financial & d.growth_window_valid.eq(True) & finite('operating_profit_ttm', 'prior_operating_profit_ttm') & d.prior_operating_profit_ttm.ge(1e6)
    value_ok = finite('operating_profit_ttm', 'market_cap') & d.market_cap.gt(0) & d.operating_profit_ttm.gt(0)
    quality_ok = finite('ocf_ttm', 'net_profit_ttm', 'operating_profit_ttm', 'total_assets') & d.net_profit_ttm.gt(0) & d.total_assets.gt(0)
    masks = {'profit_growth': trade & np_ok, 'operating_growth': trade & op_ok,
             'price_momentum': trade & finite('momentum_12_1'), 'balanced': old.eligible,
             'growth_value': trade & np_ok & value_ok, 'growth_quality': trade & np_ok & quality_ok}
    d['net_growth_raw'] = d.net_profit_ttm / d.prior_net_profit_ttm.where(d.prior_net_profit_ttm.ge(1e6)) - 1
    d['op_growth_raw'] = d.operating_profit_ttm / d.prior_operating_profit_ttm.where(d.prior_operating_profit_ttm.ge(1e6)) - 1
    d['value_raw'] = d.operating_profit_ttm / d.market_cap.where(d.market_cap.gt(0))
    d['cash_raw'] = d.ocf_ttm / d.net_profit_ttm.where(d.net_profit_ttm.gt(0))
    d['roa_raw'] = d.operating_profit_ttm / d.total_assets.where(d.total_assets.gt(0))
    common_mask = pd.concat(masks, axis=1).all(axis=1)
    results = {}
    for model in MODELS:
        v = d.copy(); mask = common_mask.copy() if common else masks[model].copy()
        v['eligible'] = mask
        v['refusals'] = ['' if ok else ';'.join(reason for bad, reason in [
            (not bool(trade.iloc[i]), 'family_or_trade_data'),
            (model != 'price_momentum' and not bool(financial.iloc[i]), 'financial_source_or_age'),
            (True, 'required_model_inputs_or_common_cohort')] if bad) for i, ok in enumerate(mask)]
        v[model] = np.nan
        for _, g in v[mask].groupby('decision_time'):
            if len(g) < 2:
                v.loc[g.index, 'eligible'] = False
                v.loc[g.index, 'refusals'] = 'fewer_than_two'
                continue
            def rank(col):
                return 100 * (g[col].rank(method='average') - 1) / (len(g) - 1)
            if model == 'balanced':
                # Recompute all cross-sectional ranks on exactly the cohort used.
                values = old_score(g, policy).balanced
            elif model == 'profit_growth': values = rank('net_growth_raw')
            elif model == 'operating_growth': values = rank('op_growth_raw')
            elif model == 'price_momentum': values = rank('momentum_12_1')
            elif model == 'growth_value': values = (rank('net_growth_raw') + rank('value_raw')) / 2
            else: values = .5 * rank('net_growth_raw') + .25 * rank('cash_raw') + .25 * rank('roa_raw')
            v.loc[g.index, model] = values
        results[model] = v
    return results
