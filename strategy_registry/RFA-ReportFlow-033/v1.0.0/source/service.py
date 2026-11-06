"""Independent paper account; durable daily receipt snapshots, never broker orders.

Called by the server after collection and each minute while enabled. A review
waits for a current, closed stock session. Historical snapshots are immutable.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from reportflow import engine
from reportflow.build_inputs import ARCHIVE, HERE, OUT, ROOT, read, sha, write

STATE = ROOT / '.runtime/reportflow'


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    write(temporary, value)
    os.replace(temporary, path)


def initialize(now=None):
    now = now or datetime.now(timezone.utc)
    account = STATE / 'account.json'
    if not account.exists():
        atomic(account, dict(strategy_id=read(HERE / 'strategy.json')['strategy_id'],
                             strategy_sha256=sha(HERE / 'strategy.json'), started_at_utc=now.isoformat(),
                             initial_toman=100_000_000, broker_execution_enabled=False))
    return read(account)


def report_fingerprint(factors, day):
    # Receipt timestamps remain in the evidence but do not create fake new reports.
    financial = sorted((str(r['company_id']), str(r['tracing_no']), r['facts']) for r in read(factors / 'input_reports.json'))
    comparative = sorted(json.dumps(c, sort_keys=True) for c in read(factors / 'comparative_lineage.json'))
    monthly = pd.read_parquet(factors / 'monthly_sales_events.parquet')
    entry = pd.to_datetime(monthly.signal_entry_date, errors='coerce')
    correction = monthly.is_correction.eq(True)
    correction_day = pd.to_datetime(monthly.published_at, utc=True).dt.tz_convert('Asia/Tehran').dt.tz_localize(None).dt.normalize() + pd.Timedelta(days=1)
    eligible = (entry.le(pd.Timestamp(day)) & monthly.current_value_version_known.eq(True)) | (correction & correction_day.le(pd.Timestamp(day)))
    monthly = monthly[eligible]
    fields = ['event_id', 'CURRENT_PERIOD_SALES', 'current_value_version_known', 'signal_entry_date']
    sales = monthly[fields].sort_values('event_id').to_json(orient='records', date_format='iso')
    return hashlib.sha256(json.dumps([financial, comparative, sales], sort_keys=True).encode()).hexdigest()


def paper_inputs(frozen, market, md, snapshots):
    """Combine immutable receipt snapshots with the current adjusted market chain."""
    from factormix.refresh_ranking import score_blocks, load_replay
    load_replay()
    import features
    actual_days = set(map(str, frozen['cal']))
    for rec in md.data.values():
        actual_days.update(str(d) for d, v, value in zip(rec['dates'], rec['vol'], rec['tval']) if v > 0 and value > 0)
    all_days = np.array(sorted(set(map(str, market['cal'])) | {s['date'] for s in snapshots}))
    positions = np.searchsorted(market['cal'], all_days, side='right') - 1
    extra_age = (all_days.astype('datetime64[D]') - market['cal'][positions].astype('datetime64[D]')).astype(int)
    market = {**market, 'cal': all_days,
              'close': market['close'][positions], 'adv': market['adv'][positions],
              'mark_age': market['mark_age'][positions] + extra_age[:, None]}
    T, S = market['close'].shape
    trading = np.array([str(d) in actual_days for d in all_days])
    old = len(frozen['cal'])
    data = {k: v for k, v in market.items()}
    raw = np.repeat(frozen['raw'][-1:], T, axis=0).copy()
    reference = np.repeat(frozen['reference_p1'][-1:], T, axis=0).copy()
    age = np.repeat(frozen['financial_age'][-1:], T, axis=0).copy()
    raw[:old] = frozen['raw']; reference[:old] = frozen['reference_p1']; age[:old] = frozen['financial_age']
    bydate = {s['date']: s for s in snapshots}
    for s in snapshots:
        if sha(STATE / 'snapshots' / (s['date'] + '.npz')) != s['packet_sha256']:
            raise RuntimeError('Previously recorded receipt snapshot changed')
    latest = None
    for i in range(old, T):
        day = str(data['cal'][i])
        if day in bydate:
            latest = bydate[day]
        if latest:
            packet = np.load(STATE / 'snapshots' / (latest['date'] + '.npz'), allow_pickle=False)
            raw[i] = packet['raw']; reference[i] = packet['reference_p1']
            age[i] = packet['financial_age'] + (pd.Timestamp(day) - pd.Timestamp(latest['date'])).days
        elif i:
            raw[i] = raw[i - 1]; reference[i] = reference[i - 1]
            age[i] = age[i - 1] + (pd.Timestamp(day) - pd.Timestamp(str(data['cal'][i - 1]))).days
    opening = np.full((T, S), np.nan)
    locked = np.zeros((T, S), dtype=bool)
    manifest = read(STATE / 'current-market-manifest.json')
    market_records = {str(r['symbol']): r for r in manifest['records']}
    for j, symbol in enumerate(data['syms']):
        sym = str(symbol); rec = md.data[sym]
        scale = data['close'][old - 1, j] / frozen['close'][-1, j] if frozen['close'][-1, j] > 0 else 1.
        opening[:old, j] = frozen['opening'][:, j] * scale
        locked[:old, j] = frozen['locked'][:, j]
        factors = np.ones(len(rec['dates']))
        for date, factor in md.events[rec['sid']]:
            factors[np.asarray(rec['dates']) < str(date)] *= factor
        # current_market verifies the daily archive body before populating md.
        item = market_records[sym]
        rows = json.loads(gzip.decompress((ROOT / item['sources']['daily']['raw_path']).read_bytes()))['closingPriceDaily']
        rows = {pd.Timestamp(str(r['dEven'])).date().isoformat(): r for r in rows}
        for i in range(old, T):
            day = str(data['cal'][i]); r = rows.get(day)
            k = rec['dmap'].get(day)
            if r and k is not None and r.get('qTotTran5J', 0) > 0 and r.get('qTotCap', 0) > 0 and r.get('priceFirst', 0) > 0:
                opening[i, j] = float(r['priceFirst']) * factors[k]
                locked[i, j] = r.get('priceMax') == r.get('priceMin')
    data.update(opening=opening, locked=locked, financial_age=age,
                symbol_index=frozen['symbol_index'], score_age=np.zeros(T, dtype=int), signal_dates=data['cal'].copy())
    policy = read(HERE / 'strategy.json')
    class SessionFeatures:
        rank_transform = staticmethod(features.rank_transform)

        @staticmethod
        def market_features(close, adv):
            # A Friday report is an information observation, not a price session.
            slots = np.flatnonzero(trading)
            lag = np.maximum(0, np.searchsorted(slots, np.arange(T), side='right') - 1)
            return {name: value[lag] for name, value in features.market_features(close[trading], adv[trading]).items()}
    data['trading_sessions'] = trading
    data['p1'] = score_blocks(raw, data['close'], data['adv'], reference, data['cal'], policy['weights'], SessionFeatures)
    return data


def cycle(now=None, *, init=False):
    now = now or datetime.now(timezone.utc)
    STATE.mkdir(parents=True, exist_ok=True)
    if init:
        initialize(now)
    if not (STATE / 'account.json').exists():
        return dict(state='DISABLED', message='حساب مستقل هنوز ایجاد نشده است.')
    account = read(STATE / 'account.json')
    if account['strategy_sha256'] != sha(HERE / 'strategy.json'):
        raise RuntimeError('Paper strategy changed: create a new version/account')
    local = now.astimezone(ZoneInfo('Asia/Tehran')); day = local.date().isoformat()
    from ranking_research.future_eval_v12_30.manual_ranking_refresh import latest_complete_market_pack, latest_codal_manifest
    pack = latest_complete_market_pack(); manifest = read(pack / 'manifest.json')
    market_day = max(manifest.get('latest_quote_dates', {}), default='')
    status = dict(strategy_id=account['strategy_id'], checked_at_utc=now.isoformat(),
                  initial_toman=account['initial_toman'], broker_execution_enabled=False,
                  started_at_utc=account['started_at_utc'], market_date=market_day)
    if local.hour < 18:
        return dict(**status, state='WAITING_END_OF_DAY',
                    message='گزارش‌ها در صف‌اند؛ بررسی خودکار پس از ساعت ۱۸ تهران انجام می‌شود.')
    if not market_day or (pd.Timestamp(day) - pd.Timestamp(market_day)).days > 10:
        return dict(**status, state='WAITING_FRESH_MARKET', message='بررسی منتظر بستهٔ کامل قیمت با عمر حداکثر ۱۰ روز است.')
    index_path = STATE / 'snapshot-index.json'
    snapshots = read(index_path) if index_path.exists() else []
    request = read(STATE / 'request.json') if (STATE / 'request.json').exists() else {}
    if snapshots and snapshots[-1]['date'] == day:
        return dict(**status, state='REVIEWED_TODAY', message='بررسی این جلسه ثبت شده؛ گزارش‌های بعدی در جلسهٔ بعد بررسی می‌شوند.')
    run_dir = STATE / 'runs' / now.strftime('%Y%m%dT%H%M%S%fZ')
    factors = run_dir / 'factor-inputs'; factors.mkdir(parents=True)
    subprocess.run([sys.executable, '-B', str(ROOT / 'ranking_research/future_eval_v12_30/build_codal_factor_inputs.py'),
                    str(latest_codal_manifest()), '--evaluation-date', day, '--output-dir', str(factors),
                    '--dynamic-store-dir', str(factors / 'raw')], cwd=ROOT, check=True)
    # Forward observation uses both publication and actual local receipt.
    reports = read(factors / 'input_reports.json')
    reports = [r for r in reports if all(pd.Timestamp(r[k]) <= pd.Timestamp(now)
               for k in ['published_at', 'observed_at', 'recovered_at', 'balance_enriched_at'] if r.get(k))]
    write(factors / 'input_reports.json', reports)
    allowed = {(str(r['company_id']), str(r['tracing_no'])) for r in reports}
    comparisons = [c for c in read(factors / 'comparative_lineage.json')
                   if (str(c['company_id']), str(c['tracing_no'])) in allowed
                   and (not c.get('available_at_utc') or pd.Timestamp(c['available_at_utc']) <= pd.Timestamp(now))]
    write(factors / 'comparative_lineage.json', comparisons)
    fingerprint = report_fingerprint(factors, day)
    from factormix.refresh_ranking import load_replay, current_market
    replay = load_replay()
    import extend_market
    frozen = dict(np.load(OUT / 'event_inputs.npz', allow_pickle=False))
    market, md = current_market(pack, frozen, day, extend_market)
    atomic(STATE / 'current-market-manifest.json', manifest)
    replay.OUT = run_dir
    meta = dict(financial=dict(reports_path=str((factors / 'input_reports.json').relative_to(ROOT)),
                               comparatives_path=str((factors / 'comparative_lineage.json').relative_to(ROOT))))
    frame = replay.append_financial(market, md, meta, [day]).set_index('symbol').reindex(frozen['syms'])
    from ranking_research.return_v8.features import FIELDS
    contract = read(ROOT / 'ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json')
    scores = replay.load_scores(frame.reset_index(), contract, frozen['syms'].tolist())['P1'][day]
    snapshot_dir = STATE / 'snapshots'; snapshot_dir.mkdir(exist_ok=True)
    packet_path = snapshot_dir / (day + '.npz')
    # A retry after interruption reuses the original receipt packet.
    record_path = packet_path.with_suffix('.json')
    if packet_path.exists() and record_path.exists():
        record = read(record_path)
        if sha(packet_path) != record['packet_sha256']:
            raise RuntimeError('Receipt packet changed')
    else:
        temporary = packet_path.with_suffix('.tmp')
        with temporary.open('wb') as handle:
            np.savez_compressed(handle, raw=frame[FIELDS].to_numpy(float), reference_p1=scores,
                                financial_age=frame.financial_age_days.to_numpy(float))
        os.replace(temporary, packet_path)
        record = dict(date=day, received_snapshot_at_utc=now.isoformat(), fingerprint=fingerprint,
                      review=not snapshots or fingerprint != snapshots[-1]['fingerprint'], request=request,
                      packet_sha256=sha(packet_path), input_reports_sha256=sha(factors / 'input_reports.json'))
        atomic(record_path, record)
    snapshots.append(record)
    data = paper_inputs(frozen, market, md, snapshots)
    policy = read(HERE / 'strategy.json')
    review_dates = [s['date'] for s in snapshots if s['review']]
    run = engine.simulate(data, engine.Config(**policy['portfolio']), engine.Execution(**policy['execution']),
                          start=pd.Timestamp(account['started_at_utc']).tz_convert('Asia/Tehran').date().isoformat(),
                          end=day, detail=True, review_dates=review_dates)
    engine.save_run(STATE / 'paper', run)
    result = dict(**status, state='READY', message='حساب کاغذی مستقل با گزارش‌های دریافت‌شده بررسی شد.',
                  final_toman=float(run['nav'][-1]), cash_toman=float(run['cash'][-1]),
                  holdings=run['terminal_positions'], trades=run['trades'], decisions=run['decisions'],
                  reviews=run['reviews'], last_review_date=review_dates[-1], packet_sha256=record['packet_sha256'])
    atomic(STATE / 'portfolio.json', result)
    atomic(index_path, snapshots)
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--init', action='store_true')
    args = parser.parse_args(); STATE.mkdir(parents=True, exist_ok=True)
    import msvcrt
    with (STATE / 'service.lock').open('a+b') as handle:
        handle.seek(0)
        if not handle.read(1): handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        try:
            result = cycle(init=args.init)
            atomic(STATE / 'status.json', result)
            print(json.dumps({k: result[k] for k in ['state', 'message'] if k in result}, ensure_ascii=True))
        except Exception as exc:
            atomic(STATE / 'status.json', dict(state='FAILED', message='بررسی خودکار ناموفق بود؛ حساب قبلی حفظ شده است.', error=str(exc)))
            raise
        finally:
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
