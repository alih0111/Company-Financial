"""Source verification for the locked FactorMix inputs.

The score is publication-reconstructed. The evidence gate separately asks
whether the versions and windows used by that score were known by decision time.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from functools import cached_property
import gzip
from hashlib import file_digest, sha256
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import jdatetime

from factormix.market_source_evidence import verify_adjustments, verify_share_interval
from ranking_research.future_eval_v12_30.prepare_codal_inputs import (
    jalali_gregorian, parse_financial, parse_sales,
)


TEHRAN = ZoneInfo('Asia/Tehran')
WINDOWS = {'trend_50_200': 200, 'near_high_126': 126, 'mom_126_skip21': 127,
           'mom_63': 64, 'vol_63': 64, 'downside_vol63': 64, 'reversal21': 22}
SALE_WINDOWS = {'sales_growth_12m': 24, 'sales_growth_3m': 6, 'sales_stability': 12}
FINANCIAL_FIELDS = ('revenue_growth', 'operating_profit_growth', 'net_profit_growth',
                    'operating_margin', 'net_margin', 'roe', 'margin_trend',
                    'interest_coverage', 'cash_conversion', 'earnings_quality',
                    'pe', 'ps', 'pb', 'leverage', 'current_ratio', 'net_profit_ttm')
LETTERS = {'financial': 6, 'sales': 58}


def stamp(value):
    try:
        instant = datetime.fromisoformat(value)
        return instant.astimezone(timezone.utc) if instant.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def day(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def exchange_day(value):
    digits = str(value)
    return day(f'{digits[:4]}-{digits[4:6]}-{digits[6:]}') if len(digits) == 8 else None


def jalali_day(value):
    try:
        return jdatetime.date(*map(int, value.split('/'))).togregorian()
    except (AttributeError, TypeError, ValueError):
        return None


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def local_day(instant):
    return instant.astimezone(TEHRAN).date()


def iso(value):
    return value.isoformat() if value is not None else None


def selections(item, field):
    value = item.get(field)
    return json.loads(value) if isinstance(value, str) else []


class EvidenceError(ValueError):
    def __init__(self, code, invalid=False):
        super().__init__(code)
        self.invalid = invalid


class EvidenceFiles:
    """Validate payload hashes and retain file hashes for paper admission."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.hashes = {}

    def load(self, name, expected=None, *, payload_hash=None):
        if not name:
            raise EvidenceError('source_file_missing')
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise EvidenceError('source_path_outside_root', True)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raise EvidenceError('source_file_missing') from None
        except OSError:
            raise EvidenceError('source_file_unreadable') from None
        digest = sha256(raw).hexdigest()
        previous = self.hashes.get(path.relative_to(self.root).as_posix())
        if previous and previous != digest:
            raise EvidenceError('source_file_changed_during_verification', True)
        try:
            payload = gzip.decompress(raw) if path.suffix == '.gz' else raw
        except (OSError, EOFError):
            raise EvidenceError('source_payload_invalid', True) from None
        if ((expected and digest != expected)
                or (payload_hash is not None and sha256(payload).hexdigest() != payload_hash)):
            raise EvidenceError('source_hash_mismatch', True)
        self.hashes[path.relative_to(self.root).as_posix()] = digest
        return payload

    def pin(self, name):
        # Binary model and parquet artifacts can be large.
        path = Path(name).resolve()
        if not path.is_relative_to(self.root):
            raise EvidenceError('source_path_outside_root', True)
        with path.open('rb') as stream:
            self.hashes[path.relative_to(self.root).as_posix()] = file_digest(stream, 'sha256').hexdigest()

    def receipt(self, value, *, path='path', digest='sha256'):
        received = stamp(value.get('retrieved_at_utc'))
        if not received or not value.get(digest):
            raise EvidenceError('receipt_or_hash_missing')
        if value.get('http_status', 200) != 200:
            raise EvidenceError('source_http_status_invalid', True)
        payload = self.load(value.get(path), value.get('stored_compressed_sha256'), payload_hash=value[digest])
        return payload, received


class InputEvidence:
    def __init__(self, symbol, factor):
        self.row = dict(symbol=symbol, factor=factor, evidence_gaps=[], source_reports=[], windows={})
        self.receipts = []
        self.identities = []

    def gap(self, code, *, group='missing', invalid=False, **detail):
        gap = dict(code=code, group=group, **detail)
        if invalid:
            gap['invalid'] = True
        self.row['evidence_gaps'].append(gap)

    def receipt(self, received, scope):
        self.receipts.append((scope, received))

    def error(self, exc, **detail):
        self.gap(str(exc), group='mapping' if str(exc) in {
            'financial_model_facts_differ_from_body', 'sales_model_value_differs_from_body',
        'report_receipt_model_version_mismatch', 'daily_payload_identity_mismatch',
        'sales_model_revision_role_differs_from_body', 'canonical_source_version_hash_unproven',
        'comparative_page_model_value_mismatch', 'archived_financial_facts_differ_from_body',
        'archived_dynamic_parser_rejected'} else 'missing', invalid=exc.invalid, **detail)

    def finish(self):
        gaps = self.row['evidence_gaps']
        sources = {}
        for scope, received in self.receipts:
            if scope not in sources or received > sources[scope]:
                sources[scope] = received
        return self.row | dict(
            identity_verified=(False if False in self.identities else True
                               if self.identities and all(v is True for v in self.identities) else None),
            complete=False if any(g.get('invalid') for g in gaps) else None if gaps else True,
            received_at=iso(max(sources.values(), default=None)),
            receipt_bounds={scope: iso(received) for scope, received in sources.items()})


class CodalEvidence:
    def __init__(self, files, manifest, prepared, admission, records, events, as_of):
        self.files = files
        self.manifest = manifest.get('feeds', {})
        self.as_of = as_of
        self.prepared = {factor: {(str(r['company_id']), str(r['tracing_no'])): r
                                  for r in prepared.get(factor, [])} for factor in LETTERS}
        self.admitted = {factor: {(str(r['company_id']), str(r['tracing_no'])): r
                                  for r in admission.get(factor, {}).get('admitted_inputs', [])} for factor in LETTERS}
        self.records = {(str(r['company_id']), str(r['tracing_no'])): r for r in records}
        self.events = {(str(r['company_id']), str(r['event_id'])): r for r in events}
        self.items = {factor: {(str(r['company_id']), str(r['tracing_no'])): r
                               for r in self.manifest.get(factor, {}).get('report_ids', [])} for factor in LETTERS}
        self.errors = {(r.get('feed'), r.get('symbol'), str(r.get('tracing_no'))): r['error']
                       for r in prepared.get('errors', [])}
        self.verified = {}
        self.archived = {}

    @cached_property
    def discovery(self):
        # Rebuild the mapping from exact-symbol query, page bytes and provider
        # IDs, including legacy pages with only the URL in the receipt.
        import codal_feed

        listings, searches = defaultdict(list), defaultdict(lambda: defaultdict(list))
        for factor, letter_type in LETTERS.items():
            feed = self.manifest.get(factor, {})
            pages = {r.get('path'): r for r in feed.get('raw_pages', [])}
            archived = {r['discovery_page'].get('path'): r['discovery_page'] for r in self.items[factor].values()
                        if r.get('discovery_page')}
            for receipt in (archived | pages).values():
                url = urlsplit(receipt.get('url', ''))
                query = parse_qs(url.query)
                if (url.scheme, url.hostname, url.path) != ('https', 'search.codal.ir', '/api/search/v2/q'):
                    continue
                try:
                    symbol, start = query['symbol'][0], jalali_day(query['FromDate'][0])
                    number = int(query['PageNumber'][0])
                    if start is None or int(query['LetterType'][0]) not in (-1, letter_type) or 'ToDate' in query:
                        continue
                    payload, received = self.files.receipt(receipt)
                    doc = json.loads(payload)
                    total = doc['Total']
                    if (type(total) is not int or total < 0 or doc.get('IsAttacker') is not False
                            or str(doc.get('Page')) != str(number) or not isinstance(doc.get('Letters'), list)):
                        continue
                    reports = [codal_feed.parse_letter(item) for item in doc['Letters']]
                except (KeyError, ValueError, TypeError, IndexError):
                    continue
                page_after_publication = True
                for report in reports:
                    if report.ticker != symbol or report.letter_type != letter_type:
                        continue
                    # The generic parser defaults absent hours to 00:00.
                    published = (report.published_at.replace(tzinfo=TEHRAN).astimezone(timezone.utc)
                                 if report.published_at and re.search(r'\d{1,2}:\d{2}', report.published_at_raw.translate(
                                     codal_feed.PERSIAN_ARABIC_DIGITS)) else None)
                    listings[(factor, symbol, report.report_id)].append((published, received, report.title))
                    if published is None or published > received:
                        page_after_publication = False
                last_page = max(1, (total + codal_feed.PAGE_SIZE - 1) // codal_feed.PAGE_SIZE)
                size = min(codal_feed.PAGE_SIZE, max(0, total - (number - 1) * codal_feed.PAGE_SIZE))
                ids = {r.report_id for r in reports}
                if (receipt.get('path') in pages and page_after_publication and number <= last_page and
                        len(reports) == len(ids) == size and all(r.ticker == symbol for r in reports)):
                    searches[(factor, symbol)][(start, local_day(received), total, last_page)].append(
                        (number, received, ids))
        return listings, searches

    def search(self, proof, start, through):
        factor, symbol = proof.row['factor'], proof.row['symbol']
        matches = []
        for (left, end, total, pages), rows in self.discovery[1][factor, symbol].items():
            if start is None or left > start or end != through:
                continue
            # Multiple runs with the same URL are ambiguous unless a single
            # complete page sequence can be identified.
            if sorted(number for number, _, _ in rows) != list(range(1, pages + 1)):
                continue
            ids = set().union(*(ids for _, _, ids in rows))
            if len(ids) == total:
                matches.append((min(t for _, t, _ in rows), max(t for _, t, _ in rows), left, ids))
        if not matches:
            proof.gap('codal_search_window_unproven', required_from=iso(start), through=iso(through))
            return None
        first, last, left, ids = max(matches, key=lambda r: r[1])
        proof.row['windows']['discovery'] = dict(start=iso(left), through=iso(through), listed=len(ids),
                                                 publication_bound=iso(first))
        proof.receipt(last, 'codal_search')
        return first, ids

    def audit_unselected(self, proof, identity, snapshots, search, as_of, calendar):
        bound, ids = search
        factor, symbol = proof.row['factor'], proof.row['symbol']
        selected = {(r['score_cutoff_date'], r['source_id']) for r in proof.row['source_reports']}
        for trace in sorted(ids):
            listed = self.discovery[0][factor, symbol, trace]
            if all(p and p > as_of for p, _, _ in listed):
                continue
            item = self.items[factor].get((str(identity['company_id']), trace), {})
            try:
                period = jalali_gregorian(item.get('title') or listed[0][2])
            except (IndexError, ValueError):
                period = None
            applicable = [d for d in snapshots if (d, trace) not in selected]
            if not applicable or irrelevant_listing(proof, factor, period, listed, applicable, calendar):
                continue
            if not item:
                proof.gap('listed_report_not_mapped_to_model_inputs', group='mapping', report=trace)
                continue
            error = self.errors.get((factor, symbol, trace))
            proof.gap('potentially_effective_report_unresolved',
                      group='missing' if error or not item.get('body_evidence') else 'mapping',
                      report=trace, error=error)
        for source in proof.row['source_reports']:
            published = stamp(source['published_at'])
            if published and published > bound:
                proof.gap('selected_version_newer_than_listing_bound', report=source['source_id'])
            if published and source['source_id'] not in ids:
                proof.gap('selected_version_absent_from_complete_listing', report=source['source_id'])

    def report(self, proof, identity, selection, cutoff, calendar):
        factor, symbol = proof.row['factor'], proof.row['symbol']
        financial = factor == 'financial'
        trace = str(selection['tracing_no'] if financial else selection[2])
        cid = str(identity['company_id'])
        key = (cid, trace)
        item = self.items[factor].get(key, {})
        admitted = self.admitted[factor].get(key, {})
        value = (self.records if financial else self.events).get(key, {})
        # Canonical identifiers are namespaced. Resolve only an explicit trace
        # from the stored export and still replay the body against model values.
        provider_trace = str(value.get('source_report_id') or trace)
        if trace == 'canonical:' + provider_trace and provider_trace.isdigit():
            item = self.items[factor].get((cid, provider_trace), {})
        prepared = self.prepared[factor].get(key, {})
        published = stamp(value.get('published_at') or (selection.get('published_at') if financial else None))
        period = day(str(value.get('period_end'))[:10]) or (day(selection.get('period_end')) if financial else None)
        effect = day(selection[3]) if not financial else local_day(published) if published else None
        info = dict(source_id=trace, score_cutoff_date=cutoff, period_end=iso(period),
                    published_at=iso(published), effective_date=iso(effect),
                    first_seen_at=None, received_at=None, source_sha256=None)
        proof.row['source_reports'].append(info)
        scope = dict(report=trace, cutoff=cutoff)
        if not financial:
            if selection[1] not in ('verified_original', 'verified_correction'):
                proof.gap('monthly_revision_value_unverified', invalid=True, **scope)
            expected, calendar_at = calendar.next_observation(local_day(published)) if published else (None, None)
            if expected is None:
                proof.gap('sales_first_effective_session_unproven', **scope)
            elif effect != expected:
                proof.gap('sales_effective_session_mismatch', invalid=True, **scope)
            else:
                proof.receipt(calendar_at, 'sales_effective_session')
        if not value:
            proof.gap('selected_report_or_event_missing', **scope)
        identity_index = len(proof.identities)
        proof.identities.append(None)
        cutoff_day = day(cutoff)
        boundary = min(self.as_of, datetime.combine(cutoff_day, time.max, TEHRAN))
        if (period and period > cutoff_day) or (published and published >= boundary) or (effect and effect > cutoff_day):
            proof.gap('selected_version_after_cutoff', invalid=True, **scope)
        matches = [r for r in self.discovery[0][factor, symbol, provider_trace]
                   if r[0] and r[0] == published and r[1] >= r[0]]
        if item and matches and not any(r[2] == item.get('title') for r in matches):
            proof.gap('report_title_differs_from_listing', group='mapping', invalid=True, **scope)
            matches = []
        if not matches:
            proof.gap('publication_listing_receipt_missing', **scope)
        else:
            observed = min(r[1] for r in matches)
            info['first_seen_at'] = iso(observed)
            proof.receipt(observed, 'codal_listing')
        if not item or not item.get('body_evidence'):
            if financial and value.get('dynamic_manifest_path'):
                archived = self.archived_pages(key, value)
                if isinstance(archived, EvidenceError):
                    proof.error(archived, **scope)
                else:
                    info['archived_pages_reproduced'] = True
                    info['source_sha256'] = value['dynamic_manifest_sha256']
                    if matches:
                        proof.identities[identity_index] = True
                    if archived is None:
                        proof.gap('archived_dynamic_page_receipts_missing', **scope)
                    else:
                        proof.receipt(archived, 'archived_codal_body')
                        info['received_at'] = iso(archived)
                        info['historical_receipt_by_score_cutoff'] = archived <= boundary
                        if archived > self.as_of or published and archived < published:
                            proof.gap('archived_receipt_outside_decision_window', invalid=True, **scope)
            else:
                proof.gap('report_body_receipt_missing', **scope)
            if trace.startswith(('canonical:', 'canonical-monthly:')) or admitted and not admitted.get('source_body_sha256'):
                proof.gap('canonical_fact_to_exact_source_version_unmapped', group='mapping', **scope)
            return published, period
        if item.get('symbol') != symbol or value and str(value.get('symbol')) != symbol:
            proof.identities.append(False)
            proof.gap('report_identity_mismatch', invalid=True, **scope)
            return published, period
        if financial and item.get('financial_pages_complete') is not True:
            proof.gap('financial_statement_pages_incomplete', invalid=True, **scope)
            return published, period
        if not prepared:
            error = self.errors.get((factor, symbol, trace))
            if error:
                proof.gap('report_extraction_incomplete', invalid=True, error=error, **scope)
                return published, period
        if not value:
            return published, period
        if financial and str(value.get('title')) != str(item.get('title')):
            proof.gap('financial_model_title_differs_from_listing', group='mapping', invalid=True, **scope)
            return published, period
        cache_key = factor, *key
        if cache_key not in self.verified:
            try:
                self.verified[cache_key] = self.verify_body(factor, item, prepared, value, admitted)
            except EvidenceError as exc:
                self.verified[cache_key] = exc
        verified = self.verified[cache_key]
        if isinstance(verified, EvidenceError):
            proof.error(verified, **scope)
            return published, period
        received, payload_hash, headers, supersedes = verified
        if published and received < published:
            proof.gap('body_receipt_precedes_publication', invalid=True, **scope)
        proof.receipt(received, 'codal_body')
        info.update(received_at=iso(received), source_sha256=payload_hash,
                    statement_period_headers=headers, supersedes=supersedes)
        info['historical_receipt_by_score_cutoff'] = received <= boundary
        if matches:
            proof.identities[identity_index] = True
        if received > self.as_of:
            proof.gap('report_received_after_decision_evidence_cutoff', invalid=True, **scope)
        return published, period

    def archived_pages(self, key, record):
        if key not in self.archived:
            self.archived[key] = None
            try:
                if not record.get('dynamic_manifest_sha256'):
                    raise EvidenceError('archived_dynamic_manifest_hash_missing')
                archived = json.loads(self.files.load(record['dynamic_manifest_path'], record['dynamic_manifest_sha256']))
                pages = archived['pages']
                if not pages or any(not page.get('sha256') for page in pages):
                    raise EvidenceError('archived_dynamic_pages_missing')
                for page in pages:
                    self.files.load(page.get('path'), payload_hash=page['sha256'])
                native = archived.get('native_export')
                if native:
                    self.files.load(native['path'], payload_hash=native['sha256'])
                    original = f"qvt_backtest/output/financial_history/reports/{key[0]}_{key[1]}.json"
                    self.files.load(original, native['original_record_sha256'])
                import dynamic_financial as D
                store = self.files.root / 'qvt_backtest/output/financial_history/dynamic_sources'
                parsed = D.verified_parsed(record, store=store)
                if {fact_key(f): f['value'] for f in D.own_facts(parsed)} != {
                        fact_key(f): f['value'] for f in record['facts']}:
                    raise EvidenceError('archived_financial_facts_differ_from_body', True)
                receipts = [stamp(p.get('received_at_utc')) for p in pages + ([native] if native else [])]
                if all(receipts):
                    self.archived[key] = max(receipts)
            except (KeyError, ValueError, TypeError) as exc:
                self.archived[key] = exc if isinstance(exc, EvidenceError) else EvidenceError('archived_dynamic_parser_rejected', True)
        return self.archived[key]

    def verify_body(self, factor, item, prepared, value, admitted):
        ref = item['body_evidence']
        raw, received = self.files.receipt(ref)
        identity = {k: item[k] for k in ('company_id', 'symbol')}
        try:
            html = raw.decode('utf-8', 'strict')
            if factor == 'financial':
                from ranking_research.future_eval_v12_30.acquire_codal_incremental import financial_sheet_requirements

                _, required = financial_sheet_requirements(item, raw)
                present = [str(page['sheet_id']) for page in item.get('financial_pages', [])]
                if len(present) != len(set(present)) or set(present) != required:
                    raise EvidenceError('financial_required_sheet_receipt_missing', True)
                for page in item.get('financial_pages', []):
                    self.files.receipt(page)
                parsed = parse_financial(html, item, identity, iso(received), ref['sha256'], root=self.files.root)
                value_facts = {fact_key(f): f['value'] for f in value['facts']}
                body_facts = {fact_key(f): f['value'] for f in parsed['facts']}
                canonical = value.get('source') == 'canonical_postgres_quick_sync'
                if canonical and not value.get('source_content_sha256'):
                    raise EvidenceError('canonical_source_version_hash_unproven')
                if canonical and value['source_content_sha256'] != ref['sha256']:
                    raise EvidenceError('report_receipt_model_version_mismatch', True)
                if (value_facts != body_facts and
                        not (canonical and all(body_facts.get(k) == v for k, v in value_facts.items()))):
                    raise EvidenceError('financial_model_facts_differ_from_body', True)
            else:
                parsed = parse_sales(html, item, iso(received), ref['sha256'])
                if (parsed['sales_current_rial'] != value.get('CURRENT_PERIOD_SALES')
                        or not value.get('current_value_version_known')):
                    raise EvidenceError('sales_model_value_differs_from_body', True)
                if bool(value.get('is_correction')) != parsed['is_correction']:
                    raise EvidenceError('sales_model_revision_role_differs_from_body', True)
                if value.get('source') == 'canonical_postgres_quick_sync':
                    if not admitted.get('source_version_id') or not admitted.get('source_content_sha256'):
                        raise EvidenceError('canonical_source_version_hash_unproven')
                    if admitted['source_content_sha256'] != ref['sha256']:
                        raise EvidenceError('report_receipt_model_version_mismatch', True)
            received = stamp(parsed['received_at_utc'])
            if (not received or (prepared and (received != stamp(prepared.get('received_at_utc'))
                    or ref['sha256'] != prepared.get('source_body_sha256')))
                    or parsed['period_end'] != str(value.get('period_end'))[:10]
                    or stamp(parsed.get('published_at_utc') or parsed.get('published_at')) != stamp(value.get('published_at'))):
                raise EvidenceError('report_receipt_model_version_mismatch', True)
            supersedes = parsed.get('supersedes_tracing_no')
            if (parsed.get('is_correction') or parsed.get('title_is_correction')) and not supersedes:
                raise EvidenceError('correction_predecessor_unproven')
            return received, ref['sha256'], parsed.get('period_headers'), supersedes
        except EvidenceError:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise EvidenceError('raw_report_parser_rejected', True) from exc


def fact_key(fact):
    return (fact['statement_type'], fact['metric_code'], int(fact['period_order']),
            fact['unit'], fact.get('basis', 'parent'))


class MarketCalendar:
    def __init__(self, files, manifests):
        self.sessions, self.covered, self.invalid = [], [], None
        self.windows = []
        for manifest in manifests or ():
            self.add(files, manifest)
        self.covered = sorted({d for dates, _, _ in self.windows for d in dates})
        self.sessions = sorted({d for _, completed, _ in self.windows for d in completed})

    def add(self, files, manifest):
        try:
            if manifest.get('source') != 'TSETMC documented API MarketInfo/NSCStart':
                raise EvidenceError('market_calendar_source_unverified')
            raw, received = files.receipt(manifest, path='raw_path', digest='raw_sha256')
            doc = json.loads(raw)
            rows = doc['Data']
            dates = [exchange_day(row['DEven']) for row in rows]
            if (doc.get('IsSuccess') is not True or not dates or None in dates or
                    len(set(dates)) != len(dates)):
                raise EvidenceError('market_calendar_payload_invalid', True)
            completed = {d for d, row in zip(dates, rows, strict=True)
                         if str(row.get('NSCEnd')) == '1' and d <= local_day(received)}
            self.windows.append((set(dates), completed, received))
        except (KeyError, ValueError, TypeError) as exc:
            self.invalid = exc if isinstance(exc, EvidenceError) else EvidenceError('market_calendar_payload_invalid', True)

    def next_observation(self, start):
        options = [(d, receipt) for dates, completed, receipt in self.windows if min(dates) <= start
                   for d in completed if d > start]
        return min(options, default=(None, None))

    def next_after(self, start):
        return self.next_observation(start)[0]

    def covered_by(self, start, end):
        if not self.covered or not self.sessions or self.covered[0] > start or self.sessions[-1] < end:
            return None
        # A rolling archive must overlap on actual sessions. Taking the union
        # of disjoint snapshots could silently drop intervening sessions.
        through = start
        latest = None
        for _, completed, received in sorted(self.windows, key=lambda w: min(w[0])):
            if completed and min(completed) <= through <= max(completed):
                through = max(completed)
                latest = max(received, latest) if latest else received
                if through >= end:
                    return latest
        return None


def verify_market(proof, files, record, identity, row, score_calendar, calendar, as_of, market_trace):
    symbol = row['symbol']
    latest = day(row['price_date'])
    through = local_day(as_of)
    proof.row.update(source_id=str(record.get('ins_code', '')) or None, effective_date=iso(latest),
                     source_unit='IRR', score_price_basis='adjusted', published_at=None)
    if not record or not identity:
        proof.gap('market_identity_record_missing')
        return
    matches = all(str(record.get(k)) == str(identity[k]) for k in ('company_id', 'security_id', 'ins_code'))
    proof.identities.append(False if not matches else None)
    if not matches:
        proof.gap('market_identity_mismatch', invalid=True)
    if calendar.invalid:
        proof.error(calendar.invalid)
    model_days = [day(d) for d in score_calendar][-200:]
    calendar_at = calendar.covered_by(model_days[0], through) if len(model_days) == 200 else None
    if calendar_at is None:
        proof.gap('market_session_window_receipt_missing', required_sessions=200,
                  model_rows=len(model_days), calendar_rows=len(calendar.sessions))
    elif model_days != [d for d in calendar.sessions if model_days[0] <= d <= through] or model_days[-1] != through:
        proof.gap('model_sessions_differ_from_completed_calendar', invalid=True)
    else:
        proof.receipt(calendar_at, 'exchange_calendar')
    source = record.get('sources', {}).get('daily', {})
    try:
        payload, received = files.receipt(source, path='raw_path', digest='raw_sha256')
        proof.row.update(daily_received_at=iso(received), source_sha256=source['raw_sha256'])
        proof.receipt(received, 'daily_bar')
        if received > as_of:
            proof.gap('daily_receipt_after_decision_evidence_cutoff', invalid=True)
        if source.get('url') != f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{identity['ins_code']}/0":
            raise EvidenceError('daily_request_identity_mismatch', True)
        bars = json.loads(payload)['closingPriceDaily']
        by_day = {exchange_day(bar['dEven']): bar for bar in bars}
        if None in by_day or len(by_day) != len(bars):
            raise EvidenceError('daily_bar_date_invalid_or_duplicate', True)
        if any(str(bar.get('insCode')) != str(identity['ins_code']) for bar in bars):
            proof.identities.append(False)
            raise EvidenceError('daily_payload_identity_mismatch', True)
        if matches and bars:
            proof.identities[0] = True
        if latest is None or latest > through or latest > local_day(received):
            raise EvidenceError('daily_mark_date_invalid_or_future', True)
        if latest == local_day(received) and received.astimezone(TEHRAN).time() < time(17):
            raise EvidenceError('same_day_close_receipt_before_paper_cutoff', True)
        usable = {d for d, b in by_day.items() if d <= through and
                  all(finite(b.get(k)) and b[k] >= 0 for k in ('pClosing', 'qTotCap', 'qTotTran5J', 'zTotTran', 'priceYesterday'))}
        traded = {d for d in usable if all(by_day[d][k] > 0 for k in ('pClosing', 'qTotCap', 'zTotTran'))}
        proof.row['windows'].update({
            key: dict(required_sessions=size, rows_observed=sum(d in usable for d in model_days[-size:]))
            for key, size in WINDOWS.items()})
        proof.row['windows']['trend_50'] = dict(required_sessions=50,
                                               rows_observed=sum(d in usable for d in model_days[-50:]))
        lag = max((d for d in score_calendar if day(d) <= through - timedelta(days=90)), default=None)
        p1 = {}
        for cutoff in (day(lag), through):
            if cutoff is None:
                continue
            count = sum(d <= cutoff for d in traded)
            p1[iso(cutoff)] = dict(traded_rows=count, trade_metrics_rows=min(count, 30), dq_threshold=90)
        proof.row['windows']['p1_market'] = p1
        if max(traded, default=None) != latest:
            proof.gap('daily_rows_or_mark_missing', invalid=True)
        if not set(model_days).issubset(usable) or any(w['traded_rows'] < 90 for w in p1.values()):
            proof.gap('daily_session_rows_or_no_trade_evidence_missing', observed_sessions=len(set(model_days) & usable))
        if any(d > local_day(received) for d in by_day):
            proof.gap('daily_payload_contains_future_session', invalid=True)
        trace = market_trace.get(symbol)
        if not trace:
            proof.gap('adjusted_close_model_lineage_unmapped', group='mapping')
        else:
            # Each dependency is in session order. The first window row can
            # carry a mark from an earlier session.
            marks = sorted(traded)
            for model_day, close, age in zip(model_days, trace['close'][-200:], trace['age'][-200:], strict=True):
                i = bisect_right(marks, model_day) - 1
                if i < 0:
                    break
                mark = marks[i]
                adjusted = by_day[mark]['pClosing'] * math.prod(
                    factor for effective, factor in trace['events'] if mark < day(effective) <= through)
                if age != (model_day - mark).days or not math.isclose(close, adjusted, rel_tol=1e-7, abs_tol=1e-6):
                    proof.gap('adjusted_model_mark_does_not_replay', invalid=True)
                    break
            first_mark = max((mark for mark in marks if mark <= model_days[0]), default=model_days[0]) if model_days else None
            relevant = [(d, f) for d, f in trace['events'] if first_mark and first_mark < day(d) <= through]
            if first_mark:
                adjustment = record.get('sources', {}).get('adjustment')
                try:
                    received, verified = verify_adjustments(files, adjustment, identity['ins_code'],
                        by_day, relevant, first_mark, through, as_of)
                    proof.receipt(received, 'price_adjustment')
                    proof.row['windows']['adjustments'] = dict(source_sha256=adjustment['raw_sha256'], events=verified)
                except EvidenceError as exc:
                    proof.error(exc, events=len(relevant))
    except (KeyError, TypeError, ValueError) as exc:
        proof.error(exc if isinstance(exc, EvidenceError) else EvidenceError('daily_payload_invalid', True))


def month_keys(last, length):
    year, month = map(int, last.split('-'))
    pairs = [divmod(year * 12 + month - 1 - i, 12) for i in range(length - 1, -1, -1)]
    return [f'{year:04d}-{month + 1:02d}' for year, month in pairs]


def sales_window(proof, selected, cutoff):
    last = max((r[0] for r in selected), default=None)
    coverage = {}
    for field, length in SALE_WINDOWS.items():
        expected = month_keys(last, length) if last else []
        observed = {r[0] for r in selected if r[1] in ('verified_original', 'verified_correction')}
        missing = [month for month in expected if month not in observed]
        start = jdatetime.date(*map(int, expected[0].split('-')), 1).togregorian() if expected else None
        coverage[field] = dict(required=length, covered=length - len(missing) if last else 0,
                               missing=missing, start=iso(start))
        # A verified mathematical null (such as zero denominator) is
        # distinguishable from missing input months.
        if not expected or missing:
            proof.gap('sales_months_missing', cutoff=cutoff, field=field, months=missing)
    proof.row['windows'][cutoff] = coverage
    return day(coverage['sales_growth_12m']['start'])


def irrelevant_listing(proof, factor, period, listed, snapshots, calendar):
    if period is None or not listed or any(p is None for p, _, _ in listed):
        return False
    for published, _, _ in listed:
        for cutoff in snapshots:
            if local_day(published) > day(cutoff) or period > day(cutoff):
                continue
            relevant = [s for s in proof.row['source_reports'] if s['score_cutoff_date'] == cutoff]
            if factor == 'sales':
                effective = calendar.next_after(local_day(published))
                if effective is not None and effective > day(cutoff):
                    continue
                # A month older than the expected 24-month window cannot
                # affect sales metrics or the fallback rank.
                first = proof.row['windows'].get(cutoff, {}).get('sales_growth_12m', {}).get('start')
                if first and period < day(first):
                    continue
            if not any(s['period_end'] == iso(period) and stamp(s['published_at']) and
                       stamp(s['published_at']) > published for s in relevant):
                return False
    return True


def financial_window(proof, item, cutoff, selected, codal, identity, model_trace, market):
    from ranking_research.v2_inputs import CM, build_fiscal_calendar

    records = [codal.records.get((str(identity['company_id']), str(r['tracing_no']))) for r in selected]
    records = [r for r in records if r]
    title_rows = [(str(r['company_id']), r['title'], *CM.fiscal_ym(day(r['period_end']))) for r in records]
    durations, _ = build_fiscal_calendar(title_rows)
    covered = [field for field in FINANCIAL_FIELDS if finite(item.get(field))]
    proof.row['windows'][cutoff] = dict(periods=sorted({r['period_end'] for r in records}),
        fiscal_durations=len(durations), computed_fields=covered, required_fields=list(FINANCIAL_FIELDS))
    income = [r for r in records if any(f['statement_type'] == 'income_statement' for f in r['facts'])]
    balance = [r for r in records if any(f['statement_type'] == 'balance_sheet' for f in r['facts'])]
    newest = max((day(r['period_end']) for r in income), default=None)
    prior = CM.fiscal_ym(newest) if newest else None
    prior = (prior[0] - 1, prior[1]) if prior else None
    prior_present = prior is not None and any(CM.fiscal_ym(day(r['period_end'])) == prior for r in income)
    proof.row['windows'][cutoff].update(latest_income=iso(newest),
        prior_year_income_cell=list(prior) if prior else None, prior_year_income_present=prior_present,
        latest_balance=max((r['period_end'] for r in balance), default=None))
    if not records or not durations or not prior_present or not balance:
        proof.gap('fiscal_report_chain_missing', cutoff=cutoff, prior_income=prior_present, balance=bool(balance))
    missing = sorted(set(FINANCIAL_FIELDS) - set(covered))
    trace = model_trace.get((proof.row['symbol'], cutoff))
    if trace is None:
        proof.gap('financial_comparative_and_share_selection_unmapped', group='mapping', cutoff=cutoff)
    else:
        nulls = {field: reason for field, reason in trace.get('validated_nulls', {}).items() if field in missing}
        proof.row['windows'][cutoff]['validated_nulls'] = nulls
        unresolved = sorted(set(missing) - nulls.keys())
        if unresolved:
            proof.gap('financial_null_cause_unmapped', group='mapping', cutoff=cutoff, fields=unresolved)
        sources = {r['source_id']: r for r in proof.row['source_reports'] if r['score_cutoff_date'] == cutoff}
        grouped = defaultdict(list)
        for comp in trace['comparatives']:
            grouped[str(comp['tracing_no'])].append(comp)
        for report_id, comps in grouped.items():
            source = sources.get(report_id, {})
            if not source.get('received_at'):
                proof.gap('comparative_parent_report_unverified', cutoff=cutoff, report=report_id, facts=len(comps))
                continue
            pages = defaultdict(list)
            for comp in comps:
                pages[(comp.get('source_page_path'), comp.get('source_page_sha256'),
                       comp.get('source_page_received_at_utc'))].append(comp)
            for (path, digest, receipt), page_facts in pages.items():
                verify_comparatives(proof, codal, identity, cutoff, report_id, path, digest, receipt, page_facts)
        interval = trace.get('share_interval')
        if interval:
            source = market.get('sources', {}).get('share_change')
            try:
                received, verified = verify_share_interval(codal.files, source, identity['ins_code'], identity,
                    interval, day(trace['share_mark_date']), day(cutoff), codal.as_of)
                proof.receipt(received, 'share_interval')
                proof.row['windows'][cutoff]['share_interval'] = verified | {'source_sha256': source['raw_sha256']}
            except EvidenceError as exc:
                proof.error(exc, cutoff=cutoff)
    return min((day(r['period_end']) for r in records), default=None)


def verify_comparatives(proof, codal, identity, cutoff, report_id, path, digest, receipt, facts):
    import dynamic_financial as D

    try:
        received = stamp(receipt)
        if not received or not digest:
            raise EvidenceError('comparative_page_receipt_missing')
        payload = codal.files.load(path, payload_hash=digest)
        report = codal.records[str(identity['company_id']), report_id]
        parsed = D.parsed_page(payload.decode('utf-8'), report)
        for comp in facts:
            statement, metric, order, _, _ = fact_key(comp | {'unit': comp['canonical_unit']})
            header = parsed['period_headers'][statement][order - 1]
            value = parsed['statements'][statement][metric][order]
            period = jalali_gregorian('/'.join(map(str, header)))
            if (period != day(comp['comparative_period'])
                    or value * (1 if comp['canonical_unit'] == 'rial_per_share' else 1_000_000) != comp['canonical_value']):
                raise EvidenceError('comparative_page_model_value_mismatch', True)
        proof.receipt(received, 'comparative')
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        proof.error(exc if isinstance(exc, EvidenceError) else EvidenceError('comparative_page_mapping_unverified'),
                    cutoff=cutoff, report=report_id, facts=len(facts))


def ranking_input_evidence(rows, market_manifest, codal_manifest, prepared, admission, snapshots, *,
                           files, as_of, identities, score_calendar, records, events,
                           calendar_manifest=None, market_trace=None, financial_trace=None):
    """Validate the exact input windows used by the scorer for the full universe."""
    if as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    through = local_day(as_of)
    calendar = MarketCalendar(files, [calendar_manifest] if isinstance(calendar_manifest, dict) else calendar_manifest)
    codal = CodalEvidence(files, codal_manifest, prepared, admission, records, events, as_of)
    prices = {r['symbol']: r for r in market_manifest['records']}
    result = []
    for row in rows:
        symbol = row['symbol']
        identity = identities.get(symbol, {})
        proof = InputEvidence(symbol, 'eod')
        verify_market(proof, files, prices.get(symbol, {}), identity, row, score_calendar, calendar, as_of,
                      market_trace or {})
        result.append(proof.finish())
        for factor in LETTERS:
            proof = InputEvidence(symbol, factor)
            periods, active_dates = [], []
            for cutoff, frame in sorted(snapshots.items()):
                item = frame.loc[symbol]
                if not identity or str(item['company_id']) != str(identity['company_id']):
                    proof.identities.append(False)
                    proof.gap('snapshot_company_identity_mismatch', invalid=True, cutoff=cutoff)
                    continue
                selected = selections(item, 'sources' if factor == 'financial' else 'sales_sources')
                if not selected:
                    proof.gap('selected_report_lineage_missing', cutoff=cutoff)
                for selection in selected:
                    published, period = codal.report(proof, identity, selection, cutoff, calendar)
                    if published and cutoff == max(snapshots):
                        active_dates.append(period if factor == 'financial' else day(selection[3]))
                start = (financial_window(proof, item, cutoff, selected, codal, identity, financial_trace or {},
                                          prices.get(symbol, {}))
                         if factor == 'financial' else sales_window(proof, selected, cutoff))
                if start:
                    periods.append(start)
            search = codal.search(proof, min(periods, default=None), through)
            if search:
                proof.row['publication_bound'] = iso(search[0])
                codal.audit_unselected(proof, identity, snapshots, search, as_of, calendar)
            proof.row['effective_date'] = iso(max((d for d in active_dates if d), default=None))
            result.append(proof.finish())
    return result


def summarize_evidence(rows):
    counts = defaultdict(Counter)
    examples = {}
    affected = defaultdict(set)
    for row in rows:
        for gap in row['evidence_gaps']:
            group, code = gap['group'], gap['code']
            counts[group][code] += 1
            affected[group].add((row['symbol'], row['factor']))
            examples.setdefault(code, dict(symbol=row['symbol'], factor=row['factor'], **gap))
    return {group: dict(occurrences=sum(values.values()), affected_pairs=len(affected[group]),
                        counts=dict(values.most_common()), examples={k: examples[k] for k in values})
            for group, values in counts.items()}
