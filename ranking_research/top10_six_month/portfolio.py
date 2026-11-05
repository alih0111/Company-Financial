"""Continuous cash-constrained adjusted-price proxy, never certified share accounting.

Integer units belong to a normalized price index, NOT actual deliverable shares.
The index has raw price at its first observation and incorporates subsequent
adjustment factors only as their event dates arrive. No dividend cash is added.
Unknown queues skip flat or incomplete OHLC sessions. This is a scenario, not
proof of fills; acceptance must reject economic certification.
"""
from bisect import bisect_right
import math
import numpy as np
import pandas as pd


class Prices:
    def __init__(self, md, unit_scale=1_000_000):
        self.cal = sorted(md.cal)
        self.mark_cache = {}; self.execution_cache = {}; self.age_cache = {}
        self.data = {}
        for symbol, rec in md.data.items():
            # Micro-index units prevent an old share's accumulated adjustments
            # from creating an artificial minimum lot worth most of the fund.
            # The constant scale is independent of future prices and returns.
            ratio = rec['cf'] / rec['cf'][0] / unit_scale
            self.data[symbol] = {
                'dates': rec['dates'], 'dmap': rec['dmap'],
                'price': rec['c'] * ratio, 'open': rec['o'] * ratio,
                'raw_price': rec['c'], 'volume': rec['vol'], 'value': rec['tval'],
                'high': rec['h'], 'low': rec['l'], 'ratio': ratio}

    def mark(self, symbol, date):
        key = (symbol, date)
        if key not in self.mark_cache: self.mark_cache[key] = self._mark(symbol, date)
        return self.mark_cache[key]

    def age(self, symbol, date):
        key = (symbol, date)
        if key not in self.age_cache:
            marked = self.mark(symbol, date)[1]
            self.age_cache[key] = (pd.Timestamp(date) - pd.Timestamp(marked)).days if marked else 99999
        return self.age_cache[key]

    def _mark(self, symbol, date):
        rec = self.data.get(symbol)
        if rec is None: return None, None
        i = bisect_right(rec['dates'], date) - 1
        while i >= 0:
            price = rec['price'][i]
            if np.isfinite(price) and price > 0: return float(price), rec['dates'][i]
            i -= 1
        return None, None

    def execution(self, symbol, date):
        key = (symbol, date)
        if key not in self.execution_cache: self.execution_cache[key] = self._execution(symbol, date)
        return self.execution_cache[key]

    def _execution(self, symbol, date):
        rec = self.data.get(symbol)
        if rec is None or date not in rec['dmap']: return None, 0, 'no_session'
        i = rec['dmap'][date]
        if rec['volume'][i] <= 0: return None, 0, 'zero_volume'
        if not all(np.isfinite(rec[k][i]) and rec[k][i] > 0 for k in ['open', 'high', 'low']):
            return None, 0, 'missing_ohlc'
        if rec['high'][i] <= rec['low'][i]: return None, 0, 'flat_session_possible_queue'
        price = float(rec['open'][i])
        # Volume converted to index units through the same causal scale.
        units = int(rec['volume'][i] / rec['ratio'][i] * .01)
        return price, units, 'proxy_fill_uncertified'


def summarize(daily, initial, orders=None, fills=None):
    if not daily:
        return {'initial_toman': initial / 10, 'final_toman': initial / 10, 'net_return': 0.,
                'cagr': 0., 'max_drawdown': 0., 'start': None, 'end': None, 'cost_toman': 0.,
                'turnover': 0., 'average_cash_fraction': 1., 'unfilled_orders': 0,
                'worst_month': None, 'worst_six_month': None, 'average_holding_days': None}
    nav = np.array([initial] + [r['nav_rial'] for r in daily])
    days = max(1, (pd.Timestamp(daily[-1]['date']) - pd.Timestamp(daily[0]['date'])).days)
    fills = fills or []; orders = orders or []
    monthly = pd.DataFrame(daily).assign(month=lambda x: x.date.str[:7]).groupby('month').nav_rial.last()
    monthly_returns = monthly.pct_change(); monthly_returns.iloc[0] = monthly.iloc[0] / initial - 1
    anchored = pd.concat([pd.Series([initial], index=['initial']), monthly.reset_index(drop=True)])
    six_month_returns = anchored.pct_change(6).dropna()
    lots = {}; holding_days_sum = 0.; closed_units = 0
    for f in fills:
        if f['side'] == 'buy':
            lots.setdefault(f['symbol'], []).append([f['date'], f['index_units']])
        else:
            remaining = f['index_units']; queue = lots.setdefault(f['symbol'], [])
            while remaining and queue:
                amount = min(remaining, queue[0][1])
                holding_days_sum += amount * (pd.Timestamp(f['date']) - pd.Timestamp(queue[0][0])).days
                closed_units += amount; remaining -= amount; queue[0][1] -= amount
                if queue[0][1] == 0: queue.pop(0)
    return {'initial_toman': initial / 10, 'final_toman': float(nav[-1] / 10),
            'net_return': float(nav[-1] / initial - 1), 'cagr': float((nav[-1] / initial) ** (365.25 / days) - 1),
            'max_drawdown': float((nav / np.maximum.accumulate(nav) - 1).min()),
            'start': daily[0]['date'], 'end': daily[-1]['date'],
            'cost_toman': sum(f['fee_rial'] for f in fills) / 10,
            'turnover': sum(f['gross_rial'] for f in fills) / initial,
            'average_cash_fraction': float(np.mean([r['cash_rial'] / r['nav_rial'] for r in daily])),
            'unfilled_orders': sum(o['remaining_units'] > 0 for o in orders),
            'worst_month': float(monthly_returns.min()),
            'worst_six_month': float(six_month_returns.min()) if len(six_month_returns) else None,
            'average_holding_days': float(holding_days_sum / closed_units) if closed_units else None}


def replay(scores, prices, protocol, start, end, schedule, cost=None, delay=0, keep=True):
    """Schedule date -> (score column, target count). Does not consume outcomes.

    All decisions use closing marks on the decision date, then execute strictly
    later at session open. Pending sales remain held after timeout. New decisions
    cancel/recompute outstanding orders; no artificial reset at block boundaries.
    """
    cash = float(protocol['initial_toman'] * protocol['rial_per_toman'])
    initial = cash; positions = {}; pending = []; orders = []; fills = []; ledger = []
    daily = []; holdings = []; selections = []; decisions = []
    cost = protocol['cost_per_side'] if cost is None else cost
    groups = {str(d): g[g.eligible].copy() for d, g in scores.groupby('decision_time')}
    days = [d for d in prices.cal if start <= d <= end]
    for day in days:
        # Execute only orders made before this session. Sells first, then cash-limited buys.
        used_capacity = {}
        for order in sorted(pending, key=lambda o: (o['side'] != 'sell', o['order_id'])):
            if day <= order['decision_time']: raise AssertionError('same_session_fill')
            order['elapsed_sessions'] += 1
            if order['elapsed_sessions'] <= delay: continue
            if order['attempts'] >= protocol['maximum_order_sessions'] or order['remaining_units'] <= 0: continue
            order['attempts'] += 1
            price, capacity, reason = prices.execution(order['symbol'], day)
            order['last_reason'] = reason
            if price is None: continue
            capacity = min(capacity, int(order['capacity_remaining_rial'] / price))
            capacity = max(0, capacity - used_capacity.get(order['symbol'], 0))
            quantity = min(order['remaining_units'], capacity)
            if order['side'] == 'buy': quantity = min(quantity, int(cash / (price * (1 + cost))))
            else: quantity = min(quantity, positions.get(order['symbol'], 0))
            if quantity <= 0: order['last_reason'] = 'cash_or_capacity'; continue
            gross = quantity * price; fee = gross * cost
            sign = 1 if order['side'] == 'buy' else -1
            cash_before = cash; cash += -sign * gross - fee
            positions[order['symbol']] = positions.get(order['symbol'], 0) + sign * quantity
            if positions[order['symbol']] == 0: del positions[order['symbol']]
            order['remaining_units'] -= quantity; order['capacity_remaining_rial'] -= gross
            used_capacity[order['symbol']] = used_capacity.get(order['symbol'], 0) + quantity
            fill = {'fill_id': len(fills), 'order_id': order['order_id'], 'date': day,
                    'decision_time': order['decision_time'], 'symbol': order['symbol'], 'side': order['side'],
                    'index_units': quantity, 'index_price_rial': price, 'gross_rial': gross, 'fee_rial': fee}
            fills.append(fill)
            ledger.append({'fill_id': fill['fill_id'], 'date': day, 'cash_before_rial': cash_before,
                           'cash_change_rial': cash - cash_before, 'cash_after_rial': cash})
            assert cash >= -.00001
        pending = [o for o in pending if o['remaining_units'] > 0 and o['attempts'] < protocol['maximum_order_sessions']]
        marks = {}; stale = 0; missing = 0; fresh_value = 0
        for symbol, quantity in positions.items():
            price, date = prices.mark(symbol, day)
            if price is None: missing += 1; price = 0
            age = prices.age(symbol, day)
            stale += age > 7; marks[symbol] = price
            if age <= 7: fresh_value += quantity * price
            if keep: holdings.append({'date': day, 'symbol': symbol, 'index_units': quantity,
                                      'index_price_rial': price, 'value_rial': quantity * price,
                                      'price_date': date, 'stale_days': age})
        nav = cash + sum(positions[s] * marks[s] for s in positions)
        daily.append({'date': day, 'nav_rial': nav, 'cash_rial': cash,
                      'stale_positions': stale, 'missing_marks': missing,
                      'lower_mark_bound_rial': cash + fresh_value})
        if day not in schedule: continue
        model, target_count = schedule[day]
        group = groups.get(day, scores.iloc[:0])
        chosen = group.sort_values([model, 'company_id'], ascending=[False, True]).head(target_count) if model != 'equal_weight' else group.sort_values('company_id')
        # Ten slots even when fewer names qualify; do not redistribute missing slots.
        divisor = len(chosen) if model == 'equal_weight' else protocol['top_n']
        targets = {}
        for rank, row in enumerate(chosen.itertuples(), 1):
            price, _ = prices.mark(row.symbol, day)
            if price is None: continue
            units = math.floor(nav / max(divisor, 1) / price)
            targets[row.symbol] = (units, float(row.capacity_rial))
            selections.append({'decision_time': day, 'company_id': row.company_id, 'symbol': row.symbol,
                               'model': model, 'rank': rank, 'target_weight': 1 / max(divisor, 1),
                               'target_index_units': units, 'score': float(getattr(row, model)) if model != 'equal_weight' else None})
        for order in pending: order['last_reason'] = 'cancelled_at_next_decision'
        pending = []
        # Exit capacity is based on the held company's market history at decision,
        # not on eligibility or its future return.
        for symbol in sorted(set(positions) | set(targets)):
            target, capacity = targets.get(symbol, (0, None))
            diff = target - positions.get(symbol, 0)
            if not diff: continue
            if capacity is None:
                rec = prices.data.get(symbol)
                trailing = [d for d in prices.cal if d <= day][-protocol['liquidity_sessions']:]
                values = [float(rec['value'][rec['dmap'][d]]) if rec and d in rec['dmap'] and np.isfinite(rec['value'][rec['dmap'][d]]) else 0 for d in trailing]
                capacity = float(np.median(values)) * protocol['order_capacity_fraction'] if values else 0
            order = {'order_id': len(orders), 'decision_time': day, 'symbol': symbol,
                     'side': 'buy' if diff > 0 else 'sell', 'requested_units': abs(diff),
                     'remaining_units': abs(diff), 'capacity_remaining_rial': capacity,
                     'attempts': 0, 'elapsed_sessions': 0, 'last_reason': 'pending'}
            orders.append(order); pending.append(order)
        decisions.append({'decision_time': day, 'model': model, 'nav_rial': nav,
                          'cash_rial': cash, 'target_count': len(chosen)})
    for order in pending:
        if order['remaining_units']: order['last_reason'] = 'pending_at_horizon'
    summary = summarize(daily, initial, orders, fills)
    return {'summary': summary, 'daily_nav': daily, 'orders': orders, 'fills': fills,
            'cash_ledger': ledger, 'holdings': holdings, 'selections': selections,
            'decisions': decisions}
