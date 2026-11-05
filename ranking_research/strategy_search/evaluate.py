"""Wave evaluation: protocol gates, each with a pass/fail field and numeric
evidence (corrective 2.6).

Primary criterion is the continuous 100M path on the shared ledger. Everything
is compared on identical non-overlapping 6-month blocks. Uncertainty is a
PAIRWISE temporal block bootstrap of the candidate-vs-baseline block excess
(circular moving-block; no tail data is silently dropped). Gates:

  g1 material_improvement   final capital >= baseline * 1.10
  g2 winning_blocks         candidate beats baseline in > half of the blocks
  g3 survives_best_block    after removing the block with the candidate's
                            LARGEST log wealth advantage, the product of the
                            remaining block wealth ratios is still > 1
  g4 extra_drawdown         <= 5 percentage points vs the baseline
  g5 stress                 (optional) same candidate under pre-registered stress

A single-candidate CI after a multi-candidate search is NOT independent
statistical confirmation; it is reported separately from the gates.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / 'output' / 'strategy_search'
MAX_EXTRA_DRAWDOWN = 0.05
MATERIAL_IMPROVEMENT = 0.10
BOOT_BLOCK = 2          # pre-registered: two 6-month blocks per bootstrap draw
BOOT_REPS = 2000
BOOT_SEED = 20261015


def blocks_from_nav(run, exp_id, months=6):
    p = Path(run) / 'results' / f'{exp_id}.nav.csv'
    if not p.exists():
        return None
    d = pd.read_csv(p)
    d['month'] = d.date.str[:7]
    monthly = d.groupby('month').nav_rial.last()
    keys = list(monthly.index)
    if not keys:
        return None
    out = {}
    for i in range(0, len(keys) - months + 1, months):
        prior = monthly.iloc[i - 1] if i > 0 else 1e9  # initial capital, 100M toman in rial
        out[keys[i]] = float(monthly.iloc[i + months - 1] / prior - 1)
    return out


def pairwise_block_excess(cand_blocks, base_blocks):
    """Aligned per-block log wealth excess, log((1+c)/(1+b))."""
    common = sorted(set(cand_blocks) & set(base_blocks))
    if not common:
        return None, None
    c = np.array([cand_blocks[m] for m in common])
    b = np.array([base_blocks[m] for m in common])
    log_excess = np.log1p(c) - np.log1p(b)
    return log_excess, common


def pairwise_bootstrap(log_excess, block=BOOT_BLOCK, reps=BOOT_REPS, seed=BOOT_SEED):
    """Circular moving-block bootstrap of the mean block log excess.

    Every observation is used: a partial tail block wraps to the start instead
    of being dropped. The CI is reported in PERCENT (exp(x)-1), not fraction.
    """
    arr = np.asarray(log_excess, float)
    n = len(arr)
    if n == 0:
        return {'mean_log_excess': None, 'ci95_percent': [None, None], 'n': 0,
                'block': block, 'replications': reps, 'note': 'no_blocks'}
    rng = np.random.default_rng(seed)
    draws = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, n, max(1, int(np.ceil(n / block))))
        picks = np.concatenate([arr[(s + np.arange(block)) % n] for s in starts])[:n]
        draws[r] = picks.mean()
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {'mean_log_excess': float(arr.mean()),
            'mean_excess_percent': float(np.expm1(arr.mean()) * 100),
            'ci95_percent': [float(np.expm1(lo) * 100), float(np.expm1(hi) * 100)],
            'n': int(n), 'block': block, 'replications': reps}


def survives_best_block(log_excess, common):
    """Remove the block with the candidate's largest advantage; the product of
    the remaining wealth ratios must exceed 1."""
    if log_excess is None or len(log_excess) == 0:
        return {'removed_block': None, 'remaining_wealth_ratio': None, 'passes': False}
    i = int(np.argmax(log_excess))
    rest = np.delete(log_excess, i)
    ratio = float(np.exp(rest.sum()))
    return {'removed_block': common[i], 'remaining_blocks': int(len(rest)),
            'remaining_wealth_ratio': ratio, 'passes': bool(ratio > 1.0)}


def evaluate(run_dir=None, stress=None):
    sys.stdout.reconfigure(encoding='utf8')
    run = Path(run_dir) if run_dir else Path(json.loads((OUT / 'latest.json').read_text(encoding='utf8'))['run_path'])
    comp = pd.read_csv(run / 'comparison.csv')
    results = []
    for scope in comp.scope.unique():
        base_id = comp[comp.scope.eq(scope) & comp.label.eq('balanced')].experiment_id
        if base_id.empty:
            base_id = comp[comp.label.eq('balanced')].experiment_id
        if base_id.empty:
            continue
        base_id = base_id.iloc[0]
        base_blocks = blocks_from_nav(run, base_id)
        base_row = comp[comp.experiment_id.eq(base_id)]
        if base_blocks is None or base_row.empty:
            continue
        base_dd = float(base_row.max_drawdown.iloc[0])
        base_final = float(base_row.final_toman.iloc[0])
        for r in comp[(comp.scope.eq(scope)) & comp.final_toman.notna()].itertuples():
            if r.experiment_id == base_id or r.kind not in ('signal', 'baseline'):
                continue
            reference_id = getattr(r, 'baseline_id', None)
            if isinstance(reference_id, str) and reference_id:
                ref_row = comp[comp.experiment_id.eq(reference_id)].iloc[0]
                base_blocks = blocks_from_nav(run, reference_id)
                base_dd = float(ref_row.max_drawdown)
                base_final = float(ref_row.final_toman)
            b = blocks_from_nav(run, r.experiment_id)
            if not b:
                continue
            log_excess, common = pairwise_block_excess(b, base_blocks)
            if log_excess is None:
                continue
            boot = pairwise_bootstrap(log_excess)
            sbb = survives_best_block(log_excess, common)
            wins = int((log_excess > 0).sum())
            gain = r.final_toman / base_final - 1
            extra_dd = abs(r.max_drawdown) - abs(base_dd)
            gates = {
                'g1_material_improvement': bool(gain >= MATERIAL_IMPROVEMENT),
                'g2_winning_blocks': bool(wins * 2 > len(common)),
                'g3_survives_best_block': bool(sbb['passes']),
                'g4_extra_drawdown': bool(extra_dd <= MAX_EXTRA_DRAWDOWN),
                'g5_stress': (None if stress is None else bool(stress.get(r.experiment_id))),
            }
            results.append({
                'scope': scope, 'candidate': r.experiment_id, 'kind': r.kind,
                'final_toman': float(r.final_toman), 'gain_vs_balanced': float(gain),
                'gain_vs_balanced_percent': float(gain * 100),
                'cagr': float(r.cagr), 'max_drawdown': float(r.max_drawdown),
                'extra_drawdown': float(extra_dd),
                'extra_drawdown_percent': float(extra_dd * 100),
                'winning_blocks': wins, 'blocks': len(common),
                'mean_excess_per_block_percent': boot['mean_excess_percent'],
                'excess_ci95_percent': boot['ci95_percent'],
                'best_block_removed': sbb,
                'gates': gates,
                'passes_original_gates_1to4': bool(all(gates[k] for k in list(gates)[:4])),
                'passes_all_gates': bool(all(v is True for v in gates.values())),
                'top_five_share_of_positive_pnl': (None if pd.isna(r.top_five_share_of_positive_pnl)
                                                    else float(r.top_five_share_of_positive_pnl)),
                'average_cash_fraction': float(r.average_cash_fraction),
                'cost_toman': float(r.cost_toman),
                'ci_note': 'single-candidate CI after a multi-candidate search is '
                           'not independent statistical confirmation',
            })
    table = pd.DataFrame(results)
    if len(table):
        table = table.sort_values(['scope', 'gain_vs_balanced'], ascending=[True, False])
    table.to_csv(run / 'evaluation.csv', index=False)
    out = {'run': str(run), 'baseline': 'balanced four-factor, same engine and policy',
           'material_improvement_threshold': MATERIAL_IMPROVEMENT,
           'max_extra_drawdown': MAX_EXTRA_DRAWDOWN,
           'bootstrap': {'kind': 'pairwise circular moving-block on 6-month blocks',
                         'block': BOOT_BLOCK, 'replications': BOOT_REPS, 'seed': BOOT_SEED,
                         'note': f'{len(common) if results else 0} blocks is a small sample; '
                                 'the CI is wide and the gates remain the primary filter'},
           'candidates': results,
           'any_candidate_passes': bool(table.passes_all_gates.any()) if len(table) else False,
           'verdict': ('no_signal_beats_balanced_on_all_gates' if not (len(table) and table.passes_all_gates.any())
                       else 'a_candidate_passed_all_gates')}
    (run / 'evaluation.json').write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                                    default=str), encoding='utf8')
    return out, table


if __name__ == '__main__':
    result, table = evaluate(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps({k: result[k] for k in ('verdict', 'any_candidate_passes')}, ensure_ascii=False))
    if len(table):
        cols = ['scope', 'candidate', 'final_toman', 'gain_vs_balanced_percent',
                'extra_drawdown_percent', 'winning_blocks', 'blocks',
                'mean_excess_per_block_percent', 'passes_all_gates']
        print(table[cols].to_string(index=False, float_format=lambda x: f'{x:.4g}'))
