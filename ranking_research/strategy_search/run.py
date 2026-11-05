"""CLI for the return-search stages.

    .venv/Scripts/python.exe -B -m ranking_research.strategy_search.run wave1c
    .venv/Scripts/python.exe -B -m ranking_research.strategy_search.run wave1c --resume RUN_PATH
    .venv/Scripts/python.exe -B -m ranking_research.strategy_search.run wave2
    .venv/Scripts/python.exe -B -m ranking_research.strategy_search.run wf
    .venv/Scripts/python.exe -B -m ranking_research.strategy_search.run evaluate RUN_PATH
"""
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['all', 'wave1c', 'wave2', 'wf', 'evaluate', 'stress', 'wave3', 'final', 'correction'])
    parser.add_argument('--resume', type=Path, default=None)
    parser.add_argument('rest', nargs='*', default=None)
    args = parser.parse_args()
    if args.rest:
        if args.stage == 'evaluate' and len(args.rest) == 1 and args.resume is None:
            args.resume = Path(args.rest[0])
        else:
            parser.error('unexpected positional arguments')
    sys.stdout.reconfigure(encoding='utf8')
    if args.stage == 'all':
        from .harness import run_wave1_corrected
        from .correction import run_correction
        from .wave2 import run_wave2
        from .wf import run_walk_forward
        from .wave3 import run_wave3
        from .stress import run_stress
        from .final_report import run_final
        from .stages import pointer
        path, _ = run_wave1_corrected(args.resume)
        pointer('wave1c', path)
        run_correction(path)
        run_wave2()
        run_walk_forward()
        run_wave3()
        run_stress()
        run_final()
    elif args.stage == 'wave1c':
        from .harness import run_wave1_corrected
        from .stages import pointer
        path, _ = run_wave1_corrected(args.resume)
        pointer('wave1c', path)
    elif args.stage == 'wave2':
        from .wave2 import run_wave2
        run_wave2(args.resume)
    elif args.stage == 'wf':
        from .wf import run_walk_forward
        run_walk_forward(args.resume)
    elif args.stage == 'evaluate':
        from .evaluate import evaluate
        result, table = evaluate(str(args.resume) if args.resume else None)
        print(result['verdict'])
    elif args.stage == 'stress':
        from .stress import run_stress
        run_stress()
    elif args.stage == 'wave3':
        from .wave3 import run_wave3
        run_wave3()
    elif args.stage == 'final':
        from .final_report import run_final
        run_final()
    elif args.stage == 'correction':
        from .correction import run_correction
        from .stages import latest
        run_correction(latest('wave1c'))
    else:
        print(f'unknown stage: {args.stage}', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
