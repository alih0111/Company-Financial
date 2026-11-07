"""Old formulas on frozen matched financial inputs; do not pretend full live QVT."""
import numpy as np
import pandas as pd
from .common import HERE, ROOT, read, write, legacy, checkpoint
from .factors import score
from .portfolio import replay
from .walk_forward import make_schedule


def compare_legacy(out, prices):
    if not (out / 'weights_by_date.csv').exists():
        write(out / 'legacy_comparison_status.json', {'status': 'insufficient_test_history'})
        checkpoint(out, 'compare_legacy', 'insufficient_data'); return
    _, _, _, _, R = legacy()
    from owner_value_engine import score as owner_score
    policy = read(out / 'protocol.json')
    parent = read(out / 'registration.json')['parent']
    old = pd.read_parquet(parent + '/features.parquet')
    fields = ['roe', 'cash_conversion', 'pe', 'pb', 'ps', 'operating_margin', 'net_margin',
              'qvt_momentum_6m_rel', 'qvt_momentum_3m_rel', 'qvt_liquidity', 'qvt_low_volatility']
    old = old[['as_of', 'company_id', 'net_profit_ttm', 'operating_profit_ttm', 'market_cap', *fields]].rename(
        columns={'as_of': 'decision_time', 'net_profit_ttm': 'old_np', 'operating_profit_ttm': 'old_op', 'market_cap': 'old_mc'})
    frame = pd.read_parquet(out / 'scores.parquet').merge(old, on=['decision_time', 'company_id'], how='left', validate='one_to_one')
    matches = np.isclose(frame.old_np, frame.net_profit_ttm, equal_nan=False) & np.isclose(frame.old_op, frame.operating_profit_ttm, equal_nan=False) & np.isclose(frame.old_mc, frame.market_cap, equal_nan=False)
    # Old family is never read. The contemporary financial raw inputs are matched
    # to the new independently reconstructed rows before old timing fields qualify.
    frame['model_family'] = frame.historical_family
    cash = owner_score(frame, read(HERE / 'owner_value_protocol.json'))
    cash_valid = frame.eligible & cash.eligible
    frame['CASH_QV'] = cash.CASH_QV
    qvt_valid = frame.eligible & matches & np.isfinite(frame[fields].to_numpy(dtype=float)).all(axis=1) & frame[['pe', 'pb', 'ps', 'roe']].gt(0).all(axis=1)
    qvt_policy = read(ROOT / 'qvt_backtest/reconstructed_protocol.json')
    mapping = {'roe_level': ('roe', True), 'cash_conversion': ('cash_conversion', True),
               'leverage': ('debt_ratio', False), 'pe': ('pe', False), 'pb': ('pb', False), 'ps': ('ps', False),
               'operating_margin': ('operating_margin', True), 'net_margin': ('net_margin', True),
               'momentum_6m_rel': ('qvt_momentum_6m_rel', True), 'momentum_3m_rel': ('qvt_momentum_3m_rel', True),
               'liquidity': ('qvt_liquidity', True), 'low_volatility': ('qvt_low_volatility', False)}
    def qvt(data, mask):
        values = pd.Series(np.nan, index=data.index)
        for _, group in data[mask].groupby('decision_time'):
            if len(group) < qvt_policy['minimum_population']: continue
            ranks = {key: R.ranked(group[col], higher) for key, (col, higher) in mapping.items()}
            ranks['margins'] = .6 * ranks['operating_margin'] + .4 * ranks['net_margin']
            values.loc[group.index] = sum(qvt_policy['weights'][key] * ranks[key] for key in qvt_policy['weights'])
        return values
    frame['QVT76'] = qvt(frame, qvt_valid)
    common_mask = cash_valid & qvt_valid & frame.QVT76.notna()
    common = frame[common_mask].drop(columns=['model_family']).copy()
    # Rebuild cross-sectional ranks for the identical cohort, not inherited ranks.
    common = score(common, policy)
    common['QVT76'] = qvt(common, pd.Series(True, index=common.index))
    common['CASH_QV'] = frame.loc[common.index, 'CASH_QV']
    primary = pd.read_csv(out / 'weights_by_date.csv')
    start = primary.iloc[0].test_month; end = primary.iloc[-1].block_end_exclusive[:7]
    end_day = (pd.Timestamp(end + '-01') - pd.Timedelta(days=1)).date().isoformat()
    records = []
    for scope in ['matched_inputs', 'own_coverage']:
        for model in ['balanced', 'CASH_QV', 'QVT76', 'equal_weight']:
            if scope == 'matched_inputs': data = common.copy()
            else:
                data = frame.copy()
                if model == 'CASH_QV': data['eligible'] = cash_valid
                elif model == 'QVT76': data['eligible'] = qvt_valid & frame.QVT76.notna()
            for cadence in policy['cadences_months']:
                result = replay(data, prices, policy, start + '-01', end_day,
                                make_schedule(data, start, end, model, cadence), keep=False)
                records.append({'scope': scope, 'model': model, 'cadence_months': cadence, **result['summary']})
    pd.DataFrame(records).to_csv(out / 'legacy_comparison.csv', index=False)
    common.groupby('decision_time').size().to_csv(out / 'legacy_common_coverage.csv', header=['companies'])
    write(out / 'legacy_comparison_status.json', {
        'QVT76': 'recomputed 76-point historical subset, not full live QVT; old raw financial facts must match new reconstruction',
        'CASH_QV': 'recomputed on new historical family and verified financial inputs; old eligibility gates retained',
        'SCREEN': 'not comparable: legacy monthly sales inputs lack reliable publication history; no proxy silently admitted',
        'old_rows_with_matching_financials': int(matches.sum()), 'common_rows': len(common),
        'no_future_outcome_filter': True, 'promotion_evidence': False,
        'common_scope': 'fixed formulas and cadences; adaptive strategy evaluated separately on its registered own population'})
    checkpoint(out, 'compare_legacy', scenarios=len(records), common_rows=len(common))
