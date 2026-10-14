import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from legacy_financial import legacy_facts


def document(unit="کلیه مبالغ درج شده به میلیون ریال می باشد", title="صورت مالی شرکت اصلی"):
    return f"""<h1>{title}</h1><div>{unit}</div>
    <table><tr><th>شرح</th><th>۱۳۹۹/۰۹/۳۰</th><th>۱۳۹۸/۰۹/۳۰</th><th>درصد</th></tr></table>
    <table id="ctl00_cphBody_ucInterimStatement_grdInterimStatement"><tr><td>درآمدهای عملیاتی</td><td>200</td><td>100</td><td>100</td></tr>
    <tr><td>سود(زیان) خالص</td><td>20</td><td>10</td><td>100</td></tr></table>"""


def test_only_own_column_and_proven_report_unit_parent():
    facts = legacy_facts(document(), "2020-12-20")
    assert {r["metric_code"]: r["value"] for r in facts} == {"revenue": 200e6, "net_profit": 20e6}
    assert legacy_facts(document(unit=""), "2020-12-20") == []
    assert legacy_facts(document(title="صورت مالی تلفیقی"), "2020-12-20") == []
    assert legacy_facts(document(), "2021-03-20") == []


def test_publication_at_exact_cutoff_is_not_prior_information():
    import datetime as dt
    from collect_financial_history import select_asof
    cutoff = dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc)
    rows = [{"company_id": "A", "period_end": "2021-09-01", "published_at": cutoff.isoformat(), "tracing_no": "1"}]
    assert select_asof(rows, cutoff) == []
