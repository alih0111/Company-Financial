"""Critical source guards, rather than a second implementation of scoring."""
import datetime as dt
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from complete_ranking_coverage import select, verified_facts
from codal_fs_parse import to_number


def test_negative_profit_sign_is_preserved():
    assert to_number("-1,234") == -1234
    assert to_number("(۱٬۲۳۴)") == -1234
    assert to_number("−1234") == -1234
    assert to_number("(-1234)") == -1234


def statement(title="صورت سود و زیان", unit="کلیه مبالغ به میلیون ریال است"):
    return f"""<h2>{title} {unit}</h2><table>
    <tr><th>شرح</th><th>1404/03/31</th><th>1403/03/31</th><th>1403/12/30</th></tr>
    <tr><td>حسابرسی نشده</td><td></td><td></td><td></td></tr>
    <tr><td>درآمدهای عملیاتی</td><td>100</td><td>80</td><td>300</td></tr></table>"""


def test_source_requires_publication_and_cutoff():
    cutoff = dt.datetime(2026, 10, 8, 23, 59, tzinfo=dt.timezone.utc)
    base = {"Title": "اطلاعات و صورت‌های مالی میاندوره‌ای دوره ۳ ماهه منتهی به ۱۴۰۴/۰۳/۳۱", "TracingNo": "123"}
    assert select([base], cutoff) == []
    assert select([{**base, "PublishDateTime": "۱۴۰۵/۰۷/۲۰ ۱۲:۰۰:۰۰"}], cutoff) == []
    assert len(select([{**base, "PublishDateTime": "۱۴۰۴/۰۴/۲۰ ۱۲:۰۰:۰۰"}], cutoff)) == 1
    assert select([{**base, 'Title': base['Title'] + ' (شرکت زیرمجموعه)',
                   'PublishDateTime': '۱۴۰۴/۰۴/۲۰ ۱۲:۰۰:۰۰'}], cutoff) == []


def test_merged_header_columns_keep_actual_dates_and_values():
    from codal_fs_parse import parse_report
    html = '''<h2>صورت سود و زیان کلیه مبالغ به میلیون ریال است</h2><table>
    <tr><th rowspan="3">شرح</th><th>دوره جاری</th><th>دوره قبل</th><th rowspan="3">درصد تغییر</th></tr>
    <tr><th>1404/03/31</th><th>1403/03/31</th></tr>
    <tr><th>حسابرسی نشده</th><th>حسابرسی نشده</th></tr>
    <tr><td>جمع درآمدهای عملیاتی</td><td>100</td><td>80</td><td>25</td></tr>
    <tr><td>سود (زیان) عملیاتی</td><td>-10</td><td>5</td><td>-300</td></tr></table>'''
    metrics = parse_report(html, parent_only=True)['statements']['income_statement']
    assert metrics['revenue'] == {1: 100, 2: 80}
    assert metrics['operating_profit'] == {1: -10, 2: 5}


def test_parent_units_and_annual_anchor_are_required():
    period = dt.date(2025, 6, 21)
    pub = dt.datetime(2025, 7, 20, tzinfo=dt.timezone.utc)
    letter = {"TracingNo": "123"}
    assert verified_facts(statement("صورت سود و زیان تلفیقی"), period, pub, letter, "fixture", set()) == []
    assert verified_facts(statement(unit=""), period, pub, letter, "fixture", set()) == []
    no_anchor = verified_facts(statement(), period, pub, letter, "fixture", set())
    anchored = verified_facts(statement(), period, pub, letter, "fixture", {dt.date(2025, 3, 20)})
    assert {f["period_order"] for f in no_anchor} == {1, 2}
    assert {f["period_order"] for f in anchored} == {1, 2, 3}
