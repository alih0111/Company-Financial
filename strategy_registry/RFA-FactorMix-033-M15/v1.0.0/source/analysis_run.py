"""Change only frozen FactorMix's review calendar to Jalali month day 15.

All output is isolated from registered policies, live and paper accounts.
The archived engine is loaded verbatim; only its in-memory schedule function
is substituted for the counterfactual after reproducing the original result.
"""
from bisect import bisect_left
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import jdatetime
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'artifacts'
spec = importlib.util.spec_from_file_location(
    'original_factormix_1401_audit', HERE.parent / 'replay_1401_20261106/run.py')
audit = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)


def monthly_schedule(cal, config, start, end):
    """Same explicit initial investment, then first session on/after each 15th."""
    ids = {start}
    first = jdatetime.date.fromgregorian(date=pd.Timestamp(cal[start]).date())
    last = jdatetime.date.fromgregorian(date=pd.Timestamp(cal[end - 1]).date())
    for year in range(first.year, last.year + 1):
        for month in range(1, 13):
            nominal = jdatetime.date(year, month, 15).togregorian().isoformat()
            # Do not map a pre-window month's review onto the initial session.
            if nominal < cal[start]:
                continue
            k = bisect_left(cal, nominal)
            if start <= k < end:
                ids.add(k)
    return ids


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive_count = audit.verify_archive()
    policy = json.loads((audit.ARCHIVE / 'strategy.locked.json').read_text(encoding='utf8'))
    raw = dict(np.load(audit.ARCHIVE / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    data = {**raw, 'p1': raw['candidate_score']}
    engine = audit.load_engine()
    cfg = engine.Config(**policy['portfolio'])
    execution = engine.Execution(**policy['execution_assumptions'])
    protocol = dict(
        declared_at_utc=datetime.now(timezone.utc).isoformat(),
        registered_strategy=policy['registry_id'], requested_start=audit.START,
        end=audit.END, initial_toman=audit.CAPITAL,
        only_change='review calendar: Jalali day 15, first following stock session if closed',
        initial_entry='same explicit initial decision as original, then monthly reviews',
        decision='after close; earliest fill next stock session; unchanged execution rules',
        unchanged=['archived candidate_score', 'market data', 'portfolio rules', 'costs', 'fill rules'],
        input_sha256=audit.sha(audit.ARCHIVE / 'snapshot_data/active_inputs.npz'),
        policy_sha256=audit.sha(audit.ARCHIVE / 'strategy.locked.json'),
        engine_sha256=audit.sha(audit.ARCHIVE / 'replay/engine_snapshot.py'),
        no_retuning_or_live_account_writes=True, calendar_chosen_by_user=True)
    audit.write_json(OUT / 'protocol.json', protocol)
    reference = json.loads((HERE.parent / 'replay_1401_20261106/artifacts/summary.json').read_text(encoding='utf8'))
    original_schedule = engine.calendar_schedule
    accounts = {}
    for label in ['original_quarterly', 'monthly_jalali_15']:
        engine.calendar_schedule = original_schedule if label == 'original_quarterly' else monthly_schedule
        run = engine.simulate(data, cfg, execution, start=audit.START, end=audit.END,
                              capital=audit.CAPITAL, detail=True)
        ledger, trades = audit.reconcile(data, run, execution)
        if label == 'original_quarterly':
            expected = pd.read_csv(HERE.parent / 'replay_1401_20261106/artifacts/candidate_nav.csv')
            assert run['cal'].tolist() == expected.session.tolist()
            np.testing.assert_allclose(run['nav'], expected.nav_toman.to_numpy(), rtol=0, atol=1)
            np.testing.assert_allclose(run['nav'][-1], reference['accounts']['candidate']['metrics']['final_toman'], rtol=0, atol=1)
        engine.save_run(OUT / label, run)
        pd.DataFrame(trades).to_csv(OUT / f'{label}_ledger.csv', index=False, encoding='utf-8-sig')
        a = bisect_left(data['cal'].tolist(), audit.START)
        b = bisect_left(data['cal'].tolist(), audit.END + '~')
        schedule = engine.calendar_schedule(data['cal'].tolist(), cfg, a, b)
        assert len(schedule) == len(run['decisions']) + run['stale_decisions_skipped']
        reviews = []
        for i in sorted(schedule):
            day = str(data['cal'][i])
            jd = jdatetime.date.fromgregorian(date=pd.Timestamp(day).date())
            initial = i == a
            nominal = None if initial else jdatetime.date(jd.year, jd.month, 15).togregorian().isoformat()
            if label == 'monthly_jalali_15' and not initial:
                assert jd.day >= 15
                assert i == bisect_left(data['cal'].tolist(), nominal)
            reviews.append(dict(session=day, jalali=str(jd), initial_entry=initial,
                                nominal_day_15=nominal if label == 'monthly_jalali_15' else None,
                                score_age=int(data['score_age'][i]), signal_date=str(data['signal_dates'][i])))
        pd.DataFrame(reviews).to_csv(OUT / f'{label}_review_schedule.csv', index=False, encoding='utf-8-sig')
        # Archived financial signal rows remain bounded by the current date.
        assert np.all(data['signal_dates'][a:b] <= data['cal'][a:b])
        accounts[label] = dict(metrics=run['metrics'], annual=audit.annual_rows(run),
            reviews_scheduled=len(schedule), decisions=len(run['decisions']),
            stale_decisions_skipped=run['stale_decisions_skipped'], fills=run['n_trades'],
            fees_toman=run['cost_toman'], slippage_toman=run['slippage_toman'],
            first_fill=run['trades'][0]['session'], ledger=ledger)
        print(json.dumps(dict(case=label, **{k:v for k,v in accounts[label].items() if k not in ['ledger', 'annual']})), flush=True)
    engine.calendar_schedule = original_schedule
    assert audit.verify_archive() == archive_count
    baseline = accounts['original_quarterly']['metrics']['final_toman']
    monthly = accounts['monthly_jalali_15']['metrics']['final_toman']
    summary = dict(initial_toman=audit.CAPITAL, start_jalali=audit.jalali(data['cal'][a]),
        end_jalali=audit.jalali(audit.END), accounts=accounts,
        monthly_minus_original_toman=monthly-baseline,
        monthly_vs_original_terminal_fraction=monthly/baseline-1,
        archive_files_verified=archive_count, original_daily_nav_reproduced=True,
        registered_strategy_unchanged=True, no_live_or_paper_account_writes=True,
        limitations=reference['limitations'],
        same_archived_information_not_daily_reportflow_inputs=True)
    audit.write_json(OUT / 'summary.json', summary)
    lines = ['# FactorMix با بازبینی پانزدهم هر ماه', '',
        f"سرمایهٔ اولیه: ۱۰۰ میلیون تومان؛ بازه: {summary['start_jalali']} تا {summary['end_jalali']}.", '',
        'فقط تقویم بازبینی تغییر کرده است. امتیازهای آرشیوشده، قیمت‌ها، نگهداری تا رتبهٔ ۸، باند تغییر وزن ۵ واحد درصد و قواعد اجرای نسخهٔ اصلی ثابت‌اند. ورود اولیه در هر دو حالت یکسان است؛ سپس بازبینی پس از پایان اولین جلسهٔ معاملاتی در روز ۱۵ یا بعد از آن انجام می‌شود. اولین فرصت اجرا جلسهٔ بعد است. تغییر سبد فقط در صورت نیاز طبق قواعد اصلی انجام می‌شود.', '',
        '| حالت | ارزش پایان، تومان | بازده کل | بیشترین افت | اجراهای خرید و فروش |',
        '|---|---:|---:|---:|---:|']
    for label, title in [('original_quarterly','FactorMix اصلی، فصلی +۴۰ روز'), ('monthly_jalali_15','FactorMix، پانزدهم هر ماه')]:
        row = accounts[label]; m = row['metrics']
        lines.append(f"| {title} | {m['final_toman']:,.0f} | {m['total_return']:.2%} | {m['max_drawdown']:.2%} | {row['fills']} |")
    lines += ['', f'اختلاف ارزش پایان با نسخهٔ اصلی: {monthly-baseline:,.0f} تومان ({monthly/baseline-1:.2%}).', '',
        'هزینه‌ها در ارزش پایان کسر شده‌اند: کارمزد ۰٫۵٪ و لغزش ۰٫۱٪ برای هر سمت معامله، با همان سقف حجم و محدودیت‌های نسخهٔ اصلی.', '',
        '| سال | پایان سال نسخهٔ اصلی، تومان | پایان سال ماهانه، تومان | بازده سال نسخهٔ ماهانه |',
        '|---|---:|---:|---:|']
    for original, changed in zip(accounts['original_quarterly']['annual'], accounts['monthly_jalali_15']['annual']):
        lines.append(f"| {original['year']} | {original['final_toman']:,.0f} | {changed['final_toman']:,.0f} | {changed['return_fraction']:.2%} |")
    monthly_account = accounts['monthly_jalali_15']
    lines += ['', f"در حالت ماهانه {monthly_account['reviews_scheduled']} نوبت بررسی شامل ورود اولیه وجود داشت؛ {monthly_account['decisions']} نوبت به تصمیم رسید. دو نوبت در ۱۶ تیر و ۱۵ مهر ۱۴۰۵ به علت عمر بیش از ۴۵ روز امتیاز آرشیوشده، طبق محدودیت خودِ نسخهٔ اصلی، کنار گذاشته شدند. اطلاعات بنیادی با داده‌های روزانهٔ ReportFlow جایگزین نشده است.", '',
        'سال ۱۴۰۵ تا ۱۳ آبان است. بازده‌ها تاریخی و اسمی‌اند. این مقایسه از همان داده‌ها و محدودیت‌های FactorMix اصلی استفاده می‌کند: زمان دریافت واقعی همهٔ گزارش‌های تاریخی اثبات نشده، جهان نمادها ثابت و واحدهای قیمت تعدیل‌شده کسری‌اند. انتخاب اولیهٔ مدل از بخشی از همین تاریخ تأثیر گرفته است؛ نتیجه، تضمین عملکرد آینده نیست.', '',
        f'کنترل‌ها: بازتولید تمام روزهای منحنی سرمایهٔ نسخهٔ اصلی؛ تطبیق مستقل نقد و دارایی هر دو سناریو؛ کنترل تاریخ اجرا و کارمزد و سقف حجم؛ تأیید هش {archive_count} فایل آرشیو قبل و بعد. هیچ تغییری در استراتژی‌های ثبت‌شده یا حساب کاغذی/واقعی اعمال نشد.', '']
    (HERE / 'REPORT.fa.md').write_text('\n'.join(lines), encoding='utf8')
    print(json.dumps(dict(status='PASS', difference_toman=monthly-baseline,
                          relative_terminal_change=monthly/baseline-1, archive_files_verified=archive_count)), flush=True)


if __name__ == '__main__':
    main()
