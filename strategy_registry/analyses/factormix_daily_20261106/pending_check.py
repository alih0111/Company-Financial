"""Diagnostic: do identical pending targets renewing indefinitely explain daily NAV?"""
from bisect import bisect_left
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(ROOT))
from factormix.reproduce_monthly15 import load,monthly_schedule


def main():
    primary = load('daily_primary_analysis',HERE / 'run.py')
    before = primary.protected_files()
    data = dict(np.load(primary.audit.ARCHIVE / 'snapshot_data/active_inputs.npz',allow_pickle=False))
    data['p1'] = data['candidate_score']
    policy = json.loads((primary.audit.ARCHIVE / 'strategy.locked.json').read_text(encoding='utf8'))
    # This archived execution variant shares target_for and fill arithmetic. It
    # suppresses no-op instructions and preserves the expiry of identical targets.
    source = ROOT / 'strategy_registry/RFA-ReportFlow-033/v1.0.0/replay/engine.py'
    engine = load('identical_pending_expiry_control',source)
    parent = primary.audit.load_engine()
    cfg = engine.Config(**policy['portfolio']); ex = engine.Execution(**policy['execution_assumptions'])
    a = bisect_left(data['cal'].tolist(),primary.audit.START)
    b = bisect_left(data['cal'].tolist(),primary.audit.END+'~')
    schedules = [('original_quarterly',parent.calendar_schedule),('monthly_jalali_15',monthly_schedule),
                 ('daily_after_close',primary.daily_schedule)]
    declaration = dict(purpose='execution semantics sensitivity, not a new strategy or score model',
        same_frozen_factormix_scores=True,engine_sha256=primary.audit.sha(source),
        change='do not renew identical pending targets; suppress reviews requiring no orders',
        registered_models_and_accounts_unchanged=True)
    primary.audit.write_json(primary.OUT / 'pending_control_protocol.json',declaration)
    results = {}
    for label,schedule in schedules:
        review_dates = {str(data['cal'][i]) for i in schedule(data['cal'].tolist(),cfg,a,b)}
        run = engine.simulate(data,cfg,ex,start=primary.audit.START,end=primary.audit.END,
                              capital=100_000_000.,detail=True,review_dates=review_dates)
        ledger,_ = primary.audit.reconcile(data,run,ex)
        engine.save_run(primary.OUT / f'pending_control_{label}',run)
        reference = pd.read_csv(primary.OUT / f'{label}_nav.csv')
        if label != 'daily_after_close':
            np.testing.assert_allclose(run['nav'],reference.nav_toman,rtol=0,atol=1)
            np.testing.assert_allclose(run['cash'],reference.cash_toman,rtol=0,atol=.01)
        results[label] = dict(metrics=run['metrics'],fills=run['n_trades'],
            decisions=len(run['decisions']),identical_pending_preserved=sum(r['preserved_pending'] for r in run['reviews']),
            daily_ledger=ledger['daily_reconciliation'])
    assert primary.protected_files() == before
    primary.audit.write_json(primary.OUT / 'pending_control_summary.json',dict(accounts=results,protocol=declaration))
    report = HERE / 'REPORT.fa.md'
    daily = results['daily_after_close']
    text = ('\n## کنترل مستقل رفتار سفارش‌های باز\n\n'
        'در یک کنترل تشخیصی جدا، هدف‌های معلق یکسان مهلت قبلی را حفظ کردند و بررسی بدون نیاز به سفارش، دستور تازه ایجاد نکرد. امتیاز، داده و قواعد انتخاب FactorMix ثابت ماندند. هر دو مسیر فصلی و ماهانه تمام روزها و نقد را دقیقاً مانند سناریوهای اصلی بازتولید کردند. این کنترل، نسخهٔ ثبت‌شدهٔ جدیدی نیست.\n\n'
        f"روزانه در این کنترل به {daily['metrics']['final_toman']:,.0f} تومان با {daily['fills']} اجرا و افت {abs(daily['metrics']['max_drawdown']):.2%} رسید. بنابراین می‌توان دید آیا ضعف نتیجهٔ روزانه به تمدید هدف‌های یکسان وابسته بوده است یا با حفظ مهلت سفارش هم باقی می‌ماند. دفتر مستقل نقد و دارایی هر سه کنترل تأیید شد.\n")
    original = report.read_text(encoding='utf8').split('\n## کنترل مستقل رفتار سفارش‌های باز')[0]
    report.write_text(original+text,encoding='utf8')
    print(json.dumps(dict(status='PASS',accounts=results)),flush=True)


if __name__ == '__main__':
    main()
