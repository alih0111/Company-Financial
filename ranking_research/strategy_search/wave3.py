"""Twelve fixed ML settings, all preprocessing fitted inside each past fold."""
from bisect import bisect_right, bisect_left
import json
import numpy as np
import pandas as pd

from . import signals
from .harness import boot
from .split import folds
from .wave2 import policies, frame_for
from .contract import check_labels_mature
from .policy_engine import run_policy
from .engine import END
from .stages import create_run, record, pointer, handoff, report, mdtable, row, reblock
from .registry import atomic_write_json
from .gap_matrix import inventory

INPUTS = ['momentum_12_1', 'mom_6_1', 'operating_improvement', 'operating_yield',
          'cash_multi', 'debt_ratio', 'vol_60', 'sales_yoy']


def configurations():
    return {f'{family}_h{h}_c{i}': {'family': family, 'horizon': h, 'complexity': v}
            for family, vals in [('ridge', [.1, 10., 1000.]), ('tree', [1, 2, 3])]
            for h in (1, 3) for i, v in enumerate(vals)}


def make_labels(panel, md, prices, horizon):
    rows = []
    eligible, *_ = signals.base_masks_for(panel, 'hybrid')
    for r in panel[eligible].itertuples():
        entry_idx = bisect_right(md.cal, r.decision_time)
        end = (pd.Timestamp(r.decision_time) + pd.DateOffset(months=horizon)).date().isoformat()
        exit_idx = bisect_left(md.cal, end)
        if entry_idx >= len(md.cal) or exit_idx >= len(md.cal) or md.cal[exit_idx] > END:
            continue
        entry, exit_day = md.cal[entry_idx], md.cal[exit_idx]
        p0, _, _ = prices.execution(r.symbol, entry)
        p1, _, _ = prices.execution(r.symbol, exit_day)
        if not p0 or not p1:
            continue
        rows.append({'decision_time': r.decision_time, 'company_id': r.company_id,
                     'actual_label_end_time': exit_day, 'target_return': p1 / p0 - 1})
    labels = pd.DataFrame(rows)
    labels['target_rank'] = labels.groupby('decision_time').target_return.rank(pct=True)
    return labels


def estimator(cfg):
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    from sklearn.tree import DecisionTreeRegressor
    model = (Ridge(alpha=cfg['complexity']) if cfg['family'] == 'ridge'
             else DecisionTreeRegressor(max_depth=cfg['complexity'], min_samples_leaf=30, random_state=20261015))
    return make_pipeline(SimpleImputer(strategy='median', keep_empty_features=True), StandardScaler(), model)


def predict_frame(model, panel):
    f = panel[['decision_time', 'company_id', 'symbol', 'capacity_rial']].copy()
    mask, *_ = signals.base_masks_for(panel, 'hybrid')
    vals = model.predict(panel[INPUTS].replace([np.inf, -np.inf], np.nan))
    f['eligible'] = mask & np.isfinite(vals)
    f['score'] = vals
    return f


def run_wave3():
    panel, md, prices = boot()
    configs = configurations()
    fs = folds(sorted(panel.decision_time.str[:7].unique()))
    settings = {'configurations': configs, 'features': INPUTS, 'folds': fs,
                'policy': policies()['P0'], 'minimum_training_dates': 18,
                'minimum_training_companies': 30, 'minimum_training_rows': 500,
                'selection': 'highest validation net wealth with DD<=balanced+5pp; turnover then id; fallback balanced P0',
                'label': 'next session open to first session on/after horizon; actual executable-price dates; rank within decision date',
                'limits': 'retrospective diagnostics; 3 evaluation blocks do not provide independent confirmation'}
    out, reg, dh, sp = create_run('wave3', settings, panel)
    db, matrix = inventory(panel, md, out)
    labels = {h: make_labels(panel, md, prices, h) for h in (1, 3)}
    for h, lab in labels.items():
        lab.to_parquet(out / f'labels_h{h}.parquet', index=False)
    ps = policies()['P0']
    pred_by_config = {name: [] for name in configs}
    selected_frames, choices, evidence = [], [], []
    for fold_id, fold in enumerate(fs):
        train_cut = max(d for d in md.cal if d[:7] <= fold['train'][-1])
        select_start = max(d for d in md.cal if d[:7] < fold['select'][0])
        boundary = max(d for d in md.cal if d[:7] < fold['evaluate'][0])
        # Boundary report is known by the policy switch close; training stays before selection.
        valid_panel = panel[panel.decision_time.ge(select_start) & panel.decision_time.le(boundary)].reset_index(drop=True)
        eval_panel = panel[panel.decision_time.ge(boundary) & panel.decision_time.str[:7].le(fold['evaluate'][-1])].reset_index(drop=True)
        bval = frame_for(valid_panel, 'balanced')
        base = record(out, reg, dh, sp, f'fold{fold_id}_validation_balanced', {'fold': fold, 'role': 'validation_baseline'},
                      lambda: run_policy(bval, md, ps, prices=prices, start=select_start, end=boundary))
        candidates = []
        for name, cfg in configs.items():
            labs = labels[cfg['horizon']]
            labs = labs[labs.decision_time.str[:7].isin(fold['train']) & labs.actual_label_end_time.le(train_cut)]
            check_labels_mature(labs, train_cut, cfg['horizon'])
            train = panel.merge(labs, on=['decision_time', 'company_id'], how='inner')
            ok, *_ = signals.base_masks_for(train, 'hybrid')
            train = train[ok]
            counts = {'dates': int(train.decision_time.nunique()), 'companies': int(train.company_id.nunique()), 'rows': len(train)}
            enough = counts['dates'] >= 18 and counts['companies'] >= 30 and counts['rows'] >= 500
            ev = {'fold': fold_id, 'config': name, **counts, 'training_cutoff': train_cut,
                  'latest_label_end': str(train.actual_label_end_time.max()), 'sufficient_for_fit': enough}
            if not enough:
                evidence.append(ev)
                continue
            model = estimator(cfg)
            x = train[INPUTS].replace([np.inf, -np.inf], np.nan)
            model.fit(x, train.target_rank)
            import joblib
            joblib.dump(model, out / f'model_{fold_id}_{name}.joblib')
            vf, ef = predict_frame(model, valid_panel), predict_frame(model, eval_panel)
            pred_by_config[name].append(ef)
            payload = record(out, reg, dh, sp, f'fold{fold_id}_validation_{name}', {'fold': fold, 'config': cfg, 'role': 'validation'},
                             lambda vf=vf: run_policy(vf, md, ps, prices=prices, start=select_start, end=boundary))
            m = payload['summary']
            passes = abs(m['max_drawdown']) <= abs(base['summary']['max_drawdown']) + .05
            ev.update(validation_final=m['final_toman'], validation_dd=m['max_drawdown'], selectable=passes)
            evidence.append(ev)
            if passes:
                candidates.append((m['final_toman'], m['turnover'], name, ef))
        candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
        if candidates:
            _, _, chosen, ef = candidates[0]
        else:
            chosen, ef = 'balanced_P0', frame_for(eval_panel, 'balanced')
        selected_frames.append(ef)
        choices.append({'fold': fold_id, 'chosen': chosen, 'train_cutoff': train_cut,
                        'selection_end': boundary, 'evaluate': fold['evaluate']})
        print('wave3 fold', fold_id, chosen, flush=True)
    start = choices[0]['selection_end']
    first_eval = fs[0]['evaluate'][0]
    def combined(frames):
        return pd.concat(frames).drop_duplicates(['decision_time', 'company_id'], keep='last').reset_index(drop=True)
    def runner(frame):
        r = run_policy(frame, md, ps, prices=prices, start=start)
        r['daily_nav'] = [d for d in r['daily_nav'] if d['date'][:7] >= first_eval]
        from ranking_research.top10_six_month.portfolio import summarize
        r['summary'].update(summarize(r['daily_nav'], 1e9, r['orders'], r['fills']))
        return reblock(r)
    rows = []
    frames_to_run = {'selected_ml': combined(selected_frames),
                     'balanced': frame_for(panel[panel.decision_time.ge(start)].reset_index(drop=True), 'balanced')}
    frames_to_run.update({name: combined(ff) for name, ff in pred_by_config.items() if len(ff) == len(fs)})
    for name, f in frames_to_run.items():
        p = record(out, reg, dh, sp, name, {'name': name, 'role': 'continuous_evaluation', 'folds': fs}, lambda f=f: runner(f))
        rows.append(row(name, p, label='balanced' if name == 'balanced' else name, scope='own',
                        kind='baseline' if name == 'balanced' else 'signal', baseline_id='balanced'))
    comp = pd.DataFrame(rows)
    comp.to_csv(out / 'comparison.csv', index=False)
    pd.DataFrame(evidence).to_csv(out / 'training_evidence.csv', index=False)
    atomic_write_json(out / 'choices.json', choices)
    from .evaluate import evaluate
    evaluate(out)
    pointer('wave3', out)
    report('RETURN_SEARCH_WAVE3.fa.md', '# موج سوم و ممیزی واقعی داده\n\n'
           f'اجرا: `{out}`. ۱۲ تنظیم ثبت‌شده؛ ۲ خانواده × ۲ افق × ۳ شدت. سیاست همگی P0.\n\n'
           + mdtable(comp, ['experiment_id', 'start', 'end', 'final_toman', 'net_return', 'max_drawdown', 'cost_toman'])
           + '\n\n' + mdtable(pd.DataFrame([{'fold': c['fold'], 'chosen': c['chosen'], 'cutoff': c['train_cutoff']} for c in choices]))
           + '\n\nتمام imputer، scaler و مدل‌ها فقط داخل آموزش هر fold برازش شدند. برچسب نارس حذف شد؛ '
           'training_evidence.csv تعداد ماه/شرکت/ردیف و آخرین پایان واقعی label را ثبت می‌کند. '
           'انتخاب از بازده خالص شبیه‌سازی پنجرهٔ انتخاب است؛ هر مسیر ارزیابی ۱۸ماهه پیوسته اجرا شد. '
           'نمونه‌های انتخاب و ارزیابی پس از مرز پایان افق وارد آموزش نشده‌اند. '
           'مدل‌ها و labels محلی برای بازبینی ذخیره شدند. این تاریخ قبلاً مشاهده شده و نتیجه تأیید مستقل نیست.\n\n'
           'data_gap_matrix.csv موجودی محلی/DB را ثبت می‌کند. گزارش‌های قدیمی‌تر واقعاً وجود دارند؛ '
           'اما افزودن صرف دورهٔ مالی بدون بازسازی منشأ/انتشار/اصلاحیه مجاز نیست. '
           'صنعت تاریخی از ۲۰۲۶ شروع می‌شود، جامعهٔ حذف‌شده تأیید نشده و بیشتر رویدادها معنای اقتصادی تأییدشده ندارند. '
           'این کمبودها را حجم ردیف زیاد برطرف نمی‌کند. اعتبارنامه/خرید جدیدی استفاده نشد.\n')
    handoff('موج سوم و ماتریس شکاف داده کامل', out, 'stress، نمونه‌های فرصت ازدست‌رفته و گزارش نهایی')
    return out, comp
