"""Recalculate the locked FactorMix score from collected local sources only."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'strategy_registry/RFA-FactorMix-033/v1.0.0'
STATE = ROOT / '.runtime/factormix-ranking'
REPLAY = ROOT / 'ranking_research/experiments/replay_1402_to_now_20261106'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def publish(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')
    os.replace(temporary, path)


def load_replay():
    sys.path.insert(0, str(REPLAY))
    spec = importlib.util.spec_from_file_location('factormix_source_replay', REPLAY / 'full_replay.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def score_blocks(raw, close, adv, p1, calendar, weights, features):
    """The same transforms, block ordering and float32 rounding as v1 replay."""
    from ranking_research.return_v8.features import FIELDS, LOW
    columns = {}
    for j, name in enumerate(FIELDS):
        value = raw[:, :, j].copy()
        if j == 11:
            value = abs(value)
        if j in (12, 13, 14):
            value[(value <= 0) | (value > {12: 60, 13: 100, 14: 30}[j])] = np.nan
        columns[name] = features.rank_transform(value, j in LOW)
    for name, value in features.market_features(close, adv).items():
        columns[name] = features.rank_transform(value, name.startswith('vol_') or name == 'downside_vol63')
    dates = calendar.astype('datetime64[D]')
    lag = np.maximum(0, np.searchsorted(dates, dates - np.timedelta64(90, 'D'), side='right') - 1)
    derived = {'sales_accel_3v12': raw[:, :, 1] - raw[:, :, 0],
               'sales_growth_change90': raw[:, :, 1] - raw[lag, :, 1],
               'profit_growth_change90': raw[:, :, 4] - raw[lag, :, 4],
               'margin_trend_change90': raw[:, :, 8] - raw[lag, :, 8], 'p1_score': p1}
    columns.update({name: features.rank_transform(value) for name, value in derived.items()})

    def mean(names):
        return np.mean(np.stack([columns[name] for name in names], axis=2), axis=2)

    blocks = np.stack([mean(FIELDS[:5]), mean(FIELDS[5:12]), mean(['pe', 'ps', 'pb']),
                       mean(['leverage', 'current_ratio', 'cash_conversion', 'sales_stability']),
                       mean(['mom_63', 'mom_126_skip21', 'near_high_126', 'trend_50_200']),
                       mean(['vol_63', 'downside_vol63', 'reversal21']),
                       mean(list(derived)[:4]), columns['p1_score']], axis=2)
    result = (blocks @ np.asarray(weights)).astype(np.float32)
    result[~np.isfinite(p1)] = np.nan
    return result


def current_market(pack, frozen, day, module):
    """Extend frozen close history using hash-bound daily source records."""
    from score_v2_research import v2lib
    from repair_marks import last_trade_arrays
    manifest = read(pack / 'manifest.json')
    records = {str(item['symbol']): item for item in manifest['records']}
    ref = v2lib.load_reference_data()
    md = v2lib.MarketData(ref, symbols=frozen['syms'].tolist())
    raw = {}
    new_days = set()
    end = str(frozen['cal'][-1])
    for symbol in frozen['syms']:
        item = records[str(symbol)]
        if str(item['ins_code']) != str(md.data[str(symbol)]['ins']):
            raise ValueError('Market identity mismatch: ' + str(symbol))
        source = item['sources']['daily']
        body = gzip.decompress((ROOT / source['raw_path']).read_bytes())
        if hashlib.sha256(body).hexdigest() != source['raw_sha256']:
            raise ValueError('Market source checksum mismatch')
        rows = sorted((r for r in json.loads(body)['closingPriceDaily'] if str(r['dEven']) <= day.replace('-', '')), key=lambda r: r['dEven'])
        raw[str(symbol)] = rows
        for row in rows:
            date = pd.Timestamp(str(row['dEven'])).date().isoformat()
            if date > end and row.get('qTotTran5J', 0) > 0 and row.get('qTotCap', 0) > 0:
                new_days.add(date)
    # Financial data may arrive on a non-session day. This last row is a score
    # observation, with carried price marks and their real ages, not a trade bar.
    calendar = np.array(sorted(set(frozen['cal'].tolist()) | new_days | {day}))
    if day < end:
        raise ValueError('Evaluation date precedes the frozen model')
    length = len(calendar)
    close = np.zeros((length, len(frozen['syms'])))
    age = np.zeros_like(close, dtype=int)
    adv = np.zeros_like(close)
    for j, symbol in enumerate(frozen['syms']):
        symbol = str(symbol)
        rows = raw[symbol]
        rec = md.data[symbol]
        actions = ref['events'][ref['events'].security_id.eq(rec['sid'])]
        events = [(str(d), float(f)) for d, f in zip(actions.action_date, actions.factor)]
        events += [(r['date'], round(r['factor'], 8)) for r in module.raw_gaps(rows) if r['date'] > '2026-09-30']
        dates = [pd.Timestamp(str(r['dEven'])).date().isoformat() for r in rows]
        factors = np.ones(len(rows))
        for date, factor in events:
            factors[np.array(dates) < date] *= factor
        rec.update(dates=dates, dmap={d: i for i, d in enumerate(dates)},
                   c=np.array([float(r.get('pClosing') or 0) for r in rows]),
                   vol=np.array([float(r.get('qTotTran5J') or 0) for r in rows]),
                   tval=np.array([float(r.get('qTotCap') or 0) for r in rows]), cf=factors)
        md.events[rec['sid']] = [(pd.Timestamp(date).date(), factor) for date, factor in events]
        close[:, j], age[:, j] = last_trade_arrays(rows, calendar, events)
        scale = np.prod([factor for date, factor in events if date > end])
        close[:len(frozen['cal']), j] = frozen['close'][:, j] * scale
        age[:len(frozen['cal']), j] = frozen['mark_age'][:, j]
        values = pd.Series(rec['tval'] / 10, index=dates).where(lambda x: x > 0).rolling(20, min_periods=10).median().shift(1)
        adv[:, j] = values.reindex(calendar, method='ffill').fillna(0).to_numpy()
        adv[:len(frozen['cal']), j] = frozen['adv'][:, j]
    md.cal = calendar.tolist()
    return dict(cal=calendar, syms=frozen['syms'], close=close, mark_age=age, adv=adv), md


def calculate(run_dir, day):
    from factormix.build_dashboard import verify_archive
    from ranking_research.future_eval_v12_30.manual_ranking_refresh import latest_complete_market_pack, latest_codal_manifest
    verify_archive(ARCHIVE)
    policy = read(ARCHIVE / 'strategy.locked.json')
    factors = run_dir / 'factor-inputs'
    pack = latest_complete_market_pack()
    subprocess.run([sys.executable, str(ROOT / 'ranking_research/future_eval_v12_30/build_codal_factor_inputs.py'),
                    str(latest_codal_manifest()), '--evaluation-date', day, '--output-dir', str(factors),
                    '--dynamic-store-dir', str(factors / 'raw')], cwd=ROOT, check=True)
    replay = load_replay()
    replay.OUT = run_dir
    import extend_market
    frozen = dict(np.load(ARCHIVE / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    data, md = current_market(pack, frozen, day, extend_market)
    meta = {'financial': {'reports_path': str((factors / 'input_reports.json').relative_to(ROOT)),
                         'comparatives_path': str((factors / 'comparative_lineage.json').relative_to(ROOT))}}
    # Reconstruct the actual 90-day comparison cutoff using publication-eligible
    # reports. A cached quarterly row would change the acceleration definition.
    lag_day = str(data['cal'][max(0, np.searchsorted(data['cal'], str((pd.Timestamp(day) - pd.Timedelta(days=90)).date()), side='right') - 1)])
    frame = replay.append_financial(data, md, meta, sorted({day, lag_day}))
    from ranking_research.return_v8.features import FIELDS
    import features
    old_features = dict(np.load(ARCHIVE / 'snapshot_data/model_features.npz', allow_pickle=False))
    old_length = len(old_features['raw'])
    raw = np.repeat(old_features['raw'][-1:], len(data['cal']), axis=0).astype(float)
    raw[:old_length] = old_features['raw']
    p1 = np.full(data['close'].shape, np.nan)
    p1[:len(frozen['cal'])] = frozen['p1']
    tables = [pd.read_parquet(p) for p in sorted((REPLAY / 'artifacts').glob('financial_*.parquet'))]
    tables.append(frame)
    snapshots = pd.concat(tables, ignore_index=True).drop_duplicates(['decision_time', 'symbol'], keep='last')
    contract = read(ROOT / 'ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json')
    score_tables = replay.load_scores(snapshots, contract, data['syms'].tolist())
    groups = {str(date): group.set_index('symbol').reindex(data['syms']) for date, group in snapshots.groupby('decision_time')}
    dates = sorted(groups)
    for i in range(old_length, len(data['cal'])):
        date = str(data['cal'][i])
        pos = np.searchsorted(dates, date, side='right') - 1
        if pos >= 0:
            selected = dates[pos]
            raw[i] = groups[selected][FIELDS].to_numpy(float)
            if i >= len(frozen['cal']) or date in (lag_day, day):
                p1[i] = score_tables['P1'][selected]
    values = score_blocks(raw, data['close'], data['adv'], p1, data['cal'], policy['source_model']['weights'], features)
    current = groups[day]
    scores = values[-1]
    reasons = []
    for j, symbol in enumerate(data['syms']):
        reason = None
        if not np.isfinite(scores[j]) or data['close'][-1, j] <= 0:
            reason = 'پوشش دادهٔ مالی برای محاسبه کافی نیست'
        elif data['mark_age'][-1, j] > policy['execution_assumptions']['max_mark_age']:
            reason = 'قیمت موجود قدیمی است'
        elif current.financial_age_days.iloc[j] > policy['execution_assumptions']['max_financial_age']:
            reason = 'دادهٔ مالی موجود قدیمی است'
        reasons.append(reason)
    order = sorted((j for j in range(len(scores)) if reasons[j] is None), key=lambda j: (-float(scores[j]), int(frozen['symbol_index'][j])))
    ranks = {j: k for k, j in enumerate(order, 1)}
    previous = read(STATE / 'latest.json') if (STATE / 'latest.json').exists() else read(ROOT / 'client/public/strategies/factormix-033/dashboard.json')['rankings']['latest']
    prior = {r['symbol']: r for r in previous['rows']}
    rows = []
    for j in order + [j for j in range(len(scores)) if j not in ranks]:
        symbol = str(data['syms'][j])
        old = prior.get(symbol, {})
        rows.append(dict(symbol=symbol, rank=ranks.get(j), score=float(scores[j]) if np.isfinite(scores[j]) else None,
                         previous_rank=old.get('rank'), previous_score=old.get('score'), reason=reasons[j],
                         price_date=str((pd.Timestamp(day) - pd.Timedelta(days=int(data['mark_age'][-1, j]))).date())))
    result = dict(schema_version=1, strategy_id=policy['registry_id'], date=day, computed_at_utc=datetime.now(timezone.utc).isoformat(),
                  market_date=max(row['price_date'] for row in rows), universe_count=len(scores), eligible_count=len(order),
                  excluded_count=len(scores)-len(order), rows=rows, policy_sha256=sha(ARCHIVE / 'strategy.locked.json'),
                  financial_snapshot_date=day, comparison_date=lag_day, previous_date=previous.get('date'),
                  source_hashes={str(path.relative_to(ROOT)): sha(path) for path in (pack / 'manifest.json', factors / 'input_reports.json', factors / 'monthly_sales_events.parquet')})
    publish(run_dir / 'ranking.json', result)
    publish(STATE / 'latest.json', result)
    return result


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    # OS releases this lock even after interruption. The lock file is retained.
    import msvcrt
    with (STATE / 'refresh.lock').open('a+b') as lock:
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit('FactorMix refresh already running')
        try:
            now = datetime.now(timezone.utc)
            day = now.astimezone(ZoneInfo('Asia/Tehran')).date().isoformat()
            run_dir = STATE / now.strftime('%Y%m%dT%H%M%S%fZ')
            run_dir.mkdir()
            publish(STATE / 'status.json', dict(state='running', started_at_utc=now.isoformat()))
            result = calculate(run_dir, day)
            publish(STATE / 'status.json', dict(state='ready', computed_at_utc=result['computed_at_utc']))
            print(json.dumps({'date': result['date'], 'eligible_count': result['eligible_count']}), flush=True)
        except Exception as exc:
            publish(STATE / 'status.json', dict(state='failed', error=str(exc)))
            raise
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
