"""Constrained four-block weights, fit only on mature past labels.

One model family, three fixed penalties; nested temporal validation and refusal
when history is short. No full-sample fitting or substitution by future winners.
"""
import numpy as np
import pandas as pd
from itertools import product

BLOCKS = ('quality', 'value', 'growth', 'resilience')
PENALTIES = (.01, .1, 1.)
PRIOR = np.full(4, .25)


def mature_panel(frame, cutoff, minimum_population=20):
    data = frame[(frame.as_of < cutoff) & (frame.label_exit_date < cutoff)].copy()
    valid = data.dropna(subset=[*BLOCKS, 'ret_126'])
    sizes = valid.groupby('as_of').symbol.transform('size')
    coverage = sizes / valid.as_of.map(data.groupby('as_of').size())
    return valid[(sizes >= minimum_population) & (coverage >= .8)].copy()


def fit(training, penalty):
    x = training[list(BLOCKS)].to_numpy(dtype=float) / 100
    y = training.groupby('as_of').ret_126.rank(pct=True).to_numpy()
    # Within-date centering and equal date mass prevent market-level returns or
    # a large single cross-section from dominating learned attractiveness.
    x = x - pd.DataFrame(x, index=training.index).groupby(training.as_of).transform('mean').to_numpy()
    y = y - pd.Series(y, index=training.index).groupby(training.as_of).transform('mean').to_numpy()
    mass = 1 / training.groupby('as_of').symbol.transform('size').to_numpy()
    mass = mass / mass.sum()
    def loss(w):
        residual = x @ w - y
        return np.sum(mass * residual ** 2) + penalty * np.sum((w - PRIOR) ** 2)
    # Four dimensions allow an exact active-bound enumeration. This solves one
    # convex fit; bound configurations are not separate backtest hypotheses.
    matrix = x.T @ (mass[:, None] * x) + penalty * np.eye(4)
    rhs = x.T @ (mass * y) + penalty * PRIOR
    lower = np.array([.2, .2, 0, 0]); upper = np.full(4, .5)
    feasible = []
    for states in product((-1, 0, 1), repeat=4):
        free = np.array([i for i, state in enumerate(states) if state == -1], dtype=int)
        fixed = np.array([i for i, state in enumerate(states) if state != -1], dtype=int)
        weights = np.zeros(4)
        for i in fixed: weights[i] = lower[i] if states[i] == 0 else upper[i]
        remaining = 1 - weights[fixed].sum()
        if len(free):
            quadratic = matrix[np.ix_(free, free)]
            linear = rhs[free] - matrix[np.ix_(free, fixed)] @ weights[fixed]
            kkt = np.block([[quadratic, np.ones((len(free), 1))], [np.ones((1, len(free))), np.zeros((1, 1))]])
            weights[free] = np.linalg.solve(kkt, np.r_[linear, remaining])[:-1]
        elif abs(remaining) > 1e-9: continue
        if np.all(weights >= lower - 1e-9) and np.all(weights <= upper + 1e-9) and abs(weights.sum() - 1) <= 1e-9:
            feasible.append((loss(weights), weights))
    if not feasible: raise ValueError('constrained_fit_failed')
    return min(feasible, key=lambda item: item[0])[1]


def choose_weights(frame, first_test_signal, minimum_outer_dates=36, minimum_inner_dates=24):
    training = mature_panel(frame, first_test_signal)
    dates = sorted(training.as_of.unique())
    receipt = {'first_test_signal': first_test_signal, 'training_dates': len(dates),
               'maximum_training_exit': training.label_exit_date.max() if len(training) else None,
               'status': 'insufficient_training', 'weights': None, 'validation': []}
    if len(dates) < minimum_outer_dates: return None, receipt
    validation_dates = dates[-6:]
    inner = mature_panel(training, validation_dates[0])
    if inner.as_of.nunique() < minimum_inner_dates: return None, receipt
    validation = training[training.as_of.isin(validation_dates)]
    choices = []
    for penalty in PENALTIES:
        weights = fit(inner, penalty)
        scored = validation.copy()
        scored['candidate'] = scored[list(BLOCKS)].to_numpy() @ weights
        values = [g.candidate.rank().corr(g.ret_126.rank()) for _, g in scored.groupby('as_of')]
        finite = [float(x) for x in values if np.isfinite(x)]
        choices.append({'penalty': penalty, 'mean_validation_ic': float(np.mean(finite)) if finite else None,
                        'validation_dates': len(finite)})
    valid = [x for x in choices if x['validation_dates'] >= 4]
    if not valid:
        receipt['validation'] = choices; return None, receipt
    # Stronger shrinkage wins an exact tie. No test outcomes enter this choice.
    chosen = max(valid, key=lambda r: (r['mean_validation_ic'], r['penalty']))
    weights = fit(training, chosen['penalty'])
    receipt.update(status='trained', weights=dict(zip(BLOCKS, map(float, weights))),
                   penalty=chosen['penalty'], validation=choices, inner_training_dates=int(inner.as_of.nunique()),
                   inner_maximum_label_exit=inner.label_exit_date.max(), first_validation_signal=validation_dates[0])
    assert receipt['maximum_training_exit'] < first_test_signal
    assert receipt['inner_maximum_label_exit'] < validation_dates[0]
    return weights, receipt
