"""Read-only arithmetic, coverage and Caspian input audit of the active bundle."""
import datetime as dt
import os
os.environ.setdefault('CDF_PILOT_DB', 'company_financial_analytics_shadow_v121')
from complete_ranking_coverage import OUT, read, write, overlay_financial_facts, mark_unattributed_legacy_reports
import compute_metrics as CM
import pilot_v2_qvt as PQ
import score_v2_raw as RAW


def main(ranking_path=None):
    result = read(OUT / 'result.json')
    from pathlib import Path
    bundle = Path(result['bundle_path'])
    q = read(bundle / 'v2_q_observed_report.json')['companies']
    v = read(bundle / 'v2_value_pilot.json')['v_observed_report']['companies']
    timing_document = read(bundle / 'v2_t_pilot.json')
    t = timing_document['t_observed_report']['companies']
    ranking = read(Path(ranking_path) if ranking_path else OUT / 'ranking_final.json')
    if Path(ranking['experimental_bundle']['dir']).resolve() != bundle.resolve():
        raise RuntimeError('ranking response belongs to a different bundle')
    failures = []
    old_momentum_anchors = []
    for row in ranking['ranked']:
        cid = row['company_id']
        total = 0
        ceiling = 0
        for axis, points_key in ((q, 'q_observed_points'), (v, 'v_observed_points'), (t, 't_observed_points')):
            rec = axis[cid]
            contributions = sum(f['contribution_points'] or 0 for f in rec['factors'].values())
            weights = sum(f['weight'] for f in rec['factors'].values() if f['included'])
            if abs(contributions - rec[points_key]) > 1e-8 or abs(weights - rec['covered_weight']) > 1e-8:
                failures.append({'symbol': row['symbol'], 'issue': 'axis arithmetic'})
            if not rec['pilot_eligible']:
                failures.append({'symbol': row['symbol'], 'issue': 'ineligible axis ranked'})
            total += contributions
            ceiling += weights
        if abs(round(total, 1) - row['score']) > 1e-8 or abs(ceiling - row['practical_ceiling']) > 1e-8:
            failures.append({'symbol': row['symbol'], 'issue': 'ranking arithmetic'})
        for fid in ('momentum_3m_rel', 'momentum_6m_rel', 'relative_strength_6m_sector'):
            factor = t[cid]['factors'][fid]
            evidence = factor.get('market_evidence', {})
            window = evidence.get('window', {})
            if timing_document.get('aligned_window_policy') and factor.get('included'):
                if (window.get('base_date') != window.get('comparison_base_date') or
                        evidence.get('last_trade_date') != window.get('comparison_end_date')):
                    failures.append({'symbol': row['symbol'], 'issue': 'included return window differs from benchmark'})
            if window.get('ref_date') and window.get('base_date'):
                age = (dt.date.fromisoformat(window['ref_date']) - dt.date.fromisoformat(window['base_date'])).days
                if age > 7:
                    old_momentum_anchors.append({'symbol': row['symbol'], 'factor': fid,
                                                 'anchor_before_reference_days': age,
                                                 'reference': window['ref_date'], 'anchor': window['base_date']})

    cid = next(cid for cid, rec in q.items() if rec['symbol'] == 'کاسپین')
    asof = dt.date.fromisoformat(result['as_of'])
    cutoff = dt.datetime.fromisoformat(result['cutoff'])
    eng = CM.Engine(asof, cutoff)
    eng.load()
    eng.load = lambda: None
    mark_unattributed_legacy_reports(eng)
    overlay_financial_facts(eng, asof, cutoff)
    report_index = eng.report_index()
    eng.report_index = lambda: report_index
    metrics = eng.compute()
    bases, _ = PQ.resolve_prev_bases(eng)
    cells, census = PQ.detect_sentinel_fact_cells(eng)
    clean, quarantine = PQ.quarantine_prev_bases(eng, bases, sentinel_cells=cells, census=census)
    import expense_ttm_recovery as REC
    durations, _ = PQ.fiscal_calendar_for(eng)
    recovered, _ = REC.recover_expense_order3(eng.report_index(), durations, asof, cutoff)
    expenses, _ = PQ.resolve_expense_ttm_channels(eng, recovery=recovered or None)
    provenance, _ = PQ.build_provenance(eng)
    raw = RAW.build_q_raw({cid: metrics[cid]}, prev_bases=clean, provenance=provenance,
                          as_of=cutoff, expense_ttm=expenses)
    facts = [r for r in eng.stmt if r['company_id'] == cid]
    dates = sorted({str(r['period_end_date']) for r in facts})
    audit = {'as_of': result['as_of'], 'bundle': str(bundle), 'database_writes': 0,
             'ranked_checked': len(ranking['ranked']), 'arithmetic_failures': failures,
             'momentum_anchors_more_than_7_days_old': old_momentum_anchors,
             'coverage_impact': ranking['coverage_impact'],
             'legacy_groups_replaced': len(eng.verified_legacy_replacements),
             'recovered_expense_columns': len(eng.verified_recovered_columns),
             'caspian': {'ranking': next(r for r in ranking['ranked'] if r['company_id'] == cid),
                         'metrics': metrics[cid], 'q_raw': raw[cid],
                         'expense_channel': expenses.get(cid), 'prior_bases': clean.get(cid),
                         'financial_periods': dates, 'financial_fact_count': len(facts),
                         'latest_financial_collection': max(str(r['collected_at']) for r in facts)}}
    write(OUT / 'score_audit.json', audit)
    print('checked', len(ranking['ranked']), 'arithmetic failures', len(failures), flush=True)
    print('Caspian financial periods:', dates, flush=True)
    print('Caspian metrics:', metrics[cid], flush=True)
    print('Caspian expenses:', expenses.get(cid), flush=True)
    if failures:
        raise RuntimeError('bundle audit failed; do not publish')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ranking', help='candidate handler response to audit before publishing')
    main(parser.parse_args().ranking)
