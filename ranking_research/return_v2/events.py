"""Source-backed report versions and per-company event checkpoints.

Reuses the existing comparative/TTM reconstruction. Publication clocks are
explicit and independent of retrieval. Historical DST comes from zoneinfo.
"""
import copy
import datetime as dt
import json
from bisect import bisect_right
from collections import defaultdict
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .common import ROOT, read, write, table, finish, handoff
from .market import fresh, observation, traded_return
from ranking_research.strategy_search.features import HIST, causal_factors, publication_flags

TEHRAN = ZoneInfo('Asia/Tehran')


def cutoff(day):
    return dt.datetime.combine(dt.date.fromisoformat(str(day)), dt.time.max, TEHRAN).replace(fold=1).astimezone(dt.timezone.utc)


def available(pub, calendar):
    stamp = pd.Timestamp(pub)
    if stamp.tzinfo is None:
        if len(str(pub)) == 10:
            local = dt.datetime.combine(stamp.date() + dt.timedelta(days=1), dt.time(), TEHRAN)
        else:
            raise ValueError('timezone missing')
    else:
        local = stamp.to_pydatetime()
    day = local.astimezone(TEHRAN).date().isoformat()
    i = bisect_right(calendar, day) - 1
    i = max(i, 0)
    while i < len(calendar):
        if cutoff(calendar[i]) > local.astimezone(dt.timezone.utc):
            return calendar[i]
        i += 1
    return None


def independent(rep, durations, key, metric):
    if key not in rep or durations.get(key) not in (3, 6, 9, 12):
        return None
    value = rep[key].get(metric, {}).get(1)
    if value is None or not np.isfinite(float(value)):
        return None
    duration = durations[key]
    if duration == 3:
        return float(value)
    prior = ((key[0] * 12 + key[1] - 4) // 12, (key[0] * 12 + key[1] - 4) % 12 + 1)
    if durations.get(prior) != duration - 3:
        return None
    before = rep.get(prior, {}).get(metric, {}).get(1)
    return float(value - before) if before is not None and np.isfinite(float(before)) else None


def quarter_features(eng, cid, row):
    from ranking_research.v2_inputs import rtt
    from fiscal_calendar import annual_month_of
    rep = eng.report_index().get(cid, {})
    durations = {k: v for (c, k), v in eng.feature_calendar[0].items() if c == cid}
    latest = max(rep, default=None)
    if latest is None:
        return row
    prev = (latest[0] - 1, latest[1])
    annual = annual_month_of(eng.feature_calendar[1], cid)[0]
    def own(key, metric):
        return rep.get(key, {}).get(metric, {}).get(1)
    a, b = own(latest, 'total_assets'), own(prev, 'total_assets')
    mean = (float(a) + float(b)) / 2 if a is not None and b is not None and a > 0 and b > 0 else None
    op, old = independent(rep, durations, latest, 'operating_profit'), independent(rep, durations, prev, 'operating_profit')
    rev, oldrev = independent(rep, durations, latest, 'revenue'), independent(rep, durations, prev, 'revenue')
    comparable = durations.get(latest) == durations.get(prev) and durations.get(latest) in (3,6,9,12)
    row.update(average_assets=mean, quarter_operating=op, quarter_prior_operating=old,
               quarter_revenue=rev, quarter_prior_revenue=oldrev,
               s2_raw=(op - old) / mean if comparable and mean and op is not None and old is not None else None,
               s4_raw=op / rev - old / oldrev if comparable and op is not None and op > 0 and old is not None and rev and rev > 0 and oldrev and oldrev > 0 else None,
               independent_quarter_comparable=comparable,
               prior_net_profit_ttm=rtt(rep, durations, annual, prev, 'net_profit')[0],
               net_growth_verified=comparable,
               ocf_ttm=rtt(rep, durations, annual, latest, 'operating_cash_flow')[0],
               prior_operating_profit_ttm=rtt(rep, durations, annual, prev, 'operating_profit')[0],
               growth_window_valid=comparable)
    row['cash_asset_quality'] = ((row['ocf_ttm'] - row['net_profit_ttm']) / mean
                                 if mean and row['ocf_ttm'] is not None and row['net_profit_ttm'] is not None else None)
    return row


def source_inputs(panel, md):
    from ranking_research.next_stage_experiment import CorrectedSnapshots
    from ranking_research.v2_inputs import feature_row
    reg = read(HIST / 'registration.json')
    records = read(__import__('pathlib').Path(reg['inputs']) / 'input_reports.json')
    policy = read(__import__('pathlib').Path(reg['inputs']) / 'protocol.json')
    ids = {r['company_id']: {'symbol': r['symbol'], 'security_id': md.sym2sid.get(r['symbol'])} for r in records if r['symbol'] in md.data}
    intervals = read(ROOT / 'qvt_backtest/output/financial_history/share_intervals.json')['intervals']
    source = CorrectedSnapshots(records, [], ids, md, intervals)
    return source, records, policy, feature_row


def build(out, panel, md):
    source, records, policy, feature_row = source_inputs(panel, md)
    identities = dict(source.identities)
    from fiscal_calendar import parse_title, annual_month_of
    from ranking_research.company_classification import classify_template
    cal = sorted(md.cal)
    bycompany = defaultdict(list)
    rows = []
    from ranking_research.strategy_search.registry import sha_file
    for r in records:
        if r['company_id'] not in identities:
            continue
        bycompany[r['company_id']].append(r)
    # Sample frozen before calculating new returns: Kaspin and stable hash order;
    # non-Esfand, corrections and missing cash flow deliberately represented.
    categories = {'non_esfand': [], 'revision': [], 'missing_cash': [], 'other': []}
    for cid, group in sorted(bycompany.items()):
        if any(parse_title(r['title'])[1] == 12 and not ('/۱۲/' in r['title'] or '/12/' in r['title']) for r in group):
            categories['non_esfand'].append(cid)
        if len({r['period_end'] for r in group}) < len(group):
            categories['revision'].append(cid)
        if any(not any(f['metric_code'] == 'operating_cash_flow' for f in r['facts']) for r in group):
            categories['missing_cash'].append(cid)
        categories['other'].append(cid)
    import hashlib
    order = sorted(bycompany, key=lambda c: hashlib.sha256(('20261015'+c).encode()).hexdigest())
    pilot = [c for c in order if identities[c]['symbol'] == 'کاسپین']
    for category in ['non_esfand', 'revision', 'missing_cash']:
        pilot += [c for c in order if c in categories[category] and c not in pilot][:4]
    pilot += [c for c in order if c not in pilot][:20-len(pilot)]
    if not (out / 'pilot_manifest.json').exists():
        write(out / 'pilot_manifest.json', {'selection': 'source-only stratified stable SHA256 order seed20261015; no returns',
             'companies': [{'company_id': c, **identities[c], 'categories': [k for k,v in categories.items() if c in v]} for c in pilot]})
    versions = []
    for cid, group in bycompany.items():
        previous = {}
        for r in sorted(group, key=lambda r: r['published_at']):
            duration = parse_title(r['title'])[1]
            day = available(r['published_at'], cal)
            versions.append({'company_id': cid, 'security_id': source.identities[cid]['security_id'],
                'report_id': str(r['tracing_no']), 'version_id': str(r['tracing_no']) + ':' + r['sha256'],
                'period_end': r['period_end'], 'duration_months': duration, 'statement_scope': 'parent',
                'published_at': r['published_at'], 'available_at': cutoff(day).isoformat() if day else None,
                'available_date': day, 'supersedes_id': previous.get(r['period_end']), 'source_hash': r['sha256'],
                'source_manifest_hash': r.get('dynamic_manifest_sha256'), 'retrieved_at': r['observed_at'],
                'unit': 'rial / rial_per_share per fact', 'is_cumulative': True,
                'evidence_status': 'source_manifest_hash_verified_on_parse', 'title': r['title']})
            previous[r['period_end']] = str(r['tracing_no'])
    ver = pd.DataFrame(versions)
    target = out / 'pit_report_versions.parquet'
    if not target.exists():
        ver.to_parquet(target, index=False)
    shards = out / 'feature_event_checkpoints'
    shards.mkdir(exist_ok=True)
    raw_hashes = {}
    errors = []
    original_md = md
    proofs = defaultdict(list)
    for raw in panel.family_source.dropna().unique():
        proof = json.loads(raw)
        if proof.get('company_id') and proof.get('family'):
            if proof.get('path') and sha_file(proof['path']) != proof['sha256']:
                raise ValueError('historical family source changed')
            proofs[proof['company_id']].append(proof)
    for n, cid in enumerate(pilot + [c for c in order if c not in pilot]):
        path = shards / (cid + '.parquet')
        if path.exists():
            continue
        sym = identities[cid]['symbol']
        small = copy.copy(original_md)
        small.data = {sym: original_md.data[sym]}
        small.asof_factors = lambda s, T, sm=small: causal_factors(sm, s, T)
        source.market = small
        source.identities = {cid: {'symbol': sym, 'security_id': original_md.sym2sid[sym]}}
        source.reports = bycompany[cid]
        dates = sorted(set(ver.loc[ver.company_id.eq(cid), 'available_date'].dropna()))
        company_rows = []
        for day in dates:
            if day < '2019-01-01':
                continue
            try:
                eng, metrics, _ = source.snapshot(day, cutoff(day))
                metric = metrics.get(cid)
                if metric is None:
                    continue
                row = feature_row(eng, cid, metric, policy)
                selected = eng.snapshot_source_reports.get(cid, [])
                known = [r for r in bycompany[cid] if pd.Timestamp(r['published_at']) < pd.Timestamp(cutoff(day))]
                fam = [p for p in proofs[cid] if pd.Timestamp(p['published_at']) < pd.Timestamp(cutoff(day))]
                fam = max(fam, key=lambda x: x['published_at'])['family'] if fam else 'unknown'
                income = [r for r in known if any(f['statement_type'] == 'income_statement' and f['metric_code'] == 'operating_profit' for f in r['facts'])]
                last_income_pub = max((r['published_at'] for r in income), default=None)
                row.update(decision_time=day, publication_cutoff=cutoff(day).isoformat(),
                           historical_family=fam, publication_valid=bool(selected), sources=json.dumps(selected),
                           event_available_at=cutoff(day).isoformat(), latest_income_publication=last_income_pub,
                           shares_outstanding=metric.get('shares_outstanding'), share_state=json.dumps(metric.get('_valuation_prov', {})),
                           security_id=original_md.sym2sid[sym])
                quarter_features(eng, cid, row)
                row.update(fresh(small, sym, day))
                company_rows.append(row)
            except (ValueError, KeyError, FileNotFoundError) as e:
                errors.append({'company_id': cid, 'symbol': sym, 'available_date': day, 'reason': type(e).__name__ + ':' + str(e)[:180]})
        if company_rows:
            pd.DataFrame(company_rows).to_parquet(path, index=False)
        else:
            pd.DataFrame(columns=['company_id', 'decision_time']).to_parquet(path, index=False)
        raw_hashes.update(source.raw_manifest)
        if n == len(pilot) - 1:
            write(out / 'pilot_result.json', {'companies': len(pilot), 'event_rows': sum(len(pd.read_parquet(shards / (c + '.parquet'))) for c in pilot), 'errors': len(errors), 'no_pnl_used': True})
            print('B pilot complete', len(pilot), flush=True)
        if n % 10 == 0:
            print('B company checkpoints', n+1, '/', len(order), 'parsed', len(source.parsed_cache), flush=True)
    frames = [pd.read_parquet(p) for p in sorted(shards.glob('*.parquet'))]
    events = pd.concat([f for f in frames if len(f)], ignore_index=True)
    events['sources_published_before_cutoff'], events['latest_source_publication'] = publication_flags(events)
    from ranking_research.strategy_search.signals import quarterly_acceleration
    events['accel_op'] = quarterly_acceleration(events)
    events.to_parquet(out / 'pit_feature_events.parquet', index=False)
    table(errors, out / 'event_build_errors.csv')
    write(out / 'event_sources_manifest.json', raw_hashes)
    handoff(out, 'B رویدادها ساخته شد', f'{len(events)} ردیف رویداد از نسخهٔ منتشرشده؛ join و پوشش پیش از عملکرد در مرحلهٔ بعد.')
    return events, ver


def panel_asof(events, md, dates, out):
    """Per-company backward as-of join; price-only rows do not require a report."""
    from ranking_research.v2_inputs import resolve_shares
    from reconstructed_replay import interval_eligible
    intervals = defaultdict(list)
    for iv in read(ROOT / 'qvt_backtest/output/financial_history/share_intervals.json')['intervals']:
        intervals[iv['codal_symbol']].append(iv)
    sec = pd.read_parquet(out / 'db_securities.parquet')
    identities = {r.codal_symbol: r.company_id for r in sec.itertuples() if r.codal_symbol in md.data}
    defaults = {c: np.nan for c in events.columns}
    rows = []
    cal = np.asarray(sorted(md.cal))
    reaction_cache = {}
    market_cache = {}
    cached = out/'market_features_reused.parquet'
    if cached.exists():
        from ranking_research.strategy_search.features import market_fingerprint
        contract = read(out/'market_features_reuse_manifest.json')
        from ranking_research.strategy_search.registry import sha_file
        assert sha_file(cached)==contract['market_rows_sha256']
        assert market_fingerprint(md.data.keys())==contract['market_fingerprint']
        for r in pd.read_parquet(cached).to_dict('records'):
            key = (r.pop('symbol'),r.pop('decision_time'))
            market_cache[key] = r
    for sym, cid in sorted(identities.items()):
        ev = events[events.company_id.eq(cid)].sort_values('decision_time')
        edates = ev.decision_time.tolist()
        erecs = ev.to_dict('records')
        for day in dates:
            i = bisect_right(edates, day) - 1
            row = dict(erecs[i]) if i >= 0 else dict(defaults)
            # There is no proof of older sector from current classification.
            row.update(company_id=cid, symbol=sym, decision_time=day, security_id=md.sym2sid[sym])
            row.update(market_cache[(sym,day)] if (sym,day) in market_cache else fresh(md, sym, day))
            row['financial_age_days'] = (pd.Timestamp(day) - pd.Timestamp(row['financial_period_end'])).days if pd.notna(row.get('financial_period_end')) else 9999
            for c in ['source_valid', 'publication_valid', 'sources_published_before_cutoff', 'growth_window_valid', 'net_growth_verified']:
                row[c] = bool(row.get(c)) if pd.notna(row.get(c)) else False
            row['used_older_income_report'] = bool(row.get('used_older_income_report')) if pd.notna(row.get('used_older_income_report')) else True
            row['historical_family'] = row['historical_family'] if isinstance(row.get('historical_family'), str) else 'unknown'
            idx = observation(md, sym, day)
            price_day = md.data[sym]['dates'][idx] if idx is not None else None
            matches=[]
            if price_day:
                for candidate in intervals.get(sym,[]):
                    if candidate['company_id']!=cid or candidate['security_id']!=md.sym2sid[sym]:continue
                    if (interval_eligible(candidate,dt.date.fromisoformat(day),cutoff(day))[0]
                        and interval_eligible(candidate,dt.date.fromisoformat(price_day),cutoff(day))[0]
                        and candidate.get('evidence') and candidate.get('shares_outstanding',0)>0):matches.append(candidate)
            iv=matches[0] if len(matches)==1 else None
            shares = iv['shares_outstanding'] if iv else None
            # An interval is NOT trusted through a later observed adjustment
            # unless its effective start is at/after that event. No factor->shares conversion.
            if iv and any(str(iv['valid_from']) < str(d) <= day for d, _ in md.events.get(md.sym2sid[sym], [])):
                shares = None
            cap = shares * row['decision_price'] if shares and np.isfinite(row.get('decision_price', np.nan)) else None
            row.update(market_cap=cap, shares_outstanding=shares, share_state=json.dumps(iv, default=str) if iv else None,
                       operating_yield=row['operating_profit_ttm']/cap if cap and pd.notna(row.get('operating_profit_ttm')) else np.nan)
            pub = row.get('latest_income_publication')
            if isinstance(pub, str):
                key = (sym,pub)
                if key not in reaction_cache:
                    # First FULL session starts after local publication date;
                    # intersect valid actual observations once per report.
                    first = bisect_right(cal, pd.Timestamp(pub).tz_convert(TEHRAN).date().isoformat())
                    sessions = cal[first:]
                    rec = md.data[sym]
                    actual = np.asarray(rec['dates'])[(rec['vol']>0)&(rec['tval']>0)&(rec['c']>0)]
                    reaction_cache[key] = sessions, np.intersect1d(sessions,actual,assume_unique=True)
                sessions,actual = reaction_cache[key]
                eligible_sessions = sessions[:bisect_right(sessions,day)]
                full = actual[:bisect_right(actual,day)]
            else:
                eligible_sessions,full = [],[]
            row['post_report_sessions'] = len(eligible_sessions)
            row['post_report_valid_observations'] = len(full)
            row['post_report_return'] = traded_return(md, sym, eligible_sessions[0], day, day) if len(full) >= 3 and len(eligible_sessions) else np.nan
            rows.append(row)
    return pd.DataFrame(rows).sort_values(['decision_time', 'company_id']).reset_index(drop=True)
