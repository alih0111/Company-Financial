"""Point-in-time passive benchmarks on the shared ledger.

The earlier `tradeable_benchmark_probe.py` decided universe membership from the
whole 4-year window and averaged monthly returns outside the engine. This module
fixes both defects:

  * membership at each decision date uses only trailing sessions (no look-ahead);
  * the benchmark runs through the same `replay` ledger as every candidate, with
    the same cost, capacity, next-session-open execution and continuous capital.

It also exposes the structural limit that cannot be fixed from this archive: the
archive contains only currently-listed survivors, so no benchmark here can carry
a delisted name to zero.
"""
import numpy as np
import pandas as pd
from bisect import bisect_right

from .engine import run_experiment, START, END

MED_RIAL_MIN = 1e10        # 1 billion toman/day
ZERO_FRAC_MAX = 0.2
TRAILING_SESSIONS = 120
MIN_OBS = 30


def _profile(md, sym, d0, trailing):
    rec = md.data.get(sym)
    if rec is None:
        return None
    idx = [rec['dmap'][d] for d in trailing if d in rec['dmap']]
    if len(idx) < MIN_OBS:
        return None
    tv = np.asarray(rec['tval'][idx], float)
    cap_idx = idx[-20:]
    cap = 0.01 * float(np.median(np.asarray(rec['tval'][cap_idx], float))) if cap_idx else 0.0
    return {'med_tval': float(np.nanmedian(tv)), 'zero_frac': float((tv <= 0).mean()), 'capacity': cap}


def build_universe_frame(panel, md, which='pit_liquid'):
    """Score frame with equal weight over a point-in-time universe."""
    cal = sorted(md.cal)
    months = sorted(panel.decision_time.astype(str).str[:7].unique())
    ids = panel.drop_duplicates('symbol').set_index('symbol').company_id.to_dict()
    rows = []
    for month in months:
        sample = panel[panel.decision_time.astype(str).str[:7].eq(month)]
        d0 = str(sample.decision_time.iloc[0])
        trailing = [d for d in cal if d <= d0][-TRAILING_SESSIONS:]
        for sym, rec in md.data.items():
            if d0 not in rec['dmap']:
                continue
            p = _profile(md, sym, d0, trailing)
            if which == 'pit_liquid':
                if not p or p['med_tval'] < MED_RIAL_MIN or p['zero_frac'] > ZERO_FRAC_MAX:
                    continue
                cap = p['capacity']
            else:  # all_listed: any symbol that has a price on the decision date
                cap = p['capacity'] if p else 0.0
            rows.append({'decision_time': d0, 'company_id': ids.get(sym, sym), 'symbol': sym,
                         'capacity_rial': cap, 'eligible': True, 'score': 0.0})
    return pd.DataFrame(rows)


def run(panel, md, policy, prices=None):
    out = {}
    for which in ('all_listed', 'pit_liquid'):
        frame = build_universe_frame(panel, md, which)
        pol = {**policy, 'name': f'benchmark_ew_{which}', 'top_n': 10, 'weight': 'equal'}
        res = run_experiment(frame, md, pol, prices=prices, model='equal_weight')
        res['universe_rows'] = len(frame)
        res['universe_last_month_size'] = int(frame[frame.decision_time.eq(frame.decision_time.max())].shape[0])
        out[which] = res
    return out
