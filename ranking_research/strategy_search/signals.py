"""Registered wave-1 signal definitions. One signal can drive several policies.

A signal is a pure function of the point-in-time panel: it returns a score in
[0,100] by cross-sectional rank inside each decision month, or None when the
family's data requirement is not met (recorded as 'not_tested', never silently
substituted). Ranking inside the cohort makes extreme adjusted-price multiples
harmless to the score; they still affect the portfolio only through the engine.

Requirement classes (corrective 2.3): every signal declares which inputs it
consumes so eligibility is honest about what it needs.
  * price      — market data only; must NOT require a fresh financial report.
  * financial  — needs valid published reports within the age window.
  * hybrid     — needs both.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

MAX_FINANCIAL_AGE = 365
MIN_VOLUME_SESSIONS = 15
LIQUIDITY_SESSIONS = 20

TRADE = ('capacity_rial', 'decision_price', 'positive_volume_sessions', 'liquidity_observations')
FINANCIAL = ('source_valid', 'publication_valid', 'used_older_income_report', 'financial_age_days')


def _finite(d, cols):
    return pd.Series(np.isfinite(d[list(cols)].to_numpy(dtype=float)).all(axis=1), index=d.index)


def base_masks(d, family_scope='general'):
    trade = (d.capacity_rial.gt(0) & d.decision_price.gt(0) & np.isfinite(d.capacity_rial)
             & np.isfinite(d.decision_price)
             & d.positive_volume_sessions.ge(MIN_VOLUME_SESSIONS)
             & d.liquidity_observations.ge(LIQUIDITY_SESSIONS))
    fams = ('general',) if family_scope == 'general' else ('general', 'unknown')
    family = d.historical_family.isin(fams)
    financial = (d.source_valid.eq(True) & d.publication_valid.eq(True)
                 & d.used_older_income_report.eq(False)
                 & d.financial_age_days.between(0, MAX_FINANCIAL_AGE))
    if 'sources_published_before_cutoff' in d.columns:
        # Strict per-source publication control (corrective 2.3): every consumed
        # source's own timestamp, unknown dates never pass.
        financial = financial & d.sources_published_before_cutoff.eq(True)
    return trade, family, financial


def _quarters(raw_keys, raw_values, field):
    """Parse (key, value) pairs newest-first; return oldest-first list of
    (linear_month, value) keeping only consecutive exact 3-month spacings."""
    def load(raw):
        if raw is None:
            return []
        try:
            v = json.loads(raw) if isinstance(raw, str) else raw
            return list(v) if v else []
        except (ValueError, TypeError):
            return []
    ks, vs = load(raw_keys), load(raw_values)
    if not ks or not vs or len(ks) != len(vs):
        return []
    pts = []
    for k, r in zip(ks, vs):
        try:
            v = (r or {}).get(field)
        except AttributeError:
            v = None
        if v is None or not np.isfinite(float(v)):
            continue
        pts.append((int(k[0]) * 12 + int(k[1]), float(v)))
    pts.sort()  # oldest first
    out = []
    for p in pts:
        if out and p[0] - out[-1][0] != 3:
            out = [p]      # restart the chain at a gap
        else:
            out.append(p)
    return out


def quarterly_acceleration(d):
    """Season-on-season acceleration from CONSECUTIVE TTM points.

    history_values carry 12-month TTM values at quarter keys (newest first).
    TTM(k) - TTM(k-1) is the independent quarter ending at k minus the same
    season one year earlier; the second difference of consecutive TTM points is
    the change of that YoY quarter change — true seasonal acceleration. Dividing
    overlapping cumulative windows directly (the old rule) mixes quarters.
    Only exact 3-month spacing chains are used; units must be equal-length
    quarters by construction of `quarter_keys`.
    """
    out = np.full(len(d), np.nan)
    for i, row in enumerate(d.itertuples()):
        pts = _quarters(getattr(row, 'quarter_keys', None),
                        getattr(row, 'history_values', None), 'operating_profit')
        if len(pts) < 3:
            continue
        pts = pts[-3:]
        yoy = [pts[k][1] - pts[k - 1][1] for k in (1, 2)]
        out[i] = yoy[1] - yoy[0]
    return out


def base_masks_for(d, requirement):
    """Masks for a declared requirement class: price signals are not limited to
    having a fresh financial report; financial/hybrid signals must respect
    source validity, publication timing and freshness."""
    trade, family, financial = base_masks(d)
    if requirement == 'price':
        return trade & family, trade, family, financial
    return trade & family & financial, trade, family, financial


CORE_REQUIREMENTS = ('momentum_12_1', 'mom_6_1', 'accel_op', 'operating_improvement', 'operating_yield')


def common_mask(d, family_scope='general'):
    """Fixed cohort = intersection of the pre-registered core input requirements.

    Used to compare the FORMULA effect on an identical population. It is frozen
    before results and does not shrink silently when a new model is added.
    This is the WAVE-1 fixed cohort only; pairwise cohort comparisons use
    `pairwise_cohort` (corrective 2.2) and are labelled as such.
    """
    trade, family, financial = base_masks(d, family_scope)
    return trade & family & financial & _finite(d, CORE_REQUIREMENTS)


def pairwise_cohort(d, require_a, require_b):
    """Explicit per-date intersection of exactly two signals' input requirements.

    A 'common population of all models' does not exist when candidates need
    different inputs; the honest comparison is pairwise on the intersection of
    the baseline's and this candidate's requirements (corrective 2.2).
    """
    trade, family, financial = base_masks(d)
    return trade & family & financial & _finite(d, tuple(require_a)) & _finite(d, tuple(require_b))


def rank_within(d, column, mask):
    """0..100 cross-sectional percentile of `column` among eligible rows per month."""
    out = pd.Series(np.nan, index=d.index)
    for _, g in d[mask].groupby('decision_time'):
        if len(g) < 2:
            continue
        out.loc[g.index] = 100 * (g[column].rank(method='average') - 1) / (len(g) - 1)
    return out


def _scored(mask, score):
    """Eligible requires a finite score: notna alone does not reject infinities."""
    score = pd.Series(score)
    finite = np.isfinite(score.astype(float).to_numpy())
    eligible = mask.fillna(False) & finite
    return eligible, score.where(eligible)


def _simple(column, require, requirement='price', family_scope='general', extra=None):
    def fn(d, cohort=None):
        base, _, _, _ = base_masks_for(d, requirement)
        mask = base & _finite(d, require)
        if extra is not None:
            mask &= extra(d)
        if cohort is not None:
            mask = mask & cohort
        return _scored(mask, rank_within(d, column, mask))
    return fn


def _mean_of(columns, require, requirement='price', family_scope='general', extra=None):
    def fn(d, cohort=None):
        base, _, _, _ = base_masks_for(d, requirement)
        mask = base & _finite(d, require)
        if extra is not None:
            mask &= extra(d)
        if cohort is not None:
            mask = mask & cohort
        parts = [rank_within(d, c, mask) for c in columns]
        return _scored(mask, pd.concat(parts, axis=1).mean(axis=1, skipna=False))
    return fn


def _trend_fund(weight_trend, weight_fund, fund_column):
    def fn(d, cohort=None):
        base, _, _, _ = base_masks_for(d, 'hybrid')
        mask = base & _finite(d, ('momentum_12_1', fund_column))
        if cohort is not None:
            mask = mask & cohort
        a = rank_within(d, 'momentum_12_1', mask)
        b = rank_within(d, fund_column, mask)
        return _scored(mask, weight_trend * a + weight_fund * b)
    return fn


def turnaround(d, cohort=None):
    """Loss exit: a separate hypothesis from percentage growth on a negative base."""
    base, _, _, _ = base_masks_for(d, 'financial')
    mask = (base & _finite(d, ('operating_profit_ttm', 'operating_improvement'))
            & d.growth_state.eq('turnaround') & d.sales_growth_status.eq('comparable')
            & d.operating_improvement.gt(0))
    if cohort is not None:
        mask = mask & cohort
    return _scored(mask, rank_within(d, 'operating_improvement', mask))


def post_report_drift(d, cohort=None):
    base, _, _, _ = base_masks_for(d, 'hybrid')
    mask = base & _finite(d, ('report_drift',))
    if cohort is not None:
        mask = mask & cohort
    return _scored(mask, rank_within(d, 'report_drift', mask))


def _positive_yield(d):
    """garp_yield: operating yield must be strictly positive to be a 'yield'."""
    return d.operating_yield.gt(0)


def _garp_quality(d):
    """Yield + cash conversion + explicit debt control (label now matches the
    implementation): yield > 0, cash_multi finite, debt_ratio finite and not
    extreme (below 0.8, the panel's pre-registered ceiling)."""
    return (d.operating_yield.gt(0) & d.cash_multi.notna()
            & d.debt_ratio.notna() & d.debt_ratio.le(0.8))


# name -> (family, description, function | None-if-not-tested, note, requirement)
SIGNALS = {
    'trend_mom6_1': ('trend', '6-month price trend excluding the most recent month',
                     _simple('mom_6_1', ('mom_6_1',), 'price'), None, 'price'),
    'trend_mom12_1': ('trend', '12-month price trend excluding the most recent month',
                      _simple('momentum_12_1', ('momentum_12_1',), 'price'), None, 'price'),
    'trend_vol': ('trend', '12m trend divided by trailing 60-session volatility',
                  _simple('trend_vol', ('trend_vol',), 'price'), None, 'price'),
    'trend_relative_industry': ('trend', 'trend relative to historical industry', None,
                                'NOT_TESTED: no certified historical industry map', 'hybrid'),
    'accel_op': ('acceleration', 'season-on-season operating-profit acceleration from consecutive TTM points',
                 _simple('accel_op', ('accel_op',), 'financial'), None, 'financial'),
    'accel_op_improvement': ('acceleration', 'operating improvement with matched growth window',
                             _simple('operating_improvement', ('operating_improvement',), 'financial'), None, 'financial'),
    'accel_sales': ('acceleration', 'reported YoY sales growth, comparable base only',
                    _simple('sales_yoy', ('sales_yoy',), 'financial',
                            extra=lambda d: d.sales_growth_status.eq('comparable')), None, 'financial'),
    'garp_yield': ('growth_at_price', 'operating profit to market cap (positive only)',
                   _simple('operating_yield', ('operating_yield',), 'financial', extra=_positive_yield),
                   None, 'financial'),
    'garp_yield_quality': ('growth_at_price', 'yield (positive) + cash conversion + debt ratio <= 0.8',
                           _mean_of(('operating_yield', 'cash_multi'),
                                    ('operating_yield', 'cash_multi', 'debt_ratio'),
                                    'financial', extra=_garp_quality),
                           'yield positive, cash_multi and debt_ratio finite with debt_ratio <= 0.8', 'financial'),
    'turnaround': ('loss_exit', 'loss-to-profit transition with confirming sales',
                   turnaround, None, 'financial'),
    'trend_fund_25': ('trend_confirmed', '25% trend / 75% fundamental improvement',
                      _trend_fund(0.25, 0.75, 'operating_improvement'), None, 'hybrid'),
    'trend_fund_50': ('trend_confirmed', '50% trend / 50% fundamental improvement',
                      _trend_fund(0.50, 0.50, 'operating_improvement'), None, 'hybrid'),
    'trend_fund_75': ('trend_confirmed', '75% trend / 25% fundamental improvement',
                      _trend_fund(0.75, 0.25, 'operating_improvement'), None, 'hybrid'),
    'industry_rotation': ('industry', 'rank industry from members then pick inside', None,
                          'NOT_TESTED: no certified historical industry map', 'hybrid'),
    'post_report_drift': ('reaction', 'price reaction since the latest report date',
                          post_report_drift, None, 'hybrid'),
}

WAVE_LISTS = {
    1: {'description': 'share selection with a fixed equal-weight top-10 monthly policy',
        'signals': list(SIGNALS),
        'fixed_policy': 'ew_top10_monthly'},
}


def signal_frame(panel, name, cohort=None):
    """Return the score frame the engine expects for one signal."""
    family, desc, fn, note, requirement = SIGNALS[name]
    if fn is None:
        raise ValueError(f'not_tested_signal: {name} ({note})')
    mask, score = fn(panel, cohort)
    # A month with fewer than two ranked names cannot produce a rank: such rows
    # are ineligible rather than eligible-with-missing-score.
    out = panel[['decision_time', 'company_id', 'symbol', 'capacity_rial']].copy()
    out['eligible'] = mask.to_numpy()
    out['score'] = score.to_numpy()
    return out


def baseline_frame(panel, model, common=False, cohort=None):
    """Reuse the frozen return_first models as baselines on the same engine.

    The equal-weight baseline must be run with model='equal_weight' through the
    engine (holding every eligible name), NOT as a zero-score ranked frame
    (which would just take the first ten by company id) — corrective 2.1.
    """
    from ranking_research.return_first.models import score
    policy = json.loads((Path(__file__).resolve().parents[1] / 'top10_protocol.json')
                        .read_text(encoding='utf8'))
    policy.update(family_scope='general', maximum_financial_age_days=MAX_FINANCIAL_AGE,
                  minimum_positive_volume_sessions=MIN_VOLUME_SESSIONS,
                  liquidity_sessions=LIQUIDITY_SESSIONS)
    if model == 'equal_weight':
        raise ValueError('equal_weight baseline must use engine model="equal_weight", '
                         'not baseline_frame (corrective 2.1)')
    panel = panel.copy()
    if 'sources_published_before_cutoff' in panel:
        panel['source_valid'] = panel.source_valid & panel.sources_published_before_cutoff.eq(True)
    if cohort is not None:
        panel.loc[~np.asarray(cohort, dtype=bool), 'capacity_rial'] = 0.0
    models = score(panel, policy, common=common)
    d = models[model]
    out = d[['decision_time', 'company_id', 'symbol', 'capacity_rial']].copy()
    out['eligible'] = d.eligible.to_numpy()
    out['score'] = d[model].to_numpy()
    return out


def wave1_list():
    return {name: {'family': SIGNALS[name][0], 'description': SIGNALS[name][1],
                   'status': 'testable' if SIGNALS[name][2] is not None else 'not_tested',
                   'note': SIGNALS[name][3], 'requirement': SIGNALS[name][4]}
            for name in SIGNALS}
