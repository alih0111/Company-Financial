"""Pure date-local ranking kernel shared by research and future serving adapters.

Accepts validated raw factors, never reads outcomes or fills missing values.
Outputs investment attractiveness separately from timing and completeness.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def score_frame(frame, policy):
    factors = list(dict.fromkeys(f for block in policy['blocks'].values() for f in block))
    needed = ['as_of', 'symbol', *factors]
    if frame.duplicated(['as_of', 'symbol']).any():
        raise ValueError('duplicate symbol/date')
    data = frame[needed].copy()
    valid = np.isfinite(data[factors].to_numpy(dtype=float)).all(axis=1)
    valid &= (data.pe > 0) & (data.roe > 0) & data.debt_ratio.between(0, 1)
    rejected = data.loc[~valid, ['as_of', 'symbol']].copy()
    rejected['reason'] = 'missing_or_economically_invalid_required_factor'
    output = []
    for date, group in data.loc[valid].groupby('as_of', sort=True):
        if len(group) < policy['minimum_population']:
            small = group[['as_of', 'symbol']].copy()
            small['reason'] = 'insufficient_common_population'
            rejected = pd.concat([rejected, small], ignore_index=True)
            continue
        group = group.sort_values('symbol').copy()
        for factor in factors:
            # All ties -> 0.5; extreme magnitude cannot outweigh its ordinal rank.
            rank = (group[factor].rank(method='average') - 1) / (len(group) - 1)
            group['p_' + factor] = 1 - rank if factor in policy['lower_better'] else rank
        for block, members in policy['blocks'].items():
            group[block] = group[['p_' + f for f in members]].mean(axis=1) * 100
        for name, weights in policy['models'].items():
            if not np.isclose(sum(weights.values()), 1) or any(w < 0 for w in weights.values()):
                raise ValueError('invalid block weights')
            group[name] = sum(group[b] * w for b, w in weights.items())
        group['required_factor_coverage'] = 1.0
        output.append(group)
    return (pd.concat(output, ignore_index=True) if output else pd.DataFrame(), rejected)
