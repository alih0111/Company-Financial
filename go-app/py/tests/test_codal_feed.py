"""تست‌های لایه‌ی discovery کدال (بدون شبکه و بدون DB)."""

import pathlib
import sys
import unittest
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from codal_feed import (
    FINANCIAL_LETTER_TYPE,
    MONTHLY_LETTER_TYPE,
    CodalReport,
    build_report_url,
    classify_report,
    filter_supported,
    parse_letter,
    parse_persian_datetime,
    route_for_letter_type,
)


class ParsePersianDateTimeTests(unittest.TestCase):
    def test_valid_datetime(self):
        result = parse_persian_datetime("۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴")
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2026)

    def test_valid_without_seconds(self):
        self.assertIsInstance(parse_persian_datetime("1405/07/02 16:28"), datetime)

    def test_invalid(self):
        self.assertIsNone(parse_persian_datetime(""))
        self.assertIsNone(parse_persian_datetime(None))
        self.assertIsNone(parse_persian_datetime("not a date"))


class BuildReportUrlTests(unittest.TestCase):
    def test_relative_url(self):
        url = build_report_url("/Reports/Decision.aspx?LetterSerial=abc")
        self.assertEqual(
            url, "https://www.codal.ir/Reports/Decision.aspx?LetterSerial=abc"
        )

    def test_empty(self):
        self.assertEqual(build_report_url(""), "")


class ParseLetterTests(unittest.TestCase):
    def _letter(self, **overrides):
        base = {
            "TracingNo": 1603166,
            "Symbol": "کروی",
            "CompanyName": "توسعه معادن روی ایران",
            "Title": "گزارش فعالیت ماهانه دوره ۱ ماهه منتهی به  ۱۴۰۵/۰۶/۳۱",
            "LetterCode": "ن-۳۱",
            "PublishDateTime": "۱۴۰۵/۰۷/۰۲ ۱۶:۲۸:۴۴",
            "Url": "/Reports/Decision.aspx?LetterSerial=x&rt=2&let=58",
            "HasHtml": True,
        }
        base.update(overrides)
        return base

    def test_mapping(self):
        report = parse_letter(self._letter(), MONTHLY_LETTER_TYPE)
        self.assertEqual(report.report_id, "1603166")
        self.assertEqual(report.tracing_no, 1603166)
        self.assertEqual(report.ticker, "کروی")
        self.assertEqual(report.letter_type, MONTHLY_LETTER_TYPE)
        self.assertTrue(report.report_url.startswith("https://www.codal.ir/"))
        self.assertIsInstance(report.published_at, datetime)

    def test_missing_tracing_no_is_zero(self):
        report = parse_letter(self._letter(TracingNo=None), MONTHLY_LETTER_TYPE)
        self.assertEqual(report.report_id, "0")


class ClassifyTests(unittest.TestCase):
    def _report(self, letter_type, title, has_html=True):
        return CodalReport(
            report_id="1",
            tracing_no=1,
            letter_type=letter_type,
            ticker="X",
            company_name="Y",
            title=title,
            letter_code="",
            published_at_raw="",
            published_at=None,
            report_url="https://www.codal.ir/Reports/Decision.aspx?LetterSerial=a",
            has_html=has_html,
        )

    def test_monthly_supported(self):
        r = self._report(MONTHLY_LETTER_TYPE, "گزارش فعالیت ماهانه دوره ۱ ماهه")
        self.assertEqual(classify_report(r), "supported")

    def test_monthly_unsupported_title(self):
        r = self._report(MONTHLY_LETTER_TYPE, "گزارش هیئت مدیره")
        self.assertEqual(classify_report(r), "unsupported")

    def test_financial_supported(self):
        r = self._report(FINANCIAL_LETTER_TYPE, "صورت‌های مالی سال مالی ۱۴۰۴")
        self.assertEqual(classify_report(r), "supported")

    def test_no_html_unsupported(self):
        r = self._report(FINANCIAL_LETTER_TYPE, "صورت‌های مالی", has_html=False)
        self.assertEqual(classify_report(r), "unsupported")

    def test_no_url_unsupported(self):
        r = self._report(FINANCIAL_LETTER_TYPE, "صورت‌های مالی")
        object.__setattr__(r, "report_url", "")
        self.assertEqual(classify_report(r), "unsupported")

    def test_filter_supported(self):
        supported = self._report(MONTHLY_LETTER_TYPE, "گزارش فعالیت ماهانه")
        unsupported = self._report(MONTHLY_LETTER_TYPE, "چیز دیگر")
        self.assertEqual(filter_supported([supported, unsupported]), [supported])


class RouteTests(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(route_for_letter_type(FINANCIAL_LETTER_TYPE), "financial")
        self.assertEqual(route_for_letter_type(MONTHLY_LETTER_TYPE), "monthly")
        self.assertEqual(route_for_letter_type(999), "unknown")


if __name__ == "__main__":
    unittest.main()
