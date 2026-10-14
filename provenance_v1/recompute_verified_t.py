"""Re-evaluate T's source-proven reopening cases at an unchanged Q/V cutoff."""
import datetime as dt
import hashlib
import os
from pathlib import Path
import sys
import shutil
os.environ.setdefault('CDF_PILOT_DB', 'company_financial_analytics_shadow_v121')
from complete_ranking_coverage import ANA, OUT, read, write
sys.path.insert(0, str(ANA))
import compute_metrics as CM
import pilot_v2_t as PT
import complete_market_coverage as M
from verified_reopenings import collect_proofs, timing_with_proofs

def eligible(rows):
    return {cid for cid, r in rows.items() if r.get('pilot_eligible')}

def recompute():
    previous = read(OUT / 'result.json')
    source = Path(previous['bundle_path'])
    q = read(source / 'v2_q_observed_report.json')
    v = read(source / 'v2_value_pilot.json')
    old_t = read(source / 'v2_t_pilot.json')
    manifest = read(source / 'coverage_manifest.json')
    if (dt.datetime.fromisoformat(q['as_of']) != dt.datetime.fromisoformat(v['cutoff']) or v['as_of'] != old_t['as_of'] or
            dt.datetime.fromisoformat(manifest['cutoff']) != dt.datetime.fromisoformat(v['cutoff']) or
            v['cutoff'] != old_t['cutoff'] or
            any(manifest['files'][name] != hashlib.sha256((source / name).read_bytes()).hexdigest()
                for name in ('v2_q_observed_report.json','v2_value_pilot.json','v2_t_pilot.json'))):
        raise ValueError('source snapshot cutoff mismatch')
    asof, cutoff = dt.date.fromisoformat(v['as_of']), dt.datetime.fromisoformat(v['cutoff'])
    engine = CM.Engine(asof, cutoff)
    engine.load()
    market = M.overlay(engine)
    prior_sources = {r['company_id']: (r['payload_sha256'], r['collected_at'])
                     for r in old_t.get('market_completion', {}).get('sources', [])}
    new_sources = {r['company_id']: (r['payload_sha256'], r['collected_at']) for r in market['sources']}
    if prior_sources != new_sources:
        raise ValueError('market inputs changed since the frozen snapshot; run a full current recompute')
    primary = M.primary_securities(engine.securities)
    companies = q['companies']
    names = {r['company_id']: r['display_name'] for r in engine.companies}
    # Timing needs identity, industry, and market history; financial quantities
    # are already frozen in the immutable Q/V artifacts at this exact cutoff.
    engine.metrics = {cid: {'security_id': primary.get(cid, {}).get('security_id')} for cid in companies}
    engine.subjects = {cid: {'symbol': r['symbol'], 'display_name': names.get(cid)} for cid, r in companies.items()}
    engine.compute = lambda: engine.metrics
    proofs = collect_proofs(engine)
    with timing_with_proofs(engine, PT, proofs) as state:
        t = PT.run_t_pilot(asof, cutoff, engine=engine,
            sector_map={cid: r.get('industry') for cid, r in companies.items()},
            q_eligible=eligible(companies), v_eligible=eligible(v['v_observed_report']['companies']))
    for cid, rec in t['t_observed_report']['companies'].items():
        if rec['model_family'] != companies[cid]['model_family']:
            raise ValueError('frozen family identity changed')
        for fid, factor in rec['factors'].items():
            raw = state['raw'][cid][fid]
            factor['validation_reason'] = raw['validation_reason']
            factor['market_evidence'] = raw['market']
            if raw.get('reopening_evidence'):
                factor['reopening_evidence'] = raw['reopening_evidence']
    flat = [r for security in proofs.values() for r in security.values()]
    t['as_of_timezone'] = old_t.get('as_of_timezone', 'Asia/Tehran')
    t['market_completion'] = market
    t['aligned_window_policy'] = {'version': 'identical_observed_start_end_v1', 'factors': state['aligned_window_policy']}
    t['construction']['return_window_alignment'] = t['aligned_window_policy']
    t['verified_reopening_policy'] = {'version': 'official_reference_corroboration_v1',
        'verified_security_count': len(proofs), 'proofs': flat,
        'unproven_gaps': 'original jump guard remains active',
        'trading_risk': 'verified realized repricing remains a warning, never a risk-cleared verdict'}
    t['engine_cross_check'] = {'status': 'not_comparable_new_source', 'note': 'Only T is re-evaluated; Q/V and their exact cutoff are frozen. Exchange weighted closes and adjusted bar closes are distinct.'}
    t['construction']['price_basis'] = old_t['construction']['price_basis']
    before = eligible(companies) & eligible(v['v_observed_report']['companies']) & eligible(old_t['t_observed_report']['companies'])
    after = eligible(companies) & eligible(v['v_observed_report']['companies']) & eligible(t['t_observed_report']['companies'])
    official_q = read(ANA / 'output' / 'v2_q_observed_report.json')['companies']
    official_v = read(ANA / 'output' / 'v2_value_pilot.json')['v_observed_report']['companies']
    official_t = read(ANA / 'output' / 'v2_t_pilot.json')['t_observed_report']['companies']
    baseline = eligible(official_q) & eligible(official_v) & eligible(official_t)
    bundle = OUT / 'bundles' / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bundle.mkdir(parents=True)
    shutil.copyfile(source / 'v2_q_observed_report.json', bundle / 'v2_q_observed_report.json')
    v['q_axis_artifact']['path'] = str(bundle / 'v2_q_observed_report.json')
    write(bundle / 'v2_value_pilot.json', v)
    write(bundle / 'v2_t_pilot.json', t)
    result = {**previous, 'expanded': len(after), 'previous_bundle': str(source), 'previous_expanded': len(before),
        'bundle_path': str(bundle), 'qv_reused_at_exact_cutoff': True,
        'timing_computed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'new_since_previous': [companies[cid]['symbol'] for cid in sorted(after - before)],
        'ineligible_since_previous': [companies[cid]['symbol'] for cid in sorted(before - after)],
        'gained': [companies[cid]['symbol'] for cid in sorted(after - baseline)],
        'previously_ranked_now_ineligible': [companies[cid]['symbol'] for cid in sorted(baseline - after)],
        'verified_reopening_securities': len(proofs)}
    write(OUT / 'result.json', result)
    write(bundle / 'coverage_manifest.json', {**result, 'files': {name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        for name in ('v2_q_observed_report.json','v2_value_pilot.json','v2_t_pilot.json')}})
    print({k: result[k] for k in ('expanded','previous_expanded','verified_reopening_securities','new_since_previous','ineligible_since_previous','bundle_path')})

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    recompute()
