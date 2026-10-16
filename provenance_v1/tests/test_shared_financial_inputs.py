import datetime as dt
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verified_financial_inputs import eligible_cache_facts

CUTOFF = dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)


def fact(**kwargs):
    return {'basis': 'parent', 'period_end_date': '2025-06-21',
            'published_at': '2026-10-12T00:00:00+00:00', 'collected_at': CUTOFF.isoformat(),
            'unit': 'million_rial', 'value': -10, 'period_order': 1,
            'source': 'fixture', 'sha256': 'fixture', 'tracing_no': '1', **kwargs}


def test_both_publication_and_observation_must_be_known():
    facts = [fact(), fact(collected_at=(CUTOFF + dt.timedelta(seconds=1)).isoformat()),
             fact(published_at=(CUTOFF + dt.timedelta(seconds=1)).isoformat()),
             fact(basis='consolidated'), fact(period_end_date='2027-01-01')]
    assert eligible_cache_facts({'facts': facts}, CUTOFF.date(), CUTOFF) == [facts[0]]


@pytest.mark.parametrize('kwargs', [{'unit': 'unknown'}, {'value': float('nan')},
                                  {'value': float('inf')}, {'period_order': 4},
                                  {'sha256': ''}, {'collected_at': '2026-10-12T00:00:00'}])
def test_ambiguous_units_and_invalid_evidence_fail_closed(kwargs):
    with pytest.raises(ValueError):
        eligible_cache_facts({'facts': [fact(**kwargs)]}, CUTOFF.date(), CUTOFF)


def test_latest_report_cannot_borrow_missing_metric_from_earlier_report():
    older = fact(metric_code='revenue')
    newer = fact(metric_code='operating_profit', tracing_no='2', published_at=CUTOFF.isoformat())
    assert eligible_cache_facts({'facts': [older, newer]}, CUTOFF.date(), CUTOFF) == [newer]

