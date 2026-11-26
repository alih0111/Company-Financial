from datetime import date, datetime, timezone
import gzip
from hashlib import sha256
import json

import pytest

from factormix.market_source_evidence import verify_adjustments, verify_share_interval
from factormix.ranking_evidence import EvidenceError, EvidenceFiles


AT = datetime(2026, 11, 14, 15, tzinfo=timezone.utc)
BEFORE, AFTER = date(2026, 11, 10), date(2026, 11, 11)


@pytest.mark.parametrize('case', ('valid', 'wrong_version', 'missing', 'after_decision'))
@pytest.mark.parametrize('factor', ('adjustment', 'shares'))
def test_consumed_market_version(tmp_path, factor, case):
    field, endpoint, values = (
        ('priceAdjust', 'ClosingPrice/GetPriceAdjustList',
         {'pClosing': 80 if case != 'wrong_version' else 81, 'pClosingNotAdjusted': 100})
        if factor == 'adjustment' else
        ('instrumentShareChange', 'Instrument/GetInstrumentShareChange',
         {'numberOfShareOld': 100, 'numberOfShareNew': 120 if case != 'wrong_version' else 121}))
    body = json.dumps({field: [dict(insCode='42', dEven=20261110, **values)]}).encode()
    (tmp_path / 'source.gz').write_bytes(gzip.compress(body))
    receipt = None if case == 'missing' else dict(raw_path='source.gz', raw_sha256=sha256(body).hexdigest(),
        url=f'https://cdn.tsetmc.com/api/{endpoint}/42', http_status=200,
        retrieved_at_utc='2026-11-14T16:00:00Z' if case == 'after_decision' else '2026-11-14T14:00:00Z')
    files = EvidenceFiles(tmp_path)
    def verify():
        if factor == 'adjustment':
            return verify_adjustments(files, receipt, '42',
                {BEFORE: {'pClosing': 100}, AFTER: {'priceYesterday': 80}},
                [(AFTER.isoformat(), .8)], BEFORE, AFTER, AT)
        identity = dict(company_id='c', security_id='s')
        interval = identity | dict(valid_from=BEFORE.isoformat(), valid_to=None, shares_outstanding=120)
        return verify_share_interval(files, receipt, '42', identity, interval, AFTER, AFTER, AT)
    if case == 'valid':
        received, evidence = verify()
        assert received < AT and evidence
        if factor == 'adjustment':
            assert evidence[0]['effective_date'] == AFTER.isoformat() and evidence[0]['numerator'] == 4
        else:
            assert evidence['source_effective_date'] == BEFORE.isoformat() and evidence['shares_outstanding'] == 120
    else:
        reason = {'missing': 'receipt_missing', 'after_decision': 'received_after_decision',
                  'wrong_version': 'mismatch'}[case]
        with pytest.raises(EvidenceError, match=reason) as caught:
            verify()
        assert caught.value.invalid == (case != 'missing')


def test_same_date_reference_resets_require_one_exact_chain(tmp_path):
    rows = [dict(insCode=42, dEven=20261110, pClosingNotAdjusted=a, pClosing=b)
            for a, b in ((90, 80), (100, 90))]
    body = json.dumps({'priceAdjust': rows}).encode()
    (tmp_path / 'source.gz').write_bytes(gzip.compress(body))
    source = dict(raw_path='source.gz', raw_sha256=sha256(body).hexdigest(),
        url='https://cdn.tsetmc.com/api/ClosingPrice/GetPriceAdjustList/42',
        retrieved_at_utc='2026-11-14T14:00:00Z')
    _, events = verify_adjustments(EvidenceFiles(tmp_path), source, '42',
        {BEFORE: {'pClosing': 100}, AFTER: {'priceYesterday': 80}},
        [(AFTER.isoformat(), .8)], BEFORE, AFTER, AT)
    assert events[0]['numerator'] == 4 and events[0]['denominator'] == 5
