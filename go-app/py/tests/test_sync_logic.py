"""تست‌های منطق sync: pagination مستقل از candidate، watermark و dry-run."""

import argparse
import pathlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codal_feed
import codal_prefilter
import codal_registry as registry
import sync_codal
from codal_feed import MONTHLY_LETTER_TYPE, CodalReport, FeedPage

TITLE = "گزارش فعالیت ماهانه دوره ۱ ماهه"


def make_report(report_id, ticker="فولاد", title=TITLE, published_at=None):
    return CodalReport(
        report_id=str(report_id),
        tracing_no=report_id,
        letter_type=MONTHLY_LETTER_TYPE,
        ticker=ticker,
        company_name="فولاد مبارکه",
        title=title,
        letter_code="ن-۳۰",
        published_at_raw="۱۴۰۵/۰۷/۰۲ ۱۲:۰۰:۰۰" if published_at else "",
        published_at=published_at,
        report_url=f"https://www.codal.ir/Reports/Decision.aspx?LetterSerial={report_id}",
        has_html=True,
    )


def make_args(**overrides) -> argparse.Namespace:
    base = {
        "dry_run": True,
        "limit": 0,
        "max_pages": 5,
        "max_attempts": 3,
        "from_date": None,
        "to_date": None,
        "overlap_hours": 24,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def make_feed(*pages):
    """Fake discover_reports که صفحه‌ی N را برمی‌گرداند."""
    def _discover(letter_type, page_number, **kwargs):
        reports = pages[page_number - 1] if page_number <= len(pages) else []
        return FeedPage(
            letter_type=letter_type,
            page_number=page_number,
            total=len(reports),
            reports=reports,
        )

    return _discover


class DryRunTests(unittest.TestCase):
    def test_all_new(self):
        reports = [make_report(1), make_report(2), make_report(3)]

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(reports)),
            mock.patch.object(registry, "get_statuses", return_value={}),
        ):
            stats, pending = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE, make_args(dry_run=True), conn=object()
            )

        self.assertEqual(stats["new"], 3)
        self.assertEqual(stats["already"], 0)
        self.assertEqual(stats["pages"], 1)
        self.assertEqual(stats["stop_reason"], "empty_feed")
        self.assertEqual(pending, [])
        self.assertEqual(len(stats["candidates"]), 3)


class PaginationTests(unittest.TestCase):
    def test_unknown_ticker_pages_do_not_stop_scanning(self):
        page1 = [make_report(100 + i, ticker=f"UNKNOWN{i}") for i in range(20)]
        page2 = [make_report(999, ticker="فولاد")]

        prefilter = codal_prefilter.ReportPreFilter(
            ticker_universe={"فولاد"}, _enforce_ticker=True
        )

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(page1, page2)),
            mock.patch.object(registry, "get_statuses", return_value={}),
            mock.patch.object(registry, "register_discovered", return_value="new"),
            mock.patch.object(registry, "claim_for_processing", return_value=True),
        ):
            stats, pending = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE,
                make_args(dry_run=False),
                conn=object(),
                prefilter=prefilter,
            )

        # صفحه‌ی اول فقط unknown ticker داشت ولی نباید اسکن متوقف شود.
        self.assertEqual(stats["pages"], 2)
        self.assertEqual(stats["skipped_unknown_ticker"], 20)
        self.assertEqual(stats["new"], 1)
        self.assertEqual([p["report_id"] for p in pending], ["999"])

    def test_watermark_stops_scanning(self):
        watermark = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
        overlap = timedelta(hours=24)
        old = datetime(2026, 9, 22, 0, 0, 0, tzinfo=timezone.utc)  # < watermark - overlap
        page1 = [make_report(i, published_at=old) for i in range(1, 4)]

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(page1)),
            mock.patch.object(registry, "get_statuses", return_value={}),
        ):
            stats, _ = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE,
                make_args(dry_run=True),
                conn=object(),
                watermark=watermark,
                overlap=overlap,
            )

        self.assertEqual(stats["pages"], 1)
        self.assertEqual(stats["stop_reason"], "watermark_reached")

    def test_watermark_continues_while_reports_are_newer(self):
        watermark = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
        overlap = timedelta(hours=24)
        fresh = datetime(2026, 9, 24, 13, 0, 0, tzinfo=timezone.utc)  # newer than watermark
        old = datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)  # older than watermark - overlap
        page1 = [make_report(i, published_at=fresh) for i in range(1, 21)]
        page2 = [make_report(999, published_at=old)]

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(page1, page2)),
            mock.patch.object(registry, "get_statuses", return_value={}),
        ):
            stats, _ = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE,
                make_args(dry_run=True),
                conn=object(),
                watermark=watermark,
                overlap=overlap,
            )

        self.assertEqual(stats["pages"], 2)
        self.assertEqual(stats["stop_reason"], "watermark_reached")

    def test_max_pages_is_safety_cap(self):
        # همه‌ی صفحه‌ها جدید؛ بدون watermark و با سقف 3 باید دقیقاً 3 صفحه بخواند.
        pages = [[make_report(i * 100 + j) for j in range(20)] for i in range(10)]

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(*pages)),
            mock.patch.object(registry, "get_statuses", return_value={}),
        ):
            stats, _ = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE, make_args(dry_run=True, max_pages=3), conn=object()
            )

        self.assertEqual(stats["pages"], 3)
        self.assertEqual(stats["stop_reason"], "max_pages_reached")


class LimitTests(unittest.TestCase):
    def test_limit_stops_claiming_within_page(self):
        reports = [make_report(i) for i in range(1, 11)]

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(reports)),
            mock.patch.object(registry, "get_statuses", return_value={}),
            mock.patch.object(registry, "register_discovered", return_value="new"),
            mock.patch.object(registry, "claim_for_processing", return_value=True),
        ):
            stats, pending = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE, make_args(dry_run=False, limit=2), conn=object()
            )

        self.assertEqual(stats["new"], 2)
        self.assertEqual(len(pending), 2)

    def test_known_reports_not_claimed(self):
        reports = [make_report(1), make_report(2)]

        with (
            mock.patch.object(codal_feed, "discover_reports", make_feed(reports)),
            mock.patch.object(registry, "get_statuses", return_value={"1": "completed"}),
            mock.patch.object(registry, "register_discovered", return_value="new"),
            mock.patch.object(registry, "claim_for_processing", return_value=True),
        ):
            stats, pending = sync_codal.sync_feed(
                MONTHLY_LETTER_TYPE, make_args(dry_run=False), conn=object()
            )

        self.assertEqual(stats["already"], 1)
        self.assertEqual(stats["new"], 1)
        self.assertEqual([p["report_id"] for p in pending], ["2"])


class ResolveLetterTypesTests(unittest.TestCase):
    def test_defaults_to_both(self):
        args = make_args()
        args.letter_types = None
        args.type = "all"
        self.assertEqual(sync_codal.resolve_letter_types(args), [6, 58])

    def test_explicit_letter_type(self):
        args = make_args()
        args.letter_types = [58]
        args.type = "all"
        self.assertEqual(sync_codal.resolve_letter_types(args), [58])


if __name__ == "__main__":
    unittest.main()
