"""تست‌های مسیر canonical-only: ترمیم گزارش ناقص، پنجرهٔ اسکن، نمادهای قرنطینه."""

import argparse
import os
import pathlib
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import canonical_hook
import codal_feed
import sync_codal
from codal_feed import FINANCIAL_LETTER_TYPE, FeedPage, CodalReport


def make_report(report_id, ticker="فولاد", published_at=None):
    return CodalReport(
        report_id=str(report_id),
        tracing_no=int(report_id),
        letter_type=FINANCIAL_LETTER_TYPE,
        ticker=ticker,
        company_name=ticker,
        title="اطلاعات و صورت‌های مالی میاندوره‌ای",
        letter_code="ن-۱۰",
        published_at_raw="۱۴۰۵/۰۷/۰۲ ۱۲:۰۰:۰۰",
        published_at=published_at,
        report_url=f"https://www.codal.ir/Reports/Decision.aspx?LetterSerial={report_id}&let=6",
        has_html=True,
    )


def make_args(**overrides) -> argparse.Namespace:
    base = {
        "dry_run": False,
        "limit": 0,
        "max_pages": 1,
        "max_attempts": 3,
        "from_date": None,
        "to_date": None,
        "overlap_hours": 24,
        "type": "financial",
        "letter_types": None,
        "symbol": None,
        "repair_days": 0,
        "repair_limit": 80,
        "backfill_days": 7,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def feed_page(reports):
    return FeedPage(
        letter_type=FINANCIAL_LETTER_TYPE,
        page_number=1,
        total=len(reports),
        reports=reports,
        all_reports=reports,
    )


class CanonicalOnlySummaryTests(unittest.TestCase):
    def test_quarantined_symbols_and_scan_window_are_reported(self):
        first = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
        second = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)
        reports = [
            make_report(1, ticker="بجهرم", published_at=first),
            make_report(2, ticker="نیلپر", published_at=second),
        ]
        ingest = mock.Mock(side_effect=[{"status": "written"}, {"status": "quarantined"}])

        with (
            mock.patch.object(codal_feed, "discover_reports", return_value=feed_page(reports)),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=None),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم", "نیلپر"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", ingest),
            mock.patch.object(canonical_hook, "resolve_codal_company_display_name", return_value="بجهرم"),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values") as extract,
        ):
            summary = sync_codal.run_sync_canonical_only(make_args())

        total = summary["total"]
        self.assertEqual(total["new"], 1)
        self.assertEqual(total["quarantined"], 1)
        self.assertEqual(total["quarantined_symbols"], {"نیلپر": 1})
        self.assertEqual(total["scan_oldest"], second.isoformat())
        self.assertEqual(total["scan_newest"], first.isoformat())
        self.assertEqual(summary["financial"]["quarantined_symbols"], {"نیلپر": 1})
        extract.assert_called_once()

    def test_page_cap_is_reported_as_incomplete(self):
        reports = [make_report(i, published_at=datetime(2026, 10, 30, 8, i, tzinfo=timezone.utc))
                   for i in range(20)]

        with (
            mock.patch.object(codal_feed, "discover_reports", return_value=feed_page(reports)),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=None),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"فولاد"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", return_value={"status": "quarantined"}),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values"),
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=1))

        self.assertEqual(summary["financial"]["stop_reason"], "max_pages_reached")


class RepairTests(unittest.TestCase):
    def test_bodyless_report_is_refetched_with_absolute_url_and_extracted(self):
        args = make_args(repair_days=7, repair_limit=5)
        rows = [{
            "report_id": "1623096",
            "title": "اطلاعات و صورت‌های مالی",
            "url": "/Reports/Decision.aspx?LetterSerial=abc&let=6",
            "published_at": "2026-10-28T14:54:56+03:30",
            "symbol": "بجهرم",
            "company_name": "بجهرم",
        }]
        ingest = mock.Mock(return_value={"status": "written"})

        with (
            mock.patch.object(canonical_hook, "incomplete_codal_reports", return_value=rows),
            mock.patch.object(canonical_hook, "codal_reports_missing_values", return_value=[]),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", ingest),
            mock.patch.object(canonical_hook, "resolve_codal_company_display_name", return_value="بجهرم"),
            mock.patch.object(codal_feed, "discover_reports", return_value=feed_page([])),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=None),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم"}),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values") as extract,
        ):
            summary = sync_codal.run_sync_canonical_only(args)

        sent = ingest.call_args.args[0]
        self.assertTrue(sent["Url"].startswith("https://www.codal.ir/Reports/"))
        self.assertEqual(sent["TracingNo"], "1623096")
        self.assertEqual(summary["total"]["repaired"], 1)
        pending = extract.call_args.args[0]
        self.assertEqual([item["report_id"] for item in pending], ["1623096"])

    def test_repair_stops_after_repeated_failures(self):
        args = make_args(repair_days=7, repair_limit=10)
        rows = [{
            "report_id": str(i), "title": None,
            "url": f"https://www.codal.ir/Reports/Decision.aspx?LetterSerial={i}&let=6",
            "published_at": None, "symbol": "فولاد", "company_name": "فولاد",
        } for i in range(10)]
        stats = {"repaired": 0, "repair_failed": 0}

        with (
            mock.patch.object(canonical_hook, "incomplete_codal_reports", return_value=rows),
            mock.patch.object(canonical_hook, "codal_reports_missing_values", return_value=[]),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative",
                              return_value={"status": "canonical_error", "error": "blocked"}),
        ):
            repaired = sync_codal._repair_incomplete_reports(
                args, {FINANCIAL_LETTER_TYPE: stats}, []
            )

        self.assertEqual(repaired, 0)
        self.assertEqual(stats["repair_failed"], 5)
        self.assertEqual(stats["repaired"], 0)

    def test_body_without_values_is_queued_without_refetch(self):
        args = make_args(repair_days=7, repair_limit=5)
        rows = [{
            "report_id": "1623096",
            "title": "اطلاعات و صورت‌های مالی",
            "url": "/Reports/Decision.aspx?LetterSerial=abc&let=6",
            "published_at": "2026-10-28T14:54:56+03:30",
            "symbol": "بجهرم",
            "company_name": "بجهرم",
        }]
        stats = {"repaired": 0, "repair_failed": 0, "values_queued": 0}
        ingest = mock.Mock()

        with (
            mock.patch.object(canonical_hook, "incomplete_codal_reports", return_value=[]),
            mock.patch.object(canonical_hook, "codal_reports_missing_values", return_value=rows),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", ingest),
            mock.patch.object(canonical_hook, "resolve_codal_company_display_name", return_value="بجهرم"),
        ):
            pending: list[dict] = []
            repaired = sync_codal._repair_incomplete_reports(
                args, {FINANCIAL_LETTER_TYPE: stats}, pending
            )

        self.assertEqual(repaired, 0)
        ingest.assert_not_called()
        self.assertEqual(stats["values_queued"], 1)
        self.assertEqual([item["report_id"] for item in pending], ["1623096"])
        self.assertTrue(pending[0]["url"].startswith("https://www.codal.ir/Reports/"))


class CoverageBackfillTests(unittest.TestCase):
    def test_report_outside_coverage_is_skipped_without_ingest(self):
        reports = [make_report(1, ticker="سلیمان",
                               published_at=datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc))]
        ingest = mock.Mock()

        with (
            mock.patch.object(codal_feed, "discover_reports", return_value=feed_page(reports)),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=None),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", ingest),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values"),
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=1))

        ingest.assert_not_called()
        self.assertEqual(summary["total"]["new"], 0)
        self.assertEqual(summary["total"]["quarantined"], 1)
        self.assertEqual(summary["total"]["quarantined_symbols"], {"سلیمان": 1})

    def test_scan_continues_past_watermark_for_unseen_covered_report(self):
        watermark = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
        covered = {"بجهرم"}
        page1 = [make_report(1, ticker="بجهرم",
                             published_at=datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc))]
        page1 += [make_report(100 + i, ticker=f"OUT{i}",
                              published_at=datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc))
                  for i in range(19)]
        page2 = [make_report(200 + i, ticker=f"OUT{i}",
                             published_at=datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc))
                 for i in range(20)]

        def discover(_letter_type, page_number, **_kwargs):
            return feed_page(page1 if page_number == 1 else page2)

        ingest = mock.Mock(return_value={"status": "written"})
        with (
            mock.patch.object(codal_feed, "discover_reports", side_effect=discover),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=watermark),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value=covered),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", ingest),
            mock.patch.object(canonical_hook, "resolve_codal_company_display_name", return_value="بجهرم"),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values"),
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=0))

        self.assertEqual(summary["total"]["new"], 1)
        self.assertEqual(summary["financial"]["pages"], 2)
        self.assertEqual(summary["financial"]["stop_reason"], "watermark_reached")

    def test_backfill_floor_stops_the_scan(self):
        old = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        reports = [make_report(300 + i, ticker=f"OUT{i}", published_at=old)
                   for i in range(20)]

        with (
            mock.patch.object(codal_feed, "discover_reports", return_value=feed_page(reports)),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=None),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", return_value={"status": "written"}),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values"),
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=0, backfill_days=7))

        self.assertEqual(summary["financial"]["stop_reason"], "backfill_floor_reached")

    def test_explicit_max_pages_ignores_backfill_floor(self):
        # عدد صریح «حداکثر صفحات» یعنی دقیقاً همان عمق؛ اسکن نباید در مرز
        # بازهٔ بازگشتی (۷ روز) زودتر بایستد.
        old = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        page1 = [make_report(300 + i, ticker=f"OUT{i}", published_at=old)
                 for i in range(20)]
        page2 = [make_report(400 + i, ticker=f"OUT{i}", published_at=old)
                 for i in range(20)]

        def discover(_letter_type, page_number, **_kwargs):
            return feed_page(page1 if page_number == 1 else page2)

        with (
            mock.patch.object(codal_feed, "discover_reports", side_effect=discover),
            mock.patch.object(canonical_hook, "get_codal_watermark", return_value=None),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative", return_value={"status": "quarantined"}),
            mock.patch.object(canonical_hook, "set_codal_watermark"),
            mock.patch.object(sync_codal, "_extract_pending_values"),
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=2, backfill_days=7))

        self.assertEqual(summary["financial"]["stop_reason"], "max_pages_reached")
        self.assertEqual(summary["financial"]["pages"], 2)
        self.assertEqual(summary["total"]["scanned"], 40)

    def test_new_report_is_fully_collected_before_scan_continues(self):
        # در جمع‌آوری سریع (مرورگر دیدنی) گزارش جدید باید همان لحظه وارد
        # صفحه‌اش بشود و تمام تب‌هایش جمع شود؛ بعد اسکن به فهرست کدال برگردد.
        page1 = [make_report(500, ticker="بجهرم",
                             published_at=datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc))]
        page1 += [make_report(510 + i, ticker=f"OUT{i}",
                              published_at=datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc))
                  for i in range(19)]
        page2 = [make_report(600 + i, ticker=f"OUT{i}",
                             published_at=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc))
                 for i in range(20)]

        def discover(_letter_type, page_number, **_kwargs):
            return feed_page(page1 if page_number == 1 else page2)

        extracted = []

        def fake_extract(item, page):
            extracted.append(item["report_id"])
            return "completed", None, None

        fake_transport = mock.Mock()
        fake_transport.visible_collection.return_value = True

        with (
            mock.patch.dict(os.environ, {"CODAL_JOB_DIR": "unused"}),
            mock.patch("codal_challenge.current_channel", return_value=None),
            mock.patch("codal_transport.current", return_value=fake_transport),
            mock.patch.object(codal_feed, "discover_reports", side_effect=discover),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative",
                              return_value={"status": "written"}),
            mock.patch.object(canonical_hook, "resolve_codal_company_display_name",
                              return_value="بجهرم"),
            mock.patch.object(canonical_hook, "mark_codal_values_extraction") as mark,
            mock.patch.object(sync_codal, "_extract_report_values", side_effect=fake_extract),
            mock.patch.object(sync_codal, "_extract_pending_values") as batch,
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=2, backfill_days=7))

        # استخراج در همان لحظهٔ پیدا شدن و پیش از خواندن صفحهٔ دوم؛ بعد اسکن ادامه یافت
        self.assertEqual(extracted, ["500"])
        mark.assert_called_once()
        self.assertEqual(summary["financial"]["pages"], 2)
        self.assertEqual(summary["total"]["completed"], 1)
        batch.assert_not_called()

    def test_silent_run_defers_extraction_to_end_phase(self):
        # اجرای بی‌صدا (HTTP/خودکار) نباید وسط اسکن مرورگر باز کند؛ استخراج
        # مثل قبل در صف انتهایی می‌ماند.
        page1 = [make_report(500, ticker="بجهرم",
                             published_at=datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc))]
        page1 += [make_report(510 + i, ticker=f"OUT{i}",
                              published_at=datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc))
                  for i in range(19)]
        page2 = [make_report(600, ticker="بجهرم",
                             published_at=datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc))]

        def discover(_letter_type, page_number, **_kwargs):
            return feed_page(page1 if page_number == 1 else page2)

        fake_transport = mock.Mock()
        fake_transport.visible_collection.return_value = False

        with (
            mock.patch.dict(os.environ, {"CODAL_JOB_DIR": "unused"}),
            mock.patch("codal_challenge.current_channel", return_value=None),
            mock.patch("codal_transport.current", return_value=fake_transport) as current,
            mock.patch.object(codal_feed, "discover_reports", side_effect=discover),
            mock.patch.object(canonical_hook, "known_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "seen_codal_report_ids", return_value=set()),
            mock.patch.object(canonical_hook, "codal_covered_symbols", return_value={"بجهرم"}),
            mock.patch.object(canonical_hook, "ingest_codal_authoritative",
                              return_value={"status": "written"}),
            mock.patch.object(canonical_hook, "resolve_codal_company_display_name",
                              return_value="بجهرم"),
            mock.patch.object(sync_codal, "_extract_report_values") as inline,
            mock.patch.object(sync_codal, "_extract_pending_values") as batch,
        ):
            summary = sync_codal.run_sync_canonical_only(make_args(max_pages=2, backfill_days=7))

        inline.assert_not_called()
        batch.assert_called_once()
        pending = batch.call_args.args[0]
        self.assertEqual([item["report_id"] for item in pending], ["500", "600"])
        self.assertEqual(summary["total"]["new"], 2)


class LetterTypeFromUrlTests(unittest.TestCase):
    def test_monthly_and_financial(self):
        self.assertEqual(
            sync_codal._letter_type_from_url(
                "https://www.codal.ir/Reports/Decision.aspx?x=1&let=58&y=2"),
            58,
        )
        self.assertEqual(
            sync_codal._letter_type_from_url("https://www.codal.ir/x?let=6"), 6)
        self.assertEqual(
            sync_codal._letter_type_from_url("https://www.codal.ir/x", default=6), 6)


class FriendlyErrorTests(unittest.TestCase):
    def test_closed_browser_error_is_explained_in_panel_language(self):
        message = sync_codal._friendly_sync_error(
            RuntimeError("Page.goto: Target page, context or browser has been closed"))
        self.assertIn("پنجرهٔ مرورگر", message)

    def test_other_errors_pass_through(self):
        self.assertEqual(
            sync_codal._friendly_sync_error(ValueError("boom")), "boom")


if __name__ == "__main__":
    unittest.main()
