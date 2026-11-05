"""Machine table, limited-line scientific charts and final Persian report."""
import json
import importlib.metadata
import numpy as np
import pandas as pd
from .harness import boot, ROOT
from .stages import create_run, latest, pointer, handoff, report, mdtable
from .registry import atomic_write_json, read_jsonl, hash_artifacts
from .stress import finalists


def plot_paths(source, names, path, title):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    for name in names:
        d = pd.read_csv(source / 'results' / (name + '.nav.csv'))
        dates = pd.to_datetime(d.date)
        nav = d.nav_rial.to_numpy() / 10 / 1e6
        axes[0].plot(dates, nav, label=name, linewidth=1.6)
        dd = nav / np.maximum.accumulate(np.r_[100., nav])[1:] - 1
        axes[1].plot(dates, dd * 100, linewidth=1.2)
    axes[0].set(ylabel='Capital (million toman)', title=title)
    axes[1].set(ylabel='Drawdown (%)', xlabel='Date')
    axes[0].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def run_final():
    panel, md, _ = boot()
    sources = {s: latest(s) for s in ('wave1c', 'correction', 'wave2', 'wf', 'wave3', 'stress')}
    names = finalists(sources['wave2'])
    out, reg, dh, sp = create_run('final', {'source_runs': {k: str(v) for k,v in sources.items()},
                             'max_finalists': 3, 'chart_names': names, 'economic_certification': False}, panel)
    stress = json.loads((sources['stress'] / 'stress_gates.json').read_text(encoding='utf8'))
    rows = []
    for stage in ('wave1c', 'wave2', 'wf', 'wave3', 'stress'):
        source = sources[stage]
        comp = pd.read_csv(source / 'comparison.csv')
        records, _ = read_jsonl(source / 'experiments.jsonl')
        idx = {r['experiment_id']: r for r in records if r['status'] == 'complete'}
        evals = json.loads((source / 'evaluation.json').read_text(encoding='utf8')) if (source / 'evaluation.json').exists() else {}
        gates = {r['candidate']: r for r in evals.get('candidates', [])}
        for r in comp.to_dict('records'):
            eid = r['experiment_id']
            if eid not in idx:
                continue
            e, m = idx[eid], idx[eid]['metrics']
            ev = gates.get(eid, {})
            rows.append({**r, 'stage': stage, 'run_id': source.name, 'run_path': str(source),
                         'config_id': eid, 'data_id': e['data_hash'], 'code_id': e['code_hash'],
                         'registered_at': e['registered_at'], 'finished_at': e['finished_at'],
                         'start': m['start'], 'end': m['end'],
                         'duration_days': (pd.Timestamp(m['end'])-pd.Timestamp(m['start'])).days,
                         'initial_toman': m['initial_toman'], 'total_profit_percent': m['net_return']*100,
                         'cagr_percent': m['cagr']*100, 'max_drawdown_percent': m['max_drawdown']*100,
                         'stress_pass': stress.get(eid), 'original_gates_1to4_pass': ev.get('passes_original_gates_1to4'),
                         'research_gate_status': 'pass' if ev.get('passes_original_gates_1to4') and stress.get(eid) is True else 'not_confirmed',
                         'accepted_for_production': False, 'coverage': r.get('scope', 'see configuration'),
                         'economic_certification': False})
    machine = pd.DataFrame(rows)
    machine.to_csv(out / 'machine_comparison.csv', index=False)
    plot_paths(sources['wave2'], ['balanced_P0'] + names, out / 'fixed_paths.png', 'Fixed historical policies | 100M initial | retrospective')
    plot_paths(sources['wf'], ['balanced', 'selected'], out / 'walk_forward_paths.png', 'Continuous walk-forward | matched 18 months | retrospective')
    plot_paths(sources['wave3'], ['balanced', 'selected_ml'], out / 'ml_walk_forward_paths.png', 'ML selection | P0 policy | matched 18 months | retrospective')
    from .opportunities import samples
    opportunities = samples(panel, md, sources['wave2'], ['balanced_P0'] + names, out)
    own = pd.read_csv(sources['wave2'] / 'comparison.csv').query('scope == "own"')
    base = own[own.experiment_id.eq('balanced_P0')].iloc[0]
    top = own[own.experiment_id.isin(names)].sort_values('final_toman', ascending=False).iloc[0]
    wf = pd.read_csv(sources['wf'] / 'comparison.csv').set_index('experiment_id')
    ml = pd.read_csv(sources['wave3'] / 'comparison.csv').set_index('experiment_id')
    research_pass = machine.query('stage == "wave2" and research_gate_status == "pass" and scope == "own"')
    verdict = ('برخی نامزدها فیلترهای پژوهشی را گذراندند؛ تأیید اقتصادی/استقلال آزمون کامل نیست و ارتقای عملیاتی موجه نشده است.'
               if len(research_pass) else 'هیچ نامزد نهایی برتری لازم را در تمام فیلترهای پژوهشی و استحکام تأیید نکرد؛ ارتقای عملیاتی موجه نیست.')
    text = ('# نتیجهٔ نهایی پژوهش بازده\n\n'
            f'با ۱۰۰ میلیون تومان در بازهٔ {base.start} تا {base.end}، متوازن قبلی به **{base.final_toman/1e6:.2f} میلیون** '
            f'و بهترین ثابت تاریخی از سه نامزد نهایی، `{top.experiment_id}`، به **{top.final_toman/1e6:.2f} میلیون** رسید. '
            f'سود کل به ترتیب **{(base.final_toman/1e8-1)*100:.2f}٪** و **{(top.final_toman/1e8-1)*100:.2f}٪** است؛ '
            f'افت بیشینه از **{abs(base.max_drawdown)*100:.2f}٪** به **{abs(top.max_drawdown)*100:.2f}٪** تغییر کرد.\n\n'
            f'**وضعیت: {verdict}**\n\n'
            '## حداکثر سه نامزد\n\n'
            + mdtable(own[own.experiment_id.isin(['balanced_P0']+names)], ['experiment_id', 'final_toman', 'max_drawdown', 'cost_toman', 'turnover', 'average_cash_fraction'])
            + '\n\n## انتخاب زمانی با دورهٔ یکسان\n\n'
            f'در ۱۸ ماه ارزیابی سیاست، متوازن با ۱۰۰ میلیون به **{wf.loc["balanced","final_toman"]/1e6:.2f} میلیون** و '
            f'انتخاب زمانی به **{wf.loc["selected","final_toman"]/1e6:.2f} میلیون** رسید. '
            f'در ارزیابی مدل یادگیرنده، مبنای هم‌بازه **{ml.loc["balanced","final_toman"]/1e6:.2f} میلیون** و انتخاب مدل '
            f'**{ml.loc["selected_ml","final_toman"]/1e6:.2f} میلیون** شد. '
            'موجودی و نقد بین سه بلوک ریست نشده‌اند. برندهٔ کل چهار سال به گذشته تزریق نشده است.\n\n'
            '## پیشنهاد\n\n'
            'رتبه‌بندی عملیاتی فعلی حفظ شود. نامزدهای جدول فقط برای پژوهش و ثبت آزمون آینده مناسب‌اند؛ '
            'انتخاب روش برنده برای استفادهٔ واقعی از این تاریخ مشاهده‌شده به‌تنهایی قابل دفاع نیست. '
            'اگر فیلترهای پژوهشی هم پاس شوند، این با تأیید امکان پرشدن واقعی، جامعهٔ کامل و حسابداری رویدادها یکسان نیست.\n\n'
            '## شواهد و محدودیت‌ها\n\n'
            f'همهٔ جدول‌ها: `{out / "machine_comparison.csv"}`؛ '
            f'نمونه‌های نماد/گزارش/دلیل نخریدن/نقد/عدم‌پرشدن: `{out / "missed_opportunities.csv"}`.\n\n'
            + mdtable(opportunities.head(12), ['configuration', 'symbol', 'decision_time', 'six_month_return', 'reason', 'cash_fraction', 'order_reasons'])
            + '\n\nفرصت‌های آینده‌بین فقط تشخیص‌اند و ورودی مدل نیستند. درصد بازده آن‌ها هزینه/پرشدن را گواهی نمی‌کند. '
            'اثر داده، فرمول، جامعه، ظرفیت و هزینه در گزارش اصلاح موج اول با counterfactual عددی آمده است؛ '
            'اثر مستقل نقد یا «باقیمانده» به عامل دلخواه نسبت داده نشده. '
            'آرشیو جامعهٔ حذف‌شده را تأیید نمی‌کند؛ اندازه و جهت سوگیری برای هر روش نامعلوم است. '
            'طبقه‌بندی صنعت از ۲۰۲۶، انتشار ناقص رکوردهای DB، معنای تأییدنشدهٔ بیشتر رویدادها و نبود دفتر مستقل وجه نقد/حق‌تقدم مانع تأیید اقتصادی‌اند. '
            'سود نقدی دوباره روی قیمت تعدیل‌شده جمع نشده است. تمام تاریخ retrospective است؛ CI تک‌نامزد پس از جست‌وجوی متعدد تأیید مستقل نیست.\n\n'
            '## نمودارها\n\n'
            f'![مسیرهای ثابت]({out / "fixed_paths.png"})\n\n'
            f'![انتخاب زمانی]({out / "walk_forward_paths.png"})\n\n'
            f'![انتخاب مدل]({out / "ml_walk_forward_paths.png"})\n')
    report('RETURN_SEARCH_FINAL.fa.md', text)
    atomic_write_json(out / 'delivery_manifest.json', {
        'sources': {k: str(v) for k,v in sources.items()}, 'artifacts': hash_artifacts({p.name:p for p in out.iterdir() if p.is_file()}),
        'dependencies': {n: importlib.metadata.version(n) for n in ('numpy','pandas','scikit-learn','scipy','matplotlib')},
        'accepted_for_production': False, 'real_orders': 0, 'production_changed': False, 'verdict': verdict})
    pointer('final', out)
    handoff('پژوهش و تحویل نهایی کامل', out, 'مرحلهٔ اجرایی باقی نمانده؛ محدودیت‌های اقتصادی/داده و آزمون آینده در گزارش ثبت شده‌اند. بازتولید: python -B -m ranking_research.strategy_search.run all')
    print(text.split('## حداکثر')[0], flush=True)
    return out
