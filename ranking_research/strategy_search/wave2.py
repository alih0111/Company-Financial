"""Exactly eight portfolio policies by three specified signals."""
import json
import pandas as pd

from . import signals
from .policy import FIXED_WAVE1
from .policy_engine import run_policy, decision_calendar
from .harness import boot, pairwise_common_frames, assert_cohorts_equal
from .asof_panel import build_asof_panel
from .contract import check_score_frame
from .engine import START, END
from .stages import create_run, record, row, pointer, handoff, report, mdtable

SIGNAL_NAMES = ['balanced', 'trend_fund_75', 'garp_yield_quality']


def policies():
    base = {**FIXED_WAVE1, 'cadence': 'monthly', 'model': 'score', 'holding': 'calendar'}
    changes = [{}, {'holding': 'rank_buffer', 'exit_rank_buffer': 15},
               {'holding': 'rank_buffer', 'exit_rank_buffer': 20},
               {'cadence': 'biweekly'}, {'cadence': 'weekly'}, {'cadence': 'quarterly'},
               {'weight': 'inverse_vol_capped'},
               {'holding': 'hold_until_rank_weakens', 'exit_rank_buffer': 20}]
    return {f'P{i}': {**base, **c, 'name': f'P{i}'} for i, c in enumerate(changes)}


def frame_for(panel, name, cohort=None):
    return (signals.baseline_frame(panel, 'balanced', cohort=cohort) if name == 'balanced'
            else signals.signal_frame(panel, name, cohort=cohort))


def panels_for(panel, md):
    dates = sorted(set(decision_calendar(md, START, END, 'weekly')) |
                   set(decision_calendar(md, START, END, 'biweekly')))
    asof = build_asof_panel(panel, md, [d for d in dates if d not in set(panel.decision_time)])
    all_panel = pd.concat([panel, asof], ignore_index=True).sort_values(['decision_time', 'company_id']).reset_index(drop=True)
    return {cad: all_panel[all_panel.decision_time.isin(decision_calendar(md, START, END, cad))].reset_index(drop=True)
            for cad in ('monthly', 'weekly', 'biweekly', 'quarterly')}


def run_wave2(resume=None):
    panel, md, prices = boot()
    ps = policies()
    settings = {'policies': ps, 'signals': SIGNAL_NAMES, 'max_configurations': 24,
                'risk_constraint_extra_dd': .05, 'bootstrap_block_six_months': 2,
                'asof_financials': 'latest available month-end, delayed until next snapshot',
                'P6': '60 observations, min30; zero/missing excluded, cash per missing slot; iterative 20% cap',
                'P7': 'old holdings remain; only actual free slots/cash; replacement deferred until next decision after exit',
                'stress': {'cost_multipliers': [2], 'extra_sessions': [1, 2],
                           'capacity_multiplier': .5, 'starts': ['2022-09-01', '2023-03-01']},
                'wf': {'screen': 'train return > 0 and DD <= balanced+5pp',
                       'select': 'highest net wealth with DD <= balanced+5pp; turnover then id',
                       'fallback': 'balanced_P0', 'fold': [24, 6, 6], 'step': 6}}
    out, reg, dh, sp = create_run('wave2', settings, panel, resume)
    handoff('موج دوم: تنظیمات پیش از اجرا ثبت شد', out, 'اجرای ۲۴ تنظیم و مقایسه‌های جفتی؛ سپس walk-forward، داده، stress و گزارش', True)
    panels = panels_for(panel, md)
    rows, coverage = [], []
    for pid, pol in ps.items():
        p = panels[pol['cadence']]
        b = frame_for(p, 'balanced')
        for name in SIGNAL_NAMES:
            exp = name + '_' + pid
            f = frame_for(p, name)
            check_score_frame(f)
            payload = record(out, reg, dh, sp, exp, {'signal': name, 'policy': pol, 'scope': 'own'},
                             lambda f=f, pol=pol: run_policy(f, md, pol, prices=prices))
            rows.append(row(exp, payload, signal=name, policy_id=pid, scope='own', kind='signal',
                            label='balanced' if exp == 'balanced_P0' else exp, baseline_id='balanced_P0'))
            if name != 'balanced':
                c, bc, cov = pairwise_common_frames(p, f, b)
                cohort = c.eligible.to_numpy()
                c, bc = frame_for(p, name, cohort), frame_for(p, 'balanced', cohort)
                assert_cohorts_equal(c, bc, exp)
                coverage.extend([{'experiment': exp, **v} for v in cov])
                ref_id = exp + '_pair_reference'
                for eid, ff, kind, ref in [(ref_id, bc, 'reference', None),
                                           (exp + '_pair', c, 'signal', ref_id)]:
                    pay = record(out, reg, dh, sp, eid, {'signal': name, 'policy': pol, 'scope': 'pair', 'kind': kind},
                                 lambda ff=ff, pol=pol: run_policy(ff, md, pol, prices=prices))
                    rows.append(row(eid, pay, signal=name, policy_id=pid, scope='pair', kind=kind,
                                    label=eid, baseline_id=ref))
            print('wave2 done', exp, flush=True)
            pd.DataFrame(rows).to_csv(out / 'comparison.partial.csv', index=False)
    comp = pd.DataFrame(rows)
    comp.to_csv(out / 'comparison.csv', index=False)
    pd.DataFrame(coverage).to_csv(out / 'pairwise_coverage.csv', index=False)
    from .evaluate import evaluate
    evaluate(out)
    pointer('wave2', out)
    own = comp[comp.scope.eq('own')].sort_values('final_toman', ascending=False)
    report('RETURN_SEARCH_WAVE2.fa.md', '# موج دوم: ۲۴ تنظیم ازپیش‌ثبت‌شده\n\n'
           f'اجرا: `{out}`. ثبت واقعی در wave_settings.json، پیش از اولین آزمایش.\n\n'
           'همهٔ ۸ سیاست × ۳ سیگنال اجرا شدند. جدول زیر مسیر ثابت تاریخی ۴۸ماهه است؛ انتخاب آینده‌نگر نیست. '
           'مبنای اصلی همهٔ مسیرهای طبیعی متوازن P0 است. مقایسهٔ جفتی جدا با متوازنِ همان سیاست و همان جامعه پیش از رتبه‌بندی ذخیره شد.\n\n'
           + mdtable(own, ['experiment_id', 'final_toman', 'net_return', 'max_drawdown', 'cost_toman', 'turnover', 'average_cash_fraction'])
           + '\n\nP3/P4 قیمت و حجم تازه دارند؛ صورت مالی تا snapshot ماهانهٔ بعد تأخیر دارد. ارزش بازار با نسبت قیمت خام به snapshot به‌روزرسانی می‌شود؛ '
           'تعداد سهام میان دو snapshot به طور مستقل تأیید نشده است. در ابتدای مارس ۲۰۲۲ پیش از اولین snapshot تصمیم بنیادی انجام نمی‌شود. '
           'P7 برای جایگزینی پس از خروج اجراشده تا تصمیم بعد صبر می‌کند؛ موقعیت متوقف از دفتر پاک نمی‌شود. '
           'این‌ها محدودیت شبیه‌سازی‌اند. پذیرش نهایی منوط به stress است.\n')
    handoff('موج دوم کامل', out, 'walk-forward پیوسته، ممیزی داده/موج۳، stress، فرصت‌ها و گزارش نهایی')
    return out, comp
