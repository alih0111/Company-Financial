"""Reuse frozen preparation only, re-score and re-register all return experiments."""
import shutil
from pathlib import Path
import pandas as pd
from .common import read, write, sha, checkpoint
from .factors import score


def reuse_prepared(out, previous):
    previous = Path(previous).resolve()
    if read(previous / 'progress.json')['stages'].get('prepare', {}).get('status') != 'complete':
        raise ValueError('reusable_preparation_must_be_complete')
    original = read(previous / 'manifest.json')
    current = read(out / 'manifest.json')
    source = read(previous / 'registration.json')
    if source['inputs'] != read(out / 'registration.json')['inputs']: raise ValueError('different_financial_source')
    # Only the new package's implementation may be repaired. All financial,
    # market, legacy parser and fiscal-calendar files must remain byte-identical.
    package = Path(__file__).resolve().parent
    for path, digest in original.items():
        p = Path(path)
        if p.parent == package: continue
        if sha(p) != digest: raise ValueError('prepared_source_changed: ' + str(p))
        current[path] = digest
    paths = ['features_point_in_time.parquet', 'outcomes.parquet', 'historical_family_proofs.json',
             'data_gaps.json', 'external_data_availability_audit.json']
    for name in paths:
        src = previous / name
        if src.exists():
            shutil.copyfile(src, out / name)
            current[str(src)] = sha(src)
    for name in ['registration.json', 'manifest.json']:
        current[str(previous / name)] = sha(previous / name)
    write(out / 'manifest.json', current)
    f = pd.read_parquet(out / 'features_point_in_time.parquet')
    from .prepare import market
    md = market(out)
    # Reuse financial reconstruction, but recompute liquidity observations under
    # the corrected volume contract. Never reuse an execution ledger.
    cal = md.cal
    from bisect import bisect_right
    counts = []
    for row in f.itertuples():
        rec = md.data.get(row.symbol); end = bisect_right(cal, row.decision_time)
        sessions = cal[max(0, end - 20):end]
        counts.append(sum(d in rec['dmap'] and rec['vol'][rec['dmap'][d]] > 0 for d in sessions) if rec else 0)
    f['positive_volume_sessions'] = counts
    f.to_parquet(out / 'features_point_in_time.parquet', index=False)
    p = read(out / 'protocol.json'); scored = score(f, p)
    scored.to_parquet(out / 'scores.parquet', index=False)
    dates = sorted(pd.read_parquet(Path(read(out / 'registration.json')['parent']) / 'features.parquet', columns=['as_of']).as_of.unique())
    coverage = scored.groupby('decision_time').agg(total=('company_id', 'size'), eligible=('eligible', 'sum')).reindex(dates, fill_value=0)
    coverage.index.name = 'decision_time'
    coverage['low_diversity'] = coverage.eligible < p['minimum_population']
    coverage.to_csv(out / 'coverage_by_date.csv')
    gaps = read(out / 'data_gaps.json')
    gaps.update(attempted_start=min(dates), attempted_end=max(dates),
                first_nonempty_financial_snapshot=str(f.decision_time.min()),
                eligible_rows=int(scored.eligible.sum()))
    gaps.pop('history_start', None); gaps.pop('history_end', None)
    write(out / 'data_gaps.json', gaps)
    scored[['decision_time', 'company_id', 'symbol', 'refusals']].to_csv(out / 'refusals.csv', index=False)
    write(out / 'preparation_reuse.json', {'previous_run': str(previous),
          'reason': 'Technical corrections only; eighteen weights/cadences and protocol unchanged. Includes corrected qTotTran5J share-volume mapping after an invalid diagnostic execution was identified. Financial features retained, liquidity observations recomputed, no old execution ledger reused.',
          'financial_preparation_reused': True, 'old_scores_reused': False,
          'previous_return_evaluation_exists': (previous / 'portfolio_summary.json').exists(),
          'previous_manifest_sha256': sha(previous / 'manifest.json')})
    checkpoint(out, 'prepare', reused_from=str(previous), rows=len(f), eligible=int(scored.eligible.sum()))
