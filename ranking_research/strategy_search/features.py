"""Point-in-time signal panel: frozen fundamentals plus causal price features.

Fundamentals come from the frozen `features.parquet` produced by the existing
preparation pipeline (already point-in-time: decision_time, publication_cutoff,
financial_age_days). This module adds only features derived from the market
archive in a strictly causal way: every adjustment chain is the as-of-decision
chain, so no later corporate action can leak into a historical decision.

Corrective 2.3: publication control compares every CONSUMED source's own
publication timestamp against the cutoff, not just the cutoff column against
the decision date; unknown/NaT dates never pass.

Corrective 2.4: the panel cache key is a fingerprint of the actual inputs —
the frozen feature table, the market reference files, the raw archive and the
effective code — so a change in any consumed input invalidates the cache. The
fingerprint of a cached panel is stored in a sidecar manifest and reused to
avoid re-hashing the whole raw archive on every experiment.
"""
import json
import sys
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'score_v2_research'))
import v2lib as V  # noqa: E402

HIST = ROOT / 'ranking_research' / 'output' / 'return_history_20261015T101320911447Z'
CACHE = ROOT / 'ranking_research' / 'output' / 'strategy_search'
TOL_DAYS = 7
CACHE_MANIFEST = CACHE / 'panel_manifests.json'


def load_market(symbols):
    """Market archive with the same corrected volume contract the frozen run uses.

    v2lib loads zTotTran into `vol` and qTotTran5J into `tcnt`; the frozen engine
    swaps them so `vol` is traded shares. Skipping this swap silently shrinks fill
    capacity and is not a valid comparison.
    """
    md = V.MarketData(V.load_reference_data(), symbols=sorted(set(symbols)))
    from ranking_research.top10_six_month.market_adapter import correct_volume
    correct_volume(md)
    return md


def causal_factors(md, sym, T):
    """Same event product as v2lib.asof_factors, vectorized; one date per symbol cached."""
    cache = getattr(md, '_search_factors', None)
    if cache is None:
        cache = md._search_factors = {}
    if sym in cache and cache[sym][0] == str(T):
        return cache[sym][1]
    rec = md.data[sym]
    dates = np.asarray(rec['dates'])
    out = np.ones(len(dates))
    for day, factor in sorted(md.events.get(rec['sid'], []), key=lambda e: e[0], reverse=True):
        if str(day) <= str(T):
            out[dates < str(day)] *= factor
    cache[sym] = (str(T), out)
    return out


def pit_return(md, sym, left_date, right_date, T):
    """Adjusted return left->right using the as-of-T causal adjustment chain."""
    rec = md.data.get(sym)
    if rec is None:
        return np.nan
    a = bisect_right(rec['dates'], str(left_date)) - 1
    b = bisect_right(rec['dates'], str(right_date)) - 1
    if a < 0 or b < 0 or rec['c'][a] <= 0:
        return np.nan
    if any((pd.Timestamp(t) - pd.Timestamp(rec['dates'][i])).days > TOL_DAYS
           for t, i in [(left_date, a), (right_date, b)]):
        return np.nan
    f = causal_factors(md, sym, str(T))
    return float(rec['c'][b] * f[b] / (rec['c'][a] * f[a]) - 1)


def trailing_vol(md, sym, T, sessions=60):
    rec = md.data.get(sym)
    if rec is None:
        return np.nan
    idx = [k for k, d in enumerate(rec['dates']) if d <= str(T)][-sessions:]
    if len(idx) < 30:
        return np.nan
    f = causal_factors(md, sym, str(T))
    p = np.array([rec['c'][k] * f[k] for k in idx], float)
    p = p[p > 0]
    if len(p) < 30:
        return np.nan
    return float(np.std(np.diff(p) / p[:-1]))


def _sources(raw):
    if raw is None:
        return []
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
        return list(v) if v else []
    except (ValueError, TypeError):
        return []


def publication_flags(frame):
    """Compare each consumed source's own publication time to the cutoff.

    A row passes only when it has at least one source, every consumed source has
    a parseable timestamp, and every one of them is strictly before the cutoff.
    NaT/unknown never passes (corrective 2.3).
    """
    ok = np.zeros(len(frame), dtype=bool)
    latest_pub = np.full(len(frame), np.nan, dtype='datetime64[ns]')
    cutoff = pd.to_datetime(frame.publication_cutoff, utc=True).dt.tz_localize(None).to_numpy()
    for i, row in enumerate(frame.itertuples()):
        srcs = _sources(getattr(row, 'sources', None))
        if not srcs:
            continue
        stamps = []
        for s in srcs:
            ts = s.get('published_at')
            if ts is None:
                stamps = None
                break
            parsed = pd.to_datetime(ts, utc=True, errors='coerce')
            if pd.isna(parsed):
                stamps = None
                break
            stamps.append(parsed.tz_localize(None))
        if stamps is None:
            continue  # unknown publication date: not allowed to pass
        if all(t < pd.Timestamp(cutoff[i]) for t in stamps):
            ok[i] = True
            latest_pub[i] = max(stamps).to_datetime64()
    return ok, latest_pub


def add_features(frame, md):
    d = frame.copy()
    moms, vols, drifts = [], [], []
    from .signals import quarterly_acceleration
    d['accel_op'] = quarterly_acceleration(d)
    pub_ok, latest_pub = publication_flags(d)
    d['sources_published_before_cutoff'] = pub_ok
    d['latest_source_publication'] = latest_pub
    for row in d.itertuples():
        T, sym = row.decision_time, row.symbol
        left6 = (pd.Timestamp(T) - pd.DateOffset(months=6)).date().isoformat()
        right1 = (pd.Timestamp(T) - pd.DateOffset(months=1)).date().isoformat()
        moms.append(pit_return(md, sym, left6, right1, T))
        vols.append(trailing_vol(md, sym, T))
        # Post-publication drift: from the latest source's own publication date
        # (not the period-end age) to the decision date, only when every
        # consumed source published before the cutoff (corrective 2.3).
        drift = np.nan
        pub = getattr(row, 'latest_source_publication', pd.NaT)
        if bool(getattr(row, 'sources_published_before_cutoff', False)) and pd.notna(pub):
            start = (pd.Timestamp(pub) + pd.Timedelta(days=1)).date().isoformat()
            if pd.Timestamp(start) < pd.Timestamp(T):
                drift = pit_return(md, sym, start, T, T)
        drifts.append(drift)
    d['mom_6_1'] = moms
    d['vol_60'] = vols
    d['trend_vol'] = d['momentum_12_1'] / d['vol_60'].where(d['vol_60'].gt(1e-9))
    d['report_drift'] = drifts
    return d


def market_fingerprint(symbols):
    """Hash of every market input actually consumed: reference files + raw
    archives for the symbols in the panel (corrective 2.4). ~32 MB here, so
    hashing per build (not per experiment) is acceptable."""
    ref_files = [V.CACHE / 'corp_actions_confirmed.parquet',
                 V.CACHE / 'calendar.parquet', V.CACHE / 'securities.parquet']
    from .registry import sha_file, sha_bytes
    parts = {str(p): sha_file(p) for p in ref_files}
    sec = V.load_reference_data()['sec']
    ins = dict(zip(sec.symbol, sec.ins_code))
    for sym in sorted(set(symbols)):
        code = ins.get(sym)
        if code is None:
            parts[f'symbol:{sym}'] = 'MISSING_SECURITY'
            continue
        p = V.RAW / f'raw_{sym}_{code}.json.gz'
        parts[f'raw:{sym}'] = sha_file(p) if p.exists() else 'MISSING_RAW'
    blob = json.dumps(parts, sort_keys=True).encode('utf8')
    return {'hash': sha_bytes(blob), 'files': len(parts)}


def panel_fingerprint(panel_path):
    """Content hash of the derived panel itself (corrective 2.4)."""
    from .registry import sha_file
    return sha_file(panel_path)


def _cache_key():
    from .registry import sha_file, combined_code_hash, tree_hash
    paths = ['ranking_research/strategy_search/' + n + '.py'
             for n in ('features', 'signals', 'contract')]
    paths += ['score_v2_research/v2lib.py', 'ranking_research/top10_six_month/market_adapter.py']
    return sha_file(HIST / 'features.parquet'), combined_code_hash(tree_hash(paths))


def build(force=False):
    base = pd.read_parquet(HIST / 'features.parquet')
    CACHE.mkdir(parents=True, exist_ok=True)
    feat_hash, code_hash = _cache_key()
    manifests = {}
    if CACHE_MANIFEST.exists():
        try:
            manifests = json.loads(CACHE_MANIFEST.read_text(encoding='utf8'))
        except ValueError:
            manifests = {}
    entry = manifests.get(f'{feat_hash[:16]}_{code_hash[:16]}')
    market_fp = market_fingerprint(base.symbol.unique())
    if entry and not force and entry.get('market_fingerprint') == market_fp:
        target = CACHE / f'panel_{feat_hash[:16]}_{code_hash[:16]}_{market_fp["hash"][:16]}.parquet'
        if target.exists() and entry.get('panel_sha256') == panel_fingerprint(target):
            return pd.read_parquet(target), target
    md = load_market(base.symbol.unique())
    panel = add_features(base, md)
    target = CACHE / f'panel_{feat_hash[:16]}_{code_hash[:16]}_{market_fp["hash"][:16]}.parquet'
    panel.to_parquet(target, index=False)
    manifests[f'{feat_hash[:16]}_{code_hash[:16]}'] = {
        'features_sha256': feat_hash, 'code_hash': code_hash,
        'market_fingerprint': market_fp,
        'panel_sha256': panel_fingerprint(target),
        'built_at': pd.Timestamp.utcnow().isoformat(),
    }
    CACHE_MANIFEST.write_text(json.dumps(manifests, indent=2), encoding='utf8')
    return panel, target


def data_hash():
    """Fingerprint of ALL inputs the experiments consume (corrective 2.4):
    the frozen feature table, the market reference files and the raw archives."""
    from .registry import sha_file
    base = pd.read_parquet(HIST / 'features.parquet', columns=['symbol'])
    fp = market_fingerprint(base.symbol.unique())
    _, derived = build()
    return {'features': sha_file(HIST / 'features.parquet'),
            'market': fp['hash'], 'market_files': fp['files'],
            'derived_panel': sha_file(derived),
            'execution_contract': sha_file(ROOT / 'ranking_research/top10_protocol.json')}


if __name__ == '__main__':
    if __package__ in (None, ''):
        sys.path.insert(0, str(ROOT))
        from ranking_research.strategy_search import features as _f
        frame, path = _f.build(force=True)
    else:
        frame, path = build(force=True)
    print('panel', frame.shape, '->', path)
    print(frame[['mom_6_1', 'vol_60', 'trend_vol', 'report_drift', 'accel_op']].describe().to_string())
