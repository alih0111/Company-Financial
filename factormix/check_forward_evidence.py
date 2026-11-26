"""Prepare and score a captured public package without publishing to the active account."""
import argparse
from datetime import datetime
import json
import subprocess
import sys

from factormix.ranking_evidence import TEHRAN
from factormix.decision_readiness import assess_ranking
from factormix.refresh_ranking import ARCHIVE, ROOT, calculate, publish, read, sha


def check(capture, output, *, reuse_ranking=False, official_calendar=None):
    output.mkdir(parents=True, exist_ok=reuse_ranking)
    market = read(capture / 'market/manifest.json')
    codal = max((capture / 'codal').glob('paper-cycle-*/manifest.json'))
    calendars = sorted((capture / 'calendar').glob('manifest.*.json'))
    public_calendar = read(calendars[-1]) if calendars else {}
    prepared = codal.parent / 'prepared/prepared-inputs.json'
    if not prepared.is_file():
        subprocess.run([sys.executable, '-B', str(ROOT / 'ranking_research/future_eval_v12_30/prepare_codal_inputs.py'),
                        str(codal)], cwd=ROOT, check=False)
    prepared_summary = read(prepared)['counts']
    summary = dict(market_symbols=market['completed_count'], prepared=prepared_summary,
                   calendar_quality=public_calendar.get('quality'),
                   calendar_completion=public_calendar.get('readiness', {}).get('completion_officially_confirmed'),
                   calendar_sha256=sha(calendars[-1]) if calendars else None,
                   state='blocked', orders=0, fills=0, reconciliation='NOT_RUN')
    if market['completed_count'] != market['universe_count']:
        summary['reason'] = 'full_market_package_missing'
    else:
        local = datetime.now(TEHRAN)
        today = local.date().isoformat()
        if reuse_ranking:
            ranking = read(output / 'ranking.json')
            if any(sha(ROOT / name) != expected for name, expected in ranking['source_hashes'].items()):
                raise ValueError('ranking source hash mismatch')
        else:
            ranking = calculate(output, today, pack=capture / 'market', codal_manifest=codal, isolated=True,
                                calendar_manifest=official_calendar)
        summary.update({k: ranking[k] for k in ('date', 'market_date', 'computed_at_utc', 'universe_count',
                                               'eligible_count', 'data_readiness')})
        reasons = []
        reviewed_at = datetime.now(TEHRAN)
        policy = read(ARCHIVE / 'strategy.locked.json')
        gate = assess_ranking(ranking, [r['symbol'] for r in ranking['rows']],
                              policy['execution_assumptions'], reviewed_at)
        summary['data_readiness'] = gate['state']
        if gate['state'] != 'PASS':
            reasons.append('input_evidence_gate')
        if ranking['market_date'] != today:
            reasons.append('current_session_close_missing')
        if ranking['date'] != today:
            reasons.append('ranking_session_date_mismatch')
        if reviewed_at.hour < 17:
            reasons.append('before_paper_review_window')
        if not all('exchange_calendar' in item.get('receipt_bounds', {})
                   for item in ranking['input_evidence'] if item['factor'] == 'eod'):
            reasons.append('completed_market_wide_calendar_missing')
        if not reasons:
            summary.update(state='ready_for_isolated_paper', reconciliation='PENDING_PAPER')
        summary['reasons'] = reasons
    publish(output / 'forward-check.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('output')
    parser.add_argument('--reuse-ranking', action='store_true')
    parser.add_argument('--official-calendar')
    args = parser.parse_args()
    for value in (args.run, args.output):
        if not value.isascii() or not value.replace('-', '').isalnum():
            parser.error('run and output must be alphanumeric with optional hyphens')
    capture = ROOT / '.runtime/factormix-source-evidence' / args.run
    print(json.dumps(check(capture, capture / args.output, reuse_ranking=args.reuse_ranking,
                           official_calendar=args.official_calendar), ensure_ascii=False))


if __name__ == '__main__':
    main()
