"""Time splitting, label-maturity guard, block bootstrap and the risk table.

Random row-level splitting is forbidden. All splits are chronological. A model's
own warm-up window is removed from BOTH sides of a comparison so no candidate is
credited for data the baseline did not have.
"""
import numpy as np
import pandas as pd

MIN_TRAIN_MONTHS = 24
SELECT_MONTHS = 6
EVAL_MONTHS = 6
STEP_MONTHS = 6


def folds(months):
    """Chronological 24/6/6 folds moving 6 months at a time."""
    months = sorted(str(m) for m in months)
    if len(months) != len(set(months)) or (months and months != [str(p) for p in pd.period_range(months[0], months[-1], freq='M')]):
        raise ValueError('months_must_be_unique_and_contiguous')
    out = []
    i = 0
    while i + MIN_TRAIN_MONTHS + SELECT_MONTHS + EVAL_MONTHS <= len(months):
        train = months[i:i + MIN_TRAIN_MONTHS]
        select = months[i + MIN_TRAIN_MONTHS:i + MIN_TRAIN_MONTHS + SELECT_MONTHS]
        ev = months[i + MIN_TRAIN_MONTHS + SELECT_MONTHS:
                   i + MIN_TRAIN_MONTHS + SELECT_MONTHS + EVAL_MONTHS]
        out.append({'train': train, 'select': select, 'evaluate': ev})
        i += STEP_MONTHS
    return out


def maturity_guard(months, horizon_months, asof_last_month):
    """Drop training samples whose outcome window has not finished by `asof`."""
    limit = pd.Period(asof_last_month, freq='M')
    return [m for m in months
            if pd.Period(m, freq='M') + horizon_months <= limit]


def block_bootstrap(values, block=6, replications=2000, seed=20261015):
    """Bootstrap over time blocks, not over independent stock rows."""
    arr = np.asarray([v for v in values if np.isfinite(v)], float)
    if len(arr) == 0:
        return {'mean': None, 'ci95': [None, None], 'n': 0}
    blocks = max(1, int(np.ceil(len(arr) / block)))
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(replications):
        picks = rng.integers(0, len(arr), blocks)
        draws.append(np.concatenate([arr[(p + np.arange(block)) % len(arr)] for p in picks])[:len(arr)].mean())
    return {'mean': float(arr.mean()), 'ci95': [float(np.percentile(draws, 2.5)),
                                               float(np.percentile(draws, 97.5))], 'n': int(len(arr))}


def risk_table(candidates, baseline_name, max_extra_drawdown=0.05):
    """Return vs drawdown table. Default choice is never 'highest return, any drawdown'."""
    base = next(c for c in candidates if c['name'] == baseline_name)
    rows = []
    for c in candidates:
        extra_dd = abs(c['max_drawdown']) - abs(base['max_drawdown'])
        rows.append({'name': c['name'], 'final_toman': c['final_toman'], 'cagr': c['cagr'],
                     'max_drawdown': c['max_drawdown'], 'extra_drawdown_vs_baseline': extra_dd,
                     'within_risk_budget': extra_dd <= max_extra_drawdown})
    return sorted(rows, key=lambda r: -r['final_toman'])
