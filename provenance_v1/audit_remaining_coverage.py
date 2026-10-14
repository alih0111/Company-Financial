"""Produce per-symbol actionable gaps from the active bundle and actual histories."""
import datetime as dt
import os
from pathlib import Path
import sys
from collections import Counter
from complete_ranking_coverage import ANA, OUT, read, write
sys.path.insert(0, str(ANA))
os.environ.setdefault('CDF_PILOT_DB', 'company_financial_analytics_shadow_v121')
import compute_metrics as CM
import score_v2_t_raw as TR

def audit():
    os.environ.setdefault('CDF_PILOT_DB', 'company_financial_analytics_shadow_v121')
    result = read(OUT / 'result.json')
    bundle = Path(result['bundle_path'])
    q = read(bundle / 'v2_q_observed_report.json')['companies']
    v = read(bundle / 'v2_value_pilot.json')['v_observed_report']['companies']
    t_document = read(bundle / 'v2_t_pilot.json')
    t = t_document['t_observed_report']['companies']
    asof, cutoff = dt.date.fromisoformat(result['as_of']), dt.datetime.fromisoformat(result['cutoff'])
    engine = CM.Engine(asof, cutoff)
    engine.load()
    if t_document.get('market_completion'):
        from complete_market_coverage import overlay
        overlay(engine)
    primary = {}
    for s in engine.securities:
        if not s['is_active']:
            continue
        rank = (int(s['is_primary']), int(s['price_rows'] or 0), s['security_id'])
        if s['company_id'] not in primary or rank > primary[s['company_id']][0]:
            primary[s['company_id']] = (rank, s)
    histories = TR.extract_daily_history(engine.prices, asof)
    raw = TR.build_t_raw(histories, {cid: primary.get(cid, (None, {}))[1].get('security_id') for cid in q}, q, as_of=asof)
    records = []
    for cid, row in q.items():
        if row.get('pilot_eligible') and v.get(cid, {}).get('pilot_eligible') and t.get(cid, {}).get('pilot_eligible'):
            continue
        axes = {}
        for axis, rec in [('Q', row), ('V', v.get(cid, {})), ('T', t.get(cid, {}))]:
            if rec.get('pilot_eligible'):
                continue
            factors = {}
            for fid, factor in rec.get('factors', {}).items():
                if factor.get('included'):
                    continue
                evidence = raw.get(cid, {}).get(fid, {}) if axis == 'T' else factor
                if axis == 'T' and factor.get('validation_reason'):
                    evidence = {'validation_reason': factor['validation_reason'], 'warnings': factor.get('warnings', []),
                                'market': factor.get('market_evidence')}
                if factor.get('normalization_status') == 'insufficient_peers':
                    evidence = {**evidence, 'validation_reason': factor.get('not_included_reason')}
                factors[fid] = {'essential': factor.get('essential'), 'raw_status': factor.get('raw_status'),
                                'reason': evidence.get('validation_reason') or factor.get('not_included_reason'),
                                'warnings': evidence.get('warnings', []),
                                'market_evidence': evidence.get('market')}
            axes[axis] = {'family': row.get('model_family'), 'missing_essentials': rec.get('essential_status', {}).get('missing', []), 'factors': factors}
        records.append({'company_id': cid, 'symbol': row['symbol'], 'axes': axes})
    counts = Counter()
    for r in records:
        for axis, info in r['axes'].items():
            for fid, f in info['factors'].items():
                if f['essential']:
                    counts[f"{axis}:{fid}:{str(f['reason']).split(':')[0]}"] += 1
    write(OUT / 'remaining_gaps.json', {'as_of': asof, 'remaining': len(records), 'essential_reason_counts': counts, 'companies': records})
    print(dict(counts), flush=True)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    audit()
