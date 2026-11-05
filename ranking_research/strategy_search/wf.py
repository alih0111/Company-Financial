"""Retrospective 24/6/6 selection with one continuous execution account."""
import json
import numpy as np
import pandas as pd

from .harness import boot
from .wave2 import policies, panels_for, frame_for
from .policy_engine import run_policy, decision_calendar
from .split import folds
from .engine import END
from .stages import create_run, latest, record, pointer, handoff, report, mdtable, row, reblock
from .registry import atomic_write_json


def window_metrics(run, exp, months):
    nav = pd.read_csv(run / 'results' / (exp + '.nav.csv'))
    lo, hi = months[0], months[-1]
    prior = nav[nav.date.str[:7].lt(lo)]
    initial = float(prior.nav_rial.iloc[-1]) if len(prior) else 1e9
    n = nav[nav.date.str[:7].between(lo, hi)].nav_rial.to_numpy()
    if not len(n):
        raise ValueError('empty window')
    n = np.r_[initial, n]
    fills = pd.read_csv(run / 'results' / (exp + '.fills.csv'))
    f = fills[fills.date.str[:7].between(lo, hi)]
    return {'wealth': float(n[-1] / n[0]),
            'dd': float((n / np.maximum.accumulate(n) - 1).min()),
            'turnover': float(f.gross_rial.sum() / n[0])}


def choose(run, configurations, fold):
    btr = window_metrics(run, 'balanced_P0', fold['train'])
    bsel = window_metrics(run, 'balanced_P0', fold['select'])
    records = []
    for exp in sorted(configurations):
        tr = window_metrics(run, exp, fold['train'])
        se = window_metrics(run, exp, fold['select'])
        passed = tr['wealth'] > 1 and abs(tr['dd']) <= abs(btr['dd']) + .05
        selectable = passed and abs(se['dd']) <= abs(bsel['dd']) + .05
        records.append({'experiment_id': exp, 'screen_pass': passed, 'selection_pass': selectable,
                        'train_wealth': tr['wealth'], 'train_dd': tr['dd'],
                        'selection_wealth': se['wealth'], 'selection_dd': se['dd'],
                        'selection_turnover': se['turnover']})
    eligible = [r for r in records if r['selection_pass']]
    eligible.sort(key=lambda r: (-r['selection_wealth'], r['selection_turnover'], r['experiment_id']))
    return (eligible[0]['experiment_id'] if eligible else 'balanced_P0'), records


def run_walk_forward(resume=None):
    panel, md, prices = boot()
    source = latest('wave2')
    configs = pd.read_csv(source / 'comparison.csv').query('scope == "own"').experiment_id.tolist()
    fs = folds(sorted(panel.decision_time.str[:7].unique()))
    settings = {'source_run': str(source), 'configurations': configs, 'folds': fs,
                'selection_rule': json.loads((source / 'wave_settings.json').read_text(encoding='utf8'))['settings']['wf'],
                'boundary_rule': 'new policy decision at last close before evaluation; next-session execution; never reset',
                'evaluation_initial_toman': 100000000, 'retrospective': True}
    out, reg, dh, sp = create_run('wf', settings, panel, resume)
    panels = panels_for(panel, md)
    union = pd.concat(panels.values(), ignore_index=True).drop_duplicates(['decision_time', 'company_id']).sort_values(['decision_time', 'company_id']).reset_index(drop=True)
    ps = policies()
    choices, scores, schedule, evidence = [], [], {}, []
    for i, fold in enumerate(fs):
        selected, ev = choose(source, configs, fold)
        sig, pid = selected.rsplit('_', 1)
        pol = ps[pid]
        start_month, end_month = fold['evaluate'][0], fold['evaluate'][-1]
        boundary = max(d for d in md.cal if d[:7] < start_month)
        dates = [d for d in decision_calendar(md, boundary, END, pol['cadence'])
                 if start_month <= d[:7] <= end_month]
        dates = sorted(set([boundary] + dates))
        p = union[union.decision_time.isin(dates)].reset_index(drop=True)
        frame = frame_for(p, sig)
        # A subsequent boundary supersedes the previous policy's last decision.
        for d in dates:
            schedule[d] = pol
        scores.append(frame.assign(fold=i))
        choices.append({'fold': i, **fold, 'chosen': selected, 'boundary_decision': boundary})
        evidence.extend([{'fold': i, **r} for r in ev])
    frame = pd.concat(scores).drop_duplicates(['decision_time', 'company_id'], keep='last').drop(columns='fold')
    start = choices[0]['boundary_decision']
    first_eval = fs[0]['evaluate'][0]
    # Discard the preparatory all-cash decision day from reported performance dates.
    def runner(f, pol, sch=None):
        r = run_policy(f, md, pol, prices=prices, start=start, end=END, policy_schedule=sch)
        r['daily_nav'] = [d for d in r['daily_nav'] if d['date'][:7] >= first_eval]
        r['holdings'] = [d for d in r['holdings'] if d['date'][:7] >= first_eval]
        from ranking_research.top10_six_month.portfolio import summarize
        r['summary'].update(summarize(r['daily_nav'], 1e9, r['orders'], r['fills']))
        r['selection_history'] = choices if sch is not None else []
        return reblock(r)
    selected = record(out, reg, dh, sp, 'selected', {'fold_choices': choices, 'policy_schedule': schedule,
                      'periods': {'start': first_eval, 'end': '2026-02'}}, lambda: runner(frame, ps['P0'], schedule))
    baseframe = frame_for(panel[panel.decision_time.ge(start)].reset_index(drop=True), 'balanced')
    baseline = record(out, reg, dh, sp, 'balanced', {'signal': 'balanced', 'policy': ps['P0'],
                      'periods': {'start': first_eval, 'end': '2026-02'}}, lambda: runner(baseframe, ps['P0']))
    comp = pd.DataFrame([row('balanced', baseline, scope='own', kind='baseline', label='balanced', baseline_id='balanced'),
                         row('selected', selected, scope='own', kind='signal', label='selected', baseline_id='balanced')])
    comp.to_csv(out / 'comparison.csv', index=False)
    pd.DataFrame(evidence).to_csv(out / 'selection_evidence.csv', index=False)
    atomic_write_json(out / 'choices.json', choices)
    from .evaluate import evaluate
    evaluate(out)
    pointer('wf', out)
    report('RETURN_SEARCH_WALK_FORWARD.fa.md', '# انتخاب زمانی با حساب پیوسته\n\n'
           f'اجرا: `{out}`. ۳ fold کامل ۲۴ ماه آموزش/غربال، ۶ ماه انتخاب، ۶ ماه ارزیابی؛ گام ۶ماه.\n\n'
           + mdtable(pd.DataFrame([{'fold': c['fold'], 'train': c['train'][0]+' تا '+c['train'][-1],
                                   'select': c['select'][0]+' تا '+c['select'][-1],
                                   'evaluate': c['evaluate'][0]+' تا '+c['evaluate'][-1], 'chosen': c['chosen']} for c in choices]))
           + '\n\n' + mdtable(comp, ['experiment_id', 'start', 'end', 'initial_toman', 'final_toman', 'net_return', 'max_drawdown', 'cost_toman'])
           + '\n\nحساب ارزیابی با ۱۰۰ میلیون از سپتامبر ۲۰۲۴ تا فوریهٔ ۲۰۲۶ ادامه یافته؛ هیچ دارایی/نقدی بین foldها ریست نشده است. '
           'تصمیم تغییر سیاست در آخرین بسته‌شدن پیش از بلوک و اجرا در جلسهٔ بعد است؛ هزینه‌ها و سفارش‌های معلق در همان دفتر می‌مانند. '
           'غربال و انتخاب از برش‌های فقط گذشتهٔ مسیرهای ثابت استفاده می‌کنند؛ موجودی تشخیصی آن مسیرها از ابتدای تاریخ آمده است. '
           'ارزیابی بیرونی حساب جدا و پیوسته دارد. تاریخ قبلاً دیده شده؛ این آزمون retrospective است. '
           'سه بلوک برای تأیید مستقل آماری کافی تلقی نمی‌شوند؛ مقدار ۴۸ماهه با این مسیر ۱۸ماهه مقایسه نمی‌شود.\n')
    handoff('walk-forward پیوسته کامل', out, 'موجودی داده/موج۳، stress و فرصت‌ها و گزارش نهایی')
    return out, comp
