import datetime as dt
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import complete_ranking_coverage as C


@pytest.mark.parametrize('mismatch,future,existing_annual,expected', [(False,False,False,1),(True,False,False,0),(False,True,False,0),(False,False,True,0)])
def test_expense_recovery_requires_matching_anchors_and_real_cutoff(tmp_path, monkeypatch, mismatch, future, existing_annual, expected):
    period = dt.date(2026, 6, 21)
    cutoff = dt.datetime(2026, 10, 13, 8, tzinfo=dt.timezone.utc)
    collected = cutoff + dt.timedelta(seconds=1) if future else cutoff - dt.timedelta(seconds=1)
    rows = [{'company_id':'c', 'period_end_date':period, 'metric_code':'finance_cost',
             'canonical_value':value, 'period_order':order, 'version_no':2, 'report_id':'canonical'}
            for order,value in ((1,-10_000_000),(2,-8_000_000))]
    if existing_annual:
        rows.append({**rows[0], 'period_order':3, 'canonical_value':0})
    engine = SimpleNamespace(stmt=rows, superseded=set())
    facts = [{'period_end_date':str(period),'metric_code':'finance_cost','statement_type':'income_statement',
              'period_order':order,'value':value,'unit':'million_rial','tracing_no':'verified',
              'published_at':str(cutoff-dt.timedelta(days=1)), 'collected_at':str(collected),
              'basis':'parent','source':'fixture','sha256':'fixture'}
             for order,value in ((1,-11 if mismatch else -10),(2,-8),(3,-40))]
    monkeypatch.setattr(C, 'OUT', tmp_path)
    monkeypatch.setattr(C, 'supplement_fiscal_titles', lambda *args: {})
    C.write(tmp_path/'facts'/'c.json', {'company_id':'c','rules_version':3,'facts':facts})
    accepted, _, _ = C.overlay_financial_facts(engine, cutoff.date(), cutoff)
    assert accepted == expected
    assert rows[0]['canonical_value'] == -10_000_000
    if expected:
        assert rows[-1]['period_order'] == 3 and rows[-1]['version_no'] == 2
        assert len(engine.verified_recovered_columns) == 1


@pytest.mark.parametrize('proven_legacy,expected_value', [(True, 40_000_000), (False, 1_000_000)])
def test_real_report_replaces_only_proven_unattributed_legacy_group(tmp_path, monkeypatch, proven_legacy, expected_value):
    cutoff = dt.datetime(2026, 10, 13, 8, tzinfo=dt.timezone.utc)
    period = dt.date(2025, 6, 21)
    row = {'company_id':'c', 'period_end_date':period,'metric_code':'operating_profit',
           'canonical_value':1_000_000,'period_order':1,'version_no':1,'report_id':'old'}
    engine = SimpleNamespace(stmt=[row], superseded=set(), verified_legacy_report_ids={'old'} if proven_legacy else set())
    fact = {'period_end_date':str(period),'metric_code':'operating_profit','statement_type':'income_statement',
            'period_order':1,'value':40,'unit':'million_rial','tracing_no':'verified',
            'published_at':str(cutoff-dt.timedelta(days=1)),'collected_at':str(cutoff),
            'basis':'parent','source':'fixture','sha256':'fixture'}
    monkeypatch.setattr(C,'OUT',tmp_path)
    monkeypatch.setattr(C,'supplement_fiscal_titles',lambda *args:{})
    C.write(tmp_path/'facts'/'c.json',{'company_id':'c','rules_version':3,'facts':[fact]})
    C.overlay_financial_facts(engine, cutoff.date(), cutoff)
    assert engine.stmt[-1]['canonical_value'] == expected_value
    assert row['canonical_value'] == 1_000_000  # Original source remains intact.


def test_fiscal_calendar_uses_the_proven_parent_annual_report(tmp_path, monkeypatch):
    cutoff = dt.datetime(2026, 10, 13, tzinfo=dt.timezone.utc)
    old = {'company_id':'c','period_end_date':dt.date(2025,3,20),
           'title':'صورت‌های مالی سال مالی منتهی به ۱۴۰۳/۱۲/۳۰'}
    other = {**old,'company_id':'other'}
    engine = SimpleNamespace(codal_titles=[old,other])
    letter = {'Title':'صورت‌های مالی سال مالی منتهی به ۱۴۰۴/۰۹/۳۰ (حسابرسی شده)',
              'TracingNo':'123','PublishDateTime':'۱۴۰۴/۱۱/۰۵ ۱۲:۰۰:۰۰'}
    monkeypatch.setattr(C,'OUT',tmp_path)
    monkeypatch.setattr(C,'letters_for',lambda *args:[letter])
    C.write(tmp_path/'facts'/'c.json',{'company_id':'c','symbol':'sample','rules_version':3,
                                   'facts':[{'tracing_no':'123','collected_at':str(cutoff)}]})
    metadata = C.supplement_fiscal_titles(engine,cutoff)
    assert [r['period_end_date'] for r in engine.codal_titles if r['company_id']=='c'] == [dt.date(2025,12,21)]
    assert other in engine.codal_titles
    assert metadata['calendar_from_verified_parent_reports'][0]['annual_periods'] == ['2025-12-21']
