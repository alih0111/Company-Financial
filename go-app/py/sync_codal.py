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
import time
import urllib.parse
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
        "--repair-days",
        type=int,
        default=7,
        help="پنجرهٔ ترمیم گزارش‌های ناقص (فقط metadata، بدون بدنه) بر حسب روز؛ "
             "۰ = غیرفعال. هر اجرا حداکثر --repair-limit گزارش را ترمیم می‌کند.",
    )
    parser.add_argument(
        "--repair-limit",
        type=int,
        default=30,
        help="سقف گزارش‌های ناقصی که در همین اجرا بدنه‌شان دوباره گرفته می‌شود "
             "(پیش‌فرض محافظه‌کارانه تا کدال محدود نشود).",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=7,
        help="اگر صفحه‌های قدیمی‌تر از آخرین sync گزارشِ تحت‌پوششِ ندیده داشته "
             "باشند، اسکن تا این تعداد روز عقب می‌رود (۰ = بدون بازگشت).",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="جمع‌آوری فقط برای یک نماد (سرچ کدال به‌جای feed سراسری).",
    )
    parser.add_argument("--from-date", default=None, help="تاریخ شمسی شروع (مثلاً 1405/01/01).")
    parser.add_argument("--to-date", default=None, help="تاریخ شمسی پایان.")
    parser.add_argument("--verbose", action="store_true", help="لاگ دیباگ.")
    parser.add_argument("--job-id", default=None, help=argparse.SUPPRESS)
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


def _record_error(stats: dict, report_id: str, res: dict) -> None:
    """Keep the first few failure reasons so the panel can explain the error."""
    reason = str(res.get("error") or res.get("status") or "unknown")
    bucket = stats.setdefault("errors_detail", [])
    if len(bucket) < 5:
        bucket.append({"report_id": str(report_id), "error": reason[:400]})


def _publish_job_progress(stage: str, stats: dict, page: int | None = None,
                          report_id: str | None = None, message: str | None = None) -> None:
    if not __import__("os").environ.get("CODAL_JOB_DIR"):
        return
    try:
        from codal_challenge import current_channel
        channel = current_channel()
        if channel:
            channel.update(state="running_browser" if stage in ("report_body", "extraction") else "running_http",
                           stage=stage, current_page=page, current_report_id=report_id,
                           counters={key:int(stats.get(key,0)) for key in
                                     ("scanned","already","new","ingested","completed","failed","errors")},
                           message=message or "در حال بررسی گزارش‌های کدال")
    except Exception:
        logger.debug("Could not publish Codal job progress", exc_info=True)


def _discover_page(letter_type: int, page_number: int, stats: dict, **kwargs):
    """یک صفحهٔ فید کدال؛ محدودیت نرخ یعنی «فعلاً بس است»، نه خرابی اجرا.

    صفحه‌های قبلی همان‌جا ذخیره شده‌اند، پس اجرا با خطا تمام نمی‌شود؛ فقط اسکن
    با ``stop_reason="rate_limited"`` می‌ایستد و اجرای بعدی ادامه می‌دهد.
    """
    from codal_transport import CodalRateLimited
    try:
        return codal_feed.discover_reports(letter_type, page_number, **kwargs)
    except CodalRateLimited as exc:
        stats["stop_reason"] = "rate_limited"
        logger.warning(
            "Codal rate limited at LetterType=%s page=%s: %s", letter_type, page_number, exc
        )
        _publish_job_progress(
            "rate_limited", stats, page_number,
            message=(f"کدال موقتاً محدود کرد؛ اسکن در صفحهٔ {page_number} ایستاد و "
                     "گزارش‌های همین چند صفحه ذخیره شدند."),
        )
        return None


def _letter_type_from_url(url: str | None, default: int = FINANCIAL_LETTER_TYPE) -> int:
    """نوع نامه از ``let`` داخل آدرس گزارش (بدون فراخوانی کدال)."""
    try:
        query = urllib.parse.urlparse(url or "").query
        let = urllib.parse.parse_qs(query).get("let", [""])[0]
        return int(let) if let.strip().isdigit() else default
    except (ValueError, AttributeError):
        return default


def _repair_incomplete_reports(args: argparse.Namespace, feeds: dict,
                               pending_values: list[dict]) -> int:
    """گزارش‌هایی که فقط metadataشان ذخیره شده را دوباره با بدنه دریافت می‌کند.

    مسیرهای soak/مایگریشن (``fetch_body=False``) ردیف گزارش را بدون بدنه
    نوشته‌اند و Dedup قدیمی آن را «دریافت‌شده» می‌شمرد؛ در نتیجه هیچ عددی
    استخراج نمی‌شد. این ترمیم همان گزارش‌ها را با بدنه و سپس با پارسرهای
    موجود تکمیل می‌کند. هر گزارش مستقل است؛ خطای یکی بقیه را متوقف نمی‌کند.
    """
    if args.dry_run or args.repair_days <= 0 or args.repair_limit <= 0:
        return 0

    import canonical_hook

    letter_types = [lt for lt in resolve_letter_types(args)
                    if route_for_letter_type(lt) != "unknown"]
    try:
        rows = canonical_hook.incomplete_codal_reports(
            days=args.repair_days,
            limit=args.repair_limit,
            letter_types=tuple(letter_types),
            symbol=args.symbol,
        )
    except Exception:
        logger.exception("⚠️ incomplete-report lookup failed; continuing without body repair")
        rows = []

    if not rows:
        logger.info("no bodyless Codal report to repair in the last %s days", args.repair_days)

    repaired = 0
    consecutive_failures = 0
    for row in rows:
        url = row.get("url") or ""
        # ردیف‌های قدیمی soak آدرس نسبی کدال را ذخیره کرده‌اند؛ برای دریافت
        # بدنه باید مطلق باشد.
        if url.startswith("/"):
            url = urllib.parse.urljoin(codal_feed.CODAL_BASE_URL, url)
        letter_type = _letter_type_from_url(url)
        if letter_type not in feeds:
            letter_type = letter_types[0]
        # گزارش‌های حسابرسی‌شده/تلفیقی (زیرمجموعه‌ها) در «سود» جمع نمی‌شوند.
        if letter_type == FINANCIAL_LETTER_TYPE and codal_feed.is_audited_title(row.get("title")):
            continue
        stats = feeds[letter_type]
        _publish_job_progress("repair", stats, None, row.get("report_id"),
                              "در حال ترمیم گزارش‌های ناقص (بدنه ذخیره نشده بود)")
        letter = {
            "TracingNo": row.get("report_id"),
            "Symbol": row.get("symbol"),
            "CompanyName": row.get("company_name") or row.get("symbol"),
            "Title": row.get("title"),
            "Url": url,
        }
        try:
            result = canonical_hook.ingest_codal_authoritative(
                letter, fetch_body=True
            )
        except (InterruptedError, TimeoutError):
            raise
        except Exception:
            logger.exception("❌ repair crashed: %s", row.get("report_id"))
            stats["repair_failed"] = stats.get("repair_failed", 0) + 1
            time.sleep(1.5)
            continue

        # فاصلهٔ اضافی مخصوص ترمیم: بدنه‌ها پشت‌سرهم از یک دامنه می‌آیند و
        # کدال در burst طولانی با XML/429 پاسخ می‌دهد.
        time.sleep(1.5)

        if result.get("status") == "written":
            repaired += 1
            consecutive_failures = 0
            stats["repaired"] = stats.get("repaired", 0) + 1
            pending_values.append({
                "report_id": str(row.get("report_id") or ""),
                "letter_type": letter_type,
                "route": "monthly" if letter_type == MONTHLY_LETTER_TYPE else "financial",
                "url": url,
                "company_name": (canonical_hook.resolve_codal_company_display_name(
                    name=row.get("company_name"), symbol=row.get("symbol")
                ) or row.get("company_name") or row.get("symbol") or ""),
            })
            logger.info("🩹 repaired report %s (%s)", row.get("report_id"), row.get("symbol"))
        else:
            stats["repair_failed"] = stats.get("repair_failed", 0) + 1
            consecutive_failures += 1
            logger.warning("⚠️ could not repair report %s: %s", row.get("report_id"),
                           result.get("error") or result.get("status"))
            if consecutive_failures >= 5:
                # کدال در دسترس/تأیید نیست؛ تلاش بیشتر فقط محدودیت را طولانی‌تر می‌کند.
                logger.warning("⏹️ repair stopped after %s consecutive failures", consecutive_failures)
                break

    # بدنه‌هایی که تازه ذخیره شده‌اند ولی استخراج اعدادشان نیمه‌کاره مانده
    # (مثلاً لغو job پیش از استخراج) را بدون دانلود دوباره صف کن.
    try:
        value_rows = canonical_hook.codal_reports_missing_values(
            days=args.repair_days, hours=6, limit=args.repair_limit,
            letter_types=tuple(letter_types), symbol=args.symbol,
        )
    except Exception:
        logger.exception("⚠️ missing-values lookup failed")
        value_rows = []

    queued = {str(item.get("report_id") or "") for item in pending_values}
    for row in value_rows:
        report_id = str(row.get("report_id") or "")
        if not report_id or report_id in queued:
            continue
        queued.add(report_id)
        url = row.get("url") or ""
        if url.startswith("/"):
            url = urllib.parse.urljoin(codal_feed.CODAL_BASE_URL, url)
        letter_type = _letter_type_from_url(url)
        if letter_type not in feeds:
            letter_type = letter_types[0]
        # گزارش‌های حسابرسی‌شده/تلفیقی (زیرمجموعه‌ها) در «سود» جمع نمی‌شوند.
        if letter_type == FINANCIAL_LETTER_TYPE and codal_feed.is_audited_title(row.get("title")):
            continue
        stats = feeds[letter_type]
        stats["values_queued"] = stats.get("values_queued", 0) + 1
        pending_values.append({
            "report_id": report_id,
            "letter_type": letter_type,
            "route": "monthly" if letter_type == MONTHLY_LETTER_TYPE else "financial",
            "url": url,
            "company_name": (canonical_hook.resolve_codal_company_display_name(
                name=row.get("company_name"), symbol=row.get("symbol")
            ) or row.get("company_name") or row.get("symbol") or ""),
        })
        logger.info("🧮 queued pending values extraction for %s (%s)", report_id, row.get("symbol"))
    return repaired


def _extract_value_item(item: dict, page, stats: dict) -> str:
    """استخراج اعداد «یک» گزارش با پارسرهای فعلی و ثبت نتیجه در stats همان feed.

    خطای لغو/کپچا عمداً بالا فرستاده می‌شود (کل job باید متوقف شود)؛ بقیهٔ
    خطاها «failed» شمرده می‌شوند تا اجرای بعدی دوباره تلاش کند.
    """
    try:
        if __import__("os").environ.get("CODAL_JOB_DIR"):
            _publish_job_progress("extraction", stats,
                                  report_id=str(item.get("report_id") or ""),
                                  message="در حال استخراج اطلاعات گزارش")
        status, report_date, _error = _extract_report_values(item, page)
    except (InterruptedError, TimeoutError):
        raise
    except Exception as exc:
        try:
            from codal_challenge import CodalChallengeError
            if isinstance(exc, CodalChallengeError):
                raise
        except ImportError:
            pass
        logger.exception("❌ value extraction crashed: %s", item["url"])
        status, report_date = "failed", None
    if status == "completed":
        stats["completed"] += 1
        logger.info("✅ values extracted: %s (%s)", item["company_name"], item["route"])
    elif status == "unsupported":
        stats["unsupported"] += 1
    else:
        stats["failed"] += 1
    # موفق/unsupported را علامت بزن تا اجرای بعدی دوباره استخراج نکند.
    # failed بدون علامت می‌ماند تا در اجرای بعدی دوباره تلاش شود.
    if status in ("completed", "unsupported") and item.get("report_id"):
        try:
            import canonical_hook
            canonical_hook.mark_codal_values_extraction(
                item["report_id"], status=status, report_date=report_date)
        except Exception:
            logger.debug("could not mark values extraction", exc_info=True)
    return status


def _extract_new_report_now(item: dict, feeds: dict) -> bool:
    """گزارش تازه را «همین لحظه» کامل جمع کن؛ بعد اسکن به فهرست کدال برگردد.

    در حالت watched (جمع‌آوری سریع با مرورگر دیدنی) بلافاصله پس از ذخیرهٔ
    بدنه، صفحهٔ همان گزارش باز و تمام تب‌هایش استخراج می‌شود تا اپراتور
    ببیند هر گزارش کامل می‌شود. اسکن بی‌صدا (HTTP/خودکار) مثل قبل استخراج
    را به صف انتهایی می‌سپارد تا وسط اسکن مرورگر باز نشود.
    """
    if not __import__("os").environ.get("CODAL_JOB_DIR"):
        return False
    from codal_transport import current
    transport = current()
    if not transport.visible_collection():
        return False
    _extract_value_item(item, transport.shared_page(), feeds[item["letter_type"]])
    return True


def _extract_pending_values(pending_values: list[dict], feeds: dict) -> None:
    """Run existing parsers in the job's browser context when a job is active."""
    if not pending_values:
        return
    import MianSql

    def process(page):
        for item in pending_values:
            _extract_value_item(item, page, feeds[item["letter_type"]])

    if __import__("os").environ.get("CODAL_JOB_DIR"):
        from codal_transport import current
        try:
            from codal_challenge import current_channel
            channel = current_channel()
            if channel:
                channel.update(state="opening_browser", stage="extraction",
                               message="در حال باز کردن مرورگر برای دریافت متن گزارش‌های جدید")
        except Exception:
            logger.debug("Could not publish opening_browser state", exc_info=True)
        process(current().shared_page())
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        context = MianSql.create_context(playwright)
        try:
            process(context.new_page())
        finally:
            context.close()


_TZ_TEHRAN = timezone(timedelta(hours=3, minutes=30))


def _aware(dt: datetime | None) -> datetime | None:
    """published_at از feed بدون timezone است (ساعت محلی تهران)؛ برای مقایسه با
    watermark در پستگرس (TIMESTAMPTZ) باید هر دو aware باشند."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_TZ_TEHRAN)


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
    scan_oldest: datetime | None = None
    page_number = 1

    while True:
        page_cap = args.max_pages
        if watermark is not None and not getattr(args, "max_pages_explicit", False):
            page_cap = 0
        if page_cap and stats["pages"] >= page_cap:
            stats["stop_reason"] = "max_pages_reached"
            break

        page = _discover_page(
            letter_type,
            page_number,
            stats,
            from_date=args.from_date,
            to_date=args.to_date,
        )
        if page is None:
            break
        stats["pages"] += 1

        if page.is_empty:
            stats["stop_reason"] = "empty_feed"
            break

        page_newest = page.newest_published
        if page_newest is not None and (scan_newest is None or page_newest > scan_newest):
            scan_newest = page_newest
        page_oldest = page.oldest_published
        if page_oldest is not None and (scan_oldest is None or page_oldest < scan_oldest):
            scan_oldest = page_oldest

        known = (
            registry.get_statuses(conn, [r.report_id for r in page.reports])
            if conn is not None
            else {}
        )

        new_on_page = 0
        for report in page.reports:
            stats["scanned"] += 1
            _publish_job_progress("discovery", stats, page_number, report.report_id)

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
        oldest = page.oldest_published
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
    stats["_scan_oldest"] = scan_oldest
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
            "quarantined_symbols": {},
            "repaired": 0,
            "repair_failed": 0,
            "values_queued": 0,
            "errors": 0,
            "errors_detail": [],
            "completed": 0,
            "failed": 0,
            "unsupported": 0,
            "scan_oldest": None,
            "scan_newest": None,
        }

    feeds = {lt: _feed_stats(lt) for lt in letter_types}
    overlap = timedelta(hours=args.overlap_hours)
    # عدد صریح max_pages = عمق دقیق اسکن (توقف watermark غیرفعال)؛ ۰ = Auto
    explicit_depth = args.max_pages if args.max_pages and args.max_pages > 0 else 0
    scan_cap = explicit_depth or 5
    watermarks = {lt: None for lt in letter_types}
    scan_newest = {lt: None for lt in letter_types}
    scan_oldest = {lt: None for lt in letter_types}
    # نامه‌های جدیدی که ذخیره شدند و باید اعدادشان استخراج شود
    pending_values: list[dict] = []

    # نمادهای تحت پوشش canonical: گزارش نمادهای بیرون از پوشش نه ذخیره می‌شود
    # و نه اسکن را وادار به عقب‌رفتن می‌کند.
    covered = canonical_hook.codal_covered_symbols()
    if not covered:
        covered = None
    # مرز بازگشتی فقط اسکن «خودکار» را مهار می‌کند؛ عدد صریح max-pages یعنی
    # «دقیقاً همین عمق» و نباید پیش از تمام‌شدن صفحات بایستد.
    backfill_floor = (
        datetime.now(_TZ_TEHRAN) - timedelta(days=args.backfill_days)
        if args.backfill_days and args.backfill_days > 0 and not explicit_depth
        else None
    )

    # ── ترمیم گزارش‌های ناقص (فقط metadata، بدون بدنه) ──
    # این کار پیش از اسکن انجام می‌شود تا گزارش‌هایی که مسیرهای soak/مایگریشن
    # بدون بدنه نوشته‌اند، دوباره دریافت و اعدادشان استخراج شود.
    _repair_incomplete_reports(args, feeds, pending_values)

    for lt in letter_types:
        stats = feeds[lt]
        page_number = 1
        feed_scan_cap = scan_cap
        # incremental: بدون from-date صریح، تا «آبستن‌ mark آخرین sync موفق» عقب می‌رویم
        if not args.from_date and not explicit_depth:
            watermarks[lt] = canonical_hook.get_codal_watermark(lt)
            # Once initialized, scan until the watermark instead of repeatedly
            # stopping at the same first five mixed-feed pages.
            if watermarks[lt] is not None:
                feed_scan_cap = 0
        while True:
            if feed_scan_cap and stats["pages"] >= feed_scan_cap:
                stats["stop_reason"] = "max_pages_reached"
                break
            page = _discover_page(
                lt, page_number,
                stats,
                from_date=args.from_date, to_date=args.to_date,
            )
            if page is None:
                break
            stats["pages"] += 1
            if page.is_empty:
                # صفحه واقعاً خالی است (نه اینکه فقط نامه‌ای از نوع ما نداشته باشد)
                stats["stop_reason"] = "empty_feed"
                break

            newest = _aware(page.newest_published)
            if newest is not None and (scan_newest[lt] is None or newest > scan_newest[lt]):
                scan_newest[lt] = newest
            oldest_on_page = _aware(page.oldest_published)
            if oldest_on_page is not None and (scan_oldest[lt] is None or oldest_on_page < scan_oldest[lt]):
                scan_oldest[lt] = oldest_on_page

            known = canonical_hook.known_codal_report_ids(
                [r.report_id for r in page.reports]
            )
            seen = canonical_hook.seen_codal_report_ids(
                [r.report_id for r in page.reports]
            )
            # آیا این صفحه گزارشِ تحت‌پوششِ «ندیده» دارد؟ اگر بله، حتی اگر از
            # watermark هم قدیمی‌تر باشد، اسکن باید ادامه پیدا کند تا گزارش
            # عقب‌افتاده هم جمع شود (خواستهٔ «قدمی‌تر برو و جمعش کن»).
            page_unseen_covered = False
            for report in page.reports:
                ticker = (report.ticker or "").strip()
                if covered is not None and ticker and ticker not in covered:
                    continue
                if report.report_id not in seen:
                    page_unseen_covered = True
                    break

            for report in page.reports:
                stats["scanned"] += 1
                _publish_job_progress("discovery", stats, page_number, report.report_id)
                ticker = (report.ticker or "").strip()
                if covered is not None and ticker and ticker not in covered:
                    # خارج از پوشش: بدون نوشتن ردیف قرنطینه و بدون اثر بر
                    # تصمیم ادامهٔ اسکن؛ فقط برای شفافیت شمرده می‌شود.
                    stats["quarantined"] += 1
                    key = ticker or report.company_name or "نامشخص"
                    per_symbol = stats["quarantined_symbols"]
                    per_symbol[key] = per_symbol.get(key, 0) + 1
                    continue
                if report.report_id in known:
                    stats["already"] += 1
                    continue
                if args.dry_run:
                    stats["new"] += 1
                    continue

                _publish_job_progress(
                    "report_body", stats, page_number, report.report_id,
                    message=f"دریافت بدنهٔ گزارش {report.report_id}",
                )
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
                    item = {
                        "report_id": report.report_id,
                        "letter_type": lt,
                        "route": "monthly" if lt == MONTHLY_LETTER_TYPE else "financial",
                        "url": report.report_url,
                        "company_name": display or report.company_name or report.ticker or "",
                    }
                    # «همین‌جا کامل جمعش کن»: بدنه ذخیره شد؛ صفحهٔ همان گزارش
                    # باز و تمام تب‌هایش استخراج می‌شود و اسکن به فهرست کدال
                    # برمی‌گردد. فقط اجرای بی‌صدا (HTTP/خودکار) آن را به صف
                    # انتهایی می‌سپارد.
                    if not _extract_new_report_now(item, feeds):
                        pending_values.append(item)
                elif status == "quarantined":
                    # خارج از پوشش: نماد/شرکت در universe کانونیکال نیست و
                    # «جدید» شمرده نمی‌شود تا UI «جدید» را فقط برای نمادهای
                    # تحت پوشش نشان دهد (خودِ تعداد در quarantined می‌آید).
                    stats["quarantined"] += 1
                    key = report.ticker or report.company_name or "نامشخص"
                    per_symbol = stats["quarantined_symbols"]
                    per_symbol[key] = per_symbol.get(key, 0) + 1
                else:
                    stats["errors"] += 1
                    _record_error(stats, report.report_id, res)

                if args.limit and stats["new"] >= args.limit:
                    break

            if args.limit and stats["new"] >= args.limit:
                stats["stop_reason"] = "limit_reached"
                break
            oldest = _aware(page.oldest_published)
            wm = watermarks[lt]
            if backfill_floor is not None and oldest is not None and oldest < backfill_floor:
                stats["stop_reason"] = "backfill_floor_reached"
                break
            if (wm is not None and oldest is not None and oldest < (wm - overlap)
                    and page.reports
                    and (backfill_floor is None or not page_unseen_covered)):
                stats["stop_reason"] = "watermark_reached"
                break
            if page.is_last_page:
                stats["stop_reason"] = "empty_feed"
                break
            page_number += 1
        if stats["stop_reason"] is None:
            stats["stop_reason"] = "max_pages_reached"
        # پنجرهٔ زمانی واقعیِ همین اسکن (برای اینکه «۲ صفحه» قابل تفسیر باشد)
        stats["scan_oldest"] = scan_oldest[lt].isoformat() if scan_oldest[lt] else None
        stats["scan_newest"] = scan_newest[lt].isoformat() if scan_newest[lt] else None

    # ── استخراج اعداد: پارس‌کننده‌های فعلی با یک browser context مشترک ──
    if pending_values and not args.dry_run:
        _extract_pending_values(pending_values, feeds)

    for lt in letter_types:
        stats = feeds[lt]
        # advance watermark فقط وقتی feed بدون خطا کامل شد؛ در خطا، اجرای بعدی
        # دوباره از همین نقطه اسکن می‌کند تا گزارشی از دست نرود
        if (stats["errors"] == 0 and not args.dry_run
                and stats["stop_reason"] in ("watermark_reached", "empty_feed")
                and scan_newest[lt] is not None):
            wm = watermarks[lt]
            target = scan_newest[lt] if (wm is None or scan_newest[lt] > wm) else wm
            canonical_hook.set_codal_watermark(lt, target)
        elif (not args.dry_run and not args.from_date and not explicit_depth
              and stats["stop_reason"] == "max_pages_reached" and watermarks[lt] is None
              and scan_oldest[lt] is not None):
            # Bootstrap only the interval actually covered by the initial
            # safety-capped scan. Later runs fill forward from this boundary.
            canonical_hook.set_codal_watermark(lt, scan_oldest[lt])

    quarantined_symbols: dict[str, int] = {}
    for stats in feeds.values():
        for key, count in (stats.get("quarantined_symbols") or {}).items():
            quarantined_symbols[key] = quarantined_symbols.get(key, 0) + int(count)

    totals = {
        "scanned": sum(s["scanned"] for s in feeds.values()),
        "already": sum(s["already"] for s in feeds.values()),
        "new": sum(s["new"] for s in feeds.values()),
        "ingested": sum(s["ingested"] for s in feeds.values()),
        "quarantined": sum(s["quarantined"] for s in feeds.values()),
        "quarantined_symbols": quarantined_symbols,
        "repaired": sum(s["repaired"] for s in feeds.values()),
        "repair_failed": sum(s["repair_failed"] for s in feeds.values()),
        "values_queued": sum(s["values_queued"] for s in feeds.values()),
        "errors": sum(s["errors"] for s in feeds.values()),
        "errors_detail": [d for s in feeds.values() for d in (s.get("errors_detail") or [])][:5],
        "pages": sum(s["pages"] for s in feeds.values()),
        # کلیدهای سازگار با UI قدیمی quick-sync — «completed» یعنی اعداد استخراج شد
        "completed": sum(s["completed"] for s in feeds.values()),
        "failed": sum(s["errors"] + s["failed"] + s["repair_failed"] for s in feeds.values()),
        "unsupported": sum(s["unsupported"] for s in feeds.values()),
        "fetched": sum(s["ingested"] for s in feeds.values()),
        "max_pages": scan_cap,
        "dry_run": args.dry_run,
        "authority": "CANONICAL",
        "mode": "canonical_only_offline",
    }
    oldest_values = [s["scan_oldest"] for s in feeds.values() if s.get("scan_oldest")]
    newest_values = [s["scan_newest"] for s in feeds.values() if s.get("scan_newest")]
    totals["scan_oldest"] = min(oldest_values) if oldest_values else None
    totals["scan_newest"] = max(newest_values) if newest_values else None
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
            "quarantined_symbols": {},
            "repaired": 0,
            "repair_failed": 0,
            "values_queued": 0,
            "errors": 0,
            "errors_detail": [],
            "completed": 0,
            "failed": 0,
            "unsupported": 0,
            "scan_oldest": None,
            "scan_newest": None,
        }

    feeds = {lt: _feed_stats(lt) for lt in letter_types}
    pending_values: list[dict] = []
    take = args.limit if args.limit and args.limit > 0 else 8

    # ترمیم گزارش‌های ناقصِ همین نماد پیش از اسکن سرچ کدال
    _repair_incomplete_reports(args, feeds, pending_values)

    for lt in letter_types:
        stats = feeds[lt]
        page = _discover_page(lt, 1, stats, symbol=args.symbol)
        stats["pages"] = 1
        if page is None:
            # تک‌نماد: هیچ گزارشی خوانده نشده، پس این «صفر گزارش» نیست؛ خطاست.
            stats["errors"] += 1
            _record_error(stats, "", {"error": (
                "کدال موقتاً درخواست‌ها را محدود کرد؛ چند دقیقه بعد همین نماد را دوباره جمع‌آوری کنید."
            )})
            continue
        if page.is_empty:
            stats["stop_reason"] = "empty_feed"
            continue
        stats["stop_reason"] = "symbol_scan_done"

        reports = page.reports[:take]
        published = [r.published_at for r in reports if r.published_at is not None]
        if published:
            stats["scan_oldest"] = min(published).isoformat()
            stats["scan_newest"] = max(published).isoformat()
        known = canonical_hook.known_codal_report_ids(
            [r.report_id for r in reports]
        )
        for report in reports:
            stats["scanned"] += 1
            _publish_job_progress("discovery", stats, 1, report.report_id,
                                  f"در حال بررسی گزارش‌های نماد {args.symbol}")
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
                item = {
                    "report_id": report.report_id,
                    "letter_type": lt,
                    "route": "monthly" if lt == MONTHLY_LETTER_TYPE else "financial",
                    "url": report.report_url,
                    "company_name": display or report.company_name or report.ticker or "",
                }
                # مثل مسیر feed: در حالت دیدنی تب‌های همان گزارش بلافاصله جمع
                # می‌شود؛ اجرای بی‌صدا به صف انتهایی می‌سپارد.
                if not _extract_new_report_now(item, feeds):
                    pending_values.append(item)
            elif status == "quarantined":
                # خارج از پوشش؛ مثل مسیر feed جزو «جدید» شمرده نمی‌شود.
                stats["quarantined"] += 1
                key = report.ticker or report.company_name or "نامشخص"
                per_symbol = stats["quarantined_symbols"]
                per_symbol[key] = per_symbol.get(key, 0) + 1
            else:
                stats["errors"] += 1
                _record_error(stats, report.report_id, res)

    # استخراج اعداد (یک browser context مشترک)
    if pending_values:
        _extract_pending_values(pending_values, feeds)

    quarantined_symbols: dict[str, int] = {}
    for stats in feeds.values():
        for key, count in (stats.get("quarantined_symbols") or {}).items():
            quarantined_symbols[key] = quarantined_symbols.get(key, 0) + int(count)

    totals = {
        "scanned": sum(s["scanned"] for s in feeds.values()),
        "already": sum(s["already"] for s in feeds.values()),
        "new": sum(s["new"] for s in feeds.values()),
        "ingested": sum(s["ingested"] for s in feeds.values()),
        "quarantined": sum(s["quarantined"] for s in feeds.values()),
        "quarantined_symbols": quarantined_symbols,
        "repaired": sum(s["repaired"] for s in feeds.values()),
        "repair_failed": sum(s["repair_failed"] for s in feeds.values()),
        "values_queued": sum(s["values_queued"] for s in feeds.values()),
        "errors": sum(s["errors"] for s in feeds.values()),
        "errors_detail": [d for s in feeds.values() for d in (s.get("errors_detail") or [])][:5],
        "pages": sum(s["pages"] for s in feeds.values()),
        "completed": sum(s["completed"] for s in feeds.values()),
        "failed": sum(s["errors"] + s["failed"] + s["repair_failed"] for s in feeds.values()),
        "unsupported": sum(s["unsupported"] for s in feeds.values()),
        "fetched": sum(s["ingested"] for s in feeds.values()),
        "dry_run": args.dry_run,
        "authority": "CANONICAL",
        "mode": "symbol_scan",
        "symbol": args.symbol,
    }
    oldest_values = [s["scan_oldest"] for s in feeds.values() if s.get("scan_oldest")]
    newest_values = [s["scan_newest"] for s in feeds.values() if s.get("scan_newest")]
    totals["scan_oldest"] = min(oldest_values) if oldest_values else None
    totals["scan_newest"] = max(newest_values) if newest_values else None
    return {
        "success": totals["errors"] == 0,
        "dry_run": args.dry_run,
        "canonical_only": True,
        "total": totals,
        "financial": feeds.get(FINANCIAL_LETTER_TYPE),
        "monthly": feeds.get(MONTHLY_LETTER_TYPE),
    }


def run_sync(args: argparse.Namespace) -> dict:
    args.max_pages_explicit = bool(args.max_pages)
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
    if not args.max_pages:  # Auto: سقف فقط برای bootstrap بدون watermark است
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
            scan_oldest = stats.pop("_scan_oldest", None)
            key = route_for_letter_type(letter_type)

            if conn is not None and not args.dry_run:
                process_pending(key, pending, conn, stats, args.max_attempts)

            # ── به‌روزرسانی watermark (فقط غیر dry-run) ──
            if (conn is not None and not args.dry_run and stats.get("errors", 0) == 0
                    and stats.get("failed", 0) == 0 and scan_newest is not None
                    and stats["stop_reason"] in ("watermark_reached", "empty_feed", "max_pages_reached")):
                if watermark is None:
                    # Initialize at the oldest covered date if the scan hit its
                    # cap, so later runs can fill the unscanned interval.
                    initial_wm = scan_oldest if stats["stop_reason"] == "max_pages_reached" else scan_newest
                    codal_sync_state.set_watermark(conn, letter_type, initial_wm)
                    logger.info("🔖 LetterType=%s watermark initialized → %s", letter_type, initial_wm)
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


def _friendly_sync_error(exc: Exception) -> str:
    """خطای خام Playwright را برای نمایش در پنل قابل‌فهم کن."""
    text = str(exc)
    if "Target page, context or browser has been closed" in text or "TargetClosedError" in text:
        return ("پنجرهٔ مرورگر وسط جمع‌آوری بسته شد و اجرا همان‌جا متوقف شد. "
                "گزارش‌هایی که تا آن لحظه کامل شده‌اند ذخیره شده‌اند؛ دوباره "
                "«جمع‌آوری» را بزنید تا ادامه دهد (گزارش‌های تکراری دوباره "
                "گرفته نمی‌شوند).")
    return text


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    channel = None
    if __import__("os").environ.get("CODAL_JOB_DIR"):
        from codal_challenge import current_channel
        channel = current_channel()
        expected = __import__("os").environ.get("CODAL_JOB_ID")
        job_id_mismatch = bool(args.job_id and expected and args.job_id != expected)
    else:
        job_id_mismatch = False

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
        if channel:
            channel.update(state="running_http", stage="discovery", message="در حال بررسی گزارش‌های کدال")
        try:
            if job_id_mismatch:
                raise ValueError("job id does not match the server-created job directory")
            summary = run_sync(args)
            exit_code = 0 if summary.get("success") else 1
        except Exception as exc:
            logger.exception("Sync failed")
            summary = {"success": False, "error": _friendly_sync_error(exc)}
            exit_code = 1
    finally:
        sys.stdout = real_stdout
        if channel:
            try:
                from codal_transport import close_current
                close_current()
            except Exception:
                logger.exception("Could not close Codal browser context")

    real_stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
    real_stdout.write("\n")
    real_stdout.flush()
    if channel:
        channel.write_json("result.json", summary)
        state = "completed" if summary.get("success") else "completed_with_errors"
        if channel.cancelled:
            state = "cancelled"
        elif channel.root.joinpath("status.json").exists():
            try:
                import json as _json
                old = _json.loads(channel.root.joinpath("status.json").read_text(encoding="utf-8"))
                if old.get("state") in ("expired", "failed"):
                    state = old["state"]
            except Exception:
                pass
        channel.update(state=state, stage="finished", message="جمع‌آوری کدال تمام شد",
                       summary=summary)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
