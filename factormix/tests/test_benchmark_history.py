import gzip
import hashlib
import json
from pathlib import Path

import pytest

from factormix.benchmark_history import SOURCE,parse_index


@pytest.fixture()
def responses():
    return (json.loads(gzip.decompress((SOURCE/'tedpix.raw.json.gz').read_bytes())),
            json.loads(gzip.decompress((SOURCE/'index-identity.raw.json.gz').read_bytes())))


def test_official_receipts_identity_and_first_last_values(responses):
    for name in ['tedpix','index-identity']:
        receipt=json.loads((SOURCE/f'{name}.receipt.json').read_text(encoding='utf8'))
        raw=gzip.decompress((SOURCE/f'{name}.raw.json.gz').read_bytes())
        assert hashlib.sha256(raw).hexdigest()==receipt['sha256']
        assert receipt['url'].startswith('https://cdn.tsetmc.com/api/Index/')
    rows=parse_index(*responses)
    assert len(rows)==1108
    assert rows[0]==dict(date='2022-03-26',closing_price=1390859.7)
    assert rows[-1]==dict(date='2026-11-04',closing_price=7912741.2)


def test_wrong_index_and_conflicting_duplicates_are_refused(responses):
    history,identity=responses
    identity['indexB1']=[dict(insCode='32097828799138957',lVal30='شاخص دیگر')]
    with pytest.raises(RuntimeError,match='identity'):parse_index(history,identity)
    identity['indexB1'][0]['lVal30']='شاخص کل'
    history['indexB2'].append({**history['indexB2'][-1],'xNivInuClMresIbs':1})
    with pytest.raises(RuntimeError,match='duplicate'):parse_index(history,identity)


def test_published_snapshot_matches_saved_checksum_and_real_gold_observations():
    path=SOURCE/'benchmarks.json'
    manifest=json.loads((SOURCE/'benchmarks.manifest.json').read_text(encoding='utf8'))
    assert hashlib.sha256(path.read_bytes()).hexdigest()==manifest['sha256']
    snapshot=json.loads(path.read_text(encoding='utf8'))
    gold=snapshot['series']['mesghal_toman']
    assert gold['public_instrument_id']=='32469128621155736'
    assert gold['count']==1076
    assert gold['rows'][0]['closing_price']==9698
    assert gold['rows'][-1]['closing_price']==201321
    assert snapshot['synthetic_prices'] is False
    assert snapshot['start']=='2022-03-26' and snapshot['as_of']=='2026-11-04'
