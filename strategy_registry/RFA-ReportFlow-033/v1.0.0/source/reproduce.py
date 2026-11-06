"""Standalone replay for the versioned ReportFlow archive; no DB or network."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    import hashlib
    manifest = json.loads((root / 'MANIFEST.sha256.json').read_text('utf8'))
    for row in manifest['files']:
        p = root / row['path']
        if hashlib.sha256(p.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Archive integrity mismatch: ' + row['path'])
    spec = importlib.util.spec_from_file_location('reportflow_versioned_engine', root / 'replay/engine.py')
    engine = importlib.util.module_from_spec(spec); sys.modules[spec.name] = engine; spec.loader.exec_module(engine)
    policy = json.loads((root / 'strategy.json').read_text('utf8'))
    summary = json.loads((root / 'results/summary.json').read_text('utf8'))
    data = dict(np.load(root / 'snapshot_data/event_inputs.npz', allow_pickle=False))
    dates = pd.read_csv(root / 'results/report_events.csv').session.unique().tolist()
    cfg = engine.Config(**policy['portfolio']); ex = engine.Execution(**policy['execution'])
    run = engine.simulate(data, cfg, ex, start=policy['backtest']['requested_start'], end=policy['backtest']['end'],
                          detail=True, review_dates=dates)
    reference = pd.read_csv(root / 'results/reportflow_nav.csv')
    assert run['cal'].tolist() == reference.session.tolist()
    np.testing.assert_allclose(run['nav'], reference.nav_toman, rtol=0, atol=1)
    np.testing.assert_allclose(run['cash'], reference.cash_toman, rtol=0, atol=.01)
    assert run['n_trades'] == summary['accounts']['reportflow']['fills']
    if args.output_dir:
        if args.output_dir.exists():
            raise ValueError('Output directory must be new')
        args.output_dir.mkdir(parents=True)
        engine.save_run(args.output_dir / 'reportflow', run)
    print(json.dumps(dict(status='PASS', verified_files=len(manifest['files']), final_toman=float(run['nav'][-1]), fills=run['n_trades'])))


if __name__ == '__main__':
    main()
