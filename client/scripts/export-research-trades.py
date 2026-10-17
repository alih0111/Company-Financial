"""Export the frozen S2 ledger without replaying or changing research."""
import csv
import gzip
import hashlib
import json
import pickle
from pathlib import Path

root = Path(__file__).resolve().parents[2]
run = root / 'ranking_research/output/return_v6/v6_20261016T144712827439Z'
with (run / 'reused_paths.csv').open(encoding='utf-8') as f:
    source = next(r for r in csv.DictReader(f) if r['method'] == 'S2_publication')
path = Path(source['source_run']) / 'results' / (source['experiment'] + '.payload.pkl.gz')
digest = hashlib.sha256(path.read_bytes()).hexdigest()
assert digest == source['sha256'], 'Source ledger hash mismatch'
with gzip.open(path, 'rb') as f:
    payload = pickle.load(f)
fills = [r for r in payload['fills'] if r['date'] <= '2026-02-25']
assert all(r['side'] in ('buy', 'sell') and r['decision_time'] < r['date'] for r in fills)
result = dict(schema_version=1, run_id=run.name, method='S2_publication', source_sha256=digest,
              source_path=str(path.relative_to(root)), start='2024-10-30', end='2026-02-25', fills=fills)
(root / 'client/public/research/return-v6-trades.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'fills': len(fills), 'source_sha256': digest}))
