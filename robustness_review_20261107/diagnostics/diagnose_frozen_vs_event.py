"""Compare the frozen FactorMix panel inputs with the event-time (ReportFlow) inputs.

Read-only. Run from the repository root on the machine that has the full research
data (ranking_research/output/..., fundamental_event_research/..., score_v2_research/):

    python -B robustness_review_20261107/diagnostics/diagnose_frozen_vs_event.py

Writes only into robustness_review_20261107/diagnostics/results_diag/ .
No database, no network, no changes to registered strategies or accounts.
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, sys, time, traceback, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'results_diag'
FIELDS = ['sales_growth_12m','sales_growth_3m','revenue_growth','operating_profit_growth','net_profit_growth',
          'operating_margin','net_margin','roe','margin_trend','interest_coverage','cash_conversion','earnings_quality',
          'pe','ps','pb','avg_trade_value_30d','sales_stability','leverage','current_ratio','volatility_30d','price_momentum_30d']
LOW = {11, 12, 13, 14, 17, 19}
W033 = [0.01178982033843565, 0.1950482489558543, 0.0021009244509838346, 0.018452940999857618,
        0.21010152399682835, 0.22776441503917455, 0.3253441466496349, 0.009397979569230856]
BLOCKS = ['growth','profitability','valuation','balance','momentum','risk','acceleration','p1']
FROZEN_ZIP = ROOT / 'client/public/strategies/factormix-033/performance/from-1401-monthly15-v1.0.0.zip'
FROZEN_NPZ = 'RFA-FactorMix-033-M15-v1.0.0/snapshot_data/active_inputs.npz'
EVENT_NPZ = ROOT / 'reportflow/artifacts/event_inputs.npz'


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rt(x, lower=False):
    x = np.asarray(x, float)
    r = pd.DataFrame(x).rank(axis=1, method='average', pct=True).to_numpy() * 2 - 1
    if lower:
        r = -r
    return np.where(np.isfinite(x), r, 0.).astype(np.float32)


def market_features(close, adv):
    c = pd.DataFrame(close).where(np.asarray(close) > 0)
    r = c.pct_change(fill_method=None)
    out = {'mom_63': c.pct_change(63, fill_method=None).to_numpy(),
           'mom_126_skip21': (c.shift(21) / c.shift(126) - 1).to_numpy(),
           'near_high_126': (c / c.rolling(126, min_periods=63).max() - 1).to_numpy(),
           'trend_50_200': (c.rolling(50, min_periods=40).mean() / c.rolling(200, min_periods=150).mean() - 1).to_numpy(),
           'vol_63': r.rolling(63, min_periods=31).std().to_numpy(),
           'downside_vol63': r.clip(upper=0).rolling(63, min_periods=40).std().to_numpy(),
           'reversal21': -c.pct_change(21, fill_method=None).to_numpy()}
    return out


def blocks_from_raw(raw, close, adv, p1, cal):
    cols = {}
    for j, name in enumerate(FIELDS):
        v = raw[:, :, j].astype(float).copy()
        if j == 11:
            v = np.abs(v)
        if j in (12, 13, 14):
            v[(v <= 0) | (v > {12: 60, 13: 100, 14: 30}[j])] = np.nan
        cols[name] = rt(v, j in LOW)
    for n, v in market_features(close, adv).items():
        cols[n] = rt(v, n in ('vol_63', 'downside_vol63'))
    d = cal.astype('datetime64[D]')
    lag = np.maximum(0, np.searchsorted(d, d - np.timedelta64(90, 'D'), side='right') - 1)
    der = {'sales_accel_3v12': raw[:, :, 1] - raw[:, :, 0], 'sales_growth_change90': raw[:, :, 1] - raw[lag, :, 1],
           'profit_growth_change90': raw[:, :, 4] - raw[lag, :, 4], 'margin_trend_change90': raw[:, :, 8] - raw[lag, :, 8]}
    for n, v in der.items():
        cols[n] = rt(v)
    cols['p1_score'] = rt(p1)
    m = lambda ns: np.mean(np.stack([cols[x] for x in ns], 2), 2)
    return np.stack([m(FIELDS[:5]), m(FIELDS[5:12]), m(['pe', 'ps', 'pb']),
                     m(['leverage', 'current_ratio', 'cash_conversion', 'sales_stability']),
                     m(['mom_63', 'mom_126_skip21', 'near_high_126', 'trend_50_200']),
                     m(['vol_63', 'downside_vol63', 'reversal21']),
                     m(list(der)), cols['p1_score']], 2).astype(np.float32)


def rank_corr(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 20:
        return np.nan
    return float(np.corrcoef(pd.Series(a[ok]).rank(), pd.Series(b[ok]).rank())[0, 1])


def load_panel(args):
    if args.panel_parquet:
        log('reading panel from --panel-parquet (no monthly correction)')
        reader = pd.read_pickle if args.panel_parquet.endswith('.pkl') else pd.read_parquet
        return reader(args.panel_parquet), 'raw_file_no_correction'
    sys.path[:0] = [str(ROOT), str(ROOT / 'ranking_research/experiments/rank_top5_rebalance_20261105')]
    import backtest_top5 as old
    log(f'reading panel {old.PANEL}')
    panel = pd.read_parquet(old.PANEL)
    try:
        panel = old.apply_monthly_correction(panel)
        mode = 'apply_monthly_correction'
    except Exception:
        traceback.print_exc()
        mode = 'correction_failed_raw_panel'
    return panel, mode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel-parquet', help='testing only: plain panel parquet path')
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'errors': []}
    ev = dict(np.load(EVENT_NPZ, allow_pickle=False))
    cal, syms = ev['cal'], ev['syms'].tolist()
    with zipfile.ZipFile(FROZEN_ZIP) as z:
        fr = dict(np.load(io.BytesIO(z.read(FROZEN_NPZ)), allow_pickle=False))
    assert fr['cal'].tolist() == cal.tolist() and fr['syms'].tolist() == syms, 'frozen/event calendars or symbols differ'
    panel, mode = load_panel(args)
    report['panel_mode'] = mode
    report['panel_columns'] = list(map(str, panel.columns))
    panel = panel.copy()
    panel['decision_time'] = panel['decision_time'].astype(str).str[:10]
    panel['symbol'] = panel['symbol'].astype(str)
    dates = sorted(panel.decision_time.unique())
    report['panel_dates'] = [dates[0], dates[-1], len(dates)]
    missing_syms = sorted(set(syms) - set(panel.symbol))
    report['symbols_missing_in_panel'] = missing_syms[:50]
    ix = pd.MultiIndex.from_product([dates, syms], names=['decision_time', 'symbol'])
    ordered = panel.drop_duplicates(['decision_time', 'symbol'], keep='last').set_index(['decision_time', 'symbol']).reindex(ix)
    praw = ordered[FIELDS].apply(pd.to_numeric, errors='coerce').to_numpy(float).reshape(len(dates), len(syms), len(FIELDS))
    end = int(np.searchsorted(cal, dates[-1], side='right'))
    dateix = np.searchsorted(np.array(dates), cal[:end], side='right') - 1
    P = np.where(dateix[:, None, None] >= 0, praw[np.maximum(dateix, 0)], np.nan)  # panel, daily, up to last panel date
    E = ev['raw'][:end].astype(float)
    report['compared_sessions'] = [str(cal[0]), str(cal[end - 1]), end]
    log(f'aligned panel {P.shape}, event {E.shape}')

    # 1. value agreement per field
    rows = []
    for j, f in enumerate(FIELDS):
        p, e = P[:, :, j], E[:, :, j]
        both = np.isfinite(p) & np.isfinite(e)
        same = both & np.isclose(p, e, rtol=1e-4, atol=1e-6)
        rows.append(dict(field=f, panel_finite=float(np.isfinite(p).mean()), event_finite=float(np.isfinite(e).mean()),
                         both_finite=float(both.mean()), same_share_of_both=float(same.sum() / max(both.sum(), 1)),
                         panel_only=float((np.isfinite(p) & ~np.isfinite(e)).mean()),
                         event_only=float((~np.isfinite(p) & np.isfinite(e)).mean())))
    agree = pd.DataFrame(rows)

    # 2. lead/lag: when a new panel value first appears vs when the same value first appears in event data
    leads, examples = [], []
    for j, f in enumerate(FIELDS):
        if j in (15, 19, 20):  # market-derived fields update daily; timing comparison not meaningful
            continue
        for s in range(len(syms)):
            p, e = P[:, s, j], E[:, s, j]
            fin = np.isfinite(p)
            if fin.sum() < 2:
                continue
            chg = np.flatnonzero(fin[1:] & (~np.isfinite(p[:-1]) | ~np.isclose(p[1:], p[:-1], rtol=1e-6, atol=1e-9))) + 1
            for t in chg:
                v = p[t]
                hit = np.flatnonzero(np.isfinite(e) & np.isclose(e, v, rtol=1e-4, atol=1e-6))
                if len(hit) == 0:
                    leads.append((j, s, t, np.nan)); continue
                lead = int(hit[0]) - int(t)  # >0: panel had the value earlier than event-time data
                leads.append((j, s, t, lead))
                if lead >= 3:
                    examples.append(dict(field=f, symbol=syms[s], panel_first=str(cal[t]), event_first=str(cal[hit[0]]),
                                         lead_sessions=lead, value=float(v),
                                         event_publication=str(ev['latest_financial_publication'][hit[0], s])))
    L = pd.DataFrame(leads, columns=['j', 's', 't', 'lead'])
    L['field'] = [FIELDS[j] for j in L.j]
    def summ(g):
        x = g.lead.dropna()
        return pd.Series(dict(changes=len(g), unmatched_share=float(g.lead.isna().mean()),
                              median_lead=float(x.median()) if len(x) else np.nan,
                              share_panel_earlier_1plus=float((x >= 1).mean()) if len(x) else np.nan,
                              share_panel_earlier_5plus=float((x >= 5).mean()) if len(x) else np.nan,
                              share_panel_later_5plus=float((x <= -5).mean()) if len(x) else np.nan,
                              p90_lead=float(x.quantile(.9)) if len(x) else np.nan))
    lead_tab = L.groupby('field').apply(summ).reset_index()
    by_year = L.assign(year=[str(cal[t])[:4] for t in L.t]).groupby('year').apply(summ).reset_index()

    # 3. blocks from panel data vs frozen candidate_score (validation) and vs event blocks
    p1 = ev['reference_p1'][:end] if 'reference_p1' in ev else fr['p1'][:end]
    close, adv = ev['close'][:end], ev['adv'][:end]
    Bp = blocks_from_raw(P, close, adv, p1, cal[:end])
    Be = blocks_from_raw(E, close, adv, p1, cal[:end])
    sp, se = Bp @ np.array(W033), Be @ np.array(W033)
    frozen = fr['candidate_score'][:end].astype(float)
    sample = list(range(260, end, 20))
    report['rank_corr_frozen_vs_panelrebuilt_median'] = float(np.nanmedian([rank_corr(frozen[i], sp[i]) for i in sample]))
    report['rank_corr_frozen_vs_eventrebuilt_median'] = float(np.nanmedian([rank_corr(frozen[i], se[i]) for i in sample]))
    blockcorr = {b: float(np.nanmedian([rank_corr(Bp[i, :, k], Be[i, :, k]) for i in sample])) for k, b in enumerate(BLOCKS)}
    report['block_rank_corr_panel_vs_event_median'] = blockcorr

    # 4. small artifacts for offline analysis
    np.savez_compressed(OUT / 'panel_blocks.npz', cal=cal[:end], syms=np.array(syms), blocks=Bp.astype(np.float16),
                        block_names=np.array(BLOCKS), score033=sp.astype(np.float32))
    np.savez_compressed(OUT / 'panel_raw_daily.npz', cal=cal[:end], syms=np.array(syms), raw=P.astype(np.float32),
                        fields=np.array(FIELDS))
    agree.to_csv(OUT / 'field_agreement.csv', index=False, encoding='utf-8-sig')
    lead_tab.to_csv(OUT / 'field_lead_lag.csv', index=False, encoding='utf-8-sig')
    by_year.to_csv(OUT / 'lead_lag_by_year.csv', index=False, encoding='utf-8-sig')
    ex = pd.DataFrame(examples)
    if len(ex):
        ex.sort_values('lead_sessions', ascending=False).head(500).to_csv(OUT / 'panel_earlier_examples.csv', index=False, encoding='utf-8-sig')
    report['sizes_mb'] = {p.name: round(p.stat().st_size / 1e6, 2) for p in OUT.glob('*.npz')}
    report['input_sha256'] = {'event_inputs.npz': sha(EVENT_NPZ), 'frozen_zip': sha(FROZEN_ZIP)}
    report['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    (OUT / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    log(json.dumps({k: v for k, v in report.items() if k not in ('panel_columns',)}, ensure_ascii=False)[:2000])
    print(lead_tab.to_string())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / 'ERROR.txt').write_text(traceback.format_exc(), encoding='utf8')
        raise
