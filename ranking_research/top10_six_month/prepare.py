"""Freeze sources, reconstruct publication-time facts, and checkpoint by month."""
import datetime as dt
import json
import shutil
import platform
import importlib.metadata
from bisect import bisect_right
from pathlib import Path
import numpy as np
import pandas as pd
from .common import HERE, ROOT, read, write, sha, now, checkpoint, legacy
from .factors import score


def register(out):
    protocol = read(HERE / 'top10_protocol.json')
    parent = Path(read(HERE / 'output/weight_development_latest.json')['run_path'])
    manifest = read(parent / 'input_manifest.json')
    reports = next(Path(p) for p in manifest if p.endswith('input_reports.json'))
    inputs = reports.parent
    paths = [reports, inputs / 'input_monthly.json', inputs / 'protocol.json',
             ROOT / 'qvt_backtest/output/financial_history/share_intervals.json',
             parent / 'features.parquet', parent / 'screen_inputs.parquet',
             HERE / 'next_stage_experiment.py', HERE / 'next_stage_preview.py',
             HERE / 'v2_inputs.py', HERE / 'company_classification.py',
             ROOT / 'canonical_postgres_v1_2_1/analytics_canonical_v1/compute_metrics.py',
             ROOT / 'canonical_postgres_v1_2_1/analytics_canonical_v1/report_chain_ttm.py',
             ROOT / 'canonical_postgres_v1_2_1/analytics_canonical_v1/fiscal_calendar.py',
             ROOT / 'qvt_backtest/run.py', ROOT / 'qvt_backtest/reconstructed_replay.py',
             ROOT / 'score_v2_research/v2lib.py', HERE / 'top10_protocol.json',
             HERE / 'owner_value_engine.py', HERE / 'owner_value_protocol.json',
             ROOT / 'qvt_backtest/reconstructed_protocol.json',
             HERE / 'tests/test_top10.py',
             *sorted(Path(__file__).parent.glob('*.py'))]
    write(out / 'protocol.json', protocol)
    prior = HERE / 'output/top10_six_month_latest.json'
    if prior.exists(): write(out / 'previous_research_pointer.json', read(prior))
    environment = {'python': platform.python_version()}
    for name in ['numpy', 'pandas', 'pyarrow', 'matplotlib']:
        try: environment[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: environment[name] = None
    write(out / 'environment.json', environment)
    write(out / 'registration.json', {
        'registered_at': now(), 'protocol_sha256': sha(out / 'protocol.json'),
        'inputs': str(inputs), 'parent': str(parent), 'initial_rial': protocol['initial_toman'] * 10,
        'candidates': [f'{m}_{c}m' for m in protocol['weights'] for c in protocol['cadences_months']],
        'previous_experiments': ['v1', 'v2', 'weight_development', 'OWNER_QV', 'CASH_QV', 'SCREEN_GATED'],
        'industry_variant_registered_before_results': True,
        'economic_certification': False, 'real_orders': 0})
    hashes = {str(p): sha(p) for p in paths}
    code_archive = out / 'registered_code'; code_archive.mkdir()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        frozen = code_archive / path.name
        shutil.copyfile(path, frozen); hashes[str(frozen)] = sha(frozen)
    write(out / 'manifest.json', hashes)
    checkpoint(out, 'register')


def market(out):
    *_, R = legacy()
    reg = read(out / 'registration.json')
    frame = pd.read_parquet(Path(reg['parent']) / 'features.parquet')
    md = R.V.MarketData(R.V.load_reference_data(), symbols=sorted(frame.symbol.unique()))
    from .market_adapter import correct_volume
    write(out / 'volume_mapping_audit.json', correct_volume(md))
    return md


def prepare(out):
    _, feature_row, H, rtt, R = legacy()
    from next_stage_experiment import CorrectedSnapshots
    from company_classification import classify_template
    from fiscal_calendar import annual_month_of
    import dynamic_financial as D
    reg = read(out / 'registration.json'); inputs = Path(reg['inputs'])
    protocol = read(out / 'protocol.json')
    parent = Path(reg['parent']); original = pd.read_parquet(parent / 'features.parquet')
    records = read(inputs / 'input_reports.json')
    identities = {r.company_id: {'symbol': r.symbol} for r in original.itertuples()}
    md = market(out)
    for row in identities.values(): row['security_id'] = md.sym2sid.get(row['symbol'])
    source = CorrectedSnapshots(records, [], identities, md, read(ROOT / 'qvt_backtest/output/financial_history/share_intervals.json')['intervals'])
    policy = read(inputs / 'protocol.json')
    hashes = read(out / 'manifest.json')
    # Freeze all market source files, including delisted/missing-price symbols in the issuer panel.
    for sym, rec in md.data.items():
        p = R.V.RAW / f"raw_{sym}_{rec['ins']}.json.gz"; hashes[str(p)] = sha(p)
    for name in ['corp_actions_confirmed.parquet', 'calendar.parquet', 'securities.parquet']:
        p = R.V.CACHE / name; hashes[str(p)] = sha(p)
    proof_path = out / 'historical_family_proofs.json'
    if proof_path.exists():
        proofs = read(proof_path)
    else:
        proofs = []
        for rec in records:
            candidates = []
            if rec.get('dynamic_manifest_path'):
                p = Path(rec['dynamic_manifest_path'])
                if sha(p) != rec['dynamic_manifest_sha256']: raise ValueError('dynamic_manifest_changed')
                hashes[str(p)] = sha(p)
                candidates += [(Path(q['path']), q['sha256']) for q in read(p)['pages'] if q.get('role', 'financial') == 'financial']
            p = D.STORE / 'ranking_next_stage' / str(rec['tracing_no']) / 'catalog_page.html'
            if p.exists(): candidates.append((p, sha(p)))
            for path, digest in candidates:
                if sha(path) != digest: raise ValueError('historical_family_source_changed')
                hashes[str(path)] = digest
                try: payload = D.payload(path.read_text(encoding='utf8'))
                except ValueError: continue
                if str(payload.get('tracingNo')) != str(rec['tracing_no']): continue
                pub = H.parse_persian_datetime(payload.get('publishDateTime'))
                if pub != dt.datetime.fromisoformat(rec['published_at']): continue
                if str(H.F.jalali_date_in(payload.get('periodEndToDate', ''))) != rec['period_end']: continue
                family = classify_template(payload.get('title_En'))
                if family:
                    proofs.append({'company_id': rec['company_id'], 'published_at': rec['published_at'],
                                   'family': family, 'tracing_no': str(rec['tracing_no']),
                                   'path': str(path), 'sha256': digest})
                    break
        write(proof_path, proofs)
    write(out / 'manifest.json', hashes)
    by_company = {}
    for proof in proofs: by_company.setdefault(proof['company_id'], []).append(proof)
    parts = out / 'checkpoints'; parts.mkdir(exist_ok=True)
    dates = sorted(original.as_of.unique())
    for date in dates:
        target = parts / f'{date}.parquet'
        if target.exists(): continue
        eng, metrics, _ = source.snapshot(str(date))
        rows = []
        for cid, m in metrics.items():
            row = feature_row(eng, cid, m, policy)
            selected = eng.snapshot_source_reports.get(cid, [])
            fam = [p for p in by_company.get(cid, []) if dt.datetime.fromisoformat(p['published_at']) < eng.cutoff]
            fam = max(fam, key=lambda p: dt.datetime.fromisoformat(p['published_at'])) if fam else {}
            rep = eng.report_index().get(cid, {})
            latest = max(rep, key=lambda k: k[0] * 12 + k[1]) if rep else None
            durations = {key: val for (company, key), val in eng.feature_calendar[0].items() if company == cid}
            annual = annual_month_of(eng.feature_calendar[1], cid)[0]
            prior = (latest[0] - 1, latest[1]) if latest else None
            previous = rtt(rep, durations, annual, prior, 'operating_profit')[0] if prior else None
            rec = md.data.get(m['symbol']); price = cap = momentum = None; positive = count = 0
            if rec:
                end = bisect_right(rec['dates'], date) - 1
                sessions = [d for d in md.cal if d <= date][-20:]
                idx = [rec['dmap'].get(d) for d in sessions]
                count = len(sessions)
                positive = sum(i is not None and rec['vol'][i] > 0 for i in idx)
                values = [float(rec['tval'][i]) if i is not None and np.isfinite(rec['tval'][i]) else 0 for i in idx]
                cap = float(np.median(values)) * protocol['order_capacity_fraction'] if values else None
                if end >= 0 and (pd.Timestamp(date) - pd.Timestamp(rec['dates'][end])).days <= 7:
                    price = float(rec['c'][end])
                left = (pd.Timestamp(date) - pd.DateOffset(months=12)).date().isoformat()
                right = (pd.Timestamp(date) - pd.DateOffset(months=1)).date().isoformat()
                a = bisect_right(rec['dates'], left) - 1; b = bisect_right(rec['dates'], right) - 1
                if a >= 0 and b >= 0 and all((pd.Timestamp(t) - pd.Timestamp(rec['dates'][i])).days <= 7 for t, i in [(left, a), (right, b)]):
                    factors = md.asof_factors(m['symbol'], str(date))
                    if rec['c'][a] > 0: momentum = float(rec['c'][b] * factors[b] / (rec['c'][a] * factors[a]) - 1)
            row.update(decision_time=str(date), publication_cutoff=eng.cutoff.isoformat(),
                       historical_family=fam.get('family', 'unknown'), family_source=json.dumps(fam),
                       publication_valid=bool(selected) and all(dt.datetime.fromisoformat(s['published_at']) < eng.cutoff for s in selected),
                       sources=json.dumps(selected), prior_operating_profit_ttm=previous,
                       growth_window_valid=latest in durations and prior in durations and durations.get(latest) == durations.get(prior),
                       ocf_ttm=m.get('ocf_ttm'),
                       momentum_12_1=momentum, capacity_rial=cap, decision_price=price,
                       positive_volume_sessions=positive, liquidity_observations=count,
                       valuation_provenance=json.dumps(m.get('_valuation_prov', {})))
            rows.append(row)
        pd.DataFrame(rows).to_parquet(target, index=False)
        hashes.update(source.raw_manifest); write(out / 'manifest.json', hashes)
        checkpoint(out, 'prepare', 'running', last_date=str(date), completed_months=len(list(parts.glob('*.parquet'))), total_months=len(dates))
        print(f'prepare {date}: {len(rows)} issuers', flush=True)
    frame = pd.concat([pd.read_parquet(parts / f'{d}.parquet') for d in dates], ignore_index=True)
    # Remove legacy present-day classification fields entirely.
    frame.drop(columns=['model_family', 'industry', 'industry_pit_valid'], errors='ignore', inplace=True)
    frame.to_parquet(out / 'features_point_in_time.parquet', index=False)
    scored = score(frame, protocol); scored.to_parquet(out / 'scores.parquet', index=False)
    coverage = scored.groupby('decision_time').agg(total=('company_id', 'size'), eligible=('eligible', 'sum')).reindex(dates, fill_value=0)
    coverage.index.name = 'decision_time'
    coverage['low_diversity'] = coverage.eligible < protocol['minimum_population']
    coverage.to_csv(out / 'coverage_by_date.csv')
    scored[['decision_time', 'company_id', 'symbol', 'refusals']].to_csv(out / 'refusals.csv', index=False)
    # Labels live in a separate file and are never passed to the factor engine.
    outcomes = []
    from .portfolio import Prices
    prices = Prices(md)
    for row in frame.itertuples():
        future = (pd.Timestamp(row.decision_time) + pd.DateOffset(months=6)).date().isoformat()
        sessions = [d for d in md.cal if row.decision_time < d <= future]
        entry = sessions[0] if sessions else None
        terminal = sessions[-1] if sessions else None
        p0, _, reason = prices.execution(row.symbol, entry) if entry else (None, 0, 'no_future_session')
        p1, marked = prices.mark(row.symbol, terminal) if terminal else (None, None)
        mature = future <= max(md.cal)
        outcomes.append({'decision_time': row.decision_time, 'company_id': row.company_id,
                         'horizon_end': future, 'entry_date': entry, 'exit_mark_date': marked,
                         'mature': mature, 'executable_exit_certified': False,
                         'adjusted_price_return': float(p1 / p0 - 1) if mature and p0 and p1 else None,
                         'entry_proxy_status': reason})
    pd.DataFrame(outcomes).to_parquet(out / 'outcomes.parquet', index=False)
    write(out / 'data_gaps.json', {
        'historical_universe_certified': False, 'historical_industry_available': False,
        'corporate_cash_and_rights_ledger_available': False, 'queue_fill_certified': False,
        'family_proofs': len(proofs), 'attempted_start': str(min(dates)), 'attempted_end': str(max(dates)),
        'first_nonempty_financial_snapshot': str(frame.decision_time.min()),
        'price_only_proxy': True, 'eligible_rows': int(scored.eligible.sum()),
        'specialized_or_unknown_are_not_bad_stocks': True})
    checkpoint(out, 'prepare', rows=len(frame), eligible=int(scored.eligible.sum()))
