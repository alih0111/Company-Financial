import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'ranking_research'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False,
                               default=str), encoding='utf8')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def checkpoint(out, stage, status='complete', **details):
    old = read(out / 'progress.json') if (out / 'progress.json').exists() else {'stages': {}}
    old['stages'][stage] = {'status': status, 'updated_at': now(), **details}
    old.update(stage=stage, status=status, real_orders=0)
    write(out / 'progress.json', old)


def legacy():
    # Existing modules are imported without displaying their connection settings.
    import os
    import sys
    sys.dont_write_bytecode = True
    os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'
    sys.path[:0] = [str(HERE), str(ROOT / 'qvt_backtest')]
    from v2_inputs import ArchiveSnapshots, feature_row, H, rtt
    import run as R
    return ArchiveSnapshots, feature_row, H, rtt, R
