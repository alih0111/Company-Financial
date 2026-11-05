"""Matched capital/date stress comparisons; no linear scaling of NAV."""
import pandas as pd
from .harness import boot
from .wave2 import panels_for, policies, frame_for
from .policy_engine import run_policy
from .engine import START
from .stages import create_run, latest, record, row, pointer, handoff, report, mdtable
from .registry import atomic_write_json


class ReducedCapacity:
    def __init__(self, prices, multiplier):
        self.prices, self.multiplier = prices, multiplier
    def __getattr__(self, key):
        return getattr(self.prices, key)
    def execution(self, sym, day):
        price, quantity, reason = self.prices.execution(sym, day)
        return price, int(quantity * self.multiplier), reason


def finalists(run, count=3):
    c = pd.read_csv(run / 'comparison.csv')
    own = c[c.scope.eq('own') & ~c.experiment_id.eq('balanced_P0')]
    baseline_dd = float(c[c.experiment_id.eq('balanced_P0')].max_drawdown.iloc[0])
    own = own.assign(within_risk=own.max_drawdown.abs().le(abs(baseline_dd) + .05))
    return own.sort_values(['within_risk', 'final_toman', 'experiment_id'], ascending=[False, False, True]).head(count).experiment_id.tolist()


def run_stress():
    panel, md, prices = boot()
    source = latest('wave2')
    names = finalists(source)
    scenarios = {'base': {}, 'double_cost': {'cost_mult': 2}, 'delay1': {'delay': 1},
                 'delay2': {'delay': 2}, 'capacity_half': {'capacity': .5},
                 'start_2022_09': {'start': '2022-09-01'}, 'start_2023_03': {'start': '2023-03-01'}}
    settings = {'source': str(source), 'finalists': names, 'selection': 'risk within5pp first; final wealth then id; at most3',
                'baselines': ['balanced_P0', 'profit_growth', 'price_momentum', 'equal_weight'], 'scenarios': scenarios,
                'additional_stress_filter_registered_now': 'relative wealth >1 and extra DD<=5pp in all six perturbed scenarios; separate from original gates'}
    out, reg, dh, sp = create_run('stress', settings, panel)
    pp = panels_for(panel, md)
    ps = policies()
    frames, pols = {}, {}
    for name in ['balanced_P0'] + names:
        sig, pid = name.rsplit('_', 1)
        pols[name] = ps[pid]
        frames[name] = frame_for(pp[ps[pid]['cadence']], sig)
    from .signals import baseline_frame
    for name in ('profit_growth', 'price_momentum'):
        pols[name], frames[name] = ps['P0'], baseline_frame(panel, name)
    pols['equal_weight'], frames['equal_weight'] = {**ps['P0'], 'model': 'equal_weight'}, frames['balanced_P0']
    rows = []
    for scenario, args in scenarios.items():
        for name, f in frames.items():
            f = f.copy()
            cap = args.get('capacity', 1)
            f['capacity_rial'] *= cap
            px = prices if cap == 1 else ReducedCapacity(prices, cap)
            kwargs = {k: v for k, v in args.items() if k != 'capacity'}
            exp = name + '__' + scenario
            payload = record(out, reg, dh, sp, exp, {'configuration': name, 'policy': pols[name], 'stress': args},
                             lambda f=f, name=name, px=px, kwargs=kwargs: run_policy(f, md, pols[name], prices=px, **kwargs))
            rows.append(row(exp, payload, configuration=name, scenario=scenario))
        print('stress done', scenario, flush=True)
    table = pd.DataFrame(rows)
    base = table[table.configuration.eq('balanced_P0')].set_index('scenario')
    table['wealth_vs_balanced'] = [r.final_toman / base.loc[r.scenario, 'final_toman'] for r in table.itertuples()]
    table['extra_drawdown_pp'] = [100 * (abs(r.max_drawdown) - abs(base.loc[r.scenario, 'max_drawdown'])) for r in table.itertuples()]
    table.to_csv(out / 'comparison.csv', index=False)
    passes = {n: bool((g.wealth_vs_balanced > 1).all() and (g.extra_drawdown_pp <= 5).all())
              for n, g in table[~table.scenario.eq('base') & table.configuration.isin(names)].groupby('configuration')}
    atomic_write_json(out / 'stress_gates.json', passes)
    pointer('stress', out)
    # Stress is registered separately; add its evidence without rewriting the source wave.
    report('RETURN_SEARCH_STRESS.fa.md', '# حساسیت نامزدهای نهایی\n\n'
           f'اجرا: `{out}`. سه نامزد طبق قاعدهٔ ثبت‌شده قبل از مشاهدهٔ stress انتخاب شدند.\n\n'
           + mdtable(table, ['configuration', 'scenario', 'start', 'end', 'final_toman', 'max_drawdown', 'wealth_vs_balanced', 'extra_drawdown_pp'])
           + '\n\nهر ردیف با ۱۰۰ میلیون و تاریخ یکسان با مبنای همان سناریو اجرا شد؛ ظرفیت متناسب با مبلغ واقعی سفارش در هر تصمیم محاسبه شد. '
           'سناریوها مستقل آماری نیستند. فیلتر اضافی استحکام (برتری سرمایه و افت در محدوده در هر stress) پیش از نتایج ثبت شد و از دروازهٔ اصلی جداست. '
           'صف و حق‌تقدم/وجه نقد رویدادها هنوز گواهی اقتصادی ندارند.\n')
    handoff('stress کامل', out, 'نمونه‌های فرصت ازدست‌رفته و گزارش نهایی')
    return out, table
