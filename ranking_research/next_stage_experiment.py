"""Registered development comparison after source repairs, never a fresh holdout.

Expanded monthly schedule, shared corrected inputs, two fixed candidates and one
temporally trained weight model. Production promotion remains a separate gate.
"""
import copy
import datetime as dt
import hashlib
import json
import sys
from bisect import bisect_right
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from next_stage_preview import comparative_facts
from next_stage_weights import choose_weights, BLOCKS, PENALTIES
from v2_inputs import ArchiveSnapshots, H, CM, feature_row
from v2_engine import score_frame
from v2_run import baseline_common
from fiscal_calendar import parse_title
from evaluate import diagnostics, forward, paired_ci
import run as R
import reconstructed_replay as B


class CorrectedSnapshots(ArchiveSnapshots):
    def snapshot(self, date, cutoff=None, require_observed=False):
        effective = cutoff or B.cutoff_for(date)
        selected = H.select_asof(self.reports, effective)
        records = {(r['company_id'], str(r['tracing_no'])): r for r in selected}
        compute = CM.Engine.compute
        def supplement(engine):
            # Only independently validated current-report comparatives qualify.
            engine.stmt = [r for r in engine.stmt if r['period_order'] == 1]
            annual = {}
            for title in engine.codal_titles:
                if parse_title(title['title'])[1] == 12:
                    annual.setdefault(title['company_id'], set()).add(title['period_end_date'])
            groups = {}; latest = {}
            for st in engine.stmt:
                groups.setdefault((st['company_id'], str(st['report_id'])), []).append(st)
                latest[st['company_id']] = max(latest.get(st['company_id'], st['period_end_date']), st['period_end_date'])
            for key, rows in groups.items():
                record = records.get(key)
                if record is None or not record['facts']: continue
                if (latest[key[0]] - dt.date.fromisoformat(record['period_end'])).days > 1000: continue
                for fact in comparative_facts(record, self.parsed(record), annual.get(key[0], set())):
                    engine.stmt.append({**rows[0], **{k: v for k, v in fact.items() if k != 'comparative_period'}})
            return compute(engine)
        CM.Engine.compute = supplement
        try: return super().snapshot(date, cutoff, require_observed)
        finally: CM.Engine.compute = compute


def month_dates(calendar, start='2020-01-01', end='2026-06-30'):
    months = {}
    for date in calendar:
        if start <= date <= end: months[date[:7]] = date
    return sorted(months.values())


def main():
    repair = Path(H.C.read(HERE / 'output/data_repair_latest.json')['run_path'])
    inputs = repair / 'comparative_history'
    out = HERE / 'output' / ('weight_development_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir()
    policy = H.C.read(inputs / 'protocol.json')
    registration = {'version': 'ranking-weight-development-3', 'registered_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'context': 'Previously inspected data and related results; expanded development history, not independent holdout',
        'models': ['CONSENSUS', 'ECONOMIC_EQUAL', 'LEARNED'], 'primary_horizon': 126,
        'window': ['2020-01-01', '2026-06-30'], 'outer_fold': 'calendar year, frozen at first eligible signal',
        'weight_constraints': {'quality_min': .2, 'value_min': .2, 'maximum_block': .5, 'sum': 1},
        'penalties': list(PENALTIES), 'outer_minimum_dates': 36, 'inner_minimum_dates': 24, 'inner_validation_dates': 6,
        'insufficient_training': 'No learned score; no fallback model substituted',
        'growth': 'Nominal sales growth, no volume/inflation-adjusted claim',
        'industry_universe': 'Current identity/family, no survivor-free or dated sector-neutral claim',
        'monthly': 'Legacy period proxies retained in screen baseline; not first-seen PIT',
        'returns': 'Mechanically adjusted price, not complete cash-dividend/rights total return',
        'production_changed': False, 'real_orders': 0, 'acceptance': policy['acceptance']}
    H.C.write(out / 'registration.json', registration)
    frozen = {}
    for name in ('input_reports.json', 'input_monthly.json', 'input_family.json', 'protocol.json'):
        raw = (inputs / name).read_bytes(); (out / name).write_bytes(raw)
        frozen[str(inputs / name)] = hashlib.sha256(raw).hexdigest()
    share_path = H.OUT / 'share_intervals.json'
    (out / 'input_shares.json').write_bytes(share_path.read_bytes())
    frozen[str(share_path)] = R.sha(share_path)
    code = [Path(__file__), HERE / 'next_stage_weights.py', HERE / 'next_stage_preview.py', HERE / 'v2_inputs.py',
            HERE / 'v2_engine.py', HERE / 'v2_run.py', HERE / 'evaluate.py', Path(CM.__file__),
            Path(CM.__file__).with_name('report_chain_ttm.py'), Path(CM.__file__).with_name('fiscal_calendar.py')]
    source_dir = out / 'source'; source_dir.mkdir()
    for path in code:
        (source_dir / path.name).write_bytes(path.read_bytes()); frozen[str(path)] = R.sha(path)
    H.C.write(out / 'input_manifest.json', frozen)
    H.C.write(HERE / 'output/weight_development_running.json', {'run_path': str(out), 'status': 'preparing'})
    reports = H.C.read(out / 'input_reports.json')
    current = H.C.read(out / 'input_family.json')
    metadata = {r['symbol']: r for r in current['ranked'] + current['unscored']}
    identities = {r['company_id']: {'symbol': r['symbol']} for r in reports
                  if metadata.get(r['symbol'], {}).get('model_family') == 'general'}
    md = R.V.MarketData(R.V.load_reference_data(), symbols=sorted(r['symbol'] for r in identities.values()))
    for row in identities.values(): row['security_id'] = md.sym2sid.get(row['symbol'])
    identities = {cid: row for cid, row in identities.items() if row['security_id']}
    source = CorrectedSnapshots(reports, H.C.read(out / 'input_monthly.json'), identities, md,
                                H.C.read(out / 'input_shares.json')['intervals'])
    features = []; metrics_by_key = {}; metric_rows = []
    for date in month_dates(md.cal):
        engine, metrics, timing = source.snapshot(date)
        raw_t, _ = R.historical_timing(md, sorted(r['symbol'] for r in metrics.values()), date)
        for cid, metric in metrics.items():
            row = feature_row(engine, cid, metric, policy)
            row.update(timing.get(cid, {'momentum': None, 'volatility': None, 'tradable': False}))
            row.update(model_family='general', industry=metadata.get(metric['symbol'], {}).get('industry'), industry_pit_valid=False,
                       publication_cutoff=engine.cutoff.isoformat(),
                       sources=json.dumps(engine.snapshot_source_reports.get(cid, []), ensure_ascii=False))
            for key in ('roe', 'cash_conversion', 'pe', 'pb', 'ps', 'operating_margin', 'net_margin'): row[key] = metric[key]
            for factor in ('momentum_6m_rel', 'momentum_3m_rel', 'liquidity', 'low_volatility'):
                fact = raw_t.get(metric['symbol'], {}).get(factor, {})
                row['qvt_' + factor] = fact.get('raw_value') if fact.get('status') == 'valid' else None
            features.append(row); metrics_by_key[(date, cid)] = metric
            metric_rows.append({'as_of': date, 'company_id': cid, **{k: v for k, v in metric.items() if not k.startswith('_')}})
        print(f'{date}: {len(metrics)} companies', flush=True)
    frame = pd.DataFrame(features)
    frame.to_parquet(out / 'features.parquet', index=False)
    pd.DataFrame(metric_rows).to_parquet(out / 'screen_inputs.parquet', index=False)
    scored = score_frame(frame, policy)
    scored.to_parquet(out / 'all_scores.parquet', index=False)
    common = baseline_common(scored, metrics_by_key, policy)
    if common.empty: raise ValueError('insufficient_common_population')
    common['CONSENSUS'] = common.groupby('as_of').SCREEN_CORRECTED.rank(pct=True) * 50 + common.groupby('as_of').QVT76_CORRECTED.rank(pct=True) * 50
    common['ECONOMIC_EQUAL'] = common['EQUAL_BLOCKS']
    common.to_parquet(out / 'scores_without_outcomes.parquet', index=False)
    for h in (126, 63, 252): common['ret_' + str(h)] = [forward(md, r.symbol, r.as_of, h) for r in common.itertuples()]
    def exit_date(date):
        idx = bisect_right(md.cal, date) + 126
        return md.cal[idx] if idx < len(md.cal) else '9999-12-31'
    common['label_exit_date'] = common.as_of.map(exit_date)
    common['LEARNED'] = np.nan; folds = []
    for year in sorted(common.as_of.str[:4].unique()):
        mask = common.as_of.str.startswith(year); first = common.loc[mask, 'as_of'].min()
        weights, receipt = choose_weights(common, first); receipt['year'] = year; folds.append(receipt)
        if weights is not None: common.loc[mask, 'LEARNED'] = common.loc[mask, list(BLOCKS)].to_numpy() @ weights
    common.to_parquet(out / 'diagnostic_panel.parquet', index=False)
    H.C.write(out / 'learned_folds.json', folds)
    records = []; models = ['SCREEN_CORRECTED', 'QVT76_CORRECTED', 'CONSENSUS', 'ECONOMIC_EQUAL', 'LEARNED']
    for model in models:
        scope = common[common[model].notna()].copy()
        for horizon in (126, 63, 252): records += diagnostics(scope, model, horizon, policy)
    diagnostic = pd.DataFrame(records)
    diagnostic.to_csv(out / 'per_date_diagnostics.csv', index=False)
    diagnostic.groupby(['model', 'horizon']).agg(mean_ic=('ic', 'mean'), ic_dates=('ic', 'count'),
        top_excess=('top_excess', 'mean'), top_dates=('top_excess', 'count')).to_csv(out / 'aggregate.csv')
    # Each candidate gets paired same-date comparisons, including absent learned folds.
    primary = diagnostic[diagnostic.horizon == 126]
    cfg = policy['acceptance']; decisions = {}
    for model in registration['models']:
        pairs = {b: paired_ci(primary, model, b, policy) if model in primary.model.unique() else
                 {'n': 0, 'mean': None, 'lower': None, 'upper': None} for b in models[:2]}
        pivot = primary.pivot(index='as_of', columns='model', values='ic')
        ic_gain = {b: float((pivot[model] - pivot[b]).dropna().mean()) if model in pivot else None for b in models[:2]}
        passed = all(p['n'] >= cfg['minimum_paired_dates'] and p['mean'] is not None
                     and p['mean'] >= cfg['minimum_top10_excess_gain_over_both_baselines'] and p['lower'] > 0 for p in pairs.values())
        passed = passed and all(v is not None and np.isfinite(v) and v >= cfg['minimum_mean_ic_gain_over_both_baselines'] for v in ic_gain.values())
        decisions[model] = {'preliminary_diagnostic_pass': bool(passed), 'paired_top': pairs, 'paired_ic_gain': ic_gain,
                            'promotion_ready': False, 'note': 'Economic/source/portfolio gates incomplete; previously inspected development data'}
    H.C.write(out / 'raw_financial_manifest.json', source.raw_manifest)
    market_manifest = {symbol: {'path': str(R.V.RAW / f"raw_{symbol}_{r['ins']}.json.gz"),
                        'sha256': R.sha(R.V.RAW / f"raw_{symbol}_{r['ins']}.json.gz")} for symbol, r in md.data.items()}
    H.C.write(out / 'market_manifest.json', market_manifest)
    for path, sha in frozen.items():
        if R.sha(Path(path)) != sha: raise ValueError('source_changed_during_experiment')
    summary = {'run_path': str(out), 'status': 'development_evaluated', 'feature_rows': len(frame),
        'eligible_rows': int(scored.eligible.sum()), 'common_rows': len(common), 'common_dates': int(common.as_of.nunique()),
        'date_range': [str(common.as_of.min()), str(common.as_of.max())],
        'learned_years': [r['year'] for r in folds if r['status'] == 'trained'], 'decisions': decisions,
        'promotion_ready': False, 'production_changed': False, 'real_orders': 0,
        'limits': registration['context'] + '; nominal growth; publication reconstruction; current universe; monthly proxies; price return only; no cost/capacity certification'}
    H.C.write(out / 'summary.json', B.safe_json(summary))
    H.C.write(HERE / 'output/weight_development_latest.json', B.safe_json(summary))
    print(json.dumps(B.safe_json(summary), ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8'); main()
