"""Controlled current before/after data comparison, fixed clock and source hashes.

Retains old research; within-report comparatives never rewrite an older period.
No official scores, model weights, orders or financial DB rows are published.
"""
import copy
import datetime as dt
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v2_live_preview as LIVE
from v2_inputs import H, CM, ArchiveSnapshots
from fiscal_calendar import parse_title


def comparative_facts(record, parsed, annual_periods):
    """Evidence-backed columns of THIS report, not restated historical own facts."""
    current = dt.date.fromisoformat(record['period_end'])
    own_key = CM.fiscal_ym(current)
    result = []
    for statement, bucket in parsed.get('statements', {}).items():
        if statement == 'balance_sheet': continue
        headers = parsed.get('period_headers', {}).get(statement, [])
        if not headers or H.F.jalali_to_gregorian(*headers[0]) != current: continue
        for metric, values in bucket.items():
            for order in (2, 3):
                value = values.get(order)
                if value is None or not math.isfinite(value) or len(headers) < order: continue
                prior = H.F.jalali_to_gregorian(*headers[order - 1])
                if order == 2:
                    if CM.fiscal_ym(prior) != (own_key[0] - 1, own_key[1]) or abs(headers[0][2] - headers[1][2]) > 1: continue
                else:
                    if prior not in annual_periods or not H.F.jalali_to_gregorian(*headers[1]) < prior < current: continue
                result.append({'statement_type': statement, 'metric_code': metric, 'period_order': order,
                    'canonical_value': value * (1 if metric in H.P.PER_SHARE else 1e6),
                    'canonical_unit': 'rial_per_share' if metric in H.P.PER_SHARE else 'rial',
                    'comparative_period': str(prior)})
    return result


def merged_reports(original, collected):
    index = {(r['company_id'], r['tracing_no']): r for r in original}
    added = []
    for record in collected:
        key = record['company_id'], record['tracing_no']
        old = index.get(key)
        if old:
            if any(old[k] != record[k] for k in ('period_end', 'published_at', 'title')):
                raise ValueError('report_identity_conflict')
            existing = {(f['statement_type'], f['metric_code']): f['value'] for f in old['facts']}
            new = {(f['statement_type'], f['metric_code']): f['value'] for f in record['facts']}
            if any(k in new and new[k] != v for k, v in existing.items()):
                raise ValueError('same_report_fact_conflict')
            # Never replace a complete dynamic archive with a partial native export.
            if set(new) <= set(existing): continue
            if not set(existing) <= set(new):
                raise ValueError('same_report_partial_sources_require_explicit_union_proof')
        index[key] = record; added.append(key)
    return list(index.values()), added


def main():
    triage = Path(H.C.read(HERE / 'output/data_triage_latest.json')['run_path'])
    collection = Path(H.C.read(HERE / 'output/data_collection_latest.json')['run_path'])
    records = [H.C.read(path) for path in sorted((collection / 'reports').glob('*.json'))]
    original = H.C.read(triage / 'input_reports.json')
    merged, added = merged_reports(original, records)
    cutoff = dt.datetime.now(dt.timezone.utc)
    out = HERE / 'output' / ('data_repair_' + cutoff.strftime('%Y%m%dT%H%M%S%fZ')); out.mkdir()
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cutoff.astimezone(tz) if tz else cutoff.replace(tzinfo=None)
    original_clock = LIVE.dt
    LIVE.dt = SimpleNamespace(datetime=Clock, date=dt.date, timezone=dt.timezone, time=dt.time)
    original_read = H.C.read
    original_compute = CM.Engine.compute
    comparative_receipts = []
    captures = []
    receipt = {'run_path': str(out), 'triage_path': str(triage), 'collection_path': str(collection),
        'cutoff': cutoff.isoformat(), 'new_or_extended_report_versions': len(added),
        'production_changed': False, 'weights_changed': False, 'real_orders': 0,
        'growth_volume_unit_coverage': 'unproven; nominal-growth model retained as development only'}
    H.C.write(out / 'registration.json', receipt)
    try:
        for variant, report_data in [('corrected_code', original), ('recovered_reports', merged), ('comparative_history', merged)]:
            directory = out / variant; directory.mkdir()
            for name in ('protocol.json', 'input_monthly.json', 'input_family.json'):
                shutil.copyfile(triage / name, directory / name)
            H.C.write(directory / 'input_reports.json', report_data)
            H.C.read = lambda path, directory=directory: {'run_path': str(directory)} if Path(path) == HERE / 'output/formula_v2_running.json' else original_read(path)
            if variant == 'comparative_history':
                selected = H.select_asof(report_data, cutoff)
                selected_index = {(r['company_id'], str(r['tracing_no'])): r for r in selected}
                adapter = ArchiveSnapshots([], [], {}, SimpleNamespace(data={}), [])
                def compute_with_comparatives(engine):
                    by_report = {}
                    for st in engine.stmt: by_report.setdefault((st['company_id'], str(st['report_id'])), []).append(st)
                    annual = {}
                    for title in engine.codal_titles:
                        if parse_title(title['title'])[1] == 12:
                            annual.setdefault(title['company_id'], set()).add(title['period_end_date'])
                    latest = {}
                    for st in engine.stmt:
                        latest[st['company_id']] = max(latest.get(st['company_id'], st['period_end_date']), st['period_end_date'])
                    for key, statements in by_report.items():
                        record = selected_index.get(key)
                        if record is None or not record['facts']: continue
                        if (latest[key[0]] - dt.date.fromisoformat(record['period_end'])).days > 1000: continue
                        # Actual source observation must precede the shared live cutoff.
                        observed = dt.datetime.fromisoformat(record.get('balance_enriched_at') or record.get('recovered_at') or record['observed_at'])
                        if observed > cutoff: continue
                        parsed = adapter.parsed(record)
                        proposed = comparative_facts(record, parsed, annual.get(key[0], set()))
                        existing = {(s['statement_type'], s['metric_code'], s['period_order']): s['canonical_value'] for s in statements}
                        for fact in proposed:
                            identity = fact['statement_type'], fact['metric_code'], fact['period_order']
                            if identity in existing:
                                if not math.isclose(float(existing[identity]), fact['canonical_value'], rel_tol=1e-12, abs_tol=1):
                                    raise ValueError('same_report_comparative_conflict')
                                continue
                            engine.stmt.append({**statements[0], **{k: v for k, v in fact.items() if k != 'comparative_period'}})
                            comparative_receipts.append({'company_id': key[0], 'tracing_no': key[1],
                                'period': record['period_end'], **fact, 'observed_at': observed.isoformat()})
                    return original_compute(engine)
                CM.Engine.compute = compute_with_comparatives
            else: CM.Engine.compute = original_compute
            LIVE.main()
            market = H.C.read(directory / 'current_market_snapshot.json')
            market.pop('cutoff', None)
            captures.append(hashlib.sha256(json.dumps(market, sort_keys=True).encode()).hexdigest())
    finally:
        LIVE.dt = original_clock; H.C.read = original_read; CM.Engine.compute = original_compute
    if len(set(captures)) != 1: raise ValueError('market_or_share_inputs_changed_between_comparisons')
    before = pd.read_csv(triage / 'current_live_preview.csv')
    variants = {name: pd.read_csv(out / name / 'current_live_preview.csv') for name in
                ('corrected_code', 'recovered_reports', 'comparative_history')}
    receipt.update(original_eligible=int(before.eligible.sum()),
        eligible_by_stage={k: int(v.eligible.sum()) for k, v in variants.items()},
        added_comparative_columns=len(comparative_receipts), market_share_parity='passed',
        market_share_hash=captures[0], scope='Current diagnostic only; no improvement in return or model promotion claimed')
    H.C.write(out / 'comparative_lineage.json', comparative_receipts)
    H.C.write(out / 'receipt.json', receipt)
    H.C.write(HERE / 'output/data_repair_latest.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8'); main()
