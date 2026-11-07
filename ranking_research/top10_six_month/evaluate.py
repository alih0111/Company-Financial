"""Registered fixed baselines, random controls, stress and explicit rejection gates."""
import numpy as np
import pandas as pd
from .common import read, write, checkpoint
from .portfolio import replay
from .walk_forward import make_schedule, run_path, six_months


def block_ci(values, cfg):
    x = np.asarray(values, dtype=float)
    # Two circular blocks can yield a degenerate interval. Small samples remain
    # explicitly insufficient rather than displaying spurious precision.
    if len(x) < 6: return [None, None]
    rng = np.random.default_rng(cfg['seed']); width = cfg['block_six_month_periods']; means = []
    for _ in range(cfg['replications']):
        indices = []
        while len(indices) < len(x):
            start = int(rng.integers(len(x))); indices += [(start + j) % len(x) for j in range(width)]
        means.append(float(x[indices[:len(x)]].mean()))
    return [float(q) for q in np.quantile(means, [.025, .975])]


def evaluate(out, prices):
    policy = read(out / 'protocol.json'); scores = pd.read_parquet(out / 'scores.parquet')
    state = read(out / 'walk_forward_status.json')
    if state['status'] != 'research_proxy_completed':
        write(out / 'acceptance.json', {'accepted': False, 'status': 'insufficient_data', 'real_orders': 0})
        checkpoint(out, 'evaluate', 'insufficient_data'); return
    weights = pd.read_csv(out / 'weights_by_date.csv').to_dict('records')
    primary = read(out / 'portfolio_summary.json')
    start = weights[0]['test_month']; end = weights[-1]['block_end_exclusive'][:7]
    start_date = start + '-01'; end_date = (pd.Timestamp(end + '-01') - pd.Timedelta(days=1)).date().isoformat()
    initial = policy['initial_toman'] * 10
    records = [{'name': 'walk_forward', 'purpose': 'primary', **primary}]; runs = {}
    directory = out / 'comparisons'; directory.mkdir(exist_ok=True)
    def cached_run(name, fn):
        target = directory / (name + '_checkpoint.json')
        if target.exists(): return read(target)
        result = fn(); write(target, result)
        checkpoint(out, 'evaluate', 'running', last_scenario=name)
        return result
    # Compare every pre-registered fixed weight/cadence on the same dates.
    for model in [*policy['weights'], 'equal_weight']:
        for cadence in policy['cadences_months']:
            key = f'{model}_{cadence}m'
            result = cached_run(key, lambda: replay(scores, prices, policy, start_date, end_date,
                            make_schedule(scores, start, end, model, cadence), keep=False))
            runs[key] = result
            records.append({'name': key, 'purpose': 'fixed_research_comparison', **result['summary']})
            pd.DataFrame(result['daily_nav']).to_csv(directory / f'{key}_daily.csv', index=False)
            pd.DataFrame(six_months(result['daily_nav'], weights, initial)).to_csv(directory / f'{key}_blocks.csv', index=False)
            print(f'fixed comparison {key}', flush=True)
    selected_schedule = {}
    for row in weights:
        selected_schedule.update(make_schedule(scores, row['test_month'], row['block_end_exclusive'][:7], row['model'], int(row['cadence_months'])))
    stress_cost = policy['cost_per_side'] * policy['stress']['cost_multiplier']
    stress_delay = policy['stress']['extra_delay_sessions']
    for name, schedule in [('walk_forward', selected_schedule),
                           ('balanced_1m', make_schedule(scores, start, end, 'balanced', 1)),
                           ('equal_weight_1m', make_schedule(scores, start, end, 'equal_weight', 1))]:
        result = cached_run(name + '_stress', lambda: replay(scores, prices, policy, start_date, end_date, schedule,
                        cost=stress_cost, delay=stress_delay, keep=False))
        runs[name + '_stress'] = result
        records.append({'name': name + '_stress', 'purpose': 'double_cost_one_session_delay', **result['summary']})
    # Five starts are sensitivities, never independent observations or a winning-start search.
    for offset in policy['calendar_offsets_months'][1:]:
        saved = directory / f'calendar_{offset}_checkpoint.json'
        if saved.exists(): result = read(saved)
        else:
            result, _, _ = run_path(scores, prices, policy, offset=offset, keep=False)
            write(saved, result)
        if result:
            records.append({'name': f'walk_forward_offset_{offset}', 'purpose': 'overlapping_calendar_sensitivity', **result['summary']})
        print(f'calendar sensitivity {offset}', flush=True)
    random_path = out / 'random_controls.csv'
    random_rows = pd.read_csv(random_path).to_dict('records') if random_path.exists() else []
    cfg = policy['random_seeds']
    random_frame = scores.copy()
    finished_seeds = {r['seed'] for r in random_rows}
    for seed in range(cfg['first'], cfg['first'] + cfg['count']):
        if seed in finished_seeds: continue
        rng = np.random.default_rng(seed)
        # Seeded scores assigned in stable company/date order; no outcomes consulted.
        random_frame = random_frame.sort_values(['decision_time', 'company_id']).reset_index(drop=True)
        random_frame['random'] = rng.random(len(random_frame))
        result = replay(random_frame, prices, policy, start_date, end_date,
                        make_schedule(scores, start, end, 'random', 1), keep=False)
        random_rows.append({'seed': seed, **result['summary']})
        pd.DataFrame(random_rows).to_csv(random_path, index=False)
        if len(random_rows) % 25 == 0: print(f'random controls {len(random_rows)}/{cfg["count"]}', flush=True)
    pd.DataFrame(random_rows).to_csv(random_path, index=False)
    pd.DataFrame(records).to_csv(out / 'comparison.csv', index=False)
    blocks = pd.read_csv(out / 'six_month_periods.csv')
    base_blocks = {key: pd.read_csv(directory / f'{key}_blocks.csv') for key in ['balanced_1m', 'equal_weight_1m']}
    excess = {key: (np.log1p(blocks['return']) - np.log1p(frame['return'])).tolist() for key, frame in base_blocks.items()}
    ci = {key: block_ci(values, policy['bootstrap']) for key, values in excess.items()}
    primary['worst_six_month'] = float(blocks['return'].min())
    checks = {
        'minimum_six_complete_blocks': len(blocks) >= policy['minimum_test_blocks'],
        'higher_final_wealth_than_both': all(primary['final_toman'] > runs[b]['summary']['final_toman'] for b in base_blocks),
        'positive_excess_in_majority_blocks': all(sum(x > 0 for x in v) > len(v) / 2 for v in excess.values()),
        'drawdown_within_five_points': abs(primary['max_drawdown']) <= abs(runs['equal_weight_1m']['summary']['max_drawdown']) + policy['maximum_extra_drawdown'],
        'stress_superiority_retained': all(runs['walk_forward_stress']['summary']['final_toman'] > runs[b + '_stress']['summary']['final_toman'] for b in base_blocks),
        'excess_confidence_excludes_zero': all(v[0] is not None and v[0] > 0 for v in ci.values()),
        'economic_execution_certified': False,
        'historical_listing_universe_certified': False,
        'complete_cash_liquidation_inside_selection_windows_certified': False,
        'six_year_history': (pd.Timestamp(scores.decision_time.max()) - pd.Timestamp(scores.decision_time.min())).days >= 365.25 * 6,
        'sufficient_population_every_test_decision': bool(scores[scores.decision_time.between(start_date, end_date)].groupby('decision_time').eligible.sum().ge(policy['minimum_population']).all())}
    acceptance = {'accepted': False, 'status': 'research_only_not_promotable', 'checks': checks,
                  'failed_checks': [k for k, v in checks.items() if not v], 'test_blocks': len(blocks),
                  'mean_log_excess_block_ci': ci, 'random_wealth_quantiles_toman': {
                      str(q): float(np.quantile([r['final_toman'] for r in random_rows], q)) for q in [.05, .5, .95]},
                  'primary_random_percentile': float(np.mean([r['final_toman'] < primary['final_toman'] for r in random_rows]) * 100),
                  'best_block_removed_log_excess': {k: float(sum(v) - max(v)) for k, v in excess.items()},
                  'baseline_legacy_comparability': 'See legacy_comparison.csv for recomputed QVT76 subset/CASH_QV; SCREEN remains noncomparable because monthly publication history is incomplete',
                  'official_index': 'no independently verified compatible total-return index supplied',
                  'calendar_sensitivities_independent': False, 'real_orders': 0}
    write(out / 'acceptance.json', acceptance)
    checkpoint(out, 'evaluate', scenarios=len(records), random_controls=len(random_rows))
