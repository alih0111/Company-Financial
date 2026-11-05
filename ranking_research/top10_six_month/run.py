"""Run with python -m ranking_research.top10_six_month.run --stage all."""
import argparse
import datetime as dt
import sys
from pathlib import Path
from .common import HERE, read, write, sha, checkpoint


def main():
    parser = argparse.ArgumentParser()
    stages = ['register', 'prepare', 'walk_forward', 'evaluate', 'compare_legacy', 'audit', 'report', 'publish']
    parser.add_argument('--stage', choices=['all', *stages], default='all')
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--reuse-prepared', type=Path, help='Register a fresh experiment using a completed frozen preparation')
    args = parser.parse_args()
    out = args.resume or HERE / 'output' / ('top10_six_month_' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    if args.resume and not (out / 'registration.json').exists(): raise ValueError('resume_registration_missing')
    out.mkdir(exist_ok=bool(args.resume), parents=True)
    print('run_path=' + str(out), flush=True)
    from .prepare import register, prepare, market
    from .portfolio import Prices
    from .walk_forward import walk_forward
    from .evaluate import evaluate
    from .audit import audit
    from .report import report
    from .publish import publish
    from .compare_legacy import compare_legacy
    prices = None
    for stage in stages if args.stage == 'all' else [args.stage]:
        previous = read(out / 'progress.json').get('stages', {}) if (out / 'progress.json').exists() else {}
        if previous.get(stage, {}).get('status') == 'complete': continue
        if stage != 'register':
            changed = [p for p, h in read(out / 'manifest.json').items() if sha(p) != h]
            if changed: raise ValueError('frozen sources changed; preserve run and register a new version: ' + ', '.join(changed[:3]))
        try:
            if stage in ['walk_forward', 'evaluate', 'compare_legacy']:
                if prices is None: prices = Prices(market(out))
                {'walk_forward': walk_forward, 'evaluate': evaluate, 'compare_legacy': compare_legacy}[stage](out, prices)
            elif stage == 'prepare' and args.reuse_prepared:
                from .reuse import reuse_prepared
                reuse_prepared(out, args.reuse_prepared)
            else: {'register': register, 'prepare': prepare, 'audit': audit, 'report': report, 'publish': publish}[stage](out)
        except Exception as exc:
            checkpoint(out, stage, 'interrupted', error_type=type(exc).__name__)
            raise
    print('completed=' + str(out), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8'); main()
