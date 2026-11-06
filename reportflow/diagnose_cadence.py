"""Isolated explanation of cadence/turnover; never changes registered strategies.

These are retrospective diagnostic counterfactuals, not model selection or a
claim of unseen validation. All cases use exactly the same daily information.
"""
from dataclasses import replace
from pathlib import Path
import json

import jdatetime
import numpy as np
import pandas as pd

from reportflow import engine
from reportflow.build_inputs import HERE, OUT, ROOT, read, sha, write

DEST = HERE / 'diagnostics/review_cadence_20261106'


def monthly_dates(cal, day_of_month):
    selected = []
    seen = set()
    for day in cal:
        jd = jdatetime.date.fromgregorian(date=pd.Timestamp(str(day)).date())
        month = (jd.year, jd.month)
        if jd.day >= day_of_month and month not in seen:
            selected.append(str(day)); seen.add(month)
    return selected


def score_blocks(data, weights):
    from factormix.refresh_ranking import load_replay
    load_replay()
    import features
    from ranking_research.return_v8.features import FIELDS, LOW
    raw = data['raw']; columns = {}
    for j, field in enumerate(FIELDS):
        value = raw[:, :, j].copy()
        if j == 11: value = abs(value)
        if j in (12, 13, 14): value[(value <= 0) | (value > {12: 60, 13: 100, 14: 30}[j])] = np.nan
        columns[field] = features.rank_transform(value, j in LOW)
    for field, value in features.market_features(data['close'], data['adv']).items():
        columns[field] = features.rank_transform(value, field.startswith('vol_') or field == 'downside_vol63')
    dates = data['cal'].astype('datetime64[D]')
    lag = np.maximum(0, np.searchsorted(dates, dates - np.timedelta64(90, 'D'), side='right') - 1)
    derived = dict(sales_accel_3v12=raw[:, :, 1] - raw[:, :, 0],
                   sales_growth_change90=raw[:, :, 1] - raw[lag, :, 1],
                   profit_growth_change90=raw[:, :, 4] - raw[lag, :, 4],
                   margin_trend_change90=raw[:, :, 8] - raw[lag, :, 8])
    columns.update({k: features.rank_transform(v) for k, v in derived.items()})
    mean = lambda names: np.mean(np.stack([columns[n] for n in names], axis=2), axis=2)
    blocks = np.stack([mean(FIELDS[:5]), mean(FIELDS[5:12]), mean(['pe', 'ps', 'pb']),
                       mean(['leverage', 'current_ratio', 'cash_conversion', 'sales_stability']),
                       mean(['mom_63', 'mom_126_skip21', 'near_high_126', 'trend_50_200']),
                       mean(['vol_63', 'downside_vol63', 'reversal21']), mean(list(derived)),
                       features.rank_transform(data['reference_p1'])], axis=2)
    value = (blocks @ weights).astype(np.float32)
    value[~np.isfinite(data['reference_p1'])] = np.nan
    np.testing.assert_array_equal(value, data['p1'])
    return blocks


def trade_characteristics(run, data, events):
    positions = {str(s): i for i, s in enumerate(data['syms'])}
    index = {str(d): i for i, d in enumerate(data['cal'])}
    targets = {d['session']: set(d['target'].split(';')) for d in run['decisions']}
    q = np.zeros(len(positions)); last_entry = {}; exits = []; trims = 0; entries = 0
    recent_exits = {}; roundtrips = []
    reports = {(str(r.session), str(r.symbol)) for r in events.itertuples()}
    sell_without_own_report = 0
    for t in run['trades']:
        symbol = t['symbol']; j = positions[symbol]
        if t['side'] == 'BUY':
            if q[j] < 1e-10:
                entries += 1; last_entry[symbol] = t['session']
                if symbol in recent_exits:
                    roundtrips.append(index[t['session']] - index[recent_exits[symbol]])
            q[j] += t['units']
        else:
            q[j] -= t['units']
            if symbol in targets[t['decision']]:
                trims += 1
            elif q[j] < 1e-10:
                recent_exits[symbol] = t['session']
                exits.append(index[t['session']] - index[last_entry[symbol]])
                if (t['decision'], symbol) not in reports: sell_without_own_report += 1
    return dict(new_entries=entries, completed_exits=len(exits), weight_trim_fills=trims,
                median_held_sessions=float(np.median(exits)) if exits else None,
                repurchases_within_20_sessions=sum(x <= 20 for x in roundtrips),
                exits_without_same_day_own_report=sell_without_own_report)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    data = dict(np.load(OUT / 'event_inputs.npz', allow_pickle=False))
    policy = read(HERE / 'strategy.json'); cfg = engine.Config(**policy['portfolio']); ex = engine.Execution(**policy['execution'])
    start, end = policy['backtest']['requested_start'], policy['backtest']['end']
    a, b = np.searchsorted(data['cal'], start), len(data['cal'])
    events = pd.read_csv(OUT / 'report_events.csv')
    report_dates = events.session.unique().tolist()
    quarterly = sorted(engine.calendar_schedule(data['cal'].tolist(), cfg, int(a), b))
    quarter_dates = data['cal'][quarterly].tolist()
    m10 = monthly_dates(data['cal'][a:], 10); m20 = monthly_dates(data['cal'][a:], 20)
    declaration = dict(input_sha256=sha(OUT / 'event_inputs.npz'), strategy_sha256=sha(HERE / 'strategy.json'),
                       purpose='diagnosis, not retuning or promotion',
                       cases=['quarterly', 'monthly_jalali_10', 'monthly_jalali_20', 'every_report',
                              'quarterly_zero_cost', 'monthly_10_zero_cost', 'every_report_zero_cost',
                              'reports_market_blocks_held_quarterly', 'reports_nonmarket_blocks_held_quarterly'])
    write(DEST / 'protocol.json', declaration)
    blocks = score_blocks(data, np.array(policy['weights']))
    # Quarter-anchor decomposition: the market blocks are 43.79% of this score.
    lag = np.maximum(0, np.searchsorted(quarterly, np.arange(len(data['cal'])), side='right') - 1)
    anchors = np.asarray(quarterly)[lag]
    inputs = {}
    for label, groups in [('market', [4, 5]), ('nonmarket', [0, 1, 2, 3, 6, 7])]:
        changed = blocks.copy()
        for group in groups: changed[:, :, group] = blocks[anchors, :, group]
        scores = (changed @ np.array(policy['weights'])).astype(np.float32)
        scores[~np.isfinite(data['reference_p1'])] = np.nan
        inputs[label] = {**data, 'p1': scores}
    zero = replace(ex, fee=0, slippage=0)
    cases = [('quarterly', data, quarter_dates, ex), ('monthly_jalali_10', data, m10, ex),
             ('monthly_jalali_20', data, m20, ex), ('every_report', data, report_dates, ex),
             ('quarterly_zero_cost', data, quarter_dates, zero), ('monthly_10_zero_cost', data, m10, zero),
             ('every_report_zero_cost', data, report_dates, zero),
             ('reports_market_blocks_held_quarterly', inputs['market'], report_dates, ex),
             ('reports_nonmarket_blocks_held_quarterly', inputs['nonmarket'], report_dates, ex)]
    accounts = {}; paths = {}
    for name, source, reviews, execution in cases:
        run = engine.simulate(source, cfg, execution, start=start, end=end, detail=True, review_dates=reviews)
        engine.save_run(DEST / name, run)
        accounts[name] = dict(metrics=run['metrics'], fills=run['n_trades'], decisions=len(run['decisions']),
                              reviews=len(run['reviews']), fees_toman=run['cost_toman'], slippage_toman=run['slippage_toman'],
                              trading=trade_characteristics(run, data, events))
        paths[name] = run['nav'].tolist()
        print(name, json.dumps(accounts[name]), flush=True)
    # A pure cadence rerun must reproduce both earlier endpoints exactly.
    old = read(OUT / 'summary.json')['accounts']
    for name, reference in [('quarterly', 'same_information_quarterly'), ('every_report', 'reportflow')]:
        np.testing.assert_allclose(accounts[name]['metrics']['final_toman'], old[reference]['metrics']['final_toman'], rtol=0, atol=1)
    # No registered files or forward state are written by this diagnostic.
    write(DEST / 'summary.json', dict(accounts=accounts, market_block_weight=sum(policy['weights'][4:6]),
                                    same_information=True, registered_strategy_changed=False,
                                    retrospective_diagnostics_not_validation=True))
    lines = ['# بررسی اختلاف بازبینی ماهانه و پس از هر گزارش', '',
             'همهٔ سناریوهای اصلی، اطلاعات روزانه و وزن‌های یکسان دارند؛ فقط نوبت بررسی فرق دارد. این آزمایش تشخیصی است و نسخه‌های ثبت‌شده و حساب آینده را تغییر نمی‌دهد.', '',
             '| سناریو | ارزش پایان، تومان | اجراهای خرید و فروش | بررسی‌ها |', '|---|---:|---:|---:|']
    for name, row in accounts.items():
        lines.append(f"| {name} | {row['metrics']['final_toman']:,.0f} | {row['fills']} | {row['reviews']} |")
    lines += ['', 'آزمایش بدون هزینه، انتخاب‌ها را با نقد و وزن‌های بدون هزینه دوباره شبیه‌سازی می‌کند؛ تفاضل آن با حالت خالص فقط جمع کارمزدهای قبلی نیست.', '',
              'دو آزمایش بلوک ثابت، سهم‌های قیمتی یا غیرقیمتی امتیاز را فقط در تاریخ‌های فصلی به‌روز می‌کنند. این‌ها تجزیهٔ تشخیصی مدل‌اند و یک آزمون صرف تغییر زمان‌بندی نیستند.', '']
    (DEST / 'REPORT.fa.md').write_text('\n'.join(lines), encoding='utf8')


if __name__ == '__main__':
    main()
