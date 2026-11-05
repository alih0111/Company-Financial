"""Policy-to-engine contract: a policy dict becomes a real decision calendar
with real member counts, target weights, entry/exit buffers and delay
(corrective 2.7).

`policy_replay` extends the frozen day loop with policy decisions and an actual
member limit at buy fill time. A stalled exit still occupies its slot. All
ranked baselines and candidates use this corrected rule. The explicit diagnostic
enforce_member_limit=False reproduces the frozen loop, verified by test; it is
never used for the corrected research ranking.

Policies:
  P0  calendar monthly, top-N equal weight (frozen behavior).
  P1  monthly, entry top-10, exit below rank 15 (buffer keeps members).
  P2  monthly, entry top-10, exit below rank 20.
  P3  biweekly on real sessions, top-10 equal weight.
  P4  weekly on the last session of each week, top-10 equal weight.
  P5  quarterly, top-10 equal weight.
  P6  monthly, top-10, inverse 60-session volatility weights, 20% cap,
      sum of weights <= 1, residual stays cash.
  P7  monthly, hold members until they leave the top-20 rank; winners are never
      trimmed (except above the hard 20% cap); replacement buys target at most
      10% of NAV from free cash; at most 10 members.

equal_weight model: the portfolio holds EVERY eligible name (passive universe
benchmark) — corrective 2.1. Members and the sum of target weights are logged
per decision date.

Unknown policy options raise PolicyError; nothing is silently ignored.
"""
import math

import numpy as np
import pandas as pd

from ranking_research.top10_six_month.portfolio import replay as _frozen_replay  # noqa: F401 (tests compare against this)

from .engine import ledger_check, concentration, protocol_for, START, END, _six_month_bounds

MONTHLY = 'monthly'
BIWEEKLY = 'biweekly'
WEEKLY = 'weekly'
QUARTERLY = 'quarterly'
CADENCE_ALIASES = {1: MONTHLY, 3: QUARTERLY, 'monthly': MONTHLY, 'biweekly': BIWEEKLY,
                   'weekly': WEEKLY, 'quarterly': QUARTERLY}

ALLOWED_WEIGHTS = ('equal', 'inverse_vol_capped')
ALLOWED_HOLDING = ('calendar', 'rank_buffer', 'hold_until_rank_weakens')
ALLOWED_MODELS = ('score', 'equal_weight')


class PolicyError(ValueError):
    pass


def validate_policy(policy):
    known = {'name', 'top_n', 'weight', 'cadence', 'cadence_months', 'cost_per_side',
             'delay_sessions', 'initial_toman', 'exit_rank_buffer', 'holding', 'model', 'enforce_member_limit'}
    unknown = set(policy) - known
    if unknown:
        raise PolicyError(f'unknown_policy_options: {sorted(unknown)}')
    if policy['weight'] not in ALLOWED_WEIGHTS:
        raise PolicyError(f'unknown_weight: {policy["weight"]}')
    holding = policy.get('holding', 'calendar')
    if holding not in ALLOWED_HOLDING:
        raise PolicyError(f'unknown_holding: {holding}')
    if policy.get('cadence') not in CADENCE_ALIASES:
        raise PolicyError(f'unknown_cadence: {policy.get("cadence")}')
    if holding in ('rank_buffer', 'hold_until_rank_weakens') and policy['weight'] != 'equal' \
            and holding == 'rank_buffer':
        raise PolicyError('rank_buffer_is_defined_for_equal_weights')
    if holding in ('rank_buffer', 'hold_until_rank_weakens'):
        buf = policy.get('exit_rank_buffer')
        if not isinstance(buf, int) or buf < policy['top_n']:
            raise PolicyError('rank_buffer_policies_need_exit_rank_buffer_ge_top_n')
    if int(policy['top_n']) < 1:
        raise PolicyError('top_n_must_be_positive')
    if policy.get('model', 'score') not in ALLOWED_MODELS:
        raise PolicyError(f'unknown_model: {policy.get("model")}')
    return True


def decision_calendar(md, start, end, cadence):
    """Real decision dates on the real market calendar.

    monthly: last session of each month; quarterly: last session of Mar/Jun/Sep/Dec;
    biweekly: last session of every OTHER calendar week (Sat..Fri), anchored at
    the first week with a session >= start; weekly: last session of every week.
    """
    cal = [d for d in md.cal if start <= d <= end]
    if not cal:
        raise PolicyError('empty_market_calendar')
    if cadence in (MONTHLY, QUARTERLY):
        months = ('03', '06', '09', '12') if cadence == QUARTERLY else None
        by_month = {}
        for d in cal:
            if months and d[5:7] not in months:
                continue
            by_month[d[:7]] = d          # last session of the month wins
        return sorted(by_month.values())
    weeks = {}
    for d in cal:
        t = pd.Timestamp(d)
        sat = (t - pd.Timedelta(days=(t.weekday() - 5) % 7)).date().isoformat()
        weeks.setdefault(sat, []).append(d)
    weekly_dates = [v[-1] for _, v in sorted(weeks.items())]
    if cadence == WEEKLY:
        return weekly_dates
    anchor = pd.Timestamp(min(d for d in md.cal if d >= START))
    anchor -= pd.Timedelta(days=(anchor.weekday() - 5) % 7)
    return [d for sat, ds in sorted(weeks.items())
            if ((pd.Timestamp(sat) - anchor).days // 7) % 2 == 0
            for d in [ds[-1]]]


def _trailing_vols(md, day, symbols, sessions=60):
    from .features import trailing_vol
    return {s: trailing_vol(md, s, day, sessions) for s in symbols}


def policy_replay(scores, prices, protocol, start, end, policy, md, cost=None,
                  delay=0, keep=True, policy_schedule=None):
    """Frozen replay day loop with the policy decision block (see module docstring)."""
    validate_policy(policy)
    cadence = CADENCE_ALIASES[policy['cadence']]
    calendar = decision_calendar(md, start, end, cadence)
    if policy_schedule is not None:
        calendar = sorted(policy_schedule)
        for p in policy_schedule.values():
            validate_policy(p)
    cal_set = set(calendar)
    model = policy.get('model', 'score')
    top_n = int(policy['top_n'])
    holding = policy.get('holding', 'calendar')
    buf = policy.get('exit_rank_buffer')
    weight_kind = policy['weight']

    cash = float(protocol['initial_toman'] * protocol['rial_per_toman'])
    initial = cash
    positions = {}
    pending = []
    orders = []
    fills = []
    ledger = []
    daily = []
    holdings = []
    selections = []
    decisions = []
    cost = protocol['cost_per_side'] if cost is None else cost
    vol_status = {'zero_or_missing_volatility_members': 0, 'decisions': 0}
    groups = {str(d): g[g.eligible].copy() for d, g in scores.groupby('decision_time')}
    days = [d for d in prices.cal if start <= d <= end]
    for day in days:
        # ---- frozen execution block (copied verbatim) ----
        used_capacity = {}
        for order in sorted(pending, key=lambda o: (o['side'] != 'sell', o['order_id'])):
            if day <= order['decision_time']:
                raise AssertionError('same_session_fill')
            order['elapsed_sessions'] += 1
            if order['elapsed_sessions'] <= delay:
                continue
            if order['attempts'] >= protocol['maximum_order_sessions'] or order['remaining_units'] <= 0:
                continue
            order['attempts'] += 1
            price, capacity, reason = prices.execution(order['symbol'], day)
            order['last_reason'] = reason
            if price is None:
                continue
            capacity = min(capacity, int(order['capacity_remaining_rial'] / price))
            capacity = max(0, capacity - used_capacity.get(order['symbol'], 0))
            quantity = min(order['remaining_units'], capacity)
            if order['side'] == 'buy':
                if (policy.get('enforce_member_limit', True) and model != 'equal_weight'
                        and order['symbol'] not in positions and len(positions) >= top_n):
                    order['last_reason'] = 'member_limit_waiting_for_exit'
                    continue
                quantity = min(quantity, int(cash / (price * (1 + cost))))
            else:
                quantity = min(quantity, positions.get(order['symbol'], 0))
            if quantity <= 0:
                order['last_reason'] = 'cash_or_capacity'
                continue
            gross = quantity * price
            fee = gross * cost
            sign = 1 if order['side'] == 'buy' else -1
            cash_before = cash
            cash += -sign * gross - fee
            positions[order['symbol']] = positions.get(order['symbol'], 0) + sign * quantity
            if positions[order['symbol']] == 0:
                del positions[order['symbol']]
            order['remaining_units'] -= quantity
            order['capacity_remaining_rial'] -= gross
            used_capacity[order['symbol']] = used_capacity.get(order['symbol'], 0) + quantity
            fill = {'fill_id': len(fills), 'order_id': order['order_id'], 'date': day,
                    'decision_time': order['decision_time'], 'symbol': order['symbol'],
                    'side': order['side'], 'index_units': quantity, 'index_price_rial': price,
                    'gross_rial': gross, 'fee_rial': fee}
            fills.append(fill)
            ledger.append({'fill_id': fill['fill_id'], 'date': day, 'cash_before_rial': cash_before,
                           'cash_change_rial': cash - cash_before, 'cash_after_rial': cash})
            assert cash >= -.00001
        pending = [o for o in pending if o['remaining_units'] > 0 and o['attempts'] < protocol['maximum_order_sessions']]
        marks = {}
        stale = 0
        missing = 0
        fresh_value = 0
        for symbol, quantity in positions.items():
            price, date = prices.mark(symbol, day)
            if price is None:
                missing += 1
                price = 0
            age = prices.age(symbol, day)
            stale += age > 7
            marks[symbol] = price
            if age <= 7:
                fresh_value += quantity * price
            if keep:
                holdings.append({'date': day, 'symbol': symbol, 'index_units': quantity,
                                 'index_price_rial': price, 'value_rial': quantity * price,
                                 'price_date': date, 'stale_days': age})
        nav = cash + sum(positions[s] * marks[s] for s in positions)
        daily.append({'date': day, 'nav_rial': nav, 'cash_rial': cash,
                      'stale_positions': stale, 'missing_marks': missing,
                      'lower_mark_bound_rial': cash + fresh_value})
        if day not in cal_set:
            continue
        if policy_schedule is not None:
            policy = policy_schedule[day]
            model = policy.get('model', 'score')
            top_n = int(policy['top_n'])
            holding = policy.get('holding', 'calendar')
            buf = policy.get('exit_rank_buffer')
            weight_kind = policy['weight']
        # ---- policy decision block (the ONLY changed part) ----
        vol_status['decisions'] += 1
        group = groups.get(day, scores.iloc[:0])
        targets = {}
        if model == 'equal_weight':
            # Passive universe benchmark: hold EVERY eligible name (corrective 2.1).
            chosen = group.sort_values('company_id')
            divisor = len(chosen)
            for rank, row in enumerate(chosen.itertuples(), 1):
                price, _ = prices.mark(row.symbol, day)
                if price is None:
                    continue
                units = math.floor(nav / max(divisor, 1) / price)
                targets[row.symbol] = (units, float(row.capacity_rial))
                selections.append({'decision_time': day, 'company_id': row.company_id,
                                   'symbol': row.symbol, 'model': model, 'rank': rank,
                                   'target_weight': 1 / max(divisor, 1),
                                   'target_index_units': units, 'score': None})
        elif holding == 'calendar' and weight_kind == 'equal':
            # Frozen behavior, identical expressions.
            chosen = group.sort_values([model, 'company_id'],
                                       ascending=[False, True]).head(top_n)
            for rank, row in enumerate(chosen.itertuples(), 1):
                price, _ = prices.mark(row.symbol, day)
                if price is None:
                    continue
                units = math.floor(nav / max(top_n, 1) / price)
                targets[row.symbol] = (units, float(row.capacity_rial))
                selections.append({'decision_time': day, 'company_id': row.company_id,
                                   'symbol': row.symbol, 'model': model, 'rank': rank,
                                   'target_weight': 1 / max(top_n, 1),
                                   'target_index_units': units,
                                   'score': float(getattr(row, model))})
        else:
            ranked = group.sort_values([model, 'company_id'], ascending=[False, True])
            rank_of = {row.symbol: i + 1 for i, row in enumerate(ranked.itertuples())}
            if holding == 'calendar' and weight_kind == 'inverse_vol_capped':
                chosen = ranked.head(top_n)
                vols = _trailing_vols(md, day, list(chosen.symbol))
                valid = {s: v for s, v in vols.items()
                         if v is not None and np.isfinite(v) and v > 0}
                vol_status['zero_or_missing_volatility_members'] += len(chosen) - len(valid)
                raw = {s: 1.0 / v for s, v in valid.items()}
                total = sum(raw.values()) if raw else 0.0
                # Missing slots retain cash; redistribute excess among uncapped members.
                weights = {}
                left = min(len(valid) / top_n, 1.0)
                active = dict(raw)
                while active and left > 1e-12:
                    denom = sum(active.values())
                    capped = [s for s, r in active.items() if left * r / denom > .2]
                    if not capped:
                        weights.update({s: left * r / denom for s, r in active.items()})
                        break
                    for s in capped:
                        weights[s] = .2
                        left -= .2
                        del active[s]
                for rank, row in enumerate(chosen.itertuples(), 1):
                    w = weights.get(row.symbol)
                    if w is None:
                        continue    # missing/zero volatility: slot stays cash (logged)
                    price, _ = prices.mark(row.symbol, day)
                    if price is None:
                        continue
                    units = math.floor(nav * w / price)
                    targets[row.symbol] = (units, float(row.capacity_rial))
                    selections.append({'decision_time': day, 'company_id': row.company_id,
                                       'symbol': row.symbol, 'model': model, 'rank': rank,
                                       'target_weight': w, 'target_index_units': units,
                                       'score': float(getattr(row, model))})
            elif holding == 'rank_buffer':
                # P1/P2: keep held members while their current rank <= buffer;
                # refill free slots with the best new names; equal weight per
                # slot (top_n slots, empty slot = cash).
                kept, kept_rank = [], {}
                for s in positions:
                    r = rank_of.get(s)
                    if r is not None and r <= buf:
                        kept.append(s)
                        kept_rank[s] = r
                slots = max(0, top_n - len(kept))
                fresh = [row.symbol for row in ranked.head(top_n).itertuples()
                         if row.symbol not in set(kept)][:slots]
                members = kept + fresh
                for s in members:
                    row = ranked[ranked.symbol.eq(s)].iloc[0]
                    price, _ = prices.mark(s, day)
                    if price is None:
                        continue
                    units = math.floor(nav / max(top_n, 1) / price)
                    targets[s] = (units, float(row.capacity_rial))
                    selections.append({'decision_time': day, 'company_id': row.company_id,
                                       'symbol': s, 'model': model,
                                       'rank': int(rank_of[s]), 'held_over': s in set(kept),
                                       'target_weight': 1 / max(top_n, 1),
                                       'target_index_units': units,
                                       'score': float(getattr(row, model))})
            else:  # hold_until_rank_weakens (P7)
                # Winners are never trimmed except above the hard 20% cap;
                # exits only when the current rank leaves the buffer. Fresh buys
                # target at most 10% of NAV from free cash; at most top_n members.
                for s in positions:
                    r = rank_of.get(s)
                    if r is None or r > buf:
                        targets[s] = (0, None)      # exit (fill still needs real sessions)
                        selections.append({'decision_time': day, 'company_id': None,
                                           'symbol': s, 'model': model, 'rank': r,
                                           'held_over': False, 'target_weight': 0.0,
                                           'target_index_units': 0, 'score': None})
                        continue
                    price, _ = prices.mark(s, day)
                    if price is None:
                        continue
                    current_w = positions[s] * price / nav if nav > 0 else 0.0
                    if current_w > 0.2:             # pre-registered trim to the cap
                        units = math.floor(0.2 * nav / price)
                    else:                           # keep the current position as-is
                        units = positions[s]
                    targets[s] = (units, None)
                    row = ranked[ranked.symbol.eq(s)]
                    selections.append({'decision_time': day,
                                       'company_id': row.company_id.iloc[0] if len(row) else None,
                                       'symbol': s, 'model': model, 'rank': int(r),
                                       'held_over': True, 'target_weight': units * price / nav if nav > 0 else 0.0,
                                       'target_index_units': units,
                                       'score': float(row[model].iloc[0]) if len(row) else None})
                free_slots = max(0, top_n - len(positions))
                per_buy_nav_fraction = 0.10
                available = cash               # buys compete for the same free cash
                for row in ranked.head(top_n).itertuples():
                    if free_slots <= 0 or available < 0:
                        break
                    if row.symbol in positions:
                        continue
                    price, _ = prices.mark(row.symbol, day)
                    if price is None:
                        continue
                    budget = min(per_buy_nav_fraction * nav, available)
                    if budget < price:
                        continue
                    units = math.floor(budget / (price * (1 + cost)))
                    available -= units * price * (1 + cost)
                    targets[row.symbol] = (units, float(row.capacity_rial))
                    selections.append({'decision_time': day, 'company_id': row.company_id,
                                       'symbol': row.symbol, 'model': model,
                                       'rank': int(rank_of[row.symbol]), 'held_over': False,
                                       'target_weight': units * price / nav if nav > 0 else 0.0,
                                       'target_index_units': units,
                                       'score': float(getattr(row, model))})
                    free_slots -= 1
        for order in pending:
            order['last_reason'] = 'cancelled_at_next_decision'
        pending = []
        # Exit capacity: the held company's market history at decision (frozen rule).
        for symbol in sorted(set(positions) | set(targets)):
            target, capacity = targets.get(symbol, (0, None))
            diff = target - positions.get(symbol, 0)
            if not diff:
                continue
            if capacity is None:
                rec = prices.data.get(symbol)
                trailing = [d for d in prices.cal if d <= day][-protocol['liquidity_sessions']:]
                values = [float(rec['value'][rec['dmap'][d]]) if rec and d in rec['dmap']
                          and np.isfinite(rec['value'][rec['dmap'][d]]) else 0 for d in trailing]
                capacity = float(np.median(values)) * protocol['order_capacity_fraction'] if values else 0
            order = {'order_id': len(orders), 'decision_time': day, 'symbol': symbol,
                     'side': 'buy' if diff > 0 else 'sell', 'requested_units': abs(diff),
                     'remaining_units': abs(diff), 'capacity_remaining_rial': capacity,
                     'attempts': 0, 'elapsed_sessions': 0, 'last_reason': 'pending'}
            orders.append(order)
            pending.append(order)
        decisions.append({'decision_time': day, 'model': model, 'nav_rial': nav,
                          'cash_rial': cash, 'target_count': len(targets)})
    for order in pending:
        if order['remaining_units']:
            order['last_reason'] = 'pending_at_horizon'
    from ranking_research.top10_six_month.portfolio import summarize
    summary = summarize(daily, initial, orders, fills)
    return {'summary': summary, 'daily_nav': daily, 'orders': orders, 'fills': fills,
            'cash_ledger': ledger, 'holdings': holdings, 'selections': selections,
            'decisions': decisions, 'vol_status': vol_status,
            'decision_calendar': {'cadence': cadence, 'dates': len(calendar),
                                  'first': calendar[0], 'last': calendar[-1]}}


def member_log(result):
    """Members and total target weight per decision date (corrective 2.1).
    Exit rows (target weight 0) are not members."""
    rows = []
    sel = pd.DataFrame(result['selections'])
    if sel.empty:
        return rows
    for day, group in sel.groupby('decision_time'):
        live = group[group.target_weight.astype(float) > 0]
        w = live.target_weight.astype(float)
        rows.append({'decision_time': day, 'members': int(len(live)),
                     'sum_target_weight': float(w.sum()),
                     'symbols': ';'.join(live.symbol)})
    return rows


def run_policy(frame, md, policy, prices=None, cost_mult=1.0, delay=None, keep=True,
               start=START, end=END, policy_schedule=None):
    """Execute one policy on the shared frozen ledger and return engine-shaped output."""
    validate_policy(policy)
    if prices is None:
        from ranking_research.top10_six_month.portfolio import Prices
        prices = Prices(md)
    delay = policy['delay_sessions'] if delay is None else delay
    proto = protocol_for(policy, cost_per_side=policy['cost_per_side'] * cost_mult)
    result = policy_replay(frame, prices, proto, start, end, policy, md,
                           cost=proto['cost_per_side'], delay=delay, keep=True,
                           policy_schedule=policy_schedule)
    ledger_check(result, frame)
    result['policy_members'] = member_log(result)
    summary = dict(result['summary'])
    summary['scenario'] = policy['name']
    summary['policy'] = {k: policy.get(k) for k in
                         ('name', 'top_n', 'weight', 'cadence', 'holding', 'exit_rank_buffer', 'model')
                         if policy.get(k) is not None}
    summary['cost_multiplier'] = cost_mult
    summary['delay_sessions'] = delay
    summary['ledger_passed'] = True
    summary['scheduled_rebalances'] = result['decision_calendar']['dates']
    summary['realized_rebalances'] = len(result['decisions'])
    summary['decision_calendar'] = result['decision_calendar']
    bounds = [{'test_month': m, 'block_end_exclusive': e, 'model': policy.get('model', 'score'),
               'cadence_months': 1 if policy['cadence'] in (MONTHLY, BIWEEKLY, WEEKLY) else 3}
              for m, e in _six_month_bounds(frame)]
    from ranking_research.top10_six_month.walk_forward import six_months
    result['blocks'] = six_months(result['daily_nav'], bounds, policy['initial_toman'] * 10)
    result['summary'] = summary
    result['concentration'] = concentration(result, policy)
    return result
