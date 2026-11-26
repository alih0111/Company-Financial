from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from factormix.decision_readiness import Observation, assess_data, money_to_rial, readiness


NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
BASE = Observation('A', 'financial', NOW - timedelta(days=2), NOW - timedelta(days=1),
                   NOW - timedelta(days=1), NOW - timedelta(days=2), timedelta(days=90), True, True)


def test_required_data_and_unrelated_failure():
    bad = replace(BASE, symbol='B', complete=False)
    assert assess_data([('A', 'financial')], [BASE, bad], NOW)['state'] == 'PASS'
    assert assess_data([('A', 'financial'), ('B', 'financial')], [BASE, bad], NOW)['state'] == 'FAIL'
    assert assess_data([], [], NOW)['state'] == 'UNKNOWN'
    assert assess_data(iter(()), [], NOW)['state'] == 'UNKNOWN'


@pytest.mark.parametrize('change,reason', [
    ({'received_at': NOW + timedelta(seconds=1)}, 'not_yet_available'),
    ({'effective_at': NOW - timedelta(days=91)}, 'stale'),
    ({'identity_verified': None}, 'identity_or_completeness_unknown'),
    ({'first_seen_at': None}, 'timestamp_unknown'),
])
def test_invalid_inputs_are_explained(change, reason):
    result = assess_data([('A', 'financial')], [replace(BASE, **change)], NOW)
    assert result['state'] != 'PASS'
    assert result['reasons'][0]['reason'] == reason


def test_revision_does_not_change_an_earlier_decision():
    revision = replace(BASE, received_at=NOW + timedelta(days=1), first_seen_at=NOW + timedelta(days=1))
    assert assess_data([('A', 'financial')], [revision], NOW)['state'] == 'FAIL'
    assert assess_data([('A', 'financial')], [BASE, revision], NOW)['state'] == 'UNKNOWN'


def test_unit_conversion_and_readiness_never_authorizes_submission():
    assert money_to_rial(Decimal('1.5'), 'TOMAN') == 15
    assert money_to_rial(Decimal('12345678901234567890123456789.1'), 'TOMAN') == 123456789012345678901234567891
    with pytest.raises(ValueError):
        money_to_rial(Decimal('.5'), 'IRR')
    with pytest.raises(ValueError):
        money_to_rial(1.0, 'TOMAN')
    assert readiness(service='PASS', data='PASS', strategy='PASS', broker='UNKNOWN', mode='paper')['decision_ready']
    assert not readiness(service='PASS', data='PASS', strategy='PASS', broker='UNKNOWN', mode='live')['decision_ready']
    assert not readiness(service='PASS', data='PASS', strategy='PASS', broker='PASS', mode='live')['trading_allowed']
