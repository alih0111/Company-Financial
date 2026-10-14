"""Compare observed returns only over identical start/end trading dates.

The largest valid date cohort is the comparison population (latest pair breaks
ties). No stale security price is carried forward or interpolated. A shared
market closure can extend the calendar window; its actual dates remain explicit.
"""
from collections import Counter
import math
import score_v2_raw as RAW

FACTORS = ('momentum_3m_rel', 'momentum_6m_rel', 'relative_strength_6m_sector')


def align_returns(raw, meta):
    policies = {}
    for fid in FACTORS:
        valid = {}
        for cid, factors in raw.items():
            rec = factors[fid]
            window = rec.get('market', {}).get('window', {})
            end = rec.get('market', {}).get('last_trade_date')
            recover_sector = (fid == 'relative_strength_6m_sector' and
                              rec.get('validation_reason', '').startswith('insufficient_sector_benchmark') and
                              factors['momentum_6m_rel']['status'] == RAW.STATUS_VALID)
            if (rec['status'] == RAW.STATUS_VALID or recover_sector) and window.get('base_date') and end:
                valid[cid] = (window['base_date'], end)
        counts = Counter(valid.values())
        common = max(counts, key=lambda pair: (counts[pair], pair)) if counts else None
        members = sorted(cid for cid, pair in valid.items() if pair == common)
        returns = {cid: raw[cid][fid]['market']['window']['stock_return'] for cid in members}
        market_mean = math.fsum(returns.values()) / len(returns) if returns else None
        sectors = {}
        for cid in members:
            industry = (meta.get(cid) or {}).get('industry')
            if industry:
                sectors.setdefault(industry, []).append(cid)
        policies[fid] = {'base_date': common[0] if common else None,
                         'end_date': common[1] if common else None,
                         'aligned_members': len(members), 'excluded_date_mismatches': len(valid) - len(members)}
        for cid, factors in raw.items():
            rec = factors[fid]
            if cid not in valid:
                continue  # Original missing/history/jump gates retain their evidence.
            rec['definition'] = 'observed adjusted return minus benchmark over identical start/end dates; nominal 3/6-month target and actual dates are separate'
            window = rec['market']['window']
            window['comparison_base_date'] = common[0]
            window['comparison_end_date'] = common[1]
            if valid[cid] != common:
                rec['status'] = RAW.STATUS_INVALID
                rec['raw_value'] = None
                rec['validation_reason'] = 'return_window_mismatch: observed start/end dates differ from the shared benchmark window; no stale-price substitution'
                window.update(benchmark=None, benchmark_n=0)
                continue
            if fid == 'relative_strength_6m_sector':
                peers = sectors.get((meta.get(cid) or {}).get('industry'), [])
                if len(peers) < 2:
                    rec['status'] = RAW.STATUS_NOT_APPLICABLE
                    rec['raw_value'] = None
                    rec['validation_reason'] = 'insufficient_sector_benchmark: fewer than two date-aligned industry returns'
                    window.update(benchmark=None, benchmark_n=len(peers))
                    continue
                benchmark = math.fsum(returns[p] for p in peers) / len(peers)
                n = len(peers)
            else:
                benchmark, n = market_mean, len(members)
            rec['raw_value'] = returns[cid] - benchmark
            rec['status'] = RAW.STATUS_VALID
            window.update(benchmark=benchmark, benchmark_n=n, actual_start_date=common[0], actual_end_date=common[1])
            rec['validation_reason'] = 'valid: observed adjusted return minus date-aligned equal-weight benchmark; actual window dates are disclosed'
            if (window['ref_date'] - window['base_date']).days > 7:
                rec['warnings'].append('shared_reference_before_calendar_window: common observed price predates the nominal calendar window; read actual start/end dates')
    return policies
