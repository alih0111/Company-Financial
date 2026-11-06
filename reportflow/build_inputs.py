"""Reconstruct report-event information sets without touching FactorMix archives.

Financial engines run only for companies with new report/comparative events.
Daily price-dependent ratios are then refreshed for the entire fixed universe.
Historical publication time is NOT represented as actual historical receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'artifacts'
ARCHIVE = ROOT / 'strategy_registry/RFA-FactorMix-033/v1.0.0'
SOURCE_MANIFEST = ROOT / 'ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261105T190004086286Z-161d8f98/extraction_manifest.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def effective_session(cal, stamp, *, following_day=False):
    local = pd.Timestamp(stamp)
    if local.tzinfo is None:
        raise ValueError('Source timestamp has no timezone')
    day = local.tz_convert('Asia/Tehran').date()
    if following_day:
        day += timedelta(days=1)
    i = int(np.searchsorted(cal, day.isoformat()))
    return str(cal[i]) if i < len(cal) else None


def prepare_sources(cal):
    meta = read(SOURCE_MANIFEST)
    reports_path = ROOT / meta['financial']['reports_path']
    comp_path = ROOT / meta['financial']['comparatives_path']
    monthly_path = reports_path.parent / 'monthly_sales_events.parquet'
    orig_path = ROOT / 'fundamental_event_research/monthly_sales_events_universe_v1_1.parquet'
    records = read(reports_path)
    companies = defaultdict(list)
    bykey = {}
    events = []
    for r in records:
        r['facts'] = [dict(f) for f in r['facts']]
        companies[str(r['company_id'])].append(r)
        bykey[(str(r['company_id']), str(r['tracing_no']))] = r
        day = effective_session(cal, r['published_at'])
        if day:
            events.append(dict(session=day, symbol=r['symbol'], company_id=str(r['company_id']),
                               event_id='financial:' + str(r['tracing_no']), kind='financial',
                               published_at=r['published_at'], period_end=r['period_end']))
    additions = defaultdict(list)
    for c in read(comp_path):
        rec = bykey[(str(c['company_id']), str(c['tracing_no']))]
        stamp = max(pd.Timestamp(rec['published_at']), pd.Timestamp(c.get('available_at_utc') or rec['published_at']))
        day = effective_session(cal, stamp)
        if day:
            additions[day].append((rec, c))
            events.append(dict(session=day, symbol=rec['symbol'], company_id=str(c['company_id']),
                               event_id='comparative:' + str(c['tracing_no']) + ':' + c['metric_code'] + ':' + str(c['period_order']),
                               kind='comparative', published_at=stamp.isoformat(), period_end=rec['period_end']))
    monthly = pd.concat([pd.read_parquet(orig_path), pd.read_parquet(monthly_path)], ignore_index=True).drop_duplicates('event_id', keep='last')
    for r in monthly.itertuples():
        correction = bool(r.is_correction)
        valid = pd.notna(r.current_value_version_known) and bool(r.current_value_version_known) and pd.notna(r.CURRENT_PERIOD_SALES)
        if not correction and not valid:
            continue
        earliest = effective_session(cal, r.published_at, following_day=True)
        if not earliest:
            continue
        day = max(earliest, str(r.signal_entry_date)[:10]) if pd.notna(r.signal_entry_date) else earliest
        i = np.searchsorted(cal, day)
        if i >= len(cal):
            continue
        day = str(cal[i])
        # Corrected unknown numbers mask their reporting month from knowledge time.
        monthly.loc[monthly.event_id.eq(r.event_id), 'signal_entry_date'] = day
        events.append(dict(session=day, symbol=r.symbol, company_id=str(r.company_id),
                           event_id=str(r.event_id), kind='sales_correction' if correction else 'sales',
                           published_at=str(r.published_at), period_end=str(r.period_end)[:10]))
    paths = [SOURCE_MANIFEST, reports_path, comp_path, monthly_path, orig_path,
             ARCHIVE / 'snapshot_data/active_inputs.npz', ARCHIVE / 'strategy.locked.json',
             ROOT / 'qvt_backtest/output/financial_history/share_intervals.json']
    return companies, additions, monthly, pd.DataFrame(events), {str(p.relative_to(ROOT)): sha(p) for p in paths}


def market_context(replay):
    import extend_market
    # The existing helper is read-only except for its OUT directory.
    extend_market.OUT = OUT / 'market_sources'
    extend_market.OUT.mkdir(parents=True, exist_ok=True)
    _, md, _ = extend_market.prepare_market()
    return md


def rebuild(*, force=False):
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'event_inputs.npz'
    if target.exists() and not force:
        proof = read(OUT / 'input_manifest.json')
        for name, checksum in proof['source_hashes'].items():
            if sha(ROOT / name) != checksum:
                raise RuntimeError('Source changed: ' + name)
        if sha(target) != proof['output_sha256']:
            raise RuntimeError('Input artifact hash changed')
        return target
    from factormix.refresh_ranking import load_replay, score_blocks
    replay = load_replay()
    from ranking_research.return_v8.features import FIELDS, ranks, penalties
    from ranking_research.return_v8.engine import scores as p1_scores
    from ranking_research.return_v11.prepare import build_monthly
    from ranking_research.future_eval_v12_30.income_statement_selection import income_statement_view
    from ranking_research.v2_inputs import resolve_shares
    from ranking_research.return_v2.events import cutoff
    import features

    data = dict(np.load(ARCHIVE / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    cal, syms = data['cal'], data['syms']
    T, S = len(cal), len(syms)
    companies, additions, monthly_events, events, hashes = prepare_sources(cal)
    # Lock source identities BEFORE observing any ReportFlow return.
    declaration = dict(strategy_sha256=sha(HERE / 'strategy.json'), source_hashes=hashes,
                       tuning=False, historical_receipt_proven=False, daily_reconstruction=True)
    protocol = OUT / 'protocol.json'
    if protocol.exists() and read(protocol) != declaration:
        raise RuntimeError('Protocol/source changed; use a new strategy analysis directory')
    write(protocol, declaration)
    events = events[events.symbol.isin(syms)].sort_values(['session', 'kind', 'event_id'])
    events.to_csv(OUT / 'report_events.csv', index=False, encoding='utf-8-sig')
    md = market_context(replay)
    ids = pd.read_csv(ROOT / 'ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv', dtype=str)
    skeleton = ids[['company_id', 'symbol']].assign(decision_time=str(cal[0]))
    sales = build_monthly(monthly_events, skeleton, cal.tolist(), [], jalali=True, keep_corrections=True)
    sales = sales.set_index(['decision_time', 'symbol']).reindex(pd.MultiIndex.from_product([cal, syms]))
    raw = np.full((T, S, len(FIELDS)), np.nan)
    raw[:, :, [0, 1, 16]] = sales[['sales_growth_12m', 'sales_growth_3m', 'sales_stability']].to_numpy(float).reshape(T, S, 3)
    intervals = read(ROOT / 'qvt_backtest/output/financial_history/share_intervals.json')['intervals']
    identities = {str(r.company_id): dict(symbol=str(r.symbol), security_id=md.sym2sid[str(r.symbol)]) for r in ids.itertuples()}
    cids = {v['symbol']: k for k, v in identities.items()}
    source = replay.LocalSnapshots([], [], identities, md, intervals)
    change = defaultdict(set)
    for e in events[events.kind.isin(['financial', 'comparative'])].itertuples():
        change[e.session].add(e.company_id)
    cache = {}
    age = np.full((T, S), 9999.)
    net = np.full((T, S), np.nan)
    quality = np.zeros((T, S))
    latest_publication = np.full((T, S), '', dtype='<U35')
    refreshes = 0
    for i, day in enumerate(cal):
        day = str(day)
        for rec, comp in additions.get(day, []):
            key = (comp['statement_type'], comp['metric_code'], int(comp['period_order']))
            old = next((f for f in rec['facts'] if (f['statement_type'], f['metric_code'], int(f['period_order'])) == key), None)
            if old is None:
                rec['facts'].append(dict(statement_type=comp['statement_type'], metric_code=comp['metric_code'],
                                        period_order=int(comp['period_order']), value=float(comp['canonical_value']),
                                        unit=comp['canonical_unit'], basis='parent'))
            elif not np.isclose(float(old['value']), float(comp['canonical_value']), rtol=1e-12, atol=1):
                raise ValueError('Comparative conflicts with admitted source')
        changed = change.get(day, set())
        if changed:
            source.identities = {cid: identities[cid] for cid in changed if cid in identities}
            source.reports = [r for cid in source.identities for r in companies[cid]]
            eng, _, _ = source.snapshot(day, cutoff(day))
            full = eng.report_index()
            income = income_statement_view(full)
            titles = eng.codal_titles
            eligible = {(cid, p) for cid, periods in income.items() for p in periods}
            eng.codal_titles = [t for t in titles if (t['company_id'], tuple(replay.CM.fiscal_ym(t['period_end_date']))) in eligible]
            eng.report_index = lambda: income
            metrics = eng.compute()
            for cid in source.identities:
                chosen = eng.snapshot_source_reports.get(cid, [])
                assert all(pd.Timestamp(s['published_at']) < pd.Timestamp(cutoff(day)) for s in chosen)
                cache[cid] = dict(rep=full.get(cid, {}), inc=income.get(cid, {}), metric=metrics.get(cid, {}),
                                  selected=chosen, pub=max((s['published_at'] for s in chosen), default=''))
            refreshes += len(source.identities)
        for j, sym in enumerate(syms):
            sym = str(sym); cid = cids[sym]
            state = cache.get(cid, dict(rep={}, inc={}, metric={}, selected=[], pub=''))
            rep, inc, m = state['rep'], state['inc'], state['metric']
            key = max(inc, default=None); cell = inc.get(key, {})
            bk = max(rep, default=None); balance = rep.get(bk, {})
            g = lambda name, order=1: cell.get(name, {}).get(order)
            bg = lambda name: balance.get(name, {}).get(1)
            ratio = replay.ratio
            vals = [float(m[f]) if m.get(f) is not None else np.nan for f in FIELDS]
            nt, op, rev = m.get('net_profit_ttm'), m.get('operating_profit_ttm'), m.get('revenue_ttm')
            vals[5] = ratio(op, abs(rev) if rev else None, scale=100)
            vals[6] = ratio(nt, abs(rev) if rev else None, scale=100)
            for k in (5, 6):
                if abs(vals[k]) > 200: vals[k] = np.nan
            vals[7] = ratio(nt, bg('total_equity'), True, 100)
            if abs(vals[7]) > 300: vals[7] = np.nan
            om = ratio(g('operating_profit'), abs(g('revenue')) if g('revenue') else None, scale=100)
            prev = ratio(g('operating_profit', 2), abs(g('revenue', 2)) if g('revenue', 2) else None, scale=100)
            vals[8] = om - prev if abs(om) <= 200 and abs(prev) <= 200 else np.nan
            vals[9] = ratio(g('operating_profit'), abs(g('finance_cost')) if g('finance_cost') else None)
            if abs(vals[9]) > 10000: vals[9] = np.nan
            vals[10] = ratio(m.get('ocf_ttm'), nt, True)
            if not -2 <= vals[10] <= 5: vals[10] = np.nan
            vals[11] = ratio(abs(g('other_non_operating')) if g('other_non_operating') is not None else None,
                             abs(g('operating_profit')) if g('operating_profit') else None, scale=100)
            vals[17] = ratio(bg('total_liabilities'), bg('total_equity'), True)
            vals[18] = ratio(bg('current_assets'), bg('current_liabilities'), True)
            if not 0 <= vals[17] <= 50: vals[17] = np.nan
            if not 0 <= vals[18] <= 15: vals[18] = np.nan
            rec = md.data[sym]; dates = np.asarray(rec['dates'])
            valid = (dates <= day) & (rec['vol'] > 0) & (rec['tval'] > 0) & (rec['c'] > 0)
            observations = np.flatnonzero(valid); tail = observations[-30:]
            # Constant later adjustment scales cancel in these within-window returns.
            prices = rec['c'][tail] * rec['cf'][tail]
            vals[15] = float(np.mean(rec['tval'][tail])) if len(tail) else np.nan
            vals[19] = float(np.std(-np.diff(prices) / prices[1:] * 100, ddof=1)) if len(tail) > 2 else np.nan
            vals[20] = float((prices[-1] / prices[0] - 1) * 100) if len(tail) >= 30 else np.nan
            actual = str(dates[observations[-1]]) if len(observations) else None
            price = float(rec['c'][observations[-1]]) if len(observations) else None
            iv = resolve_shares(source.intervals, sym, cid, md.sym2sid[sym], day, actual) if actual else None
            share_ok = bool(iv and iv.get('evidence')) and not any(str(iv.get('valid_from') or '') < str(d) <= day for d, f in md.events[rec['sid']])
            eps = ratio(nt, g('net_profit'), True) * g('eps') if g('eps') and g('eps') > 0 else np.nan
            vals[12] = ratio(price, eps, True) if share_ok else np.nan
            vals[13] = vals[12] * vals[6] / 100 if 0 < vals[12] <= 60 and vals[6] > 0 and vals[12] * vals[6] / 100 <= 100 else np.nan
            vals[14] = vals[12] * vals[7] / 100 if 0 < vals[12] <= 60 and vals[7] > 0 and vals[12] * vals[7] / 100 <= 30 else np.nan
            vals[0], vals[1], vals[16] = raw[i, j, 0], raw[i, j, 1], raw[i, j, 16]
            raw[i, j] = vals
            period = cell.get('_period')
            age[i, j] = (pd.Timestamp(day) - pd.Timestamp(period)).days if period else 9999
            net[i, j] = float(nt) if nt is not None else np.nan
            priceage = (pd.Timestamp(day) - pd.Timestamp(actual)).days if actual else 9999
            count = len(rep); now = pd.Timestamp(day)
            sqljy = now.year - (622 if now.month < 3 or now.month == 3 and now.day < 21 else 621)
            sqljm = {1:11, 2:12, 3:1, 4:2, 5:3, 6:4, 7:5, 8:6, 9:7, 10:8, 11:9, 12:10}[now.month]
            jy, jm = key if key else (0, 0); months = sqljy * 12 + sqljm - jy * 12 - jm
            quality[i, j] = ((.28 if count >= 16 else .16 if count >= 8 else .09 if count >= 4 else 0)
                             + (.21 if len(observations) >= 90 else .13 if len(observations) >= 30 else .06 if len(observations) >= 10 else 0)
                             + (.09 if price else 0) + (.08 if state['selected'] and months <= 5 else .045 if state['selected'] and months <= 8 else 0)
                             + (.06 if priceage <= 7 else .035 if priceage <= 14 else 0))
            latest_publication[i, j] = state['pub']
        if i % 50 == 0 or i == T - 1:
            print('ReportFlow reconstruction', i + 1, '/', T, day, 'company refreshes', refreshes, flush=True)
    contract = read(ROOT / 'ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json')
    weights = np.asarray(next(m['weights'] for m in contract['methods'] if m['method_id'] == 'P1'))
    observed = np.isfinite(raw)
    for j, limit in ((12, 60), (13, 100), (14, 30)):
        observed[:, :, j] &= (raw[:, :, j] > 0) & (raw[:, :, j] <= limit)
    tensor = dict(rank=np.stack([ranks(x) for x in raw]), observed=observed,
                  penalty=np.stack([penalties(x, nt) for x, nt in zip(raw, net)]), dq=quality)
    p1 = p1_scores(tensor, dict(weights=weights, vol_direction='lower', missing='defaults', penalties=True, dq=True))
    financial = [j for j in range(21) if j not in (15, 19, 20)]
    p1[(observed[:, :, financial] @ weights[financial]) / weights[financial].sum() < .5] = np.nan
    score = score_blocks(raw, data['close'], data['adv'], p1, cal, read(HERE / 'strategy.json')['weights'], features)
    data.update(p1=score, financial_age=age, score_age=np.zeros(T, dtype=int), signal_dates=cal.copy())
    np.savez_compressed(target, **data, raw=raw, reference_p1=p1, dq=quality, net_profit_ttm=net,
                        latest_financial_publication=latest_publication)
    manifest = dict(source_hashes=hashes, output_sha256=sha(target), sessions=T, universe=S,
                    events=len(events), financial_company_refreshes=refreshes,
                    historical_receipt_proven=False, source_engine='LocalSnapshots / income_statement_view / canonical compute',
                    monthly_windows='24m / 6m / 12m Jalali contiguous verified monthly chain',
                    no_future_report_selected=True, parent_archive_unchanged=True)
    write(OUT / 'input_manifest.json', manifest)
    return target


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    print(rebuild(force=parser.parse_args().force))
