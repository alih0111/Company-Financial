from datetime import datetime, timezone

import pytest

from factormix.decision_readiness import assess_ranking
from factormix.tests.evidence_fixture import controlled_evidence


AT = datetime(2026, 11, 13, 15, tzinfo=timezone.utc)
LIMITS = {'max_mark_age': 10, 'max_financial_age': 550}


@pytest.mark.parametrize('fault,state,reason', [
    (None, 'PASS', None),
    ('missing', 'UNKNOWN', 'source_file_missing'),
    ('revision', 'FAIL', 'selected_version_after_cutoff'),
    ('unselected_revision', 'UNKNOWN', 'listed_report_not_mapped_to_model_inputs'),
    ('incomplete', 'FAIL', 'financial_statement_pages_incomplete'),
    ('missing_sheet', 'FAIL', 'financial_required_sheet_receipt_missing'),
    ('future', 'FAIL', 'daily_payload_contains_future_session'),
])
def test_production_evidence_and_source_clocks(tmp_path, fault, state, reason):
    evidence, files, _ = controlled_evidence(tmp_path, ['S0'], ['asset-0'], AT, fault=fault)
    ranking = dict(computed_at_utc=AT.isoformat(), evidence_version=2, input_evidence=evidence)
    result = assess_ranking(ranking, ['S0'], LIMITS, AT)
    gaps = {g['code'] for r in evidence for g in r['evidence_gaps']}
    assert result['state'] == state, (result, gaps)
    if reason:
        assert reason in gaps
    else:
        assert all(r['complete'] and r['identity_verified'] for r in evidence)
        eod, financial, sales = evidence
        assert eod['published_at'] is None and 'effective_at' not in eod
        assert sales['source_reports'][0]['effective_date'] != sales['source_reports'][0]['period_end']
        assert financial['source_reports'][0]['received_at'] < financial['source_reports'][0]['first_seen_at']
        assert financial['windows']['2026-11-13']['validated_nulls']['pe'] == 'nonpositive_earnings_per_share'
        assert financial['windows']['2026-11-13']['prior_year_income_present']
        assert '1-daily.json.gz' in files.hashes


def test_later_receipt_cannot_certify_an_earlier_decision(tmp_path):
    evidence, _, _ = controlled_evidence(tmp_path, ['S0'], ['asset-0'], AT)
    before = AT.replace(hour=13)
    ranking = dict(computed_at_utc=before.isoformat(), evidence_version=2, input_evidence=evidence)
    result = assess_ranking(ranking, ['S0'], LIMITS, before)
    assert result['state'] == 'FAIL'
    assert {r['reason'] for r in result['reasons']} == {'not_yet_available'}
