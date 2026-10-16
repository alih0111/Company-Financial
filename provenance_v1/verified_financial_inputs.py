"""Shared bounded financial overlay for screen and QVT; no collection or DB writes."""
import datetime as dt
import json
import math
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def eligible_cache_facts(rec, asof, cutoff):
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError('cutoff must have a timezone')
    valid = []
    for f in rec.get('facts', []):
        if not f.get('collected_at'):
            raise RuntimeError('cache lacks actual collection time')
        for key in ('published_at', 'collected_at'):
            instant = dt.datetime.fromisoformat(f[key])
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError('cache timestamp lacks timezone: ' + key)
        if (f['basis'] == 'parent' and dt.date.fromisoformat(f['period_end_date']) <= asof and
                dt.datetime.fromisoformat(f['published_at']) <= cutoff and dt.datetime.fromisoformat(f['collected_at']) <= cutoff):
            if (f['unit'] not in ('million_rial', 'rial_per_share') or
                    not math.isfinite(float(f['value'])) or
                    f['period_order'] not in (1, 2, 3) or
                    not f.get('source') or not f.get('sha256') or not f.get('tracing_no')):
                raise ValueError('eligible financial fact has invalid units/value/evidence')
            valid.append(f)
    latest = {}
    for f in valid:
        key = (dt.datetime.fromisoformat(f['published_at']), f['tracing_no'])
        latest[f['period_end_date']] = max(key, latest.get(f['period_end_date'], key))
    return [f for f in valid if (dt.datetime.fromisoformat(f['published_at']), f['tracing_no']) == latest[f['period_end_date']]]


def overlay_financial_facts(engine, asof, cutoff, facts_dir, supplement_titles):
    """Attach proven facts in memory, bounded by publication AND collection."""
    existing = {(x['company_id'], x['period_end_date'], x['metric_code']) for x in engine.stmt if x['report_id'] not in engine.superseded}
    accepted, skipped = 0, 0
    recovered_columns = []
    indexed = {}
    for row in engine.stmt:
        if row['report_id'] not in engine.superseded:
            indexed.setdefault((row['company_id'], row['period_end_date'], row['metric_code']), []).append(row)
    caches = [read(cache) for cache in sorted(Path(facts_dir).glob('*.json'))]
    caches = [rec for rec in caches if rec.get('rules_version') == 3]
    for rec in caches:
        rec['facts'] = eligible_cache_facts(rec, asof, cutoff)
    legacy_ids = getattr(engine, 'verified_legacy_report_ids', set())
    replacements = {}
    for rec in caches:
        for f in rec['facts']:
            key = (rec['company_id'], dt.date.fromisoformat(f['period_end_date']), f['metric_code'])
            rows = indexed.get(key, [])
            if f['period_order'] == 1 and rows and all(r['report_id'] in legacy_ids for r in rows):
                replacements[key] = {'company_id': rec['company_id'], 'metric': f['metric_code'],
                    'period': f['period_end_date'], 'source': f['source'], 'sha256': f['sha256'],
                    'tracing_no': f['tracing_no'], 'old_values': {str(r['period_order']): str(r['canonical_value']) for r in rows},
                    'old_report_ids': sorted({r['report_id'] for r in rows})}
    if replacements:
        engine.stmt = [r for r in engine.stmt if not (r['report_id'] in legacy_ids and
            (r['company_id'], r['period_end_date'], r['metric_code']) in replacements)]
        existing.difference_update(replacements)
        for key in replacements:
            indexed.pop(key, None)
    engine.verified_legacy_replacements = list(replacements.values())
    for rec in caches:
        cid = rec['company_id']
        for f in rec['facts']:
            if not f.get('collected_at'):
                raise RuntimeError('cache lacks actual collection time')
            period = dt.date.fromisoformat(f['period_end_date'])
            pub = dt.datetime.fromisoformat(f['published_at'])
            observed = dt.datetime.fromisoformat(f['collected_at'])
            if pub > cutoff or observed > cutoff or period > asof or f['basis'] != 'parent':
                continue
            if (cid, period, f['metric_code']) in existing:
                rows = indexed.get((cid, period, f['metric_code']), [])
                version = max((r['version_no'] for r in rows), default=1)
                current = {r['period_order']: r['canonical_value'] for r in rows if r['version_no'] == version}
                source = {g['period_order']: g['value'] * 1_000_000 for g in rec['facts']
                          if g['tracing_no'] == f['tracing_no'] and g['metric_code'] == f['metric_code']
                          and g['period_end_date'] == f['period_end_date'] and g['unit'] == 'million_rial'}
                # Only a missing annual expense leg can be completed. Both
                # observed comparative anchors must match the same verified
                # parent report exactly; existing amounts are never replaced.
                fill = (f['metric_code'] in ('finance_cost', 'other_non_operating') and f['period_order'] == 3
                        and 3 not in current and all(current.get(order) is not None and order in source and
                        math.isclose(float(current[order]), source[order], rel_tol=1e-12, abs_tol=1.0)
                        for order in (1, 2)))
                if not fill:
                    skipped += 1
                    continue
                recovered_columns.append({'company_id': cid, 'metric': f['metric_code'], 'period': str(period),
                                          'tracing_no': f['tracing_no'], 'source': f['source'], 'sha256': f['sha256']})
            else:
                version = 1
            engine.stmt.append({'company_id': cid, 'statement_type': f['statement_type'],
                'period_end_date': period, 'fiscal_year': None, 'fiscal_month': None,
                'is_restated': False, 'version_no': version, 'collected_at': observed, 'published_at': pub,
                'metric_code': f['metric_code'], 'period_order': f['period_order'],
                'canonical_value': f['value'] * (1 if f['unit'] == 'rial_per_share' else 1_000_000),
                'canonical_unit': 'rial_per_share' if f['unit'] == 'rial_per_share' else 'rial',
                'report_id': f"verified-codal-{cid}-{f['tracing_no']}"})
            indexed.setdefault((cid, period, f['metric_code']), []).append(engine.stmt[-1])
            accepted += 1
    engine.verified_recovered_columns = recovered_columns
    return accepted, skipped, supplement_titles(engine, cutoff)

