"""Ex-post opportunity examples, never an input into selection or fitting."""
import json
import numpy as np
import pandas as pd
from .features import pit_return
from .stages import load_payload
from .wave2 import frame_for


def samples(panel, md, source, names, out):
    candidates = []
    for day, g in panel.groupby('decision_time'):
        end = (pd.Timestamp(day) + pd.DateOffset(months=6)).date().isoformat()
        if end > '2026-02-28':
            continue
        for r in g.itertuples():
            ret = pit_return(md, r.symbol, day, end, end)
            if np.isfinite(ret):
                candidates.append({'decision_time': day, 'symbol': r.symbol, 'six_month_return': ret,
                                   'sources': r.sources, 'financial_age_days': r.financial_age_days,
                                   'source_valid': r.source_valid,
                                   'publication_safe': r.sources_published_before_cutoff})
    winners = pd.DataFrame(candidates).sort_values('six_month_return', ascending=False).drop_duplicates('symbol').head(12)
    rows = []
    for name in names:
        payload = load_payload(source, name)
        selections = pd.DataFrame(payload['selections'])
        orders = pd.DataFrame(payload['orders'])
        fills = pd.DataFrame(payload['fills'])
        nav = pd.DataFrame(payload['daily_nav']).set_index('date')
        sig, _ = name.rsplit('_', 1)
        frame = frame_for(panel, sig)
        decision_dates = {d['decision_time'] for d in payload['decisions']}
        for w in winners.to_dict('records'):
            day, sym = w['decision_time'], w['symbol']
            scored = frame[frame.decision_time.eq(day) & frame.symbol.eq(sym)]
            sel = selections[selections.decision_time.eq(day) & selections.symbol.eq(sym)]
            oo = orders[orders.decision_time.eq(day) & orders.symbol.eq(sym)]
            ff = fills[fills.decision_time.eq(day) & fills.symbol.eq(sym)]
            score_eligible = bool(len(scored) and scored.eligible.iloc[0])
            if day not in decision_dates:
                reason = 'no_policy_decision_at_month_end'
            elif not score_eligible:
                reason = 'coverage_or_signal_requirements'
            elif not len(sel):
                reason = 'not_selected_by_policy_or_rank'
            elif not len(ff[ff.side.eq('buy')]):
                reason = 'selected_but_no_buy_fill_or_already_held'
            else:
                reason = 'bought; inspect exits and timing'
            sells = fills[fills.symbol.eq(sym) & fills.side.eq('sell') & fills.date.gt(day)]
            cash_fraction = (float(nav.loc[day, 'cash_rial'] / nav.loc[day, 'nav_rial']) if day in nav.index else None)
            rows.append({**w, 'configuration': name, 'eligible_at_month_end': score_eligible,
                         'selected_at_month_end': bool(len(sel)), 'reason': reason,
                         'cash_fraction': cash_fraction, 'order_reasons': ';'.join(oo.last_reason.astype(str).unique()),
                         'buy_gross_rial': float(ff[ff.side.eq('buy')].gross_rial.sum()),
                         'first_subsequent_sale': sells.date.min() if len(sells) else None,
                         'diagnostic_only': True})
    table = pd.DataFrame(rows)
    table.to_csv(out / 'missed_opportunities.csv', index=False)
    return table
