"""Read-only replay and evidence audit of a previously captured FactorMix run."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

import pandas as pd

from factormix.decision_readiness import assess_ranking
from factormix.ranking_evidence import EvidenceFiles, summarize_evidence
from factormix.sales_revision_evidence import correct_canonical_revisions
from factormix.refresh_ranking import (
    ARCHIVE, ROOT, REPLAY, SCORE_CONTRACT, FROZEN_SALES, market_inputs, ranking_identities,
    ranking_input_evidence, read, sales_events, score_snapshot_rows, sha,
)


def audit(archive, codal, output, calendar=None, *, compare_sales_revisions=False):
    output.mkdir(parents=True, exist_ok=False)
    factors = archive / 'factor-inputs'
    old = read(archive / 'ranking.json')
    files = EvidenceFiles(ROOT)
    for name, expected in old['source_hashes'].items():
        files.load(name, expected)
    market = next(ROOT / name for name in old['source_hashes'] if 'market' in name and name.endswith('manifest.json'))
    prepared = codal.parent / 'prepared/prepared-inputs.json'
    reports, comparatives = (factors / name for name in ('input_reports.json', 'comparative_lineage.json'))
    event_file, admission = (factors / name for name in ('monthly_sales_events.parquet', 'admission.json'))
    identities, identity_paths = ranking_identities()
    inputs = [archive / 'ranking.json', market, codal, prepared, admission, reports, comparatives,
              event_file, SCORE_CONTRACT, FROZEN_SALES, *identity_paths,
              ARCHIVE / 'snapshot_data/active_inputs.npz', ARCHIVE / 'snapshot_data/model_features.npz',
              ROOT / 'qvt_backtest/output/financial_history/share_intervals.json',
              ROOT / 'score_v2_research/_cache/corp_actions_confirmed.parquet',
              ROOT / 'score_v2_research/_cache/calendar.parquet']
    if calendar:
        inputs.append(calendar)
    # Pin the retained source files before replay. New artifacts go only under output.
    base_paths = sorted((REPLAY / 'artifacts').glob('financial_*.parquet'))
    before = {path.relative_to(ROOT).as_posix(): sha(path) for path in [*inputs, *base_paths]}
    print('Pinned ranking inputs; replaying score snapshots', file=sys.stderr, flush=True)
    replay, frozen, data, md = market_inputs(market.parent, old['date'])
    replay.OUT = output
    trace = {}
    dates = [old['comparison_date'], old['date']]
    snapshots = replay.append_financial(data, md, {'financial': {
        'reports_path': str(reports), 'comparatives_path': str(comparatives)}}, dates, evidence_trace=trace)
    base = [pd.read_parquet(p) for p in base_paths]
    panel = pd.concat([*base, snapshots], ignore_index=True).drop_duplicates(['decision_time', 'symbol'], keep='last')
    groups = {str(d): g.set_index('symbol').reindex(data['syms']) for d, g in panel.groupby('decision_time')}
    policy = read(ARCHIVE / 'strategy.locked.json')
    rows = score_snapshot_rows(replay.load_scores(panel, read(SCORE_CONTRACT), data['syms'].tolist()),
                               frozen, data, groups, policy, old['date'], dates[0], {})
    markets = {str(s): dict(close=data['close'][:, j], age=data['mark_age'][:, j],
                           events=[(d.isoformat(), f) for d, f in md.events[md.data[str(s)]['sid']]])
               for j, s in enumerate(data['syms'])}
    at = datetime.fromisoformat(old['computed_at_utc'])
    sales = sales_events(event_file)
    revisions = None
    if compare_sales_revisions:
        corrected, changes, hashes = correct_canonical_revisions(sales, [read(codal)], ROOT, at)
        _, ids = ranking_identities()
        intervals = read(ROOT / 'qvt_backtest/output/financial_history/share_intervals.json')['intervals']
        revised, _ = replay.financial_snapshots(md, read(reports), read(comparatives), corrected,
            pd.read_csv(ids[0], dtype=str), intervals, dates)
        revised_panel = pd.concat([*base, revised], ignore_index=True).drop_duplicates(['decision_time', 'symbol'], keep='last')
        revised_groups = {str(d): g.set_index('symbol').reindex(data['syms']) for d, g in revised_panel.groupby('decision_time')}
        revised_rows = score_snapshot_rows(replay.load_scores(revised_panel, read(SCORE_CONTRACT), data['syms'].tolist()),
                                           frozen, data, revised_groups, policy, old['date'], dates[0], {})
        original_rows = {r['symbol']: r for r in rows}
        revisions = dict(corrections=changes, top_five=[r['symbol'] for r in revised_rows[:5]],
            scores_changed=sum(r['score'] != original_rows[r['symbol']]['score'] for r in revised_rows),
            ranks_changed=sum(r['rank'] != original_rows[r['symbol']]['rank'] for r in revised_rows),
            ranking=revised_rows)
        files.hashes.update(hashes)
    print('Scores rebuilt; verifying source receipts', file=sys.stderr, flush=True)
    evidence = ranking_input_evidence(rows, read(market), read(codal), read(prepared), read(admission),
        {d: groups[d] for d in dates}, files=files, as_of=at, identities=identities, score_calendar=data['cal'],
        records=read(reports), events=sales.to_dict('records'),
        calendar_manifest=read(calendar) if calendar else None, market_trace=markets, financial_trace=trace)
    result = assess_ranking(old | dict(input_evidence=evidence, evidence_version=2), data['syms'],
                            policy['execution_assumptions'], at)
    previous = {r['symbol']: (r['rank'], r['score']) for r in old['rows']}
    print('Source receipts checked; verifying archived hashes again', file=sys.stderr, flush=True)
    if any(files.hashes.get(name, expected) != expected for name, expected in before.items()):
        raise RuntimeError('archived source differs from pinned input')
    verified = files.hashes | before
    if any(sha(ROOT / name) != expected for name, expected in verified.items()):
        raise RuntimeError('retained inputs changed during audit')
    metrics = dict(universe=len(rows), eligible=sum(r['rank'] is not None for r in rows),
        rank_changes=sum(r['rank'] != previous[r['symbol']][0] for r in rows),
        score_changes=sum(r['score'] != previous[r['symbol']][1] for r in rows),
        top_five=[r['symbol'] for r in rows if r['rank'] and r['rank'] <= 5],
        state=result['state'], reasons=dict(Counter(r['reason'] for r in result['reasons'])),
        sources={factor: dict(
            identity_verified=sum(e['identity_verified'] is True for e in evidence if e['factor'] == factor),
            complete=sum(e['complete'] is True for e in evidence if e['factor'] == factor),
            complete_false=sum(e['complete'] is False for e in evidence if e['factor'] == factor),
            report_references=sum(len(e['source_reports']) for e in evidence if e['factor'] == factor),
            verified_body_references=sum(bool(s['received_at']) for e in evidence if e['factor'] == factor
                                         for s in e['source_reports']),
            verified_listing_references=sum(bool(s['first_seen_at']) for e in evidence if e['factor'] == factor
                                            for s in e['source_reports']),
            historical_receipt_references=sum(s.get('historical_receipt_by_score_cutoff') is True
                                               for e in evidence if e['factor'] == factor
                                               for s in e['source_reports']))
            for factor in ('eod', 'financial', 'sales')},
        gaps=summarize_evidence(evidence))
    (output / 'audit.json').write_text(json.dumps(
        dict(summary=metrics, ranking=rows, evidence=evidence, inputs=verified, sales_revision_comparison=revisions),
        ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('archive', 'codal', 'output'):
        parser.add_argument(name, type=lambda x: Path(x).resolve())
    parser.add_argument('--calendar', type=lambda x: Path(x).resolve())
    parser.add_argument('--compare-sales-revisions', action='store_true')
    args = parser.parse_args()
    result = audit(args.archive, args.codal, args.output, args.calendar,
                   compare_sales_revisions=args.compare_sales_revisions)
    compact = result | {'gaps': {group: {k: v for k, v in detail.items() if k != 'examples'}
                                 for group, detail in result['gaps'].items()}}
    print(json.dumps(compact, ensure_ascii=False))


if __name__ == '__main__':
    main()
