"""As-of score frames for decision dates that are not month ends (corrective
for policies P3/P4).

The frozen panel is a month-end snapshot table. Weekly/biweekly policies need
decisions on real intra-month sessions. Rules, pre-registered:

  * Fundamentals (reports, growth windows, publication state) carry forward
    from the LATEST month-end snapshot whose decision_time <= D. This is never
    look-ahead: every consumed source published before that earlier cutoff,
    hence before D. Reports published between that month end and D are NOT yet
    visible (a staleness delay, disclosed, not leakage).
  * Price/volume/trend features (momentum_12_1, mom_6_1, vol_60, decision_price,
    capacity_rial, positive_volume_sessions, liquidity_observations) are
    recomputed fresh as-of D from the market archive with the as-of-D causal
    adjustment chain. Month-end values are never copied onto intra-month dates.
  * Month-end rows reproduce the frozen panel exactly (asserted by test).

The output is a score frame (decision_time, company_id, symbol, capacity_rial,
eligible, score) built by the SAME signal functions used at month ends, ranked
within the as-of date's own cross-section.
"""
import sys
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'score_v2_research'))

TOL_DAYS = 7


def _carry_forward_snapshots(panel, dates):
    """For each as-of date, the latest month-end snapshot rows with
    decision_time <= D (fundamental state; publication-safe by construction)."""
    month_ends = sorted(panel.decision_time.unique())
    by_date = {d: g for d, g in panel.groupby('decision_time')}
    out = {}
    for D in dates:
        i = bisect_right(month_ends, str(D)) - 1
        if i < 0:
            out[D] = None
            continue
        out[D] = by_date[month_ends[i]]
    return out


def _fresh_market_row(md, sym, D):
    """Trade/price features computed as-of D only from sessions <= D."""
    rec = md.data.get(sym)
    if rec is None:
        return None
    sessions = [d for d in md.cal if d <= str(D)][-20:]
    idx = [rec['dmap'].get(d) for d in sessions]
    count = len(sessions)
    positive = sum(i is not None and rec['vol'][i] > 0 for i in idx)
    values = [float(rec['tval'][i]) if i is not None and np.isfinite(rec['tval'][i]) else 0
              for i in idx]
    cap = float(np.median(values)) * 0.01 if values else 0.0
    end = bisect_right(rec['dates'], str(D)) - 1
    price = None
    if end >= 0 and (pd.Timestamp(D) - pd.Timestamp(rec['dates'][end])).days <= TOL_DAYS:
        price = float(rec['c'][end])
    return {'capacity_rial': cap, 'decision_price': price,
            'positive_volume_sessions': positive, 'liquidity_observations': count}


def _pit_return_asof(md, sym, left_date, right_date, T):
    from .features import pit_return
    return pit_return(md, sym, left_date, right_date, T)


def build_asof_panel(panel, md, dates):
    """Panel-like frame at arbitrary decision dates (see module docstring)."""
    snaps = _carry_forward_snapshots(panel, dates)
    frames = []
    for D in dates:
        snap = snaps[D]
        if snap is None:
            continue
        rows = []
        for r in snap.itertuples():
            fresh = _fresh_market_row(md, r.symbol, D)
            if fresh is None:
                continue
            T = str(D)
            left12 = (pd.Timestamp(T) - pd.DateOffset(months=12)).date().isoformat()
            right1 = (pd.Timestamp(T) - pd.DateOffset(months=1)).date().isoformat()
            left6 = (pd.Timestamp(T) - pd.DateOffset(months=6)).date().isoformat()
            mom12 = _pit_return_asof(md, r.symbol, left12, right1, T)
            mom6 = _pit_return_asof(md, r.symbol, left6, right1, T)
            from .features import trailing_vol
            vol60 = trailing_vol(md, r.symbol, T)
            rec = {'decision_time': T, 'company_id': r.company_id, 'symbol': r.symbol,
                   'capacity_rial': fresh['capacity_rial'],
                   'decision_price': fresh['decision_price'],
                   'positive_volume_sessions': fresh['positive_volume_sessions'],
                   'liquidity_observations': fresh['liquidity_observations'],
                   'momentum_12_1': mom12, 'mom_6_1': mom6, 'vol_60': vol60}
            # Fundamental state carried forward from the snapshot (never newer).
            for col in ('historical_family', 'source_valid', 'publication_valid',
                        'used_older_income_report', 'financial_age_days', 'growth_state',
                        'sales_growth_status', 'growth_window_valid', 'net_growth_verified',
                        'operating_profit_ttm', 'prior_operating_profit_ttm',
                        'prior_net_profit_ttm', 'net_profit_ttm', 'ocf_ttm', 'market_cap',
                        'total_assets', 'total_equity', 'operating_yield', 'cash_multi', 'debt_ratio',
                        'sales_yoy', 'operating_improvement', 'accel_op',
                        'quarter_keys', 'history_values', 'sources', 'publication_cutoff',
                        'sources_published_before_cutoff', 'latest_source_publication'):
                rec[col] = getattr(r, col, None)
            # financial_age grows with the carry-forward age.
            age = getattr(r, 'financial_age_days', np.nan)
            extra = (pd.Timestamp(T) - pd.Timestamp(r.decision_time)).days
            rec['financial_age_days'] = (float(age) + float(extra)
                                         if pd.notna(age) and np.isfinite(age) else age)
            # Revalue capitalization/yield using only the as-of price change.
            old_price = getattr(r, 'decision_price', None)
            if old_price and fresh['decision_price']:
                ratio = fresh['decision_price'] / old_price
                rec['market_cap'] = r.market_cap * ratio
                rec['operating_yield'] = r.operating_yield / ratio
                # Do not assume an unchanged share count across an adjustment event.
                # Snapshot share reconstruction is available only at month ends.
                sid = md.data[r.symbol]['sid']
                if any(str(r.decision_time) < str(e[0]) <= T for e in md.events.get(sid, [])):
                    rec['market_cap'] = np.nan
                    rec['operating_yield'] = np.nan
            # report_drift is recomputed as-of D from the latest VISIBLE source
            # publication (carried) to D; never copied stale from the month end.
            drift = np.nan
            pub = getattr(r, 'latest_source_publication', pd.NaT)
            ok = getattr(r, 'sources_published_before_cutoff', False)
            if bool(ok) and pub is not None and pd.notna(pub):
                start = (pd.Timestamp(pub) + pd.Timedelta(days=1)).date().isoformat()
                if pd.Timestamp(start) < pd.Timestamp(T):
                    drift = _pit_return_asof(md, r.symbol, start, T, T)
            rec['report_drift'] = drift
            rows.append(rec)
        frames.append(pd.DataFrame(rows))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out['trend_vol'] = out['momentum_12_1'] / out['vol_60'].where(out['vol_60'].gt(1e-9))
    return out


def asof_signal_frame(panel, md, dates, signal_name):
    """Score frame for `signal_name` at arbitrary dates, using the same signal
    function and ranking rule as month ends."""
    from . import signals
    asof = build_asof_panel(panel, md, dates)
    family, desc, fn, note, requirement = signals.SIGNALS[signal_name]
    if fn is None:
        raise ValueError(f'not_tested_signal: {signal_name} ({note})')
    mask, score = fn(asof, None)
    out = asof[['decision_time', 'company_id', 'symbol', 'capacity_rial']].copy()
    out['eligible'] = mask.to_numpy()
    out['score'] = score.to_numpy()
    return out
