"""Source-proven exceptions for realized repricing after a non-trading period.

Default timing guards stay intact. An exception needs official zero-turnover
records throughout the gap and agreement of the vendor adjustment ratio with
the exchange's changed reference price. A missing record or an unexplained
capital/dividend reset cannot pass. No price or calendar day is fabricated.
"""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
import complete_market_coverage as M
import score_v2_t_raw as TR


def corroborate_gap(first, last, intermediate, bar_first, bar_last):
    if not intermediate or any(float(r['qTotTran5J']) != 0 or float(r['zTotTran']) != 0
                               or float(r['qTotCap']) != 0 for r in intermediate):
        return False
    if any(float(r['qTotTran5J']) <= 0 or float(r['zTotTran']) <= 0 for r in (first, last)):
        return False
    if any(float(r[k]) <= 0 for r in (first, last) for k in ('pClosing', 'pDrCotVal')):
        return False
    if float(last['priceYesterday']) <= 0:
        return False
    factors = []
    for raw, bar in ((first, bar_first), (last, bar_last)):
        if int(raw['qTotTran5J']) != bar['volume']:
            return False
        factor = bar['close'] / float(raw['pDrCotVal'])
        if any(abs(bar[field] - float(raw[source]) * factor) > 1
               for field, source in (('high', 'priceMax'), ('low', 'priceMin'))):
            return False
        factors.append(factor)
    # This ratio also catches a capital/dividend reference reset that the
    # vendor failed to apply. Merely declaring type=3 is not sufficient.
    expected = float(last['priceYesterday']) / float(first['pClosing'])
    return math.isclose(factors[0] / factors[1], expected, rel_tol=1e-3, abs_tol=1e-6)


def collect_proofs(engine):
    primary = M.primary_securities(engine.securities)
    official, calendar = {}, set()
    for path in sorted((M.MARKET / 'closing').glob('*.json')):
        rec = M.read(path)
        s = primary.get(rec['company_id'])
        if not s or s['security_id'] != rec['security_id'] or str(s['tsetmc_ins_code']) != rec['ins_code']:
            continue
        if dt.datetime.fromisoformat(rec['collected_at']) > engine.cutoff:
            continue
        if hashlib.sha256(json.dumps(rec['rows'], sort_keys=True).encode()).hexdigest() != rec['payload_sha256']:
            raise ValueError('official reopening evidence hash mismatch')
        days = {dt.date.fromisoformat(d['date']): d['raw'] for d in rec['rows']}
        official[rec['company_id']] = (rec, days)
        calendar.update(days)
    proofs = {}
    for path in sorted(M.MARKET.glob('*.json')):
        rec = M.read(path)
        cid = rec.get('company_id')
        if cid not in official or cid not in primary:
            continue
        if dt.datetime.fromisoformat(rec['collected_at']) > engine.cutoff:
            continue
        if hashlib.sha256(json.dumps(rec['payload'], sort_keys=True, ensure_ascii=False).encode()).hexdigest() != rec['payload_sha256']:
            raise ValueError('vendor reopening evidence hash mismatch')
        source, rows = official[cid]
        bars = M.validate(rec['payload'], rec['symbol'], engine.as_of,
                          {d.isoformat(): r for d, r in rows.items()})
        bars = [b for b in bars if b['close'] >= TR.PRICE_FLOOR]
        sid = primary[cid]['security_id']
        for a, b in zip(bars, bars[1:]):
            da, db = dt.date.fromisoformat(a['date']), dt.date.fromisoformat(b['date'])
            ret = b['close'] / a['close'] - 1
            if abs(ret) <= TR.JUMP_BAND or (db - da).days < 3 or da not in rows or db not in rows:
                continue
            expected_dates = sorted(d for d in calendar if da < d < db)
            if not expected_dates or any(d not in rows for d in expected_dates):
                continue
            if not corroborate_gap(rows[da], rows[db], [rows[d] for d in expected_dates], a, b):
                continue
            proofs.setdefault(sid, {})[(da, db)] = {'company_id': cid, 'symbol': rec['symbol'],
                'from': a['date'], 'to': b['date'], 'adjusted_return': ret,
                'official_no_trade_records': len(expected_dates),
                'vendor_sha256': rec['payload_sha256'], 'official_sha256': source['payload_sha256'],
                'official_reference_ratio': float(rows[db]['priceYesterday']) / float(rows[da]['pClosing'])}
    return proofs


class ProvenChain(list):
    pass


@contextmanager
def timing_with_proofs(engine, pilot, proofs):
    """Reuse the original formulas, benchmarks, and gates in one local process.

    Each chain carries its exact security-specific witnesses. Functions are
    restored in finally; no repository core module or default guard is edited.
    """
    histories, diagnostic = pilot.build_histories(engine, engine.as_of)
    by_object = {id(rows): sid for sid, rows in histories.items()}
    original_facts, original_gaps = TR._security_facts, TR._gap_warnings
    original_build, original_histories = TR.build_t_raw, pilot.build_histories
    state = {}

    def security_facts(rows, asof):
        facts = original_facts(rows, asof)
        evidence = proofs.get(by_object.get(id(rows)), {})
        for key, chain in list(facts.chains.items()):
            annotated = ProvenChain(chain)
            annotated.evidence = evidence
            facts.chains[key] = annotated
        if 'returns' in facts.vol:
            annotated = ProvenChain(facts.vol['returns'])
            annotated.evidence = evidence
            facts.vol['returns'] = annotated
        return facts

    def gap_warnings(chains):
        filtered = {}
        for key, chain in chains.items():
            evidence = getattr(chain, 'evidence', {})
            filtered[key] = [pair for pair in chain if not (
                (pair[0], pair[1]) in evidence and pair[2] is not None and
                math.isclose(pair[2], evidence[(pair[0], pair[1])]['adjusted_return'], rel_tol=1e-12, abs_tol=1e-12))]
        return original_gaps(filtered)

    def build_raw(histories_arg, security_by_company, meta, **kwargs):
        raw = original_build(histories_arg, security_by_company, meta, **kwargs)
        from aligned_timing import align_returns
        state['aligned_window_policy'] = align_returns(raw, meta)
        for cid, factors in raw.items():
            evidence = proofs.get(security_by_company.get(cid), {})
            if not evidence:
                continue
            note = 'verified_reopening_repricing: observed non-trading interval and official price reference corroborate the adjusted jump; realized repricing remains a trading-risk warning'
            for rec in factors.values():
                rec['warnings'].append(note)
                rec['reopening_evidence'] = list(evidence.values())
        state['raw'] = raw
        return raw

    TR._security_facts, TR._gap_warnings, TR.build_t_raw = security_facts, gap_warnings, build_raw
    pilot.build_histories = lambda *args, **kwargs: (histories, diagnostic)
    try:
        yield state
    finally:
        TR._security_facts, TR._gap_warnings, TR.build_t_raw = original_facts, original_gaps, original_build
        pilot.build_histories = original_histories
