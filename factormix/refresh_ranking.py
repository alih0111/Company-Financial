"""Recalculate the locked FactorMix score from collected local sources only."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from factormix.decision_readiness import assess_ranking
from factormix.ranking_evidence import EvidenceFiles, ranking_input_evidence, summarize_evidence

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'strategy_registry/RFA-FactorMix-033/v1.0.0'
STATE = ROOT / '.runtime/factormix-ranking'
MONTHLY_MARKET = ROOT / '.runtime/factormix-monthly-paper/market'
MONTHLY_CODAL = MONTHLY_MARKET.parent / 'codal'
LEGACY_MARKET = ROOT / 'ranking_research/output/paper_cycle/market'
REPLAY = ROOT / 'ranking_research/experiments/replay_1402_to_now_20261106'
SCORE_CONTRACT = ROOT / 'ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json'
FROZEN_SALES = ROOT / 'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def market_manifests():
    manifests = [*MONTHLY_MARKET.glob('*/manifest.json'), *LEGACY_MARKET.glob('*/manifest.json')]
    return sorted(manifests, key=lambda path: path.stat().st_mtime, reverse=True)


def latest_market_pack():
    for path in market_manifests():
        info = read(path)
        if info['completed_count'] == 254 and info['failed_count'] == 0:
            return path.parent
    raise RuntimeError('Complete price package for FactorMix is missing')


def latest_factor_codal_manifest():
    from ranking_research.future_eval_v12_30.manual_ranking_refresh import latest_codal_manifest

    prepared = [p for p in MONTHLY_CODAL.glob('paper-cycle-*/manifest.json')
                if (p.parent / 'prepared/prepared-inputs.json').is_file()]
    return max(prepared, key=lambda path: path.stat().st_mtime) if prepared else latest_codal_manifest()


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
        cutoff = day.replace('-', '')
        rows = sorted((r for r in json.loads(body)['closingPriceDaily'] if str(r['dEven']) <= cutoff),
                      key=lambda r: r['dEven'])
        dates = [f'{value[:4]}-{value[4:6]}-{value[6:8]}' for value in (str(r['dEven']) for r in rows)]
        raw[str(symbol)] = rows, dates
        new_days.update(d for r, d in zip(rows, dates) if d > end and tradable_open(r))
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
        rows, dates = raw.pop(symbol)
        rec = md.data[symbol]
        actions = ref['events'][ref['events'].security_id.eq(rec['sid'])]
        events = [(str(d), float(f)) for d, f in zip(actions.action_date, actions.factor)]
        events += [(r['date'], round(r['factor'], 8)) for r in module.raw_gaps(rows) if r['date'] > '2026-09-30']
        factors = np.ones(len(rows))
        for date, factor in events:
            factors[np.array(dates) < date] *= factor
        rec.update(dates=dates, dmap={d: i for i, d in enumerate(dates)},
                   c=np.array([float(r.get('pClosing') or 0) for r in rows]),
                   o=np.array([float(r['priceFirst']) if tradable_open(r) else np.nan for r in rows]),
                   locked=np.array([r.get('priceMax') == r.get('priceMin') for r in rows]),
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


def tradable_open(row):
    return all((row.get(field) or 0) > 0 for field in ('priceFirst', 'qTotTran5J', 'qTotCap'))


def market_inputs(pack, day):
    replay = load_replay()
    import extend_market
    with np.load(ARCHIVE / 'snapshot_data/active_inputs.npz', allow_pickle=False) as archive:
        frozen = dict(archive)
    data, md = current_market(pack, frozen, day, extend_market)
    return replay, frozen, data, md


def rank_rows(symbols, scores, close, mark_age, financial_age, tie_break, execution, day, prior):
    reasons = []
    for score, price, mark, financial in zip(scores, close, mark_age, financial_age, strict=True):
        reason = None
        if not np.isfinite(score) or not np.isfinite(price) or price <= 0:
            reason = 'پوشش دادهٔ مالی برای محاسبه کافی نیست'
        elif not 0 <= mark <= execution['max_mark_age']:
            reason = 'قیمت موجود قدیمی است'
        elif not 0 <= financial <= execution['max_financial_age']:
            reason = 'دادهٔ مالی موجود قدیمی است'
        reasons.append(reason)
    order = sorted((j for j in range(len(scores)) if reasons[j] is None),
                   key=lambda j: (-float(scores[j]), int(tie_break[j])))
    ranks = {j: k for k, j in enumerate(order, 1)}
    rows = []
    for j in order + [j for j in range(len(scores)) if j not in ranks]:
        symbol = str(symbols[j])
        old = prior.get(symbol, {})
        rows.append(dict(symbol=symbol, rank=ranks.get(j), score=float(scores[j]) if np.isfinite(scores[j]) else None,
                         previous_rank=old.get('rank'), previous_score=old.get('score'), reason=reasons[j],
                         price_date=str((pd.Timestamp(day) - pd.Timedelta(days=int(mark_age[j]))).date())))
    return rows


def ranking_identities():
    universe_path = ROOT / 'ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv'
    securities_path = ROOT / 'score_v2_research/_cache/securities.parquet'
    universe = pd.read_csv(universe_path, dtype=str)[['symbol', 'company_id']]
    securities = pd.read_parquet(securities_path)[['symbol', 'security_id', 'ins_code']]
    identities = universe.merge(securities, on='symbol', how='left', validate='one_to_one')
    return identities.set_index('symbol').to_dict('index'), (universe_path, securities_path)


def score_snapshot_rows(score_tables, frozen, data, groups, policy, day, lag_day, prior):
    from ranking_research.return_v8.features import FIELDS
    import features

    old_features = dict(np.load(ARCHIVE / 'snapshot_data/model_features.npz', allow_pickle=False))
    old_length = len(old_features['raw'])
    raw = np.repeat(old_features['raw'][-1:], len(data['cal']), axis=0).astype(float)
    raw[:old_length] = old_features['raw']
    p1 = np.full(data['close'].shape, np.nan)
    p1[:len(frozen['cal'])] = frozen['p1']
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
    return rank_rows(data['syms'], values[-1], data['close'][-1], data['mark_age'][-1],
                     groups[day].financial_age_days, frozen['symbol_index'], policy['execution_assumptions'], day, prior)


def sales_events(events_path):
    return pd.concat([pd.read_parquet(FROZEN_SALES), pd.read_parquet(events_path)],
                     ignore_index=True).drop_duplicates('event_id', keep='last')


def captured_calendars(explicit):
    paths = sorted((ROOT / 'ranking_research/output/paper_v12_38_first_fill/session_calendar').glob('NSCStart.*.manifest.json'))
    explicit = explicit or os.environ.get('TSETMC_CALENDAR_MANIFEST')
    if explicit:
        paths.append(Path(explicit).resolve())
    return list(dict.fromkeys(paths))


def calculate(run_dir, day, *, pack=None, market=None, codal_manifest=None, calendar_manifest=None,
              isolated=False):
    from factormix.build_dashboard import verify_archive
    verify_archive(ARCHIVE)
    policy = read(ARCHIVE / 'strategy.locked.json')
    factors = run_dir / 'factor-inputs'
    pack = pack or latest_market_pack()
    codal_manifest = codal_manifest or latest_factor_codal_manifest()
    calendar_paths = captured_calendars(calendar_manifest) if not isolated else ([Path(calendar_manifest)] if calendar_manifest else [])
    calendar_args = [part for path in calendar_paths for part in ('--sales-timing-calendar-manifest', str(path))]
    subprocess.run([sys.executable, str(ROOT / 'ranking_research/future_eval_v12_30/build_codal_factor_inputs.py'),
                    str(codal_manifest), '--evaluation-date', day, '--output-dir', str(factors),
                    '--dynamic-store-dir', str(factors / 'raw'), *calendar_args,
                    *(['--file-only'] if isolated else [])], cwd=ROOT, check=True)
    replay, frozen, data, md = market or market_inputs(pack, day)
    market_trace = {str(symbol): dict(close=data['close'][:, j], age=data['mark_age'][:, j],
                                     events=[(iso.isoformat(), factor) for iso, factor in md.events[md.data[str(symbol)]['sid']]])
                    for j, symbol in enumerate(data['syms'])}
    financial_trace = {}
    replay.OUT = run_dir
    meta = {'financial': {'reports_path': str((factors / 'input_reports.json').relative_to(ROOT)),
                         'comparatives_path': str((factors / 'comparative_lineage.json').relative_to(ROOT))}}
    # Reconstruct the actual 90-day comparison cutoff using publication-eligible
    # reports. A cached quarterly row would change the acceleration definition.
    lag_day = str(data['cal'][max(0, np.searchsorted(data['cal'], str((pd.Timestamp(day) - pd.Timedelta(days=90)).date()), side='right') - 1)])
    frame = replay.append_financial(data, md, meta, sorted({day, lag_day}), evidence_trace=financial_trace)
    base_paths = sorted((REPLAY / 'artifacts').glob('financial_*.parquet'))
    tables = [pd.read_parquet(p) for p in base_paths]
    tables.append(frame)
    snapshots = pd.concat(tables, ignore_index=True).drop_duplicates(['decision_time', 'symbol'], keep='last')
    score_tables = replay.load_scores(snapshots, read(SCORE_CONTRACT), data['syms'].tolist())
    groups = {str(date): group.set_index('symbol').reindex(data['syms']) for date, group in snapshots.groupby('decision_time')}
    previous = read(STATE / 'latest.json') if (STATE / 'latest.json').exists() else read(ROOT / 'client/public/strategies/factormix-033/dashboard.json')['rankings']['latest']
    prior = {r['symbol']: r for r in previous['rows']}
    rows = score_snapshot_rows(score_tables, frozen, data, groups, policy, day, lag_day, prior)
    eligible = sum(row['rank'] is not None for row in rows)
    prepared = codal_manifest.parent / 'prepared/prepared-inputs.json'
    admission = factors / 'admission.json'
    files = EvidenceFiles(ROOT)
    identities, identity_paths = ranking_identities()
    market_path = pack / 'manifest.json'
    reports_path = factors / 'input_reports.json'
    events_path = factors / 'monthly_sales_events.parquet'
    for path in (market_path, codal_manifest, prepared, admission, reports_path, events_path,
                 factors / 'comparative_lineage.json', SCORE_CONTRACT, FROZEN_SALES,
                 ROOT / 'qvt_backtest/output/financial_history/share_intervals.json',
                 ROOT / 'score_v2_research/_cache/corp_actions_confirmed.parquet',
                 ROOT / 'score_v2_research/_cache/calendar.parquet',
                 ARCHIVE / 'snapshot_data/active_inputs.npz', ARCHIVE / 'snapshot_data/model_features.npz',
                 *identity_paths, *base_paths, *(run_dir / f'financial_{d}.parquet' for d in {lag_day, day}),
                 *calendar_paths):
        if path.is_file():
            files.pin(path)
    as_of = datetime.now(timezone.utc)
    input_evidence = ranking_input_evidence(rows, read(market_path), read(codal_manifest),
        read(prepared) if prepared.is_file() else {}, read(admission), {d: groups[d] for d in {lag_day, day}},
        files=files, as_of=as_of, identities=identities, score_calendar=data['cal'],
        records=read(reports_path), events=sales_events(events_path).to_dict('records'),
        calendar_manifest=[read(path) for path in calendar_paths],
        market_trace=market_trace, financial_trace=financial_trace)
    computed = datetime.now(timezone.utc)
    result = dict(schema_version=1, evidence_version=2, strategy_id=policy['registry_id'], date=day,
                  computed_at_utc=computed.isoformat(),
                  market_date=max(row['price_date'] for row in rows),
                  universe_count=len(rows), eligible_count=eligible, excluded_count=len(rows)-eligible,
                  rows=rows, policy_sha256=sha(ARCHIVE / 'strategy.locked.json'),
                  financial_snapshot_date=day, comparison_date=lag_day, previous_date=previous.get('date'),
                  input_evidence=input_evidence, source_hashes=files.hashes)
    result['data_readiness'] = assess_ranking(
        result, data['syms'], policy['execution_assumptions'], computed)['state']
    publish(run_dir / 'ranking.json', result)
    publish(run_dir / 'input-evidence-summary.json', summarize_evidence(input_evidence))
    if not isolated:
        publish(STATE / 'latest.json', result)
    return result


@contextmanager
def ranking_lock():
    STATE.mkdir(parents=True, exist_ok=True)
    # OS releases this lock even after interruption. The lock file is retained.
    from runtime_lock import acquire_file_lock, release_file_lock
    with (STATE / 'refresh.lock').open('a+b') as lock:
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            acquire_file_lock(lock)
        except OSError as exc:
            raise RuntimeError('FactorMix refresh already running') from exc
        try:
            yield
        finally:
            lock.seek(0)
            release_file_lock(lock)


def main():
    with ranking_lock():
        try:
            now = datetime.now(timezone.utc)
            day = now.astimezone(ZoneInfo('Asia/Tehran')).date().isoformat()
            run_dir = STATE / now.strftime('%Y%m%dT%H%M%S%fZ')
            run_dir.mkdir()
            publish(STATE / 'status.json', dict(state='running', started_at_utc=now.isoformat()))
            result = calculate(run_dir, day)
            publish(STATE / 'status.json', dict(state='ready', computed_at_utc=result['computed_at_utc'],
                                                data_readiness=result['data_readiness']))
            print(json.dumps({k: result[k] for k in ('date', 'eligible_count', 'data_readiness')}), flush=True)
        except Exception as exc:
            publish(STATE / 'status.json', dict(state='failed', error=str(exc)))
            raise


if __name__ == '__main__':
    main()
