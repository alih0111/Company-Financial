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
from datetime import datetime, timedelta

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
        default=5,
        help="سقف ایمنی تعداد صفحه از هر feed (پیش‌فرض 5)؛ فقط safety cap است، نه هدف.",
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


def run_sync_canonical_only(args: argparse.Namespace) -> dict:
    """Canonical-only Codal sync: fetch -> raw body -> canonical report lineage.

    No SQL Server connection is created. Legacy registry/watermark state is skipped.
    TracingNo -> source_report_id semantics are unchanged (canonical_hook uses it).
    """
    import canonical_hook  # lazy

    letter_types = [
        lt for lt in resolve_letter_types(args) if route_for_letter_type(lt) != "unknown"
    ]
    if not letter_types:
        raise ValueError("No supported --letter-type given (only 6 and 58 are supported)")

    totals = {"scanned": 0, "ingested": 0, "quarantined": 0, "errors": 0, "pages": 0,
              "max_pages": args.max_pages, "dry_run": args.dry_run,
              "authority": "CANONICAL", "mode": "canonical_only_offline"}
    for lt in letter_types:
        page_number = 1
        while True:
            if args.max_pages and totals["pages"] >= args.max_pages:
                break
            page = codal_feed.discover_reports(lt, page_number,
                                              from_date=args.from_date, to_date=args.to_date)
            totals["pages"] += 1
            if not page.reports:
                break
            for report in page.reports:
                totals["scanned"] += 1
                if args.dry_run:
                    continue
                res = canonical_hook.ingest_codal_authoritative(report.raw, fetch_body=True)
                status = res.get("status")
                if status == "written":
                    totals["ingested"] += 1
                elif status == "quarantined":
                    totals["quarantined"] += 1
                elif status in ("canonical_error", "no_tracing_no"):
                    totals["errors"] += 1
            if page.is_last_page:
                break
            page_number += 1
    logger.info("canonical-only codal sync: %s", totals)
    return {"success": totals["errors"] == 0, "dry_run": args.dry_run, "canonical_only": True,
            "total": totals}


def run_sync(args: argparse.Namespace) -> dict:
    # Canonical-only offline: never open SQL Server for the Codal path.
    try:
        import canonical_hook as _hook
        if _hook.canonical_only_offline() and _hook.codal_canonical_authority():
            return run_sync_canonical_only(args)
    except Exception:  # noqa: BLE001 - fall through to legacy behaviour
        pass

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
