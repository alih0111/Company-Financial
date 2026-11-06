"""Isolated daily-close FactorMix cadence test; never publish or change accounts.

Same frozen input scores, portfolio rules and archived engine as the original
and registered M15 comparison. Zero-cost cases diagnose execution-cost effects;
they are not replacements for the primary after-cost results.
"""
from bisect import bisect_left
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from factormix.reproduce_monthly15 import monthly_schedule

HERE = Path(__file__).resolve().parent
OUT = HERE / 'artifacts'
spec = importlib.util.spec_from_file_location('daily_independent_ledger', HERE.parent / 'replay_1401_20261106/run.py')
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def daily_schedule(cal, config, start, end):
    return set(range(start, end))


def protected_files():
    """All registered strategies, public comparison and existing account state."""
    paths = []
    for version in [audit.ARCHIVE,
        ROOT / 'strategy_registry/RFA-FactorMix-033-M15/v1.0.0',
        ROOT / 'strategy_registry/RFA-ReportFlow-033/v1.0.0']:
        manifest = json.loads((version / 'MANIFEST.sha256.json').read_text(encoding='utf8'))
        for item in manifest['files']:
            p = version / item['path']
            assert audit.sha(p) == item['sha256'], str(p)
            paths.append(p)
        paths.append(version / 'MANIFEST.sha256.json')
    paths.append(ROOT / 'client/public/strategies/factormix-033/performance/performance.json')
    # Forward observers may independently update status during the analysis;
    # checking immutable policies above avoids attributing those updates to us.
    return {str(p.relative_to(ROOT)):audit.sha(p) for p in paths}


def holding_stats(run, full_calendar):
    ids = {str(d):i for i,d in enumerate(full_calendar)}
    units = {}; entered = {}; durations = []; last_exit = {}; quick = 0
    full_buys = full_sells = 0
    for t in run['trades']:
        symbol = t['symbol']; previous = units.get(symbol,0.)
        if t['side'] == 'BUY':
            if previous < 1e-10:
                full_buys += 1; entered[symbol] = t['session']
                if symbol in last_exit and ids[t['session']] - ids[last_exit[symbol]] <= 20:
                    quick += 1
            units[symbol] = previous + t['units']
        else:
            units[symbol] = previous - t['units']
            if units[symbol] < 1e-10:
                full_sells += 1
                durations.append(ids[t['session']] - ids[entered[symbol]])
                last_exit[symbol] = t['session']
    return dict(new_position_entries=full_buys,complete_exits=full_sells,
                median_closed_holding_sessions=float(np.median(durations)) if durations else None,
                repurchases_within_20_sessions=quick)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    before = protected_files()
    policy = json.loads((audit.ARCHIVE / 'strategy.locked.json').read_text(encoding='utf8'))
    raw = dict(np.load(audit.ARCHIVE / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    data = {**raw,'p1':raw['candidate_score']}
    engine = audit.load_engine()
    cfg = engine.Config(**policy['portfolio'])
    ex = engine.Execution(**policy['execution_assumptions'])
    original_schedule = engine.calendar_schedule
    cases = [('original_quarterly',original_schedule,ex),('monthly_jalali_15',monthly_schedule,ex),
             ('daily_after_close',daily_schedule,ex),
             ('quarterly_zero_cost',original_schedule,replace(ex,fee=0,slippage=0)),
             ('monthly15_zero_cost',monthly_schedule,replace(ex,fee=0,slippage=0)),
             ('daily_zero_cost',daily_schedule,replace(ex,fee=0,slippage=0)),
             ('daily_delay_2_sessions',daily_schedule,replace(ex,delay=2))]
    protocol = dict(declared_at_utc=datetime.now(timezone.utc).isoformat(),
        requested_start=audit.START,end=audit.END,initial_toman=audit.CAPITAL,
        primary_cases=[c[0] for c in cases[:3]],diagnostic_cases=[c[0] for c in cases[3:]],
        primary_only_change='review schedule; after each stock session close, earliest fill next session',
        review_is_not_mandatory_trade=True,keep_rank_buffer=8,weight_band_absolute=.05,
        all_other_primary_rules_unchanged=True,input_kind='same archived FactorMix candidate_score, not ReportFlow daily fundamentals',
        input_sha256=audit.sha(audit.ARCHIVE / 'snapshot_data/active_inputs.npz'),
        policy_sha256=audit.sha(audit.ARCHIVE / 'strategy.locked.json'),
        engine_sha256=audit.sha(audit.ARCHIVE / 'replay/engine_snapshot.py'),
        execution=policy['execution_assumptions'],no_retuning=True,
        no_website_publication_or_registration_or_account_writes=True,
        pending_policy='archived engine unchanged: each eligible review replaces pending instructions and starts their lifetime anew; daily reviews can repeatedly renew or cancel them')
    audit.write_json(OUT / 'protocol.json', protocol)
    a = bisect_left(data['cal'].tolist(),audit.START)
    b = bisect_left(data['cal'].tolist(),audit.END+'~')
    assert np.all(data['signal_dates'][a:b] <= data['cal'][a:b])
    accounts = {}
    for label,schedule,execution in cases:
        engine.calendar_schedule = schedule
        run = engine.simulate(data,cfg,execution,start=audit.START,end=audit.END,
                              capital=audit.CAPITAL,detail=True)
        ledger,trades = audit.reconcile(data,run,execution)
        if label in ['original_quarterly','monthly_jalali_15']:
            source = ROOT / 'strategy_registry/RFA-FactorMix-033-M15/v1.0.0/results'
            frame = pd.read_csv(source / f'{label}_nav.csv')
            assert run['cal'].tolist() == frame.session.tolist()
            np.testing.assert_allclose(run['nav'],frame.nav_toman,rtol=0,atol=1)
            np.testing.assert_allclose(run['cash'],frame.cash_toman,rtol=0,atol=.01)
        engine.save_run(OUT / label,run)
        pd.DataFrame(trades).to_csv(OUT / f'{label}_ledger.csv',index=False,encoding='utf-8-sig')
        reviews = sorted(schedule(data['cal'].tolist(),cfg,a,b))
        assert len(reviews) == len(run['decisions']) + run['stale_decisions_skipped']
        decision_dates = {d['session'] for d in run['decisions']}
        pd.DataFrame([dict(session=str(data['cal'][i]),jalali=audit.jalali(data['cal'][i]),
            score_age=int(data['score_age'][i]),signal_date=str(data['signal_dates'][i]),
            accepted=str(data['cal'][i]) in decision_dates) for i in reviews]).to_csv(
                OUT / f'{label}_reviews.csv',index=False,encoding='utf-8-sig')
        trade_days = {t['session'] for t in run['trades']}
        accounts[label] = dict(metrics=run['metrics'],annual=audit.annual_rows(run),
            reviews_scheduled=len(reviews),decisions=len(run['decisions']),stale_decisions_skipped=run['stale_decisions_skipped'],
            fills=run['n_trades'],buy_fills=sum(t['side']=='BUY' for t in run['trades']),
            sell_fills=sum(t['side']=='SELL' for t in run['trades']),days_with_fills=len(trade_days),
            stock_sessions_without_fills=len(run['cal'])-len(trade_days),
            fees_toman=run['cost_toman'],slippage_toman=run['slippage_toman'],
            gross_turnover_toman=run['gross_turnover_toman'],first_fill=run['trades'][0]['session'],
            expired_orders=run['expired_orders'],blocked_order_days=run['blocked_order_days'],
            holding=holding_stats(run,data['cal']),ledger=ledger)
        print(json.dumps(dict(case=label,**{k:v for k,v in accounts[label].items() if k not in ['annual','ledger']})),flush=True)
    engine.calendar_schedule = original_schedule
    assert protected_files() == before
    daily = accounts['daily_after_close']['metrics']['final_toman']
    month = accounts['monthly_jalali_15']['metrics']['final_toman']
    quarter = accounts['original_quarterly']['metrics']['final_toman']
    reference = json.loads((HERE.parent / 'replay_1401_20261106/artifacts/summary.json').read_text(encoding='utf8'))
    summary = dict(initial_toman=audit.CAPITAL,start_jalali=audit.jalali(data['cal'][a]),
        end_jalali=audit.jalali(audit.END),accounts=accounts,
        daily_minus_monthly_toman=daily-month,daily_relative_to_monthly=daily/month-1,
        daily_minus_quarterly_toman=daily-quarter,daily_relative_to_quarterly=daily/quarter-1,
        daily_nav_cash_primary_controls_reproduced=True,independent_daily_accounting_all_cases='PASS',
        registered_and_public_files_verified_unchanged=len(before),no_live_or_paper_account_writes=True,
        limitations=reference['limitations'],
        additional_limitations=[protocol['pending_policy'],
            'Daily schedule is daily stock-session review, not mandatory daily portfolio replacement.',
            'Delay sensitivity retains archived scheduling semantics: fresh daily decisions can supersede older orders before a two-session delay elapses.',
            'Frozen historical fundamental snapshot cadence is retained; not a fresh daily reconstruction of all newly published reports.'])
    audit.write_json(OUT / 'summary.json',summary)
    labels = {'original_quarterly':'FactorMix اصلی، فصلی +۴۰ روز','monthly_jalali_15':'ماهانه، پانزدهم',
        'daily_after_close':'روزانه، پس از بازار','quarterly_zero_cost':'فصلی بدون هزینه',
        'monthly15_zero_cost':'ماهانهٔ ۱۵ بدون هزینه','daily_zero_cost':'روزانه بدون هزینه',
        'daily_delay_2_sessions':'روزانه با دو جلسه تأخیر اجرا'}
    lines = ['# بررسی مستقل بازبینی روزانهٔ FactorMix', '',
        f"سرمایهٔ آغازین: ۱۰۰ میلیون تومان؛ {summary['start_jalali']} تا {summary['end_jalali']}.", '',
        'در سه سناریوی اصلی، فقط تقویم بازبینی فرق دارد. همه از همان امتیازهای آرشیوشده و موتور FactorMix، قیمت‌ها، قواعد نگهداری تا رتبهٔ ۸، وزن هدف ۲۰٪ و باند ۵ واحد درصد استفاده می‌کنند. بررسی پس از پایان بازار است و نخستین فرصت اجرا جلسهٔ بعد؛ بررسی روزانه به معنی معاملهٔ اجباری روزانه نیست.', '',
        '| سناریو | ارزش پایان، تومان | بازده کل | بیشترین افت | اجراهای خرید و فروش |',
        '|---|---:|---:|---:|---:|']
    for label,_,_ in cases:
        row=accounts[label];m=row['metrics']
        lines.append(f"| {labels[label]} | {m['final_toman']:,.0f} | {m['total_return']:.2%} | {abs(m['max_drawdown']):.2%} | {row['fills']} |")
    lines += ['',f'اختلاف روزانه با ماهانه: {daily-month:,.0f} تومان ({daily/month-1:.2%} ارزش پایان).',
        f'اختلاف روزانه با فصلی: {daily-quarter:,.0f} تومان ({daily/quarter-1:.2%} ارزش پایان).', '',
        'کارمزد ۰٫۵٪ و لغزش ۰٫۱٪ هر سمت معامله در سناریوهای اصلی کسر شده‌اند؛ سقف حجم، توقف/تک‌قیمت و سایر قواعد همان اصل‌اند. آزمایش بدون هزینه مسیر معاملات را از نو محاسبه می‌کند؛ تفاضل آن فقط جمع هزینه‌های مسیر اصلی نیست.', '',
        '| سناریوی اصلی | بررسی برنامه‌ریزی‌شده | تصمیم پذیرفته‌شده | کنارگذاشته‌شده به علت عمر امتیاز | روزهای دارای اجرا | میانهٔ مدت موقعیت‌های بسته‌شده، جلسه |',
        '|---|---:|---:|---:|---:|---:|']
    for label,_,_ in cases[:3]:
        r=accounts[label]
        lines.append(f"| {labels[label]} | {r['reviews_scheduled']} | {r['decisions']} | {r['stale_decisions_skipped']} | {r['days_with_fills']} | {r['holding']['median_closed_holding_sessions']} |")
    lines += ['', '| سال | پایان فصلی، تومان | پایان ماهانه، تومان | پایان روزانه، تومان | بازده سال روزانه |',
        '|---|---:|---:|---:|---:|']
    for q,m,d in zip(*(accounts[label]['annual'] for label in ['original_quarterly','monthly_jalali_15','daily_after_close'])):
        lines.append(f"| {d['year']} | {q['final_toman']:,.0f} | {m['final_toman']:,.0f} | {d['final_toman']:,.0f} | {d['return_fraction']:.2%} |")
    lines += ['', 'سال ۱۴۰۵ تا ۱۳ آبان است. سناریوی اصلی روزانه هنوز محدودیت عمر ۴۵ روز برای امتیاز را دارد؛ روزهایی که امتیاز قدیمی‌تر است تصمیم تازه نمی‌سازند. داده‌های بنیادی با سری روزانهٔ ReportFlow جایگزین نشده‌اند؛ این آزمایش اثر تغییر تقویم روی همان FactorMix قبلی است.', '',
        'رفتار سفارش‌های باز دقیقاً مانند موتور آرشیوشده حفظ شده است: هر بازبینیِ پذیرفته‌شده دستورهای در انتظار را با هدف تازه جایگزین و مهلت را از نو شروع می‌کند. بنابراین در بازبینی روزانه امکان تمدید مکرر یا لغو سفارش وجود دارد. آزمایش تأخیر دو جلسه حساسیت به همین رفتار است؛ با بازبینی روزانه، تصمیم روز بعد می‌تواند پیش از رسیدن مهلت اجرا دستور قبلی را جایگزین کند. این سناریو برآورد خالص اثر تأخیر بازار نیست.', '',
        'نتیجه تاریخی و اسمی است؛ بخشی از همین تاریخ در انتخاب مدل نقش داشته، زمان دریافت واقعی همهٔ گزارش‌ها اثبات نشده و جهان نمادها ثابت است. واحدها شاخصی تعدیل‌شده‌اند و ارزش پایان لزوماً نقد قابل تسویهٔ فوری نیست. این بررسی نسخهٔ تازه ثبت یا فعال نمی‌کند.', '',
        f"کنترل‌ها: بازتولید کل منحنی سرمایه و نقد نسخهٔ اصلی و ماهانهٔ ثبت‌شده؛ دفتر مستقل نقد و دارایی و محدودیت حجم برای هر هفت سناریو؛ بررسی عدم استفاده از سیگنال آینده؛ تأیید ثابت ماندن {len(before)} فایل ثبت‌شده و خروجی عمومی. تمام خروجی‌ها در پوشهٔ همین تحلیل ذخیره شدند.",'']
    (HERE / 'REPORT.fa.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(dict(status='PASS',daily_final_toman=daily,daily_relative_to_monthly=daily/month-1,
        daily_relative_to_quarterly=daily/quarter-1,protected_files_unchanged=len(before))),flush=True)


if __name__ == '__main__':
    main()
