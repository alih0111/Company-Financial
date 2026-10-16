"""Stage by default; publish an exactly validated input repair via the serving orchestrator."""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--publish', action='store_true')
    args = ap.parse_args()
    if not args.publish:
        os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'
    from verified_screen import VerifiedScreenEngine, validate_metrics, source_manifest, CM
    from complete_ranking_coverage import OUT, write
    import orchestrate_refresh as O
    read = lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
    approved = read(ROOT / 'ranking_research/output/input_attribution_latest.json')
    directory = Path(approved['run_path'])
    # The expected metrics themselves must still match the frozen attribution manifest.
    import hashlib
    manifest = read(directory / 'manifest.json')
    for name in ('corrected_metrics.json', 'summary.json'):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != manifest[name]:
            raise ValueError('controlled attribution artifact changed: ' + name)
    asof = dt.date.fromisoformat(approved['as_of'])
    cutoff = dt.datetime.fromisoformat(approved['cutoff'])
    if cutoff.tzinfo is None or cutoff > dt.datetime.now(dt.timezone.utc) or asof > cutoff.date():
        raise ValueError('invalid/future snapshot cutoff')
    engine = VerifiedScreenEngine(asof, cutoff)
    metrics = engine.compute()
    validate_metrics(metrics, read(directory / 'corrected_metrics.json'))
    if source_manifest() != engine.financial_input_evidence['source_manifest']:
        raise RuntimeError('financial sources changed during computation')
    result = {'prepared_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'as_of': str(asof), 'cutoff': cutoff.isoformat(), 'population': len(metrics),
              'digest': engine.digest(), 'evidence': engine.financial_input_evidence,
              'attribution_path': str(directory), 'published': False, 'previous_run_id': None}
    if args.publish:
        with CM.pg_pilot_conn() as db:
            with db.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(71420261014)')
                previous = O.latest_serving_run(cur, CM.SCORE_VERSION)
                result['previous_run_id'] = previous[0] if previous else None
                if previous and (previous[1] > asof or previous[2] > cutoff):
                    raise ValueError('a newer serving snapshot exists; refuse to publish older evidence')
                prior = {}
                if previous:
                    cur.execute('SELECT parameters FROM analytics.score_runs WHERE id=%s', (previous[0],))
                    prior = cur.fetchone()[0]
                if (prior or {}).get('verified_financial_input', {}).get('metric_digest') == engine.digest():
                    result['action'] = 'ALREADY_PUBLISHED'
                else:
                    # Keep the existing sole serving-write path and its append-only transaction.
                    engine.previous_serving_run_id = result['previous_run_id']
                    O.VerifiedScreenEngine = lambda a, c: engine
                    outcome = O.run_engine(cur, asof, cutoff, CM.SCORE_VERSION, store=True)
                    run_id = outcome['stored_run_id']
                    verified = O.summarize_run(cur, run_id)
                    if not verified.get('completed') or verified['company_scores'] != len(metrics):
                        raise RuntimeError('incomplete serving run; transaction rolled back')
                    if source_manifest() != result['evidence']['source_manifest']:
                        raise RuntimeError('source changed before publication; transaction rolled back')
                    result.update(published=True, action='PUBLISHED', new_run={**outcome, **verified})
    else:
        result['action'] = 'VALIDATED_READ_ONLY'
    suffix = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write(OUT / ('screen_refresh_' + suffix + '.json'), result)
    write(OUT / 'screen_refresh_latest.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'evidence'}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    main()
