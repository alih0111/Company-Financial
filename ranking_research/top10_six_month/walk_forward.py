"""Select only with calendar windows ending before each outer block."""
import numpy as np
import pandas as pd
from .portfolio import replay
from .common import write, read, checkpoint


def shift(date, months):
    return (pd.Timestamp(date).to_period('M') + months).strftime('%Y-%m')


def calendar(scores):
    return {str(d)[:7]: str(d) for d in sorted(scores.decision_time.unique())}


def make_schedule(scores, start_month, end_month, model, cadence):
    dates = calendar(scores)
    first = pd.Period(start_month, freq='M')
    return {date: (model, 10) for month, date in dates.items()
            if start_month <= month < end_month and (pd.Period(month, freq='M') - first).n % cadence == 0}


def block_bounds(scores, offset=0):
    dates = calendar(scores)
    # Start with the first eligible observation, not the best-return start.
    eligible = scores.loc[scores.eligible, 'decision_time']
    if eligible.empty: return []
    first = shift(eligible.min(), 36 + offset)
    last_month = max(dates)
    bounds = []
    while shift(first + '-01', 6) <= last_month:
        end = shift(first + '-01', 6)
        # A missing decision month is a data gap, not permission to shift a rebalance.
        bounds.append((first, end)); first = end
    return bounds


def choose(scores, prices, protocol, test_month, cost=None, delay=0):
    screen_start = shift(test_month + '-01', -36)
    select_start = shift(test_month + '-01', -12)
    cache = {}

    def result(model, cadence, start, end):
        key = (model, cadence, start, end)
        if key not in cache:
            schedule = make_schedule(scores, start, end, model, cadence)
            # Scoring and decisions restricted to the section; no crossing labels.
            result = replay(scores[scores.decision_time.lt(end + '-01')], prices, protocol,
                            start + '-01', (pd.Timestamp(end + '-01') - pd.Timedelta(days=1)).date().isoformat(),
                            schedule, cost=cost, delay=delay, keep=False)
            cache[key] = result['summary']
        return cache[key]

    screened = []
    trials = []
    for model in protocol['weights']:
        for cadence in protocol['cadences_months']:
            perf = result(model, cadence, screen_start, select_start)
            baseline = result('equal_weight', cadence, screen_start, select_start)
            valid = abs(perf['max_drawdown']) <= abs(baseline['max_drawdown']) + protocol['maximum_extra_drawdown']
            trial = {'test_month': test_month, 'stage': 'screen', 'model': model, 'cadence_months': cadence,
                     'window_start': screen_start, 'window_end_exclusive': select_start,
                     'wealth': perf['final_toman'], 'max_drawdown': perf['max_drawdown'], 'risk_pass': valid}
            trials.append(trial)
            if valid: screened.append(trial)
    screened.sort(key=lambda r: (-r['wealth'], abs(r['max_drawdown']), f"{r['model']}_{r['cadence_months']}m"))
    finalists = []
    for candidate in screened[:3]:
        model, cadence = candidate['model'], candidate['cadence_months']
        perf = result(model, cadence, select_start, test_month)
        baseline = result('equal_weight', cadence, select_start, test_month)
        valid = abs(perf['max_drawdown']) <= abs(baseline['max_drawdown']) + protocol['maximum_extra_drawdown']
        row = {'test_month': test_month, 'stage': 'select', 'model': model, 'cadence_months': cadence,
               'window_start': select_start, 'window_end_exclusive': test_month,
               'wealth': perf['final_toman'], 'max_drawdown': perf['max_drawdown'], 'risk_pass': valid}
        trials.append(row)
        if valid: finalists.append(row)
    finalists.sort(key=lambda r: (-r['wealth'], abs(r['max_drawdown']), f"{r['model']}_{r['cadence_months']}m"))
    selected = finalists[0] if finalists else {'model': 'balanced', 'cadence_months': 1}
    return {**selected, 'test_month': test_month, 'fallback': not bool(finalists),
            'selection_information_end_exclusive': test_month + '-01'}, trials


def run_path(scores, prices, protocol, offset=0, cost=None, delay=0, keep=True):
    bounds = block_bounds(scores, offset)
    if not bounds: return None, [], []
    schedule = {}; weights = []; all_trials = []
    for start, end in bounds:
        # Stress freezes original decisions: selection always uses base costs/delay.
        selection, trials = choose(scores, prices, protocol, start)
        weights.append({**selection, 'block_end_exclusive': end + '-01',
                        'weights': protocol['weights'][selection['model']]})
        all_trials += trials
        schedule.update(make_schedule(scores, start, end, selection['model'], selection['cadence_months']))
    result = replay(scores, prices, protocol, bounds[0][0] + '-01',
                    (pd.Timestamp(bounds[-1][1] + '-01') - pd.Timedelta(days=1)).date().isoformat(),
                    schedule, cost=cost, delay=delay, keep=keep)
    return result, weights, all_trials


def write_result(out, result):
    columns = {
        'orders': ['order_id', 'decision_time', 'symbol', 'side', 'requested_units', 'remaining_units', 'last_reason'],
        'fills': ['fill_id', 'order_id', 'date', 'decision_time', 'symbol', 'side', 'index_units', 'gross_rial', 'fee_rial'],
        'cash_ledger': ['fill_id', 'date', 'cash_before_rial', 'cash_change_rial', 'cash_after_rial'],
        'holdings': ['date', 'symbol', 'index_units', 'value_rial', 'stale_days'],
        'daily_nav': ['date', 'nav_rial', 'cash_rial', 'stale_positions', 'missing_marks'],
        'selections': ['decision_time', 'company_id', 'symbol', 'model', 'rank', 'target_weight']}
    for name, empty_columns in columns.items():
        pd.DataFrame(result[name] if result[name] else [], columns=None if result[name] else empty_columns).to_csv(out / f'{name}.csv', index=False)
    decisions = pd.DataFrame(result['decisions'])
    if not decisions.empty:
        decisions['next_decision'] = decisions.decision_time.shift(-1)
        decisions['end_nav_rial'] = decisions.nav_rial.shift(-1)
        decisions.loc[decisions.index[-1], 'end_nav_rial'] = result['daily_nav'][-1]['nav_rial']
        decisions['return'] = decisions.end_nav_rial / decisions.nav_rial - 1
    decisions.to_csv(out / 'rebalance_periods.csv', index=False)
    write(out / 'portfolio_summary.json', result['summary'])


def six_months(daily, weights, initial):
    rows = []; prior = initial
    for w in weights:
        dates = [r for r in daily if w['test_month'] <= r['date'][:7] < w['block_end_exclusive'][:7]]
        if not dates: continue
        end = dates[-1]['nav_rial']
        rows.append({'start': w['test_month'], 'end_exclusive': w['block_end_exclusive'],
                     'initial_toman': prior / 10, 'final_toman': end / 10, 'return': end / prior - 1,
                     'model': w['model'], 'cadence_months': w['cadence_months']})
        prior = end
    return rows


def walk_forward(out, prices):
    scores = pd.read_parquet(out / 'scores.parquet'); protocol = read(out / 'protocol.json')
    result, weights, trials = run_path(scores, prices, protocol)
    if result is None:
        write(out / 'walk_forward_status.json', {'status': 'insufficient_36_month_history'})
        checkpoint(out, 'walk_forward', 'insufficient_data'); return
    write_result(out, result)
    pd.DataFrame(weights).to_csv(out / 'weights_by_date.csv', index=False)
    pd.DataFrame(trials).to_csv(out / 'selection_trials.csv', index=False)
    blocks = six_months(result['daily_nav'], weights, protocol['initial_toman'] * 10)
    pd.DataFrame(blocks).to_csv(out / 'six_month_periods.csv', index=False)
    write(out / 'walk_forward_status.json', {'status': 'research_proxy_completed', 'blocks': len(blocks),
          'integer_units': 'normalized adjusted-price index units, not deliverable shares',
          'selection_terminal_valuation': 'marked NAV inside each window; complete cash liquidation is not certified',
          'real_orders': 0})
    checkpoint(out, 'walk_forward', blocks=len(blocks))
