"""Causal validation of actual traded observations; preserve raw archives."""
from bisect import bisect_right
import numpy as np
import pandas as pd
from ranking_research.top10_six_month.portfolio import Prices
from ranking_research.strategy_search.features import causal_factors
from ranking_research.strategy_search.asof_panel import _fresh_market_row


class TradedPrices(Prices):
    """Same normalized index, with marks sourced only from actual trades.

    A suspended holding keeps its last observed index mark and its actual age;
    this mark does not assert a currently executable sale or settled cash.
    """
    def __init__(self, md, unit_scale=1_000_000):
        super().__init__(md, unit_scale)
        self.trade_ids = {s: np.flatnonzero(
            (r['volume'] > 0) & (r['value'] > 0) &
            np.isfinite(r['price']) & (r['price'] > 0))
            for s, r in self.data.items()}

    def _mark(self, symbol, date):
        if symbol not in self.data:
            return None, None
        r, ids = self.data[symbol], self.trade_ids[symbol]
        k = np.searchsorted(np.asarray(r['dates'])[ids], str(date), side='right') - 1
        if k < 0:
            return None, None
        i = ids[k]
        return float(r['price'][i]), str(r['dates'][i])

    def _execution(self, symbol, date):
        r = self.data.get(symbol)
        if r is not None and date in r['dmap']:
            i = r['dmap'][date]
            if not np.isfinite(r['value'][i]) or r['value'][i] <= 0:
                return None, 0, 'no_positive_traded_value'
        return super()._execution(symbol, date)


def observation(md, sym, date):
    date = str(date)
    r = md.data.get(sym)
    if r is None:
        return None
    valid = getattr(md, '_v2_valid', None)
    if valid is None:
        valid = md._v2_valid = {}
    if sym not in valid:
        valid[sym] = np.flatnonzero((r['vol'] > 0) & (r['tval'] > 0) & np.isfinite(r['c']) & (r['c'] > 0))
    ids = valid[sym]
    k = bisect_right(ids, bisect_right(r['dates'], str(date)) - 1) - 1
    if k < 0:
        return None
    i = int(ids[k])
    return i if 0 <= (pd.Timestamp(date) - pd.Timestamp(r['dates'][i])).days <= 7 else None


def traded_return(md, sym, left, right, cutoff):
    if str(right) > str(cutoff) or str(left) > str(right):
        raise ValueError('future return endpoint')
    a, b = observation(md, sym, left), observation(md, sym, right)
    if a is None or b is None:
        return np.nan
    r = md.data[sym]
    f = causal_factors(md, sym, cutoff)
    return float(r['c'][b] * f[b] / (r['c'][a] * f[a]) - 1)


def fresh(md, sym, day):
    row = _fresh_market_row(md, sym, day)
    if row is None:
        return {}
    i = observation(md, sym, day)
    row['decision_price'] = float(md.data[sym]['c'][i]) if i is not None else np.nan
    for m, name in [(12, 'momentum_12_1'), (6, 'mom_6_1')]:
        row[name] = traded_return(md, sym, str((pd.Timestamp(day) - pd.DateOffset(months=m)).date()),
                                  str((pd.Timestamp(day) - pd.DateOffset(months=1)).date()), day)
    r = md.data[sym]
    ids = np.flatnonzero((np.asarray(r['dates']) <= day) & (r['vol'] > 0) & (r['tval'] > 0) & (r['c'] > 0))[-60:]
    f = causal_factors(md, sym, day)
    prices = r['c'][ids] * f[ids]
    row['vol_60'] = float(np.std(np.diff(prices) / prices[:-1])) if len(ids) >= 30 else np.nan
    row['trend_vol'] = row['momentum_12_1'] / row['vol_60'] if row['vol_60'] > 1e-9 else np.nan
    return row


def corrected(panel, md):
    d = panel.copy()
    for i, r in d.iterrows():
        for k, v in fresh(md, r.symbol, r.decision_time).items():
            d.at[i, k] = v
    return d
