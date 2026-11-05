"""Shared registration and evidence helpers for research stages."""
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from .harness import OUT, ROOT, SEED, _record
from .registry import Registry, atomic_write_json, combined_code_hash, tree_hash, sha_file, runtime_versions
from . import ENGINE_VERSION, features


def handoff(stage, out, remaining, active=False):
    p = ROOT / 'docs/RETURN_SEARCH_HANDOFF.fa.md'
    with p.open('a', encoding='utf8') as f:
        f.write(f'\n\n## ادامهٔ حسابرسی‌شده — {dt.datetime.now(dt.timezone.utc).isoformat()}\n\n'
                f'مرحله: {stage}\n\nخروجی: `{out}`\n\n'
                f'فرایند فعال: {"اجرای پژوهش در نشست جاری" if active else "هیچ"}.\n\n'
                f'کار باقی‌مانده: {remaining}\n')


def create_run(stage, settings, panel, resume=None):
    out = Path(resume) if resume else OUT / (stage + '_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'results').mkdir(exist_ok=True)
    data = features.data_hash()
    env = {'code_hash': combined_code_hash(), 'code_tree': tree_hash(), 'data_hash': data,
           'engine_version': ENGINE_VERSION, 'seed': SEED, 'runtime_versions': runtime_versions()}
    ep, sp = out / 'environment.json', out / 'wave_settings.json'
    if ep.exists():
        old = json.loads(ep.read_text(encoding='utf8'))
        if any(old.get(k) != env[k] for k in ('code_hash', 'data_hash')):
            raise ValueError('Code/data changed: create a new run, preserve previous attempt')
        if json.loads(sp.read_text(encoding='utf8'))['settings'] != settings:
            raise ValueError('Settings changed: create a new run')
    else:
        atomic_write_json(sp, {'registered_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                              'settings': settings, 'retrospective': True})
        atomic_write_json(ep, env)
        archive = out / 'registered_code'
        for rel in env['code_tree']:
            source = ROOT / rel
            if source.exists():
                target = archive / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    return out, Registry(out), json.dumps(data, sort_keys=True), sp


def record(out, reg, dh, sp, exp_id, config, runner):
    return _record(reg, exp_id, config.get('hypothesis', exp_id), config,
                   'registered research stage', config.get('scope', 'own'), dh,
                   out / 'results', runner, sp)


def row(exp_id, payload, **extra):
    return {'experiment_id': exp_id, **payload['summary'],
            'top_five_share_of_positive_pnl': payload['concentration'].get('top_five_share_of_positive_pnl'),
            **extra}


def pointer(stage, out):
    atomic_write_json(OUT / (stage + '_latest.json'), {'run_path': str(out)})


def latest(stage):
    return Path(json.loads((OUT / (stage + '_latest.json')).read_text(encoding='utf8'))['run_path'])


def mdtable(df, cols=None):
    d = df[cols].copy() if cols else df.copy()
    def fmt(v):
        if isinstance(v, float):
            return f'{v:,.4f}'
        return str(v).replace('|', '/')
    return '| ' + ' | '.join(d.columns) + ' |\n|' + '|'.join(['---'] * len(d.columns)) + '|\n' + '\n'.join(
        '| ' + ' | '.join(fmt(v) for v in r) + ' |' for r in d.itertuples(index=False, name=None))


def report(name, text):
    (ROOT / 'docs' / name).write_text(text, encoding='utf8')


def load_payload(run, exp):
    import gzip
    import pickle
    from .registry import read_jsonl, artifacts_match
    entries, _ = read_jsonl(Path(run) / 'experiments.jsonl')
    e = next(e for e in reversed(entries) if e['experiment_id'] == exp and e['status'] == 'complete')
    if not artifacts_match(e['artifacts']):
        raise ValueError('Artifact integrity failure: ' + exp)
    with gzip.open(e['artifacts']['payload']['path'], 'rb') as f:
        return pickle.load(f)


def reblock(result):
    """Six-month evidence follows the actual evaluation window, not warmup scores."""
    from .engine import _six_month_bounds
    from ranking_research.top10_six_month.walk_forward import six_months
    nav = pd.DataFrame(result['daily_nav']).rename(columns={'date': 'decision_time'})
    bounds = [{'test_month': m, 'block_end_exclusive': e, 'model': 'score', 'cadence_months': 1}
              for m, e in _six_month_bounds(nav)]
    result['blocks'] = six_months(result['daily_nav'], bounds, result['summary']['initial_toman'] * 10)
    return result
