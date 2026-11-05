"""Experiment registry: pre-registered ids, code/data hashes, atomic log, resume.

Every attempt, successful or not, is appended to experiments.jsonl. A run is
reused only when its stored code+data hashes match the current hashes AND every
recorded artifact still exists with the recorded content hash, so an unchanged
rerun is cheap and any effective change forces a new experiment.

The code hash is NOT git HEAD. It hashes the working-tree bytes of every module
this package actually loads (including the frozen engine modules and the
evaluator), so uncommitted but effective edits change the hash.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import datetime as dt
import uuid
import importlib.metadata
from functools import lru_cache
from pathlib import Path

MODULES = [
    'ranking_research/top10_protocol.json',
    'ranking_research/strategy_search/registry.py',
    'ranking_research/strategy_search/contract.py',
    'ranking_research/strategy_search/features.py',
    'ranking_research/strategy_search/signals.py',
    'ranking_research/strategy_search/engine.py',
    'ranking_research/strategy_search/policy.py',
    'ranking_research/strategy_search/policy_engine.py',
    'ranking_research/strategy_search/asof_panel.py',
    'ranking_research/strategy_search/split.py',
    'ranking_research/strategy_search/benchmarks.py',
    'ranking_research/strategy_search/evaluate.py',
    'ranking_research/strategy_search/harness.py',
    'ranking_research/strategy_search/wave2.py',
    'ranking_research/strategy_search/wf.py',
    'ranking_research/strategy_search/stress.py',
    'ranking_research/strategy_search/opportunities.py',
    'ranking_research/strategy_search/gap_matrix.py',
    'ranking_research/strategy_search/wave3.py',
    'ranking_research/strategy_search/final_report.py',
    'ranking_research/strategy_search/run.py',
    'ranking_research/top10_six_month/portfolio.py',
    'ranking_research/top10_six_month/walk_forward.py',
    'ranking_research/top10_six_month/factors.py',
    'ranking_research/top10_six_month/market_adapter.py',
    'ranking_research/return_first/models.py',
    'score_v2_research/v2lib.py',
]


class RegistryError(ValueError):
    pass


def root():
    return Path(__file__).resolve().parents[2]


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def sha_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def tree_hash(paths=None):
    """Hash the working-tree bytes of the loaded modules (uncommitted included)."""
    base = root()
    out = {}
    effective = sorted(set(MODULES) | {str(p.relative_to(base)).replace('\\', '/')
                                     for p in (base / 'ranking_research/strategy_search').glob('*.py')})
    for rel in (paths or effective):
        p = base / rel
        out[rel] = sha_file(p) if p.exists() else None
    return out


@lru_cache(maxsize=1)
def runtime_versions():
    versions = {}
    for name in ('numpy', 'pandas', 'pyarrow', 'scikit-learn', 'scipy', 'joblib', 'threadpoolctl', 'matplotlib', 'psycopg'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def combined_code_hash(tree=None):
    tree = tree or tree_hash()
    blob = json.dumps({'tree': tree, 'runtime': runtime_versions()}, sort_keys=True).encode('utf8')
    return hashlib.sha256(blob).hexdigest()


def git_head():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root(),
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def atomic_write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as fh:
            json.dump(value, fh, ensure_ascii=False, indent=2, allow_nan=False, default=str)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _, diag = read_jsonl(path)
        if diag['torn_last_line']:
            raw = path.read_bytes()
            backup = path.with_name(path.name + '.torn_' + uuid.uuid4().hex)
            backup.write_bytes(raw)
            path.write_bytes(raw[:raw.rfind(b'\n') + 1])
        elif path.stat().st_size and not path.read_bytes().endswith(b'\n'):
            with path.open('ab') as fh:
                fh.write(b'\n')
    line = json.dumps(record, ensure_ascii=False, allow_nan=False, default=str)
    # Append + flush: a crash can tear only the LAST line, never a middle one.
    with path.open('a', encoding='utf8') as fh:
        fh.write(line + '\n')
        fh.flush()
        os.fsync(fh.fileno())


def read_jsonl(path):
    """Parse a JSONL log. A torn LAST line (interrupted write) is skipped and
    reported; corruption in any earlier line is a hard error, never ignored."""
    path = Path(path)
    if not path.exists():
        return [], {'torn_last_line': False}
    lines = path.read_text(encoding='utf8').splitlines()
    out, diagnostics = [], {'torn_last_line': False, 'blank_lines': 0}
    for i, line in enumerate(lines):
        if not line.strip():
            diagnostics['blank_lines'] += 1
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            if i == len(lines) - 1:
                diagnostics['torn_last_line'] = True
            else:
                raise RegistryError(f'corrupt_jsonl_line {path.name}:{i + 1}')
    return out, diagnostics


def hash_artifacts(artifacts):
    """{name: path} -> {name: {'path', 'sha256', 'bytes'}}; missing file is an error."""
    out = {}
    for name, path in (artifacts or {}).items():
        p = Path(path)
        if not p.exists():
            raise RegistryError(f'missing_artifact: {name} at {p}')
        out[name] = {'path': str(p), 'sha256': sha_file(p), 'bytes': p.stat().st_size}
    return out


def artifacts_match(stored):
    """True when every stored artifact still exists with the recorded hash."""
    for name, meta in (stored or {}).items():
        p = Path(meta['path'])
        if not p.exists() or sha_file(p) != meta['sha256']:
            return False
    return True


class Registry:
    """Append-only experiment registry rooted at a run directory."""

    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.log = self.out / 'experiments.jsonl'
        self.index = self.out / 'index.json'
        self.data_hash = None

    def register(self, experiment_id, hypothesis, config, reason, data_hash,
                 engine_version, seed, periods, settings_file=None):
        """Record an experiment BEFORE it runs. Returns the frozen registration."""
        code = tree_hash()
        entry = {
            'experiment_id': experiment_id,
            'hypothesis': hypothesis,
            'config': config,
            'reason': reason,
            'registered_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'code_hash': combined_code_hash(code),
            'code_tree': code,
            'runtime_versions': runtime_versions(),
            'git_head': git_head(),
            'data_hash': data_hash,
            'engine_version': engine_version,
            'seed': seed,
            'periods': periods,
            'settings_file': str(settings_file) if settings_file else None,
            'status': 'registered',
            'real_orders': 0,
        }
        append_jsonl(self.log, entry)
        self._merge_index(entry)
        return entry

    def finish(self, registration, status, metrics, artifacts=None):
        """Record completion ONLY after artifacts exist; their hashes are stored."""
        hashed = hash_artifacts(artifacts)
        entry = {**registration, 'status': status, 'metrics': metrics,
                 'artifacts': hashed,
                 'finished_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        append_jsonl(self.log, entry)
        self._merge_index(entry)
        return entry

    def _merge_index(self, entry):
        idx = json.loads(self.index.read_text(encoding='utf8')) if self.index.exists() else {}
        idx[entry['experiment_id']] = {k: entry.get(k) for k in
                                       ('status', 'code_hash', 'data_hash', 'registered_at',
                                        'finished_at', 'hypothesis', 'artifacts')}
        atomic_write_json(self.index, idx)

    def reusable(self, experiment_id, data_hash, config=None):
        """A completed registration with matching code+data and intact artifacts."""
        code = combined_code_hash()
        records, _ = read_jsonl(self.log)
        for entry in reversed(records):
            if (entry.get('experiment_id') == experiment_id and entry.get('status') == 'complete'
                    and entry.get('code_hash') == code and entry.get('data_hash') == data_hash):
                if (config is None or entry.get('config') == config) and entry.get('artifacts') and artifacts_match(entry.get('artifacts')):
                    return entry
        return None
