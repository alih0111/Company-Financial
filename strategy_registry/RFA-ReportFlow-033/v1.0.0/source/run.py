"""Run predeclared ReportFlow strategy and same-information quarterly control."""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from reportflow import engine
from reportflow.build_inputs import ARCHIVE, HERE, OUT, ROOT, read, rebuild, sha, write


def analysis_helpers():
    path = ROOT / 'strategy_registry/analyses/replay_1401_20261106/run.py'
    spec = importlib.util.spec_from_file_location('reportflow_ledger_verifier', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute():
    policy = read(HERE / 'strategy.json')
    verifier = analysis_helpers()
    count = verifier.verify_archive()
    inputs = rebuild()
    data = dict(np.load(inputs, allow_pickle=False))
    cfg = engine.Config(**policy['portfolio'])
    ex = engine.Execution(**policy['execution'])
    dates = pd.read_csv(OUT / 'report_events.csv').session.unique().tolist()
    start, end = policy['backtest']['requested_start'], policy['backtest']['end']
    cases = [('reportflow', data, cfg, ex, dates),
             ('same_information_quarterly', data, cfg, ex, None),
             ('double_cost', data, cfg, replace(ex, fee=ex.fee * 2, slippage=ex.slippage * 2), dates),
             ('delay_2_sessions', data, cfg, replace(ex, delay=2), dates)]
    archived = dict(np.load(ARCHIVE / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    old_policy = read(ARCHIVE / 'strategy.locked.json')
    cases.append(('original_factormix', {**archived, 'p1': archived['candidate_score']},
                  engine.Config(**old_policy['portfolio']), ex, None))
    accounts = {}; runs = {}
    for label, source, config, execution, reviews in cases:
        run = engine.simulate(source, config, execution, start=start, end=end, detail=True, review_dates=reviews)
        # The archived verifier expects the original archived holding_values key.
        ledger, detailed = verifier.reconcile(source, {**run, 'holding_values': run['holding_values']}, execution)
        engine.save_run(OUT / label, run)
        pd.DataFrame(detailed).to_csv(OUT / f'{label}_ledger.csv', index=False, encoding='utf-8-sig')
        pd.DataFrame(run['reviews']).to_csv(OUT / f'{label}_reviews.csv', index=False, encoding='utf-8-sig')
        accounts[label] = dict(metrics=run['metrics'], annual=verifier.annual_rows(run),
                               fees_toman=run['cost_toman'], slippage_toman=run['slippage_toman'],
                               fills=run['n_trades'], decisions=len(run['decisions']), reviews=len(run['reviews']),
                               expired_orders=run['expired_orders'], blocked_order_days=run['blocked_order_days'],
                               maximum_position_count=int(run['positions'].max()), ledger=ledger,
                               first_fill=run['trades'][0]['session'] if run['trades'] else None,
                               execution=execution.__dict__)
        runs[label] = run
        print(label, json.dumps(accounts[label]['metrics']), 'fills', run['n_trades'], 'decisions', len(run['decisions']), flush=True)
    expected = read(ROOT / 'strategy_registry/analyses/replay_1401_20261106/artifacts/summary.json')['accounts']['candidate']['metrics']['final_toman']
    np.testing.assert_allclose(accounts['original_factormix']['metrics']['final_toman'], expected, atol=1, rtol=0)
    # Daily features of the new model must only depend on the prefix available then.
    from factormix.refresh_ranking import load_replay, score_blocks
    load_replay()
    import features
    prefix_checks = []
    for boundary in ['2023-03-19', '2025-03-19']:
        k = int(np.searchsorted(data['cal'], boundary, side='right'))
        recomputed = score_blocks(data['raw'][:k], data['close'][:k], data['adv'][:k], data['reference_p1'][:k],
                                  data['cal'][:k], policy['weights'], features)
        np.testing.assert_array_equal(recomputed, data['p1'][:k])
        prefix_checks.append(boundary)
    assert verifier.verify_archive() == count
    summary = dict(strategy_id=policy['strategy_id'], actual_start=str(runs['reportflow']['cal'][0]), end=end,
                   initial_toman=100_000_000, accounts=accounts, original_archive_verified_files=count,
                   original_result_reproduced=True, future_market_feature_invariance=prefix_checks,
                   input_sha256=sha(inputs), strategy_sha256=sha(HERE / 'strategy.json'),
                   selection_or_retuning=False, historical_receipt_proven=False,
                   limitations=['Retrospective model weights were selected using part of this history; no unseen validation.',
                                'Fixed present-day 254-company universe; historical survivorship and incomplete report coverage.',
                                'Historical report publication reconstruction, not actual historical collection timestamps.',
                                'Daily-bar next-open fills, 5% ADV cap, no proof of real exchange queue priority.',
                                'Fractional adjusted units with assumed dividend reinvestment; not real share/cash corporate actions.',
                                'Terminal NAV is marked portfolio value, not guaranteed cash liquidation proceeds.'])
    write(OUT / 'summary.json', summary)
    publish(summary, runs, verifier)
    return summary


def publish(summary, runs, verifier):
    public = ROOT / 'client/public/strategies/reportflow-033'
    public.mkdir(parents=True, exist_ok=True)
    paths = []
    run = runs['reportflow']
    for i, day in enumerate(run['cal']):
        paths.append(dict(date=str(day), reportflow=float(run['nav'][i]),
                          original=float(runs['original_factormix']['nav'][i]),
                          same_information_quarterly=float(runs['same_information_quarterly']['nav'][i])))
    write(public / 'backtest.json', dict(**summary, path=paths, policy=read(HERE / 'strategy.json')))
    for label in ['reportflow', 'original_factormix', 'same_information_quarterly']:
        for suffix in ['nav', 'trades', 'decisions']:
            (public / f'{label}_{suffix}.csv').write_bytes((OUT / f'{label}_{suffix}.csv').read_bytes())
    labels = dict(reportflow='ReportFlow جدید؛ بررسی پس از گزارش', original_factormix='FactorMix اصلی و بدون تغییر',
                  same_information_quarterly='کنترل فصلی با اطلاعات بازسازی‌شدهٔ یکسان',
                  double_cost='حساسیت: دو برابر هزینه', delay_2_sessions='حساسیت: اجرا با دو جلسه تأخیر')
    lines = ['# ReportFlow-033 — بررسی سبد پس از گزارش جدید', '',
             'نسخهٔ مستقل ۱٫۰٫۰؛ FactorMix اصلی تغییر نکرده است.', '',
             f"شروع واقعی: {verifier.jalali(summary['actual_start'])}؛ پایان: {verifier.jalali(summary['end'])}؛ سرمایه: ۱۰۰ میلیون تومان.", '',
             'قواعد پیش از مشاهدهٔ نتیجه ثبت شده‌اند؛ وزن‌ها یا آستانه‌ها بر اساس این بک‌تست تنظیم نشده‌اند.', '',
             'هر گزارش مالی، فروش ماهانه یا اصلاحیهٔ معتبر یک بررسی ایجاد می‌کند. گزارش‌های یک جلسه تجمیع می‌شوند. پنج سهم، وزن هدف ۲۰٪، حفظ تا رتبهٔ ۸، بازتنظیم با انحراف بیش از ۵ واحد درصد. اگر تغییری لازم نباشد معامله ساخته نمی‌شود.', '',
             '۱۰ام ماه بعد و ۴۰ روز پس از فصل فقط زمان انتظار گزارش‌اند. تصمیم بر اساس انتشار و دسترس‌پذیری واقعی است؛ معامله زودتر از جلسهٔ بعد نیست.', '',
             'رشد فروش ۳ماهه، سه ماه اخیر را با سه ماه قبل مقایسه می‌کند؛ رشد ۱۲ماهه از دو پنجرهٔ ۱۲ماههٔ متوالی است. این تعریف از مدل والد به ارث رسیده و رشد نقطه‌به‌نقطهٔ همان ماه نیست.', '',
             '| سناریو | ارزش پایان، تومان | بیشترین افت | اجراهای خرید و فروش |',
             '|---|---:|---:|---:|']
    for name, a in summary['accounts'].items():
        lines.append(f"| {labels[name]} | {a['metrics']['final_toman']:,.0f} | {a['metrics']['max_drawdown']:.2%} | {a['fills']} |")
    lines += ['', 'نتیجهٔ این مقایسه: واکنش پس از هر گزارش، با این قواعد و هزینه‌ها از نسخهٔ فصلی بهتر نبوده است. مدل جدید به عنوان آزمایش مستقل حفظ می‌شود و جایگزین FactorMix اصلی نمی‌شود. حساسیت به هزینه و تأخیر نیز بالاست؛ بهتر شدن سناریوی تأخیر به معنی انتخاب آن پس از دیدن نتیجه نیست.']
    lines += ['', '## پایان هر سال شمسی', '', '| سال | ReportFlow، تومان | FactorMix اصلی، تومان |', '|---|---:|---:|']
    for new, old in zip(summary['accounts']['reportflow']['annual'], summary['accounts']['original_factormix']['annual']):
        lines.append(f"| {new['year']} | {new['final_toman']:,.0f} | {old['final_toman']:,.0f} |")
    a = summary['accounts']['reportflow']
    lines += ['', f"کارمزد کسرشده: {a['fees_toman']:,.0f} تومان؛ لغزش قیمت: {a['slippage_toman']:,.0f} تومان. این دو هزینه در ارزش نهایی لحاظ شده‌اند.", '',
              f"{a['reviews']} بررسی گزارش و {a['decisions']} تصمیم دارای سفارش؛ تطبیق مستقل نقد و دارایی در تمام روزها انجام شده است.", '',
              '## حدود نتیجه', '',
              'بک‌تست بازسازی‌شده و اسمی است، نه حساب واقعی یا ارزش نقد قابل برداشت. زمان دریافت واقعی گزارش در گذشته اثبات نشده است. جهان ثابت ۲۵۴ نماد، پوشش ناقص آرشیو، وزن‌های منتخب با استفاده از بخشی از همین تاریخ، واحدهای تعدیل‌شده و فرض سرمایه‌گذاری مجدد سود از محدودیت‌های مهم‌اند.', '',
              'تفاوت نتیجهٔ مدل جدید با مدل اصلی فقط از زمان‌بندی نیست؛ بازسازی ریزتر اطلاعات نیز اثر دارد. سناریوی «کنترل فصلی با اطلاعات یکسان» برای تفکیک اثر زمان‌بندی ارائه شده است.', '',
              'دادهٔ بازار تا ۱۳ آبان ۱۴۰۵ است؛ نتیجه تا ۱۵ آبان امتداد مصنوعی داده نشده است.', '',
              'راهنمای ارزیابی ادعاهای عملکرد و فرضی بودن بک‌تست: [Investor.gov](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47).', '']
    report = '\n'.join(lines)
    (HERE / 'REPORT.fa.md').write_text(report, encoding='utf8')
    (public / 'report.fa.md').write_text(report, encoding='utf8')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    execute()
