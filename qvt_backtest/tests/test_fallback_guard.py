import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_financial_panel import reconstruct
from audit_reconstructed import catalog_errors
from collect_financial_history import select_asof
import datetime as dt


def test_revision_selection_compares_instants_across_historical_dst_offsets():
    old = {"company_id": "A", "period_end": "2022-03-20", "tracing_no": "old",
           "published_at": "2022-09-21T23:30:00+04:30"}
    new = {**old, "tracing_no": "new", "published_at": "2022-09-21T23:20:00+03:30"}
    selected = select_asof([old, new], dt.datetime(2022, 9, 22, tzinfo=dt.timezone.utc))
    assert selected[0]["tracing_no"] == "new"


def test_independent_catalog_check_rejects_omitted_new_report():
    catalog = [{"company_id": "A", "letter": {"TracingNo": "new"},
                "period": "2021-06-21", "published_at": "2021-07-20T00:00:00+00:00"}]
    stub = {"company_id": "A", "tracing_no": "new", "period_end": "2021-06-21",
            "published_at": "2021-07-20T00:00:00+00:00", "facts": []}
    assert catalog_errors([stub], catalog) == []
    assert catalog_errors([], catalog)
    assert catalog_errors([{**stub, "period_end": "2021-03-20"}], catalog)


def test_unparsed_new_financial_report_blocks_using_old_annual_profit():
    old = {"period_end": "2021-03-20", "title": "صورت مالی 12 ماهه", "tracing_no": "old",
           "published_at": "2021-05-01T00:00:00+00:00", "facts": [
               {"statement_type": "income_statement", "metric_code": "revenue", "value": 100},
               {"statement_type": "income_statement", "metric_code": "net_profit", "value": 10}]}
    newer = {"period_end": "2021-06-21", "title": "صورت مالی 3 ماهه", "tracing_no": "new",
             "published_at": "2021-07-20T00:00:00+00:00", "facts": [], "archive_status": "missing"}
    result = reconstruct([old, newer])
    assert result["financial_period_end"] == old["period_end"]
    assert result["latest_income_period"] == newer["period_end"]
    assert result["used_older_income_report"] is True
