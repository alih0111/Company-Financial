"""Thin execution wrapper: reuses the frozen adjusted-price engine unchanged.

No new price, capacity or fill model is introduced. `Prices`, `replay` and
`six_months` come from `ranking_research.top10_six_month`, so any candidate is
measured on exactly the same ledger as the existing baseline.
"""
import numpy as np
import pandas as pd

from ranking_research.top10_six_month.portfolio import Prices, replay
from ranking_research.top10_six_month.walk_forward import make_schedule, six_months

START = '2022-03-01'
END = '2026-02-28'
END_MONTH = '2026-03'


def protocol_for(policy, **overrides):
    proto = {
        'initial_toman': policy['initial_toman'],
        'rial_per_toman': 10,
        'top_n': policy['top_n'],
        'cost_per_side': policy['cost_per_side'],
        'liquidity_sessions': 20,
        'order_capacity_fraction': 0.01,
        'maximum_order_sessions': 5,
    }
    proto.update(overrides)
    return proto


def ledger_check(result, frame):
    """Cash reconciles to fills; holdings reconcile to buys/sells; NAV reconciles."""
    cash = float(result['summary']['initial_toman'] * 10)
    qty = {}
    for fill, entry in zip(result['fills'], result['cash_ledger']):
        assert fill['date'] > fill['decision_time']
        delta = (-1 if fill['side'] == 'buy' else 1) * fill['gross_rial'] - fill['fee_rial']
        assert abs(delta - entry['cash_change_rial']) < .01
        cash += delta
        assert cash >= -.01
    actual = {}
    for h in result['holdings']:
        actual.setdefault(h['date'], {})[h['symbol']] = h
    by_day = {}
    for fill in result['fills']:
        by_day.setdefault(fill['date'], []).append(fill)
    for row in result['daily_nav']:
        for fill in by_day.get(row['date'], []):
            qty[fill['symbol']] = qty.get(fill['symbol'], 0) + (1 if fill['side'] == 'buy' else -1) * fill['index_units']
        held = actual.get(row['date'], {})
        assert {s: q for s, q in qty.items() if q} == {s: r['index_units'] for s, r in held.items()}
        assert abs(row['nav_rial'] - row['cash_rial'] - sum(h['value_rial'] for h in held.values())) < .01
    return True


def concentration(result, policy):
    """Per-symbol P&L attributed from fills plus terminal holdings."""
    fills = pd.DataFrame(result['fills'])
    holds = pd.DataFrame(result['holdings'])
    total = result['summary']['final_toman'] - policy['initial_toman']
    if fills.empty:
        return {'total_pnl_toman': total, 'top_five_share': None, 'best_symbol': None, 'symbols': 0}
    terminal_date = result['daily_nav'][-1]['date']
    terminal = holds[holds.date.eq(terminal_date)].set_index('symbol').value_rial.to_dict()
    values = np.where(fills.side.eq('sell'), fills.gross_rial, -fills.gross_rial) - fills.fee_rial
    flows = fills.assign(pnl=values).groupby('symbol').pnl.sum()
    pnl = {s: (flows.get(s, 0) + terminal.get(s, 0)) / 10 for s in set(flows.index) | set(terminal)}
    gains = sorted([v for v in pnl.values() if v > 0], reverse=True)
    return {'total_pnl_toman': float(total), 'symbols': len(pnl),
            'positive_pnl_toman': float(sum(gains)),
            'top_five_share_of_positive_pnl': float(sum(gains[:5]) / sum(gains)) if gains else None,
            'best_symbol': max(pnl, key=pnl.get) if pnl else None}


def run_experiment(frame, md, policy, cost_mult=1.0, delay=0, keep=True, prices=None,
                   model='score'):
    """Run one candidate on the shared ledger and return summary + diagnostics.

    `model='equal_weight'` makes the engine hold every eligible name at equal
    weight (the replay divisor becomes the held count), which is how a passive
    universe benchmark is built on the same ledger as a ranked candidate.
    """
    prices = prices or Prices(md)
    proto = protocol_for(policy, cost_per_side=policy['cost_per_side'] * cost_mult)
    schedule = make_schedule(frame, START[:7], END_MONTH, model, policy['cadence_months'])
    result = replay(frame, prices, proto, START, END, schedule,
                    cost=proto['cost_per_side'], delay=delay, keep=keep)
    passed = ledger_check(result, frame)
    bounds = [{'test_month': m, 'block_end_exclusive': e, 'model': 'score',
               'cadence_months': policy['cadence_months']}
              for m, e in _six_month_bounds(frame)]
    blocks = six_months(result['daily_nav'], bounds, policy['initial_toman'] * 10)
    summary = dict(result['summary'])
    summary['scenario'] = policy['name']
    summary['cost_multiplier'] = cost_mult
    summary['delay_sessions'] = delay
    summary['ledger_passed'] = passed
    summary['scheduled_rebalances'] = len(schedule)
    summary['realized_rebalances'] = len(result['decisions'])
    return {'summary': summary, 'blocks': blocks, 'concentration': concentration(result, policy),
            'daily_nav': result['daily_nav'], 'fills': result['fills'],
            'orders': result['orders'], 'selections': result['selections']}


def _six_month_bounds(frame):
    months = sorted(frame.decision_time.astype(str).str[:7].unique())
    if not months:
        return []
    first = pd.Period(months[0], freq='M')
    bounds = []
    cur = first
    while cur + 6 <= pd.Period(months[-1], freq='M') + 1:
        nxt = cur + 6
        bounds.append((str(cur), str(nxt) + '-01'))
        cur = nxt
    return bounds
