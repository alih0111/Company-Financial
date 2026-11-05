"""Registration-first harness: register, execute, checkpoint, report.

Corrective 2.5 (resume and evidence persistence):
  * wave settings and the environment snapshot are written INSIDE the run
    directory before any experiment runs, and are never overwritten on resume;
  * an experiment is reused only when settings, code, data AND the hashes of
    every recorded artifact match; the reused payload is reloaded in full;
  * NAV, orders, fills, selections, cash ledger and holdings are saved with a
    schema and a content hash; completion is recorded only after every artifact
    is written and validated;
  * the money ledger is controlled: fill and ledger ids match one-to-one and
    the running cash balance reproduces from the fill stream.

Corrective 2.2 (cohort): the 'common' scope is built per date as the explicit
intersection of the baseline's and the candidate's eligible sets, asserted
equal on both frames handed to the engine, with coverage and exclusion counts
written out. It is labelled 'pair' (pairwise), never 'the common population of
all models'.
"""
import datetime as dt
import gzip
import json
import sys
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from . import ENGINE_VERSION, features, signals
from .engine import run_experiment
from .policy import FIXED_WAVE1
from .policy_engine import run_policy
from .registry import (Registry, atomic_write_json, combined_code_hash, tree_hash,
                       sha_file, read_jsonl)
from ranking_research.top10_six_month.portfolio import Prices

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'ranking_research' / 'output' / 'strategy_search'
SEED = 20261015
BASELINES = ['balanced', 'profit_growth', 'growth_value', 'growth_quality',
             'price_momentum', 'operating_growth']

NAV_SCHEMA = ['date', 'nav_rial', 'cash_rial', 'stale_positions', 'missing_marks', 'lower_mark_bound_rial']
LEDGER_SCHEMA = ['fill_id', 'date', 'cash_before_rial', 'cash_change_rial', 'cash_after_rial']


def boot():
    panel, _ = features.build()
    md = features.load_market(panel.symbol.unique())
    prices = Prices(md)
    return panel, md, prices


def money_ledger_check(result):
    """Cash ledger must reconcile to fills exactly, id by id (corrective 2.5)."""
    fills, ledger = result['fills'], result['cash_ledger']
    if len(fills) != len(ledger):
        raise AssertionError(f'fills_vs_ledger_length: {len(fills)} != {len(ledger)}')
    cash = float(result['summary']['initial_toman'] * 10)
    for f, e in zip(fills, ledger):
        if f['fill_id'] != e['fill_id'] or f['date'] != e['date']:
            raise AssertionError('fill_ledger_id_or_date_mismatch')
        delta = (-1 if f['side'] == 'buy' else 1) * f['gross_rial'] - f['fee_rial']
        if abs(delta - e['cash_change_rial']) > .01 or abs(e['cash_after_rial'] - (e['cash_before_rial'] + e['cash_change_rial'])) > .01:
            raise AssertionError('ledger_entry_inconsistent')
        if abs(cash - e['cash_before_rial']) > .01:
            raise AssertionError('ledger_running_cash_mismatch')
        cash += delta
        if cash < -.01:
            raise AssertionError('negative_cash')
    if abs(cash - result['daily_nav'][-1]['cash_rial']) > .01:
        raise AssertionError('final_cash_mismatch')
    by_day = {}
    for f in fills:
        by_day[f['date']] = by_day.get(f['date'], 0) + ((-1 if f['side'] == 'buy' else 1) * f['gross_rial'] - f['fee_rial'])
    cash = float(result['summary']['initial_toman'] * 10)
    for day in result['daily_nav']:
        cash += by_day.get(day['date'], 0)
        if abs(cash - day['cash_rial']) > .01:
            raise AssertionError('daily_cash_mismatch')
    return True


def _write_artifacts(results_dir, exp_id, payload):
    """Persist all evidence with schema; return {name: path} for hashing."""
    arts = {}
    nav = pd.DataFrame(payload['daily_nav'])
    if list(nav.columns) != NAV_SCHEMA:
        raise AssertionError(f'nav_schema_changed: {list(nav.columns)}')
    p = results_dir / f'{exp_id}.nav.csv'
    nav.to_csv(p, index=False)
    arts['nav'] = p
    fills = pd.DataFrame(payload['fills'],
                         columns=['fill_id', 'order_id', 'date', 'decision_time', 'symbol',
                                  'side', 'index_units', 'index_price_rial', 'gross_rial', 'fee_rial'])
    p = results_dir / f'{exp_id}.fills.csv'
    fills.to_csv(p, index=False)
    arts['fills'] = p
    ledger = pd.DataFrame(payload['cash_ledger'], columns=LEDGER_SCHEMA)
    p = results_dir / f'{exp_id}.cash_ledger.csv'
    ledger.to_csv(p, index=False)
    arts['cash_ledger'] = p
    orders = pd.DataFrame(payload['orders'],
                          columns=['order_id', 'decision_time', 'symbol', 'side', 'requested_units',
                                   'remaining_units', 'attempts', 'last_reason'])
    p = results_dir / f'{exp_id}.orders.csv'
    orders.to_csv(p, index=False)
    arts['orders'] = p
    sel_cols = ['decision_time', 'symbol', 'model', 'rank', 'target_weight', 'target_index_units', 'score']
    sel = pd.DataFrame(payload['selections'])
    if len(sel):
        sel = sel.copy()  # retain company_id, held_over and all refusal/decision evidence
    p = results_dir / f'{exp_id}.selections.csv'
    sel.to_csv(p, index=False)
    arts['selections'] = p
    if payload.get('holdings'):
        hold = pd.DataFrame(payload['holdings'])
        p = results_dir / f'{exp_id}.holdings.csv.gz'
        with open(p, 'wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as gz:
                hold.to_csv(gz, index=False)
        arts['holdings'] = p
    if payload.get('policy_members') is not None:
        p = results_dir / f'{exp_id}.members.json'
        atomic_write_json(p, payload['policy_members'])
        arts['members'] = p
    return arts


def _record(reg, exp_id, hypothesis, config, reason, scope, data_hash, results_dir,
            runner, settings_file):
    existing = reg.reusable(exp_id, data_hash, config)
    if existing is not None:
        # Full-payload reuse: reload every stored artifact, not just metrics.
        with gzip.open(existing['artifacts']['payload']['path'], 'rb') as fh:
            payload = pickle.load(fh)  # local artifact, content hash verified above
        payload['reused'] = True
        money_ledger_check(payload)
        return payload
    if (results_dir / f'{exp_id}.json').exists():
        raise ValueError('Existing incompatible experiment; use a NEW run directory: ' + exp_id)
    entry = reg.register(exp_id, hypothesis, config, reason, data_hash,
                         ENGINE_VERSION, SEED, config.get('periods', {'start': '2022-03', 'end': '2026-02'}),
                         settings_file=str(settings_file))
    try:
        payload = runner()
        money_ledger_check(payload)
        arts = _write_artifacts(results_dir, exp_id, payload)
        payload_file = results_dir / f'{exp_id}.payload.pkl.gz'
        with gzip.open(payload_file, 'wb') as fh:
            pickle.dump(payload, fh, protocol=5)
        arts['payload'] = payload_file
        metadata = results_dir / f'{exp_id}.json'
        atomic_write_json(metadata,
                          {'experiment_id': exp_id, 'summary': payload['summary'],
                           'blocks': payload['blocks'], 'concentration': payload['concentration'],
                           'policy_members': payload.get('policy_members', []),
                           'decision_calendar': payload.get('decision_calendar')})
        arts['metadata'] = metadata
        # completion is recorded only after artifacts exist and hash
        reg.finish(entry, 'complete', payload['summary'], arts)
        payload['reused'] = False
    except Exception as exc:  # failed attempts stay in the log, never hidden
        reg.finish(entry, 'failed', {'error': f'{type(exc).__name__}: {exc}'})
        raise
    return payload


def pairwise_common_frames(panel, cand_frame, base_frame):
    """Explicit per-date intersection of the two frames' eligible sets.

    Returns (cand_common, base_common, coverage_rows). Both output frames have
    EXACTLY the same eligible member set on every date (asserted by the caller
    via assert_cohorts_equal)."""
    cand = cand_frame.copy()
    base = base_frame.copy()
    keep_c = np.zeros(len(cand), dtype=bool)
    keep_b = np.zeros(len(base), dtype=bool)
    coverage = []
    for day, gc in cand.groupby('decision_time'):
        gb = base[base.decision_time.eq(day)]
        ec = set(gc[gc.eligible].company_id)
        eb = set(gb[gb.eligible].company_id)
        inter = ec & eb
        idx_c = gc.index[list(map(lambda c: c in inter, gc.company_id))]
        idx_b = gb.index[list(map(lambda c: c in inter, gb.company_id))]
        keep_c[idx_c] = True
        keep_b[idx_b] = True
        coverage.append({'decision_time': day, 'base_eligible': len(eb),
                         'candidate_eligible': len(ec), 'intersection': len(inter),
                         'excluded_from_base': len(eb - ec),
                         'excluded_from_candidate': len(ec - eb)})
    cand['eligible'] = cand['eligible'] & keep_c
    base['eligible'] = base['eligible'] & keep_b
    return cand, base, coverage


def assert_cohorts_equal(frame_a, frame_b, label):
    """The two frames handed to a pairwise comparison have identical eligible
    member sets per date (corrective 2.2)."""
    a = frame_a[frame_a.eligible].groupby('decision_time').company_id.apply(set)
    b = frame_b[frame_b.eligible].groupby('decision_time').company_id.apply(set)
    days = sorted(set(a.index) | set(b.index))
    for day in days:
        sa, sb = a.get(day, set()), b.get(day, set())
        if sa != sb:
            raise AssertionError(f'pairwise_cohort_mismatch {label} {day}: '
                                 f'{len(sa)} vs {len(sb)} members')
    return True


def run_wave1_corrected(resume_dir=None):
    """Corrected wave-1 rerun (corrective section 3): same settings, new run."""
    sys.stdout.reconfigure(encoding='utf8')
    out = Path(resume_dir) if resume_dir else OUT / ('wave1c_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    results_dir = out / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    panel, md, prices = boot()
    from .contract import (check_panel, check_publication, check_growth_handling,
                           check_score_frame, summarize)
    check_panel(panel)
    check_publication(panel)
    check_growth_handling(panel)

    settings = {'registered_purpose': 'wave 1 CORRECTED rerun after validity fixes (section 2)',
                'registered_before_results': True,
                'registration_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'signals': signals.wave1_list(),
                'baselines': BASELINES + ['equal_weight'],
                'policy': FIXED_WAVE1,
                'scopes': {'own': 'independent coverage of each method',
                           'pair': 'per-date intersection of baseline and candidate '
                                   'eligible sets (pairwise common cohort, corrective 2.2)'},
                'fixes_applied': ['2.1_equal_weight_correct_path', '2.2_pairwise_cohorts',
                                  '2.3_publication_and_accel_op', '2.4_market_fingerprint',
                                  '2.5_artifact_hashes_and_resume', '2.6_gate_fields',
                                  '2.7_policy_engine_contract']}
    settings_file = out / 'wave_settings.json'
    if not settings_file.exists():        # never overwrite the first registration
        atomic_write_json(settings_file, settings)
    data_hash = features.data_hash()
    reg = Registry(out)
    env_file = out / 'environment.json'
    if env_file.exists():
        prior_env = json.loads(env_file.read_text(encoding='utf8'))
        if prior_env.get('code_hash') != combined_code_hash() or prior_env.get('data_hash') != data_hash:
            raise ValueError('Code/data changed: create a new run; prior environment preserved')
    if not env_file.exists():
        atomic_write_json(env_file, {
            'engine_version': ENGINE_VERSION, 'code_hash': combined_code_hash(),
            'code_tree': tree_hash(), 'data_hash': data_hash, 'seed': SEED,
            'panel': summarize(panel), 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'real_orders': 0, 'production_changed': False})
        for rel in tree_hash():
            source = ROOT / rel
            if source.exists():
                target = out / 'registered_code' / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())

    def validate(frame):
        check_score_frame(frame)

    rows = []
    coverage_all = []

    def add(exp_id, payload, scope, kind, label, notes=None, baseline_id=None):
        m = payload['summary']
        rows.append({'experiment_id': exp_id, 'scope': scope, 'kind': kind, 'label': label,
                     'final_toman': m['final_toman'], 'cagr': m['cagr'],
                     'max_drawdown': m['max_drawdown'], 'average_cash_fraction': m['average_cash_fraction'],
                     'cost_toman': m['cost_toman'], 'turnover': m['turnover'],
                     'unfilled_orders': m['unfilled_orders'], 'notes': notes,
                     'reused': payload.get('reused'), 'baseline_id': baseline_id,
                     'top_five_share_of_positive_pnl': payload['concentration'].get('top_five_share_of_positive_pnl')})

    def policy_for_run():
        p = dict(FIXED_WAVE1)
        p['cadence'] = 'monthly'
        return p

    POL = policy_for_run()
    base_frame = signals.baseline_frame(panel, 'balanced')

    # ---- signals, own coverage and pairwise-common vs balanced
    for name in signals.SIGNALS:
        family, desc, fn, note, requirement = signals.SIGNALS[name]
        if fn is None:
            for scope in ('own', 'pair'):
                rows.append({'experiment_id': f'wave1c_{scope}_{name}', 'scope': scope,
                             'kind': 'signal', 'label': name, 'notes': f'not_tested: {note}'})
            continue
        for scope in ('own', 'pair'):
            exp_id = f'wave1c_{scope}_{name}'
            if scope == 'own':
                frame = signals.signal_frame(panel, name)
                validate(frame)
                payload = _record(reg, exp_id, desc, {'signal': name, 'scope': scope,
                                                      'policy': FIXED_WAVE1['name']},
                                  'corrected wave 1 signal, own coverage', scope,
                                  json.dumps(data_hash, sort_keys=True), results_dir,
                                  lambda f=frame: run_policy(f, md, POL, prices=prices),
                                  settings_file)
            else:
                cand = signals.signal_frame(panel, name)
                cand_c, base_c, coverage = pairwise_common_frames(panel, cand, base_frame)
                cohort = cand_c.eligible.to_numpy()
                cand_c = signals.signal_frame(panel, name, cohort=cohort)
                base_c = signals.baseline_frame(panel, 'balanced', cohort=cohort)
                assert_cohorts_equal(cand_c, base_c, exp_id)
                validate(cand_c)
                for row in coverage:
                    coverage_all.append({'experiment': name, **row})
                payload = _record(reg, exp_id, desc,
                                  {'signal': name, 'scope': 'pair_vs_balanced',
                                   'policy': FIXED_WAVE1['name']},
                                  'corrected wave 1 signal, pairwise common cohort with balanced',
                                  scope, json.dumps(data_hash, sort_keys=True), results_dir,
                                  lambda f=cand_c: run_policy(f, md, POL, prices=prices),
                                  settings_file)
                ref_id = exp_id + '_balanced_reference'
                ref = _record(reg, ref_id, 'balanced on candidate intersection',
                              {'candidate': name, 'scope': 'pair_reference', 'policy': POL},
                              'same cohort before ranking', scope, json.dumps(data_hash, sort_keys=True),
                              results_dir, lambda f=base_c: run_policy(f, md, POL, prices=prices), settings_file)
                add(ref_id, ref, scope, 'reference', ref_id)
            add(exp_id, payload, scope, 'signal', name,
                baseline_id=ref_id if scope == 'pair' else 'wave1c_own_base_balanced')
            print('done', exp_id, flush=True)

    # ---- model baselines (own + pairwise)
    for model in BASELINES:
        for scope in ('own', 'pair'):
            exp_id = f'wave1c_{scope}_base_{model}'
            if scope == 'own':
                frame = signals.baseline_frame(panel, model)
                validate(frame)
                payload = _record(reg, exp_id, f'frozen baseline {model}',
                                  {'baseline': model, 'scope': scope, 'policy': FIXED_WAVE1['name']},
                                  'reference point', scope,
                                  json.dumps(data_hash, sort_keys=True), results_dir,
                                  lambda f=frame: run_policy(f, md, POL, prices=prices),
                                  settings_file)
            else:
                cand = signals.baseline_frame(panel, model)
                cand_c, base_c, coverage = pairwise_common_frames(panel, cand, base_frame)
                cohort = cand_c.eligible.to_numpy()
                cand_c = signals.baseline_frame(panel, model, cohort=cohort)
                base_c = signals.baseline_frame(panel, 'balanced', cohort=cohort)
                assert_cohorts_equal(cand_c, base_c, exp_id)
                validate(cand_c)
                for row in coverage:
                    coverage_all.append({'experiment': f'base_{model}', **row})
                payload = _record(reg, exp_id, f'frozen baseline {model}, pairwise vs balanced',
                                  {'baseline': model, 'scope': 'pair_vs_balanced',
                                   'policy': FIXED_WAVE1['name']},
                                  'reference point on the pairwise common cohort', scope,
                                  json.dumps(data_hash, sort_keys=True), results_dir,
                                  lambda f=cand_c: run_policy(f, md, POL, prices=prices),
                                  settings_file)
                ref_id = exp_id + '_balanced_reference'
                ref = _record(reg, ref_id, 'balanced on candidate intersection',
                              {'candidate': model, 'scope': 'pair_reference', 'policy': POL},
                              'same cohort before ranking', scope, json.dumps(data_hash, sort_keys=True),
                              results_dir, lambda f=base_c: run_policy(f, md, POL, prices=prices), settings_file)
                add(ref_id, ref, scope, 'reference', ref_id)
            add(exp_id, payload, scope, 'baseline', model,
                baseline_id=ref_id if scope == 'pair' else 'wave1c_own_base_balanced')
            print('done', exp_id, flush=True)

    # ---- equal-weight baseline on the CORRECT path (corrective 2.1)
    for scope in ('own', 'pair'):
        exp_id = f'wave1c_{scope}_base_equal_weight'
        if scope == 'pair':
            # equal-weight over the balanced eligible set is identical to own;
            # record the equivalence instead of faking a second run
            rows.append({'experiment_id': exp_id, 'scope': 'pair', 'kind': 'baseline',
                         'label': 'equal_weight',
                         'notes': 'identical to own by construction: the pairwise cohort '
                                  'of balanced with itself is its own eligible set'})
            continue
        ew_pol = dict(POL)
        ew_pol['model'] = 'equal_weight'
        frame = base_frame
        payload = _record(reg, exp_id, 'equal-weight passive baseline over the balanced '
                                       'eligible universe, engine model=equal_weight',
                          {'baseline': 'equal_weight', 'scope': scope,
                           'policy': FIXED_WAVE1['name'], 'engine_model': 'equal_weight'},
                          'corrected passive reference (corrective 2.1)', scope,
                          json.dumps(data_hash, sort_keys=True), results_dir,
                          lambda: run_policy(frame, md, ew_pol, prices=prices),
                          settings_file)
        members = payload.get('policy_members') or []
        if members:
            add(exp_id, payload, scope, 'baseline', 'equal_weight',
                notes=f'members/date min={min(m["members"] for m in members)} '
                      f'max={max(m["members"] for m in members)}; weight sum=1.0')
        else:
            add(exp_id, payload, scope, 'baseline', 'equal_weight')
        print('done', exp_id, flush=True)

    comparison = pd.DataFrame(rows)
    comparison.to_csv(out / 'comparison.csv', index=False)
    atomic_write_json(out / 'comparison.json',
                      json.loads(comparison.to_json(orient='records')))
    pd.DataFrame(coverage_all).to_csv(out / 'pairwise_coverage.csv', index=False)
    from .evaluate import evaluate
    evaluate(out)
    atomic_write_json(OUT / 'latest.json', {'run_path': str(out), 'code_hash': combined_code_hash(),
                                            'data_hash': data_hash, 'real_orders': 0,
                                            'production_changed': False, 'accepted': False})
    print('wave1c_path=' + str(out), flush=True)
    return out, comparison
