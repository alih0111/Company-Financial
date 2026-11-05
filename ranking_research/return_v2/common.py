import datetime as dt
import json
import platform
from pathlib import Path

import pandas as pd

from ranking_research.strategy_search.registry import sha_file, atomic_write_json, tree_hash, Registry
from ranking_research.strategy_search.harness import _record

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'ranking_research/output/return_v2'
OLD = ROOT / 'ranking_research/output/strategy_search'
SOURCES = {k: OLD / v for k, v in {
    'final': 'final_20261015T154401928221Z', 'wave2': 'wave2_20261015T152128852374Z',
    'wave1': 'wave1c_20261015T151420569397Z', 'wave3': 'wave3_20261015T153641027706Z'}.items()}


def read(p):
    return json.loads(Path(p).read_text(encoding='utf8'))


def write(p, v):
    atomic_write_json(Path(p), v)


def code_tree():
    files = set(tree_hash())
    for directory in ['ranking_research/return_v2', 'canonical_postgres_v1_2_1/analytics_canonical_v1',
                      'ranking_research/top10_six_month']:
        files.update(str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / directory).glob('*.py'))
    files.update(['ranking_research/v2_inputs.py', 'ranking_research/next_stage_experiment.py',
                  'ranking_research/next_stage_preview.py', 'qvt_backtest/reconstructed_replay.py',
                  'qvt_backtest/collect_financial_history.py', 'qvt_backtest/dynamic_financial.py',
                  'qvt_backtest/paired_balance.py','qvt_backtest/legacy_financial.py','qvt_backtest/run.py',
                  'provenance_v1/codal_fs_parse.py','provenance_v1/codal_fs_fetch.py',
                  'provenance_v1/codal_publish_resolver.py','provenance_v1/complete_ranking_coverage.py',
                  'ranking_research/company_classification.py'])
    return {f: sha_file(ROOT / f) for f in sorted(files) if (ROOT / f).is_file()}


def register():
    out = BASE / ('v2_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    (out / 'results').mkdir()
    config = {'registered_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'source_runs': {k: str(v) for k, v in SOURCES.items()}, 'seed': 20261015,
              'signals': {
                  'S0': 'existing balanced', 'S1': 'existing garp_yield_quality',
                  'S2': 'rank((independent OP quarter - same quarter last year) / mean assets at current/prior year ends)',
                  'S3': 'mean ranks of S2, positive OP_TTM / proven current market cap, (OCF_TTM-net_profit_TTM)/mean_assets; all required',
                  'S4': 'rank(independent OP quarter/revenue quarter - same quarter prior year margin); current OP>0, both revenue>0',
                  'S5': 'rank(sum last3 monthly sales/same3 lastyear -1); all6 version/units/source proven; no substitute',
                  'S6': 'within20 full market sessions strictly after local INCOME publication DAY (conservative daily archive convention); S2>0; >=3 valid observations; mean ranks S2 and post-publication return',
                  'S7': 'mean S1 and rank momentum12to1 on same eligible intersection'},
              'policies': ['P0', 'P3'], 'maximum_main_configurations': 16,
              'selectors': ['existing_choose', 'two_of_three_2month_wins_then_net_wealth_dd5pp_turnover_id'],
              'selection': {'train': 24, 'select': 6, 'evaluate': 6, 'step': 6, 'fallback': 'S0_P0'},
              'holding': ['P3', 'P3_buffer20_equal', 'P3_buffer20_no_equalization_cap20'],
              'holding_selection': 'two highest net wealth candidates within each selection window; train/risk screens; policy choice only selection',
              'stress': ['double_cost', 'delay1', 'delay2', 'capacity_half', 'combined',
                         'start_plus6m', 'start_plus12m', 'capital5x', 'unknown_events_raw_price_assumption'],
              'acceptance': {'relative_wealth_min': 1.1, 'wins_majority': True, 'remove_best_log_block_positive': True,
                             'dd_extra_max': .05, 'combined_advantage_positive': True},
              'time_contract': 'decision at local civil-day end23:59:59.999999 Asia/Tehran with historical DST/fold1; daily final OHLCV known after session; known date-only publications eligible next session; next-session execution; no claim of intraday reaction',
              'quarter_contract': 'parent scope, rial, cumulative3/6/9/12 from explicit fiscal titles; subtract prior cumulative only within same fiscal year/duration; no zero fill',
              'known_missing_releases':'financial eligibility veto from publication day end for newer financial period or later unverified replacement of a selected period within existing1000-day chain horizon; metadata never supplies amounts',
              'price_contract': 'ratio endpoints must have actual positive volume/value and valid close by endpoint, <=7 calendar days old; no clipping',
              'start_rule': 'main matched window2022-03 through2026-02; expansion begins first month>=2019 with>=2 baseline eligible, determined solely from coverage before PnL; missing ten slots remain cash; full24/6/6 folds only',
              'universe': 'reconstructable locally, survivor-free not certified', 'retrospective': True,
              'real_orders': 0, 'production_changed': False, 'code_tree': code_tree(), 'python': platform.python_version()}
    write(out / 'registration.json', config)
    for rel in config['code_tree']:
        target = out / 'registered_code' / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / rel).read_bytes())
    handoff(out, 'ثبت اولیه', 'A سپس پایلوت B و ادامهٔ مراحل؛ فرایند فقط هنگام اجرای فرمان زنده است.')
    return out


def handoff(out, stage, detail):
    p = ROOT / 'docs/SOL61_RETURN_RESEARCH_HANDOFF.fa.md'
    text = (f'# تحویل پژوهش Return V2\n\nاجرا: `{out}`\n\nآخرین مرحله: {stage}\n\n{detail}\n\n'
            f'فرمان ادامهٔ پیاده‌سازی‌شده: `.venv/Scripts/python.exe -B -m ranking_research.return_v2.run all --run "{out}"`\n'
            'منابع قبلی با شناسهٔ صریح در registration.json حفظ شده‌اند. رتبه‌بندی عملیاتی و کارگزاری تغییر نکرده‌اند.\n')
    p.write_text(text, encoding='utf8')


def record(out, exp, config, runner):
    config = dict(config)
    if 'periods' not in config:
        window = read(out/'coverage_window_freeze.json')
        scope = config.get('scope')
        start,end = window['expanded_start'],window['expanded_end']
        if scope == 'ablation':
            start,end = window['old_common_start'],window['old_common_end']
        elif scope == 'holding_inner':
            end = config['cutoff']
            start = str(pd.Period(end,freq='M')-5)
        elif scope in ['evaluation','counterfactual','stress']:
            protocol = read(out/'selection_protocol.json')
            fs = protocol['folds']
            skip = config.get('args',{}).get('skip',0)
            start = fs[skip]['evaluate'][0]
            end = fs[config['fold']]['evaluate'][-1] if scope=='counterfactual' else protocol['outer_end']
        config['periods']={'start':start,'end':end,'decision_and_fill_dates':'actual timestamps in payload; boundary decision precedes initial evaluation NAV'}
    # Both new research code and data are part of the registered effective settings.
    settings = out / 'experiment_settings.json'
    if not settings.exists():
        write(settings, {'registration_sha256': sha_file(out / 'registration.json'),
                         'code_tree': code_tree(), 'data': read(out / 'data_manifest.json')})
    return _record(Registry(out), exp, exp, config, 'return_v2 registered bounded research',
                   config.get('scope', 'own'), sha_file(out / 'data_manifest.json'), out / 'results', runner, settings)


def done(out, stage):
    p = out / ('stage_' + stage + '.json')
    return p.exists() and read(p)['status'] == 'complete'


def finish(out, stage, **extra):
    write(out / ('stage_' + stage + '.json'), {'status': 'complete', 'at': dt.datetime.now(dt.timezone.utc).isoformat(), **extra})


def table(rows, path):
    pd.DataFrame(rows).to_csv(path, index=False)
