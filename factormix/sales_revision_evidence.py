"""Reproduce Codal revision roles before ranking uses a canonical sales row."""
from factormix.ranking_evidence import EvidenceError, EvidenceFiles, stamp
from ranking_research.future_eval_v12_30.prepare_codal_inputs import parse_sales


def correct_canonical_revisions(events, manifests, root, cutoff):
    """Replay known exact reports. Mask unlinked revisions under the locked rule."""
    files = EvidenceFiles(root)
    receipts = {(str(r['company_id']), str(r['tracing_no'])): r
                for m in manifests for r in m.get('feeds', {}).get('sales', {}).get('report_ids', [])
                if r.get('body_evidence')}
    result = events.copy()
    changes = []
    for idx, row in events.iterrows():
        if row.get('source') != 'canonical_postgres_quick_sync':
            continue
        item = receipts.get((str(row['company_id']), str(row['event_id'])))
        if not item or item['symbol'] != row['symbol']:
            continue
        try:
            source = item['body_evidence']
            body, received = files.receipt(source)
            if received > cutoff:
                continue
            parsed = parse_sales(body.decode('utf8'), item, received.isoformat(), source['sha256'])
            if (parsed['period_end'] != str(row['period_end'])[:10] or
                    stamp(parsed['published_at_utc']) != stamp(row['published_at'].isoformat())):
                continue
        except (EvidenceError, KeyError, TypeError, ValueError, AttributeError):
            continue
        if not parsed['is_correction'] or bool(row['is_correction']):
            continue
        exact_value = parsed['sales_current_rial'] == row['CURRENT_PERIOD_SALES']
        linked = bool(parsed['supersedes_tracing_no'])
        changes.append(dict(symbol=row['symbol'], tracing_no=str(row['event_id']), same_value=bool(exact_value),
                            predecessor=parsed['supersedes_tracing_no'], received_at=received.isoformat(),
                            source_sha256=source['sha256'], masked=not linked or not exact_value))
        result.at[idx, 'is_correction'] = True
        result.at[idx, 'publication_role'] = 'correction'
        result.at[idx, 'current_period_has_correction'] = True
        result.at[idx, 'current_value_version_known'] = bool(linked and exact_value)
        result.at[idx, 'supersedes_event_id'] = parsed['supersedes_tracing_no']
    return result, changes, files.hashes
