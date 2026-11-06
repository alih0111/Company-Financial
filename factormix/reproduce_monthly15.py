"""Offline replay of a registered monthly FactorMix package (no DB/network)."""
from bisect import bisect_left
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sys

import jdatetime
import numpy as np
import pandas as pd


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def monthly_schedule(cal, config, start, end):
    ids = {start}
    first = jdatetime.date.fromgregorian(date=pd.Timestamp(cal[start]).date())
    last = jdatetime.date.fromgregorian(date=pd.Timestamp(cal[end - 1]).date())
    for year in range(first.year, last.year + 1):
        for month in range(1, 13):
            nominal = jdatetime.date(year, month, 15).togregorian().isoformat()
            if nominal < cal[start]:
                continue
            k = bisect_left(cal, nominal)
            if start <= k < end:
                ids.add(k)
    return ids


def verify(version):
    manifest = json.loads((version / 'MANIFEST.sha256.json').read_text(encoding='utf8'))
    for item in manifest['files']:
        path = version / item['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Archive checksum mismatch: ' + item['path'])
    return len(manifest['files'])


def reproduce(version):
    count = verify(version)
    engine = load('monthly15_frozen_engine', version / 'replay/engine_snapshot.py')
    audit = load('monthly15_independent_ledger', version / 'replay/audit.py')
    policy = json.loads((version / 'strategy.locked.json').read_text(encoding='utf8'))
    expected = json.loads((version / 'results/summary.json').read_text(encoding='utf8'))
    data = dict(np.load(version / 'snapshot_data/active_inputs.npz', allow_pickle=False))
    data['p1'] = data['candidate_score']
    cfg = engine.Config(**policy['portfolio'])
    ex = engine.Execution(**policy['execution_assumptions'])
    original = engine.calendar_schedule
    for label in ['original_quarterly', 'monthly_jalali_15']:
        engine.calendar_schedule = original if label == 'original_quarterly' else monthly_schedule
        run = engine.simulate(data, cfg, ex, start=policy['replay']['requested_start'],
                              end=policy['replay']['end'], capital=100_000_000., detail=True)
        ledger, _ = audit.reconcile(data, run, ex)
        frame = pd.read_csv(version / f'results/{label}_nav.csv')
        assert run['cal'].tolist() == frame.session.tolist()
        np.testing.assert_allclose(run['nav'], frame.nav_toman, rtol=0, atol=1)
        np.testing.assert_allclose(run['cash'], frame.cash_toman, rtol=0, atol=.01)
        trades = pd.read_csv(version / f'results/{label}_trades.csv')
        assert run['n_trades'] == len(trades) == expected['accounts'][label]['fills']
        for field in ['session', 'decision', 'symbol', 'side']:
            assert [t[field] for t in run['trades']] == trades[field].tolist()
        for field in ['units', 'gross_toman', 'fee_toman', 'slippage_toman']:
            np.testing.assert_allclose([t[field] for t in run['trades']], trades[field], rtol=1e-12, atol=.01)
        assert ledger['daily_reconciliation'] == 'PASS'
    assert verify(version) == count
    result = dict(status='PASS', files_verified=count, daily_nav_cash_and_fills_reproduced=True,
                  final_toman=float(run['nav'][-1]), fills=run['n_trades'])
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version-directory', type=Path, default=Path(__file__).resolve().parents[1])
    reproduce(parser.parse_args().version_directory)
