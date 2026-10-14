"""Collect verified market caches; optionally append official current closes.

Collection is read-only. --ingest-closing appends versioned source-proven
observations to the configured analytics shadow database; no history is changed.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import math
import json
import os
os.environ.setdefault('CDF_PILOT_DB', 'company_financial_analytics_shadow_v121')
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'go-app' / 'py'))
sys.path.insert(0, str(ROOT / 'canonical_postgres_v1_2_1' / 'analytics_canonical_v1'))
import brs_prices as B
import score_v2_t_raw as TR
from complete_ranking_coverage import OUT, read, write

MARKET = OUT / 'market'

def primary_securities(securities):
    primary = {}
    for s in securities:
        if not s['is_active']:
            continue
        rank = (int(s['is_primary']), int(s['price_rows'] or 0), s['security_id'])
        if s['company_id'] not in primary or rank > primary[s['company_id']][0]:
            primary[s['company_id']] = (rank, s)
    return {cid: entry[1] for cid, entry in primary.items()}

def collect_closing(delay=1.5):
    """Acquire official dated weighted closing prices and actual turnover."""
    from zoneinfo import ZoneInfo
    from compute_metrics import pg_pilot_conn
    now = dt.datetime.now(dt.timezone.utc)
    asof = now.astimezone(ZoneInfo('Asia/Tehran')).date()
    bundle = Path(read(OUT / 'result.json')['bundle_path'])
    targets = read(bundle / 'v2_q_observed_report.json')['companies']
    with pg_pilot_conn(autocommit=True) as conn:
        conn.execute('SET default_transaction_read_only=on')
        cur = conn.execute('''SELECT id::text AS security_id, company_id::text AS company_id,
           codal_symbol, tsetmc_ins_code, is_primary, is_active,
           (SELECT count(*) FROM market.price_observations p WHERE p.security_id=s.id) AS price_rows
           FROM core.securities s''')
        cols = [c.name for c in cur.description]
        primary = primary_securities([dict(zip(cols, r)) for r in cur.fetchall()])
    results = []
    for cid in sorted(targets, key=lambda x: targets[x]['symbol']):
        s = primary.get(cid)
        if not s or not str(s.get('tsetmc_ins_code') or '').isdigit():
            results.append({'symbol': targets[cid]['symbol'], 'state': 'missing_canonical_instrument_code'})
            continue
        path = MARKET / 'closing' / f'{cid}.json'
        if path.exists() and read(path).get('as_of') == asof.isoformat():
            results.append({'symbol': s['codal_symbol'], 'state': 'cached'})
            continue
        ins = str(s['tsetmc_ins_code'])
        url = f'https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins}/0'
        time.sleep(delay)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://cdn.tsetmc.com/'})
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read())
            observed = dt.datetime.now(dt.timezone.utc)
            rows = []
            for row in payload.get('closingPriceDaily', []):
                if str(row.get('insCode')) != ins:
                    raise ValueError('official source instrument identity mismatch')
                date = dt.datetime.strptime(str(row['dEven']), '%Y%m%d').date()
                if date > asof or date < TR.months_back(asof, 13):
                    continue
                # Current-day partial trading is never labeled a settled close.
                if date == asof and observed.astimezone(ZoneInfo('Asia/Tehran')).time() < dt.time(12, 35):
                    continue
                close, turnover, volume = (float(row[k]) for k in ('pClosing', 'qTotCap', 'qTotTran5J'))
                if not all(math.isfinite(v) for v in (close, turnover, volume)) or close <= 0 or turnover < 0 or volume < 0:
                    raise ValueError('invalid official closing/turnover')
                rows.append({'date': date.isoformat(), 'raw': row})
            if not rows:
                raise ValueError('official dated history unavailable')
            rows.sort(key=lambda x: x['date'])
            write(path, {'company_id': cid, 'security_id': s['security_id'], 'symbol': s['codal_symbol'],
                         'ins_code': ins, 'as_of': asof, 'collected_at': observed.isoformat(),
                         'source_url': url, 'rows': rows,
                         'payload_sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()})
            entry = {'symbol': s['codal_symbol'], 'state': 'collected', 'latest': rows[-1]['date'], 'days': len(rows)}
        except Exception as exc:
            entry = {'symbol': s['codal_symbol'], 'state': 'unavailable', 'error_type': type(exc).__name__}
            if isinstance(exc, ValueError):
                entry['reason'] = str(exc)
            if getattr(exc, 'code', None) in (403, 429):
                results.append(entry)
                write(MARKET / 'closing_status.json', {'results': results, 'paused': True})
                return
        results.append(entry)
        write(MARKET / 'closing_status.json', {'results': results})
        print(json.dumps(entry, ensure_ascii=False), flush=True)

def ingest_latest_closing():
    """Append source-proven current observations; never alter prior versions."""
    from compute_metrics import pg_pilot_conn
    from psycopg.types.json import Jsonb
    inserted = 0
    with pg_pilot_conn() as conn:
        for path in sorted((MARKET / 'closing').glob('*.json')):
            rec = read(path)
            digest = hashlib.sha256(json.dumps(rec['rows'], sort_keys=True).encode()).hexdigest()
            if digest != rec['payload_sha256']:
                raise ValueError('official closing cache hash mismatch')
            # Recheck canonical identity inside the append transaction.
            identity = conn.execute('SELECT company_id::text,tsetmc_ins_code FROM core.securities WHERE id=%s', (rec['security_id'],)).fetchone()
            if not identity or identity[0] != rec['company_id'] or str(identity[1]) != rec['ins_code']:
                raise ValueError('canonical instrument identity changed')
            day = rec['rows'][-1]
            row = day['raw']
            observation_hash = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            result = conn.execute('''INSERT INTO market.price_observations
              (security_id,trade_date,price_series,first_price_rial,open_price_rial,high_price_rial,
               low_price_rial,closing_price_rial,last_price_rial,yesterday_price_rial,
               volume,trade_value_rial,trade_count,is_adjusted,adjustment_method,provenance,
               source,source_url,collected_at,observation_hash)
              VALUES (%s,%s,'unadjusted',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,'none',%s,
                      'tsetmc_verified_daily',%s,%s,%s) ON CONFLICT DO NOTHING''',
              (rec['security_id'], day['date'], row['priceFirst'], row['priceFirst'], row['priceMax'], row['priceMin'],
               row['pClosing'], row['pDrCotVal'], row['priceYesterday'], int(row['qTotTran5J']), row['qTotCap'], int(row['zTotTran']),
               Jsonb({'collector': 'verified_current_closing_v1', 'payload_sha256': digest, 'ins_code': rec['ins_code'],
                      'cache_path': str(path), 'price_semantics': 'official weighted closing; not adjusted bar close'}),
               rec['source_url'], rec['collected_at'], observation_hash))
            inserted += result.rowcount
    write(MARKET / 'ingestion_result.json', {'inserted_observations': inserted, 'updated_or_deleted': 0,
                                           'source': 'tsetmc_verified_daily', 'price_series': 'unadjusted'})
    print(f'Appended {inserted} official closing observations; no history overwritten', flush=True)

def validate(payload, symbol, asof, official=None):
    if not isinstance(payload, dict) or B.normalize_persian(payload.get('l18')) != B.normalize_persian(symbol):
        raise ValueError('source symbol identity mismatch')
    if payload.get('type') not in (3, '3'):
        raise ValueError('source does not declare adjusted type=3')
    candles = payload.get('candle_daily_adjusted')
    if not isinstance(candles, list) or not candles:
        raise ValueError('adjusted candle history absent (subscription/access may be required)')
    reference = TR.months_back(asof, 6)
    anchor_dates = []
    for candle in candles:
        date_text, _ = B.parse_brs_date(candle.get('date'))
        close = B.to_int(candle.get('close'))
        date = dt.date.fromisoformat(date_text) if date_text else None
        if date and date <= reference and close is not None and close >= TR.PRICE_FLOOR:
            anchor_dates.append(date)
    # Keep the actual six-month base quote plus every later bar. Older OHLC
    # anomalies cannot enter any of the declared timing factor windows.
    lower_bound = max(anchor_dates) if anchor_dates else TR.months_back(asof, 13)
    lower_bound = max(lower_bound, TR.months_back(asof, 13))
    days = {}
    for candle in candles:
        date_text, _ = B.parse_brs_date(candle.get('date'))
        date = dt.date.fromisoformat(date_text) if date_text else None
        # The scoring engine needs at most 13 months. Ancient malformed bars
        # outside that declared window cannot contaminate a current reading.
        if date is None or date >= asof or date < lower_bound:
            continue
        values = {k: B.to_int(candle.get(k)) for k in ('open', 'high', 'low', 'close', 'volume')}
        if any(values[k] is None or values[k] <= 0 for k in ('high', 'low', 'close')):
            raise ValueError('invalid OHLC value')
        missing_open = values['open'] in (None, 0)
        if missing_open:
            raw = (official or {}).get(date.isoformat(), {})
            # Both feeds occasionally omit priceFirst. Close-based factors
            # may use the independently corroborated remaining inputs; the
            # missing open stays missing and is never fabricated.
            last = float(raw.get('pDrCotVal') or 0)
            ratio = values['close'] / last if last > 0 else None
            if (raw.get('priceFirst') != 0 or ratio is None or
                    abs(values['high'] - float(raw.get('priceMax') or 0) * ratio) > 1 or
                    abs(values['low'] - float(raw.get('priceMin') or 0) * ratio) > 1):
                raise ValueError('missing open lacks corroborated official close/high/low')
        elif values['open'] < 0 or not values['low'] <= values['open'] <= values['high']:
            raise ValueError('inconsistent OHLC range')
        if not values['low'] <= values['close'] <= values['high']:
            raise ValueError('inconsistent OHLC range')
        if values['volume'] is None or values['volume'] < 0:
            raise ValueError('invalid volume')
        row = {'date': date.isoformat(), **values}
        if missing_open:
            row['open_missing_confirmed'] = True
        if date in days and days[date] != row:
            raise ValueError('conflicting duplicate candle date')
        days[date] = row
    if not days:
        raise ValueError('no candles on or before snapshot')
    return sorted(days.values(), key=lambda x: x['date'])

def collect(limit=271, delay=1):
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(dt.timezone.utc)
    asof = now.astimezone(ZoneInfo('Asia/Tehran')).date()
    result = read(OUT / 'result.json')
    bundle = Path(result['bundle_path'])
    q = read(bundle / 'v2_q_observed_report.json')['companies']
    t = read(bundle / 'v2_t_pilot.json')['t_observed_report']['companies']
    targets = sorted(q.items(), key=lambda item: (bool(t.get(item[0], {}).get('pilot_eligible')), item[1].get('symbol', '')))
    results = []
    B.HTTP_TIMEOUT = 25
    for cid, row in targets[:limit]:
        symbol = row['symbol']
        path = MARKET / f'{cid}.json'
        if path.exists() and read(path).get('as_of') == asof.isoformat():
            results.append({'symbol': symbol, 'state': 'cached'})
            continue
        time.sleep(delay)
        try:
            payload = B.fetch_candlestick(symbol, 3)
            observed = dt.datetime.now(dt.timezone.utc).isoformat()
            # Keep paid source responses before parsing so a rejected payload
            # can be audited without spending another request.
            write(MARKET / 'raw' / f'{cid}.json', {'symbol': symbol, 'collected_at': observed, 'payload': payload})
            days = validate(payload, symbol, asof)
            write(path, {'company_id': cid, 'symbol': symbol, 'as_of': asof,
                         'collected_at': observed, 'source': 'brs_candlestick_type3',
                         'payload_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                         'payload': payload, 'days': days})
            entry = {'symbol': symbol, 'state': 'collected', 'days': len(days), 'latest': days[-1]['date']}
        except Exception as exc:
            # Request URLs contain credentials. Never print an exception URL.
            entry = {'symbol': symbol, 'state': 'unavailable', 'error_type': type(exc).__name__}
            if isinstance(exc, ValueError):
                entry['reason'] = str(exc)
            if getattr(exc, 'code', None) in (401, 402, 403, 429):
                entry['reason'] = f'access/rate limit HTTP {exc.code}'
                results.append(entry)
                write(MARKET / 'collection_status.json', {'as_of': asof, 'results': results, 'paused': True})
                print(json.dumps(entry, ensure_ascii=False), flush=True)
                return
        results.append(entry)
        write(MARKET / 'collection_status.json', {'as_of': asof, 'results': results})
        print(json.dumps(entry, ensure_ascii=False), flush=True)

def reparse():
    from zoneinfo import ZoneInfo
    results = []
    for path in sorted((MARKET / 'raw').glob('*.json')):
        raw = read(path)
        asof = dt.datetime.fromisoformat(raw['collected_at']).astimezone(ZoneInfo('Asia/Tehran')).date()
        cid = path.stem
        try:
            official_path = MARKET / 'closing' / f'{cid}.json'
            official = read(official_path) if official_path.exists() else None
            if official and hashlib.sha256(json.dumps(official['rows'], sort_keys=True).encode()).hexdigest() != official['payload_sha256']:
                raise ValueError('official corroboration hash mismatch')
            days = validate(raw['payload'], raw['symbol'], asof,
                            {d['date']: d['raw'] for d in official['rows']} if official else None)
            write(MARKET / f'{cid}.json', {'company_id': cid, 'symbol': raw['symbol'], 'as_of': asof,
                         'collected_at': raw['collected_at'], 'source': 'brs_candlestick_type3',
                         'payload_sha256': hashlib.sha256(json.dumps(raw['payload'], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                         'payload': raw['payload'], 'days': days})
            results.append({'symbol': raw['symbol'], 'state': 'verified', 'days': len(days)})
        except ValueError as exc:
            results.append({'symbol': raw['symbol'], 'state': 'quarantined', 'reason': str(exc)})
    write(MARKET / 'validation_audit.json', {'window_months': 13, 'results': results})
    print(f'verified {sum(r["state"] == "verified" for r in results)} / {len(results)} raw histories', flush=True)

def overlay(engine):
    """Replace entire close history per exact canonical primary identity.

    Preserve actual trade values on matching dates; adjusted OHLC*volume is
    never used to invent turnover. Every candle keeps real collection time.
    """
    primary = {}
    for s in engine.securities:
        if not s['is_active']:
            continue
        rank = (int(s['is_primary']), int(s['price_rows'] or 0), s['security_id'])
        if s['company_id'] not in primary or rank > primary[s['company_id']][0]:
            primary[s['company_id']] = (rank, s)
    existing = {}
    for row in engine.prices:
        existing.setdefault((row['security_id'], row['trade_date']), row)
    official_turnover, official_bars = {}, {}
    for path in sorted((MARKET / 'closing').glob('*.json')):
        rec = read(path)
        if dt.datetime.fromisoformat(rec['collected_at']) > engine.cutoff:
            continue
        if rec.get('company_id') not in primary or primary[rec['company_id']][1]['security_id'] != rec['security_id']:
            continue
        if hashlib.sha256(json.dumps(rec['rows'], sort_keys=True).encode()).hexdigest() != rec['payload_sha256']:
            raise ValueError('official turnover cache hash mismatch')
        official_bars[rec['company_id']] = {d['date']: d['raw'] for d in rec['rows']}
        for day in rec['rows']:
            official_turnover[(rec['security_id'], dt.date.fromisoformat(day['date']))] = (
                day['raw']['qTotCap'], dt.datetime.fromisoformat(rec['collected_at']))
    replaced, injected, accepted = set(), [], []
    for path in sorted(MARKET.glob('*.json')):
        rec = read(path)
        cid = rec.get('company_id')
        if cid not in primary:
            continue
        s = primary[cid][1]
        if B.normalize_persian(s['codal_symbol']) != B.normalize_persian(rec['symbol']):
            continue
        collected = dt.datetime.fromisoformat(rec['collected_at'])
        if collected > engine.cutoff:
            continue
        digest = hashlib.sha256(json.dumps(rec['payload'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if digest != rec['payload_sha256']:
            raise ValueError('saved market payload hash mismatch')
        days = validate(rec['payload'], rec['symbol'], engine.as_of, official_bars.get(cid))
        sid = s['security_id']
        for day in days:
            date = dt.date.fromisoformat(day['date'])
            if date < TR.months_back(engine.as_of, 13):
                continue
            old = existing.get((sid, date), {})
            turnover, turnover_collected = official_turnover.get((sid, date), (old.get('trade_value_rial'), collected))
            injected.append({**old, 'security_id': sid, 'trade_date': date,
                             'closing_price_rial': day['close'], 'volume': day['volume'],
                             'high_price_rial': day['high'], 'low_price_rial': day['low'], 'last_price_rial': day['close'],
                             'trade_value_rial': turnover,
                             'collected_at': max(collected, turnover_collected)})
        replaced.add(sid)
        accepted.append({'company_id': cid, 'symbol': rec['symbol'], 'latest': days[-1]['date'],
                         'source': rec['source'], 'collected_at': rec['collected_at'],
                         'payload_sha256': digest, 'cache_path': str(path), 'unit': 'rial'})
        accepted[-1]['missing_open_bars_not_used_in_factors'] = sum(bool(day.get('open_missing_confirmed')) for day in days)
    engine.prices = [r for r in engine.prices if r['security_id'] not in replaced] + injected
    engine.prices.sort(key=lambda r: (r['security_id'], r['trade_date'], r['collected_at']), reverse=True)
    return {'companies': len(accepted), 'rows': len(injected), 'sources': accepted,
            'turnover_policy': 'preserve observed trade value; never adjusted price times volume', 'database_writes': 0}

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=271)
    parser.add_argument('--delay', type=float, default=1)
    parser.add_argument('--reparse', action='store_true', help='validate saved responses without spending API requests')
    parser.add_argument('--closing', action='store_true', help='collect dated official weighted closes and actual turnover')
    parser.add_argument('--ingest-closing', action='store_true', help='append verified latest official closes to the shadow database')
    args = parser.parse_args()
    if args.closing:
        collect_closing(args.delay)
    elif args.ingest_closing:
        ingest_latest_closing()
    elif args.reparse:
        reparse()
    else:
        collect(args.limit, args.delay)
