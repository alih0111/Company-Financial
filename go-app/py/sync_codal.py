"""Discovery-based sync کدال.

به‌جای جستجوی تک‌تک نمادها، فقط feed لیست گزارش‌های کدال خوانده می‌شود:

    LetterType=6  (صورت‌های مالی)   ─┐
                                     ├─> کشف گزارش‌ها
    LetterType=58 (فعالیت ماهانه)  ─┘        ↓
                                      pre-filter (metadata-only، بدون مرورگر)
                                             ↓
                               ticker در universe ما؟ نوع گزارش پشتیبانی می‌شود؟
                                             ↓
                                   dedup با SQL Server (CodalReports)
                                             ↓
                                   فقط جدید + مرتبط → باز کردن گزارش
                                             ↓
                                   parserهای موجود (MianSql / MianSql2)
                                             ↙                ↘
                                        miandore2          mahane

قرارداد خروجی: ``stdout`` فقط JSON نهایی، ``stderr`` لاگ‌ها.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

import codal_feed
import codal_prefilter
import codal_registry as registry
import codal_sync_state
import codal_universe
from codal_feed import FINANCIAL_LETTER_TYPE, MONTHLY_LETTER_TYPE, route_for_letter_type

logger = logging.getLogger("sync_codal")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync new Codal reports via report-list feed (incremental).",
    )
    parser.add_argument(
        "--type",
        choices=("all", "financial", "monthly"),
        default="all",
        help="کدام feed پردازش شود (پیش‌فرض all).",
    )
    parser.add_argument(
        "--letter-type",
        type=int,
        action="append",
        dest="letter_types",
        help="LetterType مشخص (مثلاً 6 یا 58). قابل تکرار.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="فقط کشف و گزارش؛ هیچ جدولی تغییر نمی‌کند.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="۰/خالی = Auto (اسکن تا watermark با سقف ایمنی ۵). عدد صریح = دقیقاً این "
             "تعداد صفحه برای هر feed، بدون توقف زودهنگام watermark.",
    )
    parser.add_argument(
        "--overlap-hours",
        type=int,
        default=24,
        help="پنجره‌ی همپوشانی (ساعت) برای اینکه گزارش‌های مرزی از دست نروند (پیش‌فرض 24).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="حداکثر تعداد گزارش جدید برای پردازش (0 = بی‌نهایت).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="حداکثر تلاش مجدد برای گزارش‌های failed.",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="جمع‌آوری فقط برای یک نماد (سرچ کدال به‌جای feed سراسری).",
    )
    parser.add_argument("--from-date", default=None, help="تاریخ شمسی شروع (مثلاً 1405/01/01).")
    parser.add_argument("--to-date", default=None, help="تاریخ شمسی پایان.")
    parser.add_argument("--verbose", action="store_true", help="لاگ دیباگ.")
    return parser.parse_args(argv)


def resolve_letter_types(args: argparse.Namespace) -> list[int]:
    if args.letter_types:
        return list(dict.fromkeys(args.letter_types))
    if args.type == "financial":
        return [FINANCIAL_LETTER_TYPE]
    if args.type == "monthly":
        return [MONTHLY_LETTER_TYPE]
    return [FINANCIAL_LETTER_TYPE, MONTHLY_LETTER_TYPE]


def _new_stats(letter_type: int) -> dict:
    return {
        "letter_type": letter_type,
        "pages": 0,
        "stop_reason": None,
        "scanned": 0,
        "skipped_unknown_ticker": 0,
        "skipped_unsupported_type": 0,
        "skipped_missing_metadata": 0,
        "already": 0,
        "new": 0,
        "fetched": 0,
        "processed": 0,
        "completed": 0,
        "failed": 0,
        "unsupported": 0,
        "candidates": [],
        "errors": [],
    }


def _record_skip(stats: dict, reason: str) -> None:
    if reason in ("unknown_ticker", "missing_symbol"):
        stats["skipped_unknown_ticker"] += 1
    elif reason in ("missing_metadata", "no_html"):
        stats["skipped_missing_metadata"] += 1
    else:
        stats["skipped_unsupported_type"] += 1


_TZ_TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _aware(dt: datetime | None) -> datetime | None:
    """published_at از feed بدون timezone است (ساعت محلی تهران)؛ برای مقایسه با
    watermark در پستگرس (TIMESTAMPTZ) باید هر دو aware باشند."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_TZ_TEHRAN)


def _oldest_published(reports) -> datetime | None:
    values = [r.published_at for r in reports if r.published_at is not None]
    return min(values) if values else None


def _newest_published(reports) -> datetime | None:
    values = [r.published_at for r in reports if r.published_at is not None]
    return max(values) if values else None


def sync_feed(
    letter_type: int,
    args: argparse.Namespace,
    conn,
    prefilter: codal_prefilter.ReportPreFilter | None = None,
    watermark: datetime | None = None,
    overlap: timedelta | None = None,
) -> tuple[dict, list[dict]]:
    """یک feed را اسکن می‌کند. خروجی: (stats, pending).

    ترتیب: pre-filter (metadata-only) → dedup با SQL Server → فقط سپس pending.
    توقف صفحه‌ها **مستقل از candidate** است: تا وقتی PublishDateTime گزارش‌های
    صفحه جدیدتر از ``watermark - overlap`` باشد ادامه می‌دهد؛ در نبود watermark
    (اولین اجرا) فقط ``--max-pages`` به‌عنوان سقف ایمنی عمل می‌کند.
    """
    route = route_for_letter_type(letter_type)
    stats = _new_stats(letter_type)
    overlap = overlap or timedelta(0)

    if prefilter is None:
        prefilter = codal_prefilter.ReportPreFilter.allow_all()

    pending: list[dict] = []
    scan_newest: datetime | None = None
    page_number = 1

    while True:
        if args.max_pages and stats["pages"] >= args.max_pages:
            stats["stop_reason"] = "max_pages_reached"
            break

        page = codal_feed.discover_reports(
            letter_type,
            page_number,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        stats["pages"] += 1

        if not page.reports:
            stats["stop_reason"] = "empty_feed"
            break

        page_newest = _newest_published(page.reports)
        if page_newest is not None and (scan_newest is None or page_newest > scan_newest):
            scan_newest = page_newest

        known = (
            registry.get_statuses(conn, [r.report_id for r in page.reports])
            if conn is not None
            else {}
        )

        new_on_page = 0
        for report in page.reports:
            stats["scanned"] += 1

            # ── PRE-FILTER: فقط از روی metadata، بدون باز کردن مرورگر ──
            decision = prefilter.decide(report)
            if not decision.should_fetch:
                _record_skip(stats, decision.reason)
                if (
                    conn is not None
                    and not args.dry_run
                    and decision.ticker_known
                    and decision.reason
                    in (
                        "unsupported_monthly_title",
                        "unsupported_financial_title",
                        "unsupported_letter_type",
                        "missing_metadata",
                        "no_html",
                    )
                ):
                    status = known.get(report.report_id)
                    if status is None:
                        registry.register_discovered(conn, report)
                    if status not in registry.TERMINAL_STATUSES:
                        registry.mark_unsupported(conn, report.report_id, decision.reason)
                continue

            # ── DB FILTER: فقط بعد از عبور از pre-filter ──
            status = known.get(report.report_id)

            if args.dry_run:
                if status in registry.TERMINAL_STATUSES:
                    stats["already"] += 1
                else:
                    stats["new"] += 1
                    new_on_page += 1
                    stats["candidates"].append(
                        {
                            "report_id": report.report_id,
                            "ticker": report.ticker,
                            "title": report.title,
                            "published_at": report.published_at_raw,
                            "route": decision.route,
                            "url": report.report_url,
                        }
                    )
                if args.limit and stats["new"] >= args.limit:
                    break
                continue

            if status in registry.TERMINAL_STATUSES:
                stats["already"] += 1
                continue
            if status == registry.STATUS_PROCESSING:
                stats["already"] += 1
                continue

            if status is None:
                registry.register_discovered(conn, report)

            if registry.claim_for_processing(conn, report.report_id, args.max_attempts):
                stats["new"] += 1
                new_on_page += 1
                pending.append(
                    {
                        "report_id": report.report_id,
                        "route": decision.route or route,
                        "url": report.report_url,
                        "company_name": report.ticker or report.company_name,
                        "letter_type": letter_type,
                    }
                )
                if args.limit and stats["new"] >= args.limit:
                    break
            else:
                stats["already"] += 1

        logger.info(
            "📄 LetterType=%s page %s: %s scanned | candidates=%s | "
            "skip(ticker=%s type=%s meta=%s) | already=%s",
            letter_type,
            page.page_number,
            len(page.reports),
            new_on_page,
            stats["skipped_unknown_ticker"],
            stats["skipped_unsupported_type"],
            stats["skipped_missing_metadata"],
            stats["already"],
        )

        if args.limit and stats["new"] >= args.limit:
            logger.info("⏹️ Reached --limit=%s; stopping discovery.", args.limit)
            stats["stop_reason"] = "limit_reached"
            break

        # ── stop condition مستقل از candidate: watermark زمانی ──
        oldest = _oldest_published(page.reports)
        if watermark is not None and oldest is not None and oldest < (watermark - overlap):
            logger.info(
                "⏹️ LetterType=%s: reached watermark (oldest=%s < %s - %s); stop.",
                letter_type,
                oldest,
                watermark,
                overlap,
            )
            stats["stop_reason"] = "watermark_reached"
            break

        if page.is_last_page:
            stats["stop_reason"] = "empty_feed"
            break

        page_number += 1

    if stats["stop_reason"] is None:
        stats["stop_reason"] = "max_pages_reached"

    stats["_scan_newest"] = scan_newest
    return stats, pending


def process_pending(route: str, pending: list[dict], conn, stats: dict, max_attempts: int) -> None:
    if not pending:
        return

    import codal_processor  # lazy: فقط وقتی کاری برای پردازش هست

    handled: set[str] = set()

    def on_result(item: dict, status: str, report_date: str | None, error: str | None) -> None:
        handled.add(item["report_id"])
        stats["processed"] += 1
        if status == "completed":
            registry.mark_completed(conn, item["report_id"], report_date)
            stats["completed"] += 1
            logger.info("✅ %s (%s)", item["report_id"], item["company_name"])
        elif status == "unsupported":
            registry.mark_unsupported(conn, item["report_id"], error)
            stats["unsupported"] += 1
        else:
            registry.mark_failed(conn, item["report_id"], error or "unknown error")
            stats["failed"] += 1
            stats["errors"].append({"report_id": item["report_id"], "error": error})
            logger.error("❌ %s failed: %s", item["report_id"], error)

    try:
        codal_processor.process_batch(route, pending, conn, on_result)
    except Exception as exc:
        logger.exception("❌ Batch processing crashed for route=%s", route)
        for item in pending:
            if item["report_id"] in handled:
                continue
            registry.mark_failed(conn, item["report_id"], f"batch crash: {exc}")
            stats["processed"] += 1
            stats["failed"] += 1
            stats["errors"].append({"report_id": item["report_id"], "error": str(exc)})


FINANCIAL_TABLE = "miandore2"
MONTHLY_TABLE = "mahane"


def _extract_report_values(item: dict, page) -> tuple[str, str | None, str | None]:
    """استخراج اعداد از بدنه‌ی گزارش با پارس‌کننده‌های فعلی و نوشتن canonical.

    در حالت canonical-only، ``save_report_to_sql``/``scrape_report`` خودشان
    شاخه‌ی بدون SQL Server را می‌روند؛ اینجا فقط صدا زدن و ترجمه‌ی نتیجه است.
    خروجی: (status, report_date, error)
    """
    route = item["route"]
    url = item["url"]
    company_name = item["company_name"]
    if route == "monthly":
        import MianSql2
        parsed = MianSql2.parse_report_table(page, url)
        if not parsed:
            return "unsupported", None, "monthly report format not supported by parser"
        report_date = parsed.get("report_date")
        monthly_values = parsed.get("monthly_values")
        if not report_date or not monthly_values:
            return "unsupported", report_date, "missing report date or monthly values"
        ok = MianSql2.save_report_to_sql(
            company_name=company_name,
            report_date=report_date,
            monthly_values=monthly_values,
            base_url=url,
            table_name=MONTHLY_TABLE,
        )
        return ("completed" if ok else "failed"), report_date, (
            None if ok else "parser could not save values")
    import MianSql
    ok = MianSql.scrape_report(
        page=page, link=url, company_name=company_name,
        base_url=url, table_name=FINANCIAL_TABLE,
    )
    return ("completed" if ok else "failed"), None, (
        None if ok else "parser returned no saved data")


def run_sync_canonical_only(args: argparse.Namespace) -> dict:
    """Canonical-only Codal sync: fetch -> raw body -> canonical report lineage.

    No SQL Server connection is created. Discovery dedups against
    ``ingestion.reports`` (TracingNo) via ``canonical_hook.known_codal_report_ids``
    تا گزارش‌های شناخته‌شده دوباره دانلود و بازنویسی نشوند. بودجه‌ی صفحه
    (``--max-pages``) برای هر feed مستقل است و ``--limit`` روی گزارش‌های جدید
    اعمال می‌شود.

    خروجی علاوه بر کلیدهای canonical (``ingested/quarantined/errors``)، کلیدهای
    سازگار با UI قدیمی (``new/already/completed/failed/fetched`` و
    ``financial/monthly``) را هم دارد تا نمایش درست باشد.
    """
    import canonical_hook  # lazy

    letter_types = [
        lt for lt in resolve_letter_types(args) if route_for_letter_type(lt) != "unknown"
    ]
    if not letter_types:
        raise ValueError("No supported --letter-type given (only 6 and 58 are supported)")

    def _feed_stats(lt: int) -> dict:
        return {
            "letter_type": lt,
            "pages": 0,
            "stop_reason": None,
            "scanned": 0,
            "already": 0,
            "new": 0,
            "ingested": 0,
            "quarantined": 0,
            "errors": 0,
            "completed": 0,
            "failed": 0,
            "unsupported": 0,
        }

    feeds = {lt: _feed_stats(lt) for lt in letter_types}
    overlap = timedelta(hours=args.overlap_hours)
    # عدد صریح max_pages = عمق دقیق اسکن (توقف watermark غیرفعال)؛ ۰ = Auto
    explicit_depth = args.max_pages if args.max_pages and args.max_pages > 0 else 0
    scan_cap = explicit_depth or 5
    watermarks = {lt: None for lt in letter_types}
    scan_newest = {lt: None for lt in letter_types}
    # نامه‌های جدیدی که ذخیره شدند و باید اعدادشان استخراج شود
    pending_values: list[dict] = []

    for lt in letter_types:
        stats = feeds[lt]
        page_number = 1
        # incremental: بدون from-date صریح، تا «آبستن‌ mark آخرین sync موفق» عقب می‌رویم
        if not args.from_date and not explicit_depth:
            watermarks[lt] = canonical_hook.get_codal_watermark(lt)
        while True:
            if scan_cap and stats["pages"] >= scan_cap:
                stats["stop_reason"] = "max_pages_reached"
                break
            page = codal_feed.discover_reports(
                lt, page_number,
                from_date=args.from_date, to_date=args.to_date,
            )
            stats["pages"] += 1
            if not page.reports:
                stats["stop_reason"] = "empty_feed"
                break

            newest = _aware(_newest_published(page.reports))
            if newest is not None and (scan_newest[lt] is None or newest > scan_newest[lt]):
                scan_newest[lt] = newest

            known = canonical_hook.known_codal_report_ids(
                [r.report_id for r in page.reports]
            )
            for report in page.reports:
                stats["scanned"] += 1
                if report.report_id in known:
                    stats["already"] += 1
                    continue
                if args.dry_run:
                    stats["new"] += 1
                    continue

                res = canonical_hook.ingest_codal_authoritative(
                    report.raw, fetch_body=True
                )
                status = res.get("status")
                if status == "written":
                    stats["new"] += 1
                    stats["ingested"] += 1
                    display = canonical_hook.resolve_codal_company_display_name(
                        name=(report.raw.get("CompanyName") or "").strip() or None,
                        symbol=(report.raw.get("Symbol") or "").strip() or None,
                    )
                    pending_values.append({
                        "letter_type": lt,
                        "route": "monthly" if lt == MONTHLY_LETTER_TYPE else "financial",
                        "url": report.report_url,
                        "company_name": display or report.company_name or report.ticker or "",
                    })
                elif status == "quarantined":
                    # گزارش جدید است ولی هویت شرکت حل نشد
                    stats["new"] += 1
                    stats["quarantined"] += 1
                else:
                    stats["errors"] += 1

                if args.limit and stats["new"] >= args.limit:
                    break

            if args.limit and stats["new"] >= args.limit:
                stats["stop_reason"] = "limit_reached"
                break
            oldest = _aware(_oldest_published(page.reports))
            wm = watermarks[lt]
            if wm is not None and oldest is not None and oldest < (wm - overlap):
                stats["stop_reason"] = "watermark_reached"
                break
            if page.is_last_page:
                stats["stop_reason"] = "empty_feed"
                break
            page_number += 1
        if stats["stop_reason"] is None:
            stats["stop_reason"] = "max_pages_reached"

    # ── استخراج اعداد: پارس‌کننده‌های فعلی با یک browser context مشترک ──
    if pending_values and not args.dry_run:
        from playwright.sync_api import sync_playwright
        import MianSql
        with sync_playwright() as pw:
            context = MianSql.create_context(pw)
            page = context.new_page()
            try:
                for item in pending_values:
                    st = feeds[item["letter_type"]]
                    try:
                        v_status, _rdate, _err = _extract_report_values(item, page)
                    except Exception as exc:  # noqa: BLE001 - خطای هر گزارش مستقل است
                        logger.exception("❌ value extraction crashed: %s", item["url"])
                        v_status = "failed"
                    if v_status == "completed":
                        st["completed"] += 1
                        logger.info("✅ values extracted: %s (%s)",
                                    item["company_name"], item["route"])
                    elif v_status == "unsupported":
                        st["unsupported"] += 1
                    else:
                        st["failed"] += 1
            finally:
                context.close()

    for lt in letter_types:
        stats = feeds[lt]
        # advance watermark فقط وقتی feed بدون خطا کامل شد؛ در خطا، اجرای بعدی
        # دوباره از همین نقطه اسکن می‌کند تا گزارشی از دست نرود
        if stats["errors"] == 0 and not args.dry_run and scan_newest[lt] is not None:
            wm = watermarks[lt]
            target = scan_newest[lt] if (wm is None or scan_newest[lt] > wm) else wm
            canonical_hook.set_codal_watermark(lt, target)

    totals = {
        "scanned": sum(s["scanned"] for s in feeds.values()),
        "already": sum(s["already"] for s in feeds.values()),
        "new": sum(s["new"] for s in feeds.values()),
        "ingested": sum(s["ingested"] for s in feeds.values()),
        "quarantined": sum(s["quarantined"] for s in feeds.values()),
        "errors": sum(s["errors"] for s in feeds.values()),
        "pages": sum(s["pages"] for s in feeds.values()),
        # کلیدهای سازگار با UI قدیمی quick-sync — «completed» یعنی اعداد استخراج شد
        "completed": sum(s["completed"] for s in feeds.values()),
        "failed": sum(s["errors"] + s["failed"] for s in feeds.values()),
        "unsupported": sum(s["unsupported"] for s in feeds.values()),
        "fetched": sum(s["ingested"] for s in feeds.values()),
        "max_pages": scan_cap,
        "dry_run": args.dry_run,
        "authority": "CANONICAL",
        "mode": "canonical_only_offline",
    }
    summary = {
        "success": totals["errors"] == 0,
        "dry_run": args.dry_run,
        "canonical_only": True,
        "total": totals,
        "financial": feeds.get(FINANCIAL_LETTER_TYPE),
        "monthly": feeds.get(MONTHLY_LETTER_TYPE),
    }
    logger.info("canonical-only codal sync: %s", totals)
    return summary


def run_sync_symbol(args: argparse.Namespace) -> dict:
    """جمع‌آوری فقط برای یک نماد: آخرین ``--limit`` گزارش از سرچ کدال.

    برای هر گزارش: dedup با TracingNo → جدید = ذخیره‌ی خام + استخراج اعداد با
    پارس‌کننده‌ها؛ قدیمی = شمرده‌شده به‌عنوان already. Watermark در این مسیر
    معنا ندارد (هدف همان نماد است، نه feed سراسری).
    """
    import canonical_hook

    letter_types = [
        lt for lt in resolve_letter_types(args) if route_for_letter_type(lt) != "unknown"
    ]
    if not letter_types:
        raise ValueError("No supported --letter-type given (only 6 and 58 are supported)")

    def _feed_stats(lt: int) -> dict:
        return {
            "letter_type": lt,
            "pages": 0,
            "stop_reason": None,
            "scanned": 0,
            "already": 0,
            "new": 0,
            "ingested": 0,
            "quarantined": 0,
            "errors": 0,
            "completed": 0,
            "failed": 0,
            "unsupported": 0,
        }

    feeds = {lt: _feed_stats(lt) for lt in letter_types}
    pending_values: list[dict] = []
    take = args.limit if args.limit and args.limit > 0 else 8

    for lt in letter_types:
        stats = feeds[lt]
        page = codal_feed.discover_reports(lt, 1, symbol=args.symbol)
        stats["pages"] = 1
        if not page.reports:
            stats["stop_reason"] = "empty_feed"
            continue
        stats["stop_reason"] = "symbol_scan_done"

        reports = page.reports[:take]
        known = canonical_hook.known_codal_report_ids(
            [r.report_id for r in reports]
        )
        for report in reports:
            stats["scanned"] += 1
            if report.report_id in known:
                stats["already"] += 1
                continue
            res = canonical_hook.ingest_codal_authoritative(
                report.raw, fetch_body=True
            )
            status = res.get("status")
            if status == "written":
                stats["new"] += 1
                stats["ingested"] += 1
                display = canonical_hook.resolve_codal_company_display_name(
                    name=(report.raw.get("CompanyName") or "").strip() or None,
                    symbol=(report.raw.get("Symbol") or "").strip() or None,
                )
                pending_values.append({
                    "letter_type": lt,
                    "route": "monthly" if lt == MONTHLY_LETTER_TYPE else "financial",
                    "url": report.report_url,
                    "company_name": display or report.company_name or report.ticker or "",
                })
            elif status == "quarantined":
                stats["new"] += 1
                stats["quarantined"] += 1
            else:
                stats["errors"] += 1

    # استخراج اعداد (یک browser context مشترک)
    if pending_values:
        from playwright.sync_api import sync_playwright
        import MianSql
        with sync_playwright() as pw:
            context = MianSql.create_context(pw)
            page = context.new_page()
            try:
                for item in pending_values:
                    st = feeds[item["letter_type"]]
                    try:
                        v_status, _rdate, _err = _extract_report_values(item, page)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("❌ value extraction crashed: %s", item["url"])
                        v_status = "failed"
                    if v_status == "completed":
                        st["completed"] += 1
                        logger.info("✅ values extracted: %s (%s)",
                                    item["company_name"], item["route"])
                    elif v_status == "unsupported":
                        st["unsupported"] += 1
                    else:
                        st["failed"] += 1
            finally:
                context.close()

    totals = {
        "scanned": sum(s["scanned"] for s in feeds.values()),
        "already": sum(s["already"] for s in feeds.values()),
        "new": sum(s["new"] for s in feeds.values()),
        "ingested": sum(s["ingested"] for s in feeds.values()),
        "quarantined": sum(s["quarantined"] for s in feeds.values()),
        "errors": sum(s["errors"] for s in feeds.values()),
        "pages": sum(s["pages"] for s in feeds.values()),
        "completed": sum(s["completed"] for s in feeds.values()),
        "failed": sum(s["failed"] for s in feeds.values()),
        "unsupported": sum(s["unsupported"] for s in feeds.values()),
        "fetched": sum(s["ingested"] for s in feeds.values()),
        "dry_run": args.dry_run,
        "authority": "CANONICAL",
        "mode": "symbol_scan",
        "symbol": args.symbol,
    }
    return {
        "success": totals["errors"] == 0,
        "dry_run": args.dry_run,
        "canonical_only": True,
        "total": totals,
        "financial": feeds.get(FINANCIAL_LETTER_TYPE),
        "monthly": feeds.get(MONTHLY_LETTER_TYPE),
    }


def run_sync(args: argparse.Namespace) -> dict:
    # Canonical-only offline: never open SQL Server for the Codal path.
    # فقط «بررسی شرایط» در try است؛ خود اجرای canonical نباید در خطا بی‌صدا
    # به مسیر legacy بیفتد (اجرای دوباره/دوگانه). خطا به main() برمی‌گردد.
    try:
        import canonical_hook as _hook
        canonical_route = _hook.canonical_only_offline() and _hook.codal_canonical_authority()
    except Exception:  # noqa: BLE001
        canonical_route = False
    if canonical_route and getattr(args, "symbol", None):
        return run_sync_symbol(args)
    if canonical_route:
        return run_sync_canonical_only(args)
    if not args.max_pages:  # Auto در مسیر legacy هم به کپ ایمنی ۵ ترجمه می‌شود
        args.max_pages = 5

    letter_types = [
        lt for lt in resolve_letter_types(args) if route_for_letter_type(lt) != "unknown"
    ]
    if not letter_types:
        raise ValueError("No supported --letter-type given (only 6 and 58 are supported)")

    conn = None
    if not args.dry_run:
        conn = registry.get_db_connection()
        registry.ensure_registry(conn)
        codal_sync_state.ensure_state(conn)
    else:
        try:
            conn = registry.get_db_connection()
        except Exception as exc:  # noqa: BLE001 - dry-run بدون DB هم کار می‌کند
            logger.warning("⚠️ dry-run without DB connection: %s", exc)
            conn = None

    # universe نمادها از master ticker list خوانده می‌شود (نه از داده‌ی تاریخی).
    prefilter = codal_prefilter.ReportPreFilter.allow_all()
    if conn is not None:
        try:
            if args.dry_run:
                # dry-run نباید چیزی بنویسد؛ universe را in-memory می‌سازیم.
                tickers = codal_universe.load_tickers_inmemory(conn)
                prefilter = codal_prefilter.ReportPreFilter(
                    ticker_universe=tickers, _enforce_ticker=True
                )
                logger.info(
                    "🧭 ticker universe (dry-run, in-memory) source=dbo.%s.Symbol "
                    "+ seed sources total=%s",
                    codal_universe.UNIVERSE_TABLE,
                    len(tickers),
                )
            else:
                codal_universe.ensure_universe(conn)
                added = codal_universe.refresh_universe(conn)
                prefilter = codal_prefilter.ReportPreFilter.from_db(conn)
                logger.info(
                    "🧭 ticker universe source=dbo.%s.Symbol total=%s (added %s new)",
                    codal_universe.UNIVERSE_TABLE,
                    codal_universe.count_tickers(conn),
                    added,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️ ticker filter disabled (universe load failed): %s", exc)

    summary: dict = {"success": True, "dry_run": args.dry_run}
    totals = {
        "scanned": 0,
        "skipped_unknown_ticker": 0,
        "skipped_unsupported_type": 0,
        "skipped_missing_metadata": 0,
        "already": 0,
        "new": 0,
        "fetched": 0,
        "completed": 0,
        "failed": 0,
        "unsupported": 0,
    }
    any_error = False
    overlap = timedelta(hours=max(0, args.overlap_hours))

    try:
        for letter_type in letter_types:
            watermark = (
                codal_sync_state.get_watermark(conn, letter_type) if conn is not None else None
            )
            logger.info(
                "🔖 LetterType=%s watermark=%s overlap=%s",
                letter_type,
                watermark,
                overlap,
            )

            stats, pending = sync_feed(
                letter_type, args, conn, prefilter, watermark=watermark, overlap=overlap
            )
            scan_newest = stats.pop("_scan_newest", None)
            key = route_for_letter_type(letter_type)

            if conn is not None and not args.dry_run:
                process_pending(key, pending, conn, stats, args.max_attempts)

            # ── به‌روزرسانی watermark (فقط غیر dry-run) ──
            if conn is not None and not args.dry_run and scan_newest is not None:
                if watermark is None:
                    # اولین اجرا: بعد از سقف ایمنی، watermark ذخیره می‌شود تا
                    # اجرای بعدی incremental شود.
                    codal_sync_state.set_watermark(conn, letter_type, scan_newest)
                    logger.info("🔖 LetterType=%s watermark initialized → %s", letter_type, scan_newest)
                elif stats["stop_reason"] != "max_pages_reached":
                    new_wm = max(scan_newest, watermark)
                    codal_sync_state.set_watermark(conn, letter_type, new_wm)
                    logger.info("🔖 LetterType=%s watermark advanced → %s", letter_type, new_wm)
                else:
                    logger.warning(
                        "⚠️ LetterType=%s watermark NOT advanced (max_pages_reached; "
                        "possible unscanned pages).",
                        letter_type,
                    )

            stats["fetched"] = stats["processed"]
            candidates = stats.pop("candidates", [])
            errors = stats.pop("errors", [])
            summary[key] = stats
            summary[key]["candidates"] = candidates
            summary[key]["errors"] = errors

            logger.info(
                "═ %s summary ═ pages=%s stop_reason=%s | scanned=%s | "
                "skip(unknown_ticker=%s, unsupported_type=%s, missing_metadata=%s) | "
                "already=%s | candidates=%s | fetched=%s (completed=%s failed=%s)",
                key,
                stats["pages"],
                stats["stop_reason"],
                stats["scanned"],
                stats["skipped_unknown_ticker"],
                stats["skipped_unsupported_type"],
                stats["skipped_missing_metadata"],
                stats["already"],
                stats["new"],
                stats["fetched"],
                stats["completed"],
                stats["failed"],
            )

            for k in totals:
                totals[k] += int(stats.get(k, 0))
            if stats.get("failed"):
                any_error = True
    finally:
        if conn is not None:
            conn.close()

    summary["total"] = totals
    summary["success"] = not any_error
    return summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    # قرارداد Go: stdout فقط JSON نهایی؛ همه‌ی print/log پارسرها به stderr.
    real_stdout = sys.stdout
    for stream in (real_stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.stdout = sys.stderr

    try:
        try:
            summary = run_sync(args)
            exit_code = 0 if summary.get("success") else 1
        except Exception as exc:
            logger.exception("Sync failed")
            summary = {"success": False, "error": str(exc)}
            exit_code = 1
    finally:
        sys.stdout = real_stdout

    real_stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
    real_stdout.write("\n")
    real_stdout.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
