"""Capture incremental official Codal financial/monthly feed evidence.

This collector is append-only and read-only: it retains raw feed pages, identifies
the 254 frozen symbols, and does not claim parsed facts or ranking admission.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import re
import sys
import time
from datetime import timezone, timedelta
import urllib.parse
import urllib.request
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "go-app/py"))
sys.path.insert(0, str(ROOT))
import codal_feed
from ranking_research.future_eval_v12_30.http_retry import open_readonly, ReadOnlyRateLimitedError

UNIVERSE = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv"
OWNER = ROOT / "ranking_research/output/owner_current_inputs_20261014T215850582899Z/input_reports.json"
SALES = ROOT / "fundamental_event_research/monthly_sales_events_universe_v1_1.parquet"
OUT = ROOT / "ranking_research/output/paper_cycle/codal"
TEHRAN = timezone(timedelta(hours=3, minutes=30))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_stamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp.replace(tzinfo=dt.timezone.utc) if stamp.tzinfo is None else stamp.astimezone(dt.timezone.utc)


def invalid_response_retry_at(value: str | None, now: dt.datetime | None = None) -> str:
    """Respect an HTTP Retry-After header; otherwise cool down invalid challenge pages for one day."""
    current = now or dt.datetime.now(dt.timezone.utc)
    if value:
        try:
            return (current + dt.timedelta(seconds=max(0.0, float(value)))).isoformat()
        except (TypeError, ValueError):
            try:
                from email.utils import parsedate_to_datetime
                target = parsedate_to_datetime(value)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=dt.timezone.utc)
                return max(current, target.astimezone(dt.timezone.utc)).isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
    return (current + dt.timedelta(hours=24)).isoformat()


def challenge_cooldown_until(items: dict, now: dt.datetime | None = None) -> str | None:
    current = now or dt.datetime.now(dt.timezone.utc)
    candidates = []
    for item in items.values():
        evidence = item.get("invalid_response_evidence") or {}
        if evidence.get("kind") not in ("codal_captcha_page", "codal_rate_limit_page"):
            continue
        received = parse_stamp(evidence.get("retrieved_at_utc"))
        if received and received <= current:
            candidates.append(received + dt.timedelta(hours=24))
    future = [value for value in candidates if value > current]
    return max(future).isoformat() if future else None


def deferred_identity_coverage(previously_checked: int, universe: int = 254) -> dict:
    """Do not report old checkpoint checks as work performed in this deferred run."""
    return {"companies_checked": 0, "companies_new_reports": 0, "companies_no_new_reports": 0,
            "companies_failed": 0, "companies_unchecked": universe,
            "companies_previously_checked": min(universe, max(0, previously_checked)),
            "frozen_identity_coverage": 0, "pagination_complete": False,
            "previous_checkpoint_complete": previously_checked >= universe}


def merge_cached_report_items(*sources: dict) -> dict:
    """Merge local manifests/checkpoints while retaining the richest body evidence."""
    merged: dict = {}
    for source in sources:
        for tracing_no, candidate in (source or {}).items():
            previous = merged.get(str(tracing_no), {})
            keep = dict(candidate)
            for field in ("body_evidence", "financial_pages", "financial_pages_complete",
                          "invalid_response_evidence", "body_error"):
                if not keep.get(field) and previous.get(field):
                    keep[field] = previous[field]
            if previous.get("financial_pages_complete") and not keep.get("financial_pages_complete"):
                keep["financial_pages_complete"] = previous["financial_pages_complete"]
            merged[str(tracing_no)] = keep
    return merged


def read_archived_body(item: dict) -> bytes:
    evidence = item.get("body_evidence") or {}
    body = gzip.decompress((ROOT / evidence["path"]).read_bytes())
    if evidence.get("sha256") and digest(body) != evidence["sha256"]:
        raise ValueError("archived_report_body_sha256_mismatch")
    if http_200_error_kind(body):
        raise ValueError("archived_report_body_is_invalid_response")
    return body


def normalize_archived_report_items(items: dict) -> dict:
    """Quarantine legacy captcha/error pages and untrustworthy local body files."""
    for item in items.values():
        evidence = item.get("body_evidence")
        if not evidence:
            continue
        try:
            read_archived_body(item)
        except (OSError, EOFError, KeyError, ValueError) as exc:
            try:
                raw = gzip.decompress((ROOT / evidence["path"]).read_bytes())
                invalid_kind = http_200_error_kind(raw)
            except (OSError, EOFError, KeyError):
                invalid_kind = None
            item.pop("body_evidence", None)
            if invalid_kind:
                item["invalid_response_evidence"] = {**evidence, "kind": invalid_kind}
            else:
                item["body_error"] = f"archived_body_unusable: {type(exc).__name__}: {str(exc)[:120]}"
    return items


def load_archived_report_items(key: str) -> dict:
    """Read local caches, checkpoints and prior run manifests before any request."""
    sources = []
    cache_path = OUT / "archive" / f"{key}-report-cache.json"
    if cache_path.exists():
        try:
            sources.append(json.loads(cache_path.read_text(encoding="utf-8")).get("report_items", {}))
        except (OSError, ValueError, TypeError):
            pass
    resume_path = OUT / f"{key}-resume.json"
    if resume_path.exists():
        try:
            sources.append(json.loads(resume_path.read_text(encoding="utf-8")).get("report_items", {}))
        except (OSError, ValueError, TypeError):
            pass
    for manifest_path in OUT.glob("paper-cycle-*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            sources.append({str(x.get("tracing_no")): x for x in
                            manifest.get("feeds", {}).get(key, {}).get("report_ids", [])
                            if x.get("tracing_no")})
        except (OSError, ValueError, TypeError):
            continue
    return normalize_archived_report_items(merge_cached_report_items(*sources))


def discover_with_evidence(letter_type: int, page_number: int, *, symbol: str, from_date: str):
    url = codal_feed._build_query(letter_type, page_number, from_date=from_date, symbol=symbol)
    request = urllib.request.Request(url, headers=codal_feed.DEFAULT_HEADERS)
    response, attempts, wait = open_readonly(request, timeout=45)
    with response:
        raw = response.read(8 * 1024 * 1024 + 1)
        http_status, http_date = response.status, response.headers.get("Date")
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("codal_feed_page_over_8mb")
    if http_status != 200:
        raise ValueError(f"codal_feed_http_{http_status}")
    payload = json.loads(raw.decode("utf-8"))
    reports = [codal_feed.parse_letter(letter, letter_type) for letter in (payload.get("Letters") or [])]
    from codal_feed import FeedPage
    page = FeedPage(letter_type=letter_type, page_number=page_number,
                    total=int(payload.get("Total") or 0), reports=reports)
    return page, raw, {"url": url, "http_status": http_status, "http_date": http_date,
                       "request_attempts": attempts, "retry_wait_seconds": wait}


def watermarks_by_identity(letter_type: int) -> dict[str, str]:
    # Extend the frozen owner archive's watermark with reports already captured
    # by this collector.  A completed run must not make the next run rediscover
    # and redownload the same reports from the original, unchanged archive.
    key = "financial" if letter_type == 6 else "sales"
    cached = load_archived_report_items(key)
    result: dict[str, str] = {}
    if letter_type == 6 and OWNER.exists():
        rows = json.loads(OWNER.read_text(encoding="utf-8"))
        for row in rows:
            value = row.get("published_at")
            if value:
                stamp = parse_stamp(str(value))
                cid = str(row.get("company_id"))
                if stamp and (cid not in result or stamp > parse_stamp(result[cid])):
                    result[cid] = stamp.isoformat()
    elif letter_type == 58 and SALES.exists():
        import pandas as pd
        df = pd.read_parquet(SALES, columns=["company_id", "published_at"])
        df["published_at"] = pd.to_datetime(df.published_at, errors="coerce", utc=True)
        grouped = df.dropna(subset=["published_at"]).groupby(df.company_id.astype(str)).published_at.max()
        result.update({str(cid): ts.isoformat() for cid, ts in grouped.items()})
    for item in cached.values():
        cid, published = str(item.get("company_id") or ""), item.get("published_at")
        stamp = parse_stamp(published) if published else None
        if cid and stamp and (cid not in result or stamp > parse_stamp(result[cid])):
            result[cid] = stamp.isoformat()
    return result


def jalali_day(stamp: dt.datetime) -> str:
    import jdatetime
    local = stamp.astimezone(TEHRAN).date()
    jdate = jdatetime.date.fromgregorian(date=local)
    return jdate.strftime("%Y/%m/%d")


def window_start(watermark: str | None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    lower = parse_stamp(watermark) - dt.timedelta(days=7) if watermark else now - dt.timedelta(days=365)
    return jalali_day(lower)


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def http_200_error_kind(body: bytes) -> str | None:
    text = body.decode("utf-8", "replace")
    lowered = text.lower()
    if "خطای سیستمی | کدال" in text or "خطاى سيستمى | كدال" in text:
        return "codal_system_error_page"
    if ("captchaimage" in lowered or "captchacode" in lowered or "security code" in lowered
            or "کد امنیتی" in text or "کد تصویر" in text
            or re.search(r"(?:id|name)\s*=\s*['\"][^'\"]*captcha", lowered)):
        return "codal_captcha_page"
    if "429 too many requests" in lowered or "درخواست‌های بیش از حد" in text or "درخواست هاي بيش از حد" in text:
        return "codal_rate_limit_page"
    return None


def record_report_body_evidence(item: dict, body: bytes, *, path: str, content_type: str | None,
                               http_date: str | None, retrieved_at_utc: str,
                               request_attempts: int, retry_wait_seconds: int) -> bool:
    """Keep invalid HTTP-200 pages auditable without treating them as report bodies."""
    invalid_kind = http_200_error_kind(body)
    evidence = {"path": path, "sha256": digest(body), "bytes": len(body),
                "content_type": content_type, "http_date": http_date,
                "retrieved_at_utc": retrieved_at_utc,
                "request_attempts": request_attempts,
                "retry_wait_seconds": retry_wait_seconds}
    if invalid_kind:
        item.pop("body_evidence", None)
        item["invalid_response_evidence"] = {**evidence, "kind": invalid_kind}
        return False
    item.pop("invalid_response_evidence", None)
    item["body_evidence"] = evidence
    return True


def acquire_financial_sheets(item: dict, body: bytes, raw_dir: Path) -> None:
    """Fetch the report's explicitly listed parent statement sheets, once each."""
    from bs4 import BeautifulSoup
    import dynamic_financial as D
    from dynamic_financial import source_url
    source = urllib.parse.urlparse(item.get("url", ""))
    if source.scheme != "https" or source.hostname not in ("codal.ir", "www.codal.ir"):
        raise ValueError("untrusted_financial_report_url")
    html = body.decode("utf-8", "strict")
    rec = {"tracing_no": str(item["tracing_no"]), "published_at": item["published_at"],
           "period_end": __import__("ranking_research.future_eval_v12_30.prepare_codal_inputs", fromlist=["jalali_gregorian"]).jalali_gregorian(item["title"]).isoformat(),
           "parser_version": D.VERSION}
    shown_codes = set()
    try:
        parsed = D.parsed_page(html, rec)
        shown_codes = {str(sheet.get("code")) for sheet in D.payload(html).get("sheets", [])}
    except ValueError as exc:
        if str(exc) != "no_dynamic_datasource":
            raise
        parsed = {"statements": {}}
    soup = BeautifulSoup(html, "html.parser")
    selector = soup.find("select", id="ctl00_ddlTable") or soup.find("select", id="ddlTable")
    related = list(item.get("financial_pages", []))
    if selector:
        for option in selector.find_all("option"):
            kind = D.H.P._caption_kind(" ".join(option.find_all(string=True, recursive=False)))
            code = option.get("value")
            if not kind or kind[1] or not code or not str(code).isdigit() or str(code) in shown_codes:
                continue
            query = urllib.parse.parse_qs(source.query, keep_blank_values=True)
            if query.get("sheetId") == [str(code)]:
                continue
            query["sheetId"] = [str(code)]
            url = urllib.parse.urlunsplit((source.scheme, source.netloc, source.path,
                                           urllib.parse.urlencode(query, doseq=True), ""))
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,*/*", "Referer": item["url"]})
            response, attempts, wait = open_readonly(request, timeout=35)
            with response:
                page_body = response.read(8 * 1024 * 1024 + 1)
                status, http_date, content_type = response.status, response.headers.get("Date"), response.headers.get("Content-Type")
            if len(page_body) > 8 * 1024 * 1024 or status != 200:
                raise ValueError("financial_sheet_response_invalid")
            invalid_kind = http_200_error_kind(page_body)
            if invalid_kind:
                raise ValueError(f"{invalid_kind}_http_200")
            # Validate each page against the report's own identity/publication/period now.
            try:
                D.parsed_page(page_body.decode("utf-8", "strict"), rec)
            except ValueError as exc:
                if str(exc) != "duplicate_dynamic_cell":
                    raise
            sha256 = digest(page_body)
            path = raw_dir / f"letter-{item['letter_type']}-tracing-{item['tracing_no']}-sheet-{code}.html.gz"
            path.write_bytes(gzip.compress(page_body, compresslevel=6))
            related.append({"sheet_id": str(code), "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256, "bytes": len(page_body), "content_type": content_type,
                "http_date": http_date, "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "request_attempts": attempts, "retry_wait_seconds": wait, "url": url})
            time.sleep(0.15)
    item["financial_pages"] = related
    item["financial_pages_complete"] = True


def main() -> int:
    import pandas as pd
    if len(sys.argv) != 2:
        raise SystemExit("usage: acquire_codal_incremental.py <run-id>")
    run_id = sys.argv[1]
    symbols_df = pd.read_csv(UNIVERSE, dtype=str)
    if len(symbols_df) != 254 or symbols_df.company_id.nunique() != 254 or symbols_df.symbol.nunique() != 254:
        raise SystemExit("FROZEN_UNIVERSE_NOT_254_UNIQUE")
    frozen = dict(zip(symbols_df.symbol, symbols_df.company_id))
    out = OUT / run_id
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 2, "run_id": run_id, "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "source": "Codal search feed LetterType 6/58", "read_only": True,
              "frozen_universe_count": 254, "feeds": {}}
    watermarks = {6: watermarks_by_identity(6), 58: watermarks_by_identity(58)}
    for letter_type, key in ((6, "financial"), (58, "sales")):
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        feed = {"letter_type": letter_type, "state": "started", "last_successful_retrieval_utc": None,
                "latest_published_at": None, "pages": 0, "reports_seen": 0, "frozen_symbol_reports": 0,
                "companies_checked": 0, "companies_new_reports": 0, "companies_no_new_reports": 0,
                "companies_failed": 0, "companies_unchecked": 254, "companies_previously_checked": 0,
                "frozen_identity_coverage": 0,
                "new_reports": 0, "report_bodies_received": 0, "report_body_errors": [],
                "report_ids": [], "error": None, "raw_pages": [], "search_window_policy": "per-identity archive watermark minus 7-day overlap; 365 days for identities without local watermark; all reported pages fetched",
                "identities_checked_path": None, "coverage_basis": "successful_exact-symbol_query_with_consistent_page_total"}
        resume_path = OUT / f"{key}-resume.json"
        cache_path = OUT / "archive" / f"{key}-report-cache.json"
        cached_items = load_archived_report_items(key)
        resume = json.loads(resume_path.read_text(encoding="utf-8")) if resume_path.exists() else {}
        if resume.get("state") == "complete":
            resume = {}
        audits = list(resume.get("audits", []))
        checkpoint_checked_symbols = {str(x.get("symbol")) for x in audits
            if str(x.get("status", "")).startswith("checked_")}
        report_items = merge_cached_report_items(cached_items, resume.get("report_items", {}))
        # Persist the discovered archive locally before continuing. This is a
        # file-only step and ensures a later run can retry missing bodies without
        # losing the successful metadata search or its page checkpoint.
        save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
            "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
        feed["archive_reuse"] = {"cached_report_count": len(cached_items),
            "valid_bodies_reused": sum(bool(x.get("body_evidence")) for x in cached_items.values()),
            "incomplete_or_invalid_cached_bodies": sum(not x.get("body_evidence") for x in cached_items.values()),
            "quarantined_invalid_responses": sum(bool(x.get("invalid_response_evidence")) for x in cached_items.values()),
            "missing_cached_bodies": sum(not x.get("body_evidence") and not x.get("invalid_response_evidence") for x in cached_items.values()),
            "cache_manifest": str(cache_path.relative_to(ROOT)).replace("\\", "/")}
        feed["raw_pages"] = list(resume.get("raw_pages", []))
        feed["pages"] = int(resume.get("pages", 0))
        feed["pages_fetched_this_run"] = 0
        feed["reports_seen"] = sum(int(x.get("reports_in_window", 0)) for x in audits)
        feed["report_bodies_received"] = 0
        run_started = dt.datetime.now(dt.timezone.utc)
        feed["frozen_symbol_reports"] = feed["reports_seen"]
        cursor = resume.get("cursor")
        newest = resume.get("latest_published_at")
        retry_at = resume.get("next_attempt_at_utc")
        cooldown_until = challenge_cooldown_until(report_items)
        if cooldown_until and (not retry_at or not parse_stamp(retry_at) or parse_stamp(cooldown_until) > parse_stamp(retry_at)):
            retry_at = cooldown_until
        if retry_at and parse_stamp(retry_at) and parse_stamp(retry_at) > dt.datetime.now(dt.timezone.utc):
            audit_by_symbol = {str(x.get("symbol")): x for x in audits}
            if cursor and cursor.get("symbol"):
                audit_by_symbol[str(cursor["symbol"])] = cursor.get("audit", {})
            full_audit = []
            for row in symbols_df.itertuples(index=False):
                sym, cid = str(row.symbol), str(row.company_id)
                prior = audit_by_symbol.get(sym, {})
                full_audit.append({"symbol": sym, "company_id": cid,
                    "status": "deferred_until_retry", "prior_checkpoint_status": prior.get("status"),
                    "watermark_utc": watermarks[letter_type].get(cid),
                    "from_date_jalali": prior.get("from_date_jalali") or window_start(watermarks[letter_type].get(cid)),
                    "to_date_jalali": jalali_day(dt.datetime.now(dt.timezone.utc)), "pages_fetched": 0,
                    "prior_checkpoint_pages_fetched": prior.get("pages_fetched", 0),
                    "expected_pages": prior.get("expected_pages"), "reports_in_window": prior.get("reports_in_window", 0),
                    "new_reports": 0, "report_ids": prior.get("report_ids", []),
                    "error": "feed_deferred_before_this_run; prior checkpoint retained"})
            audit_path = out / f"identity-checks-{key}.json"
            save_json(audit_path, {"letter_type": letter_type, "search_window_policy": feed["search_window_policy"], "identities": full_audit})
            deferred_coverage = deferred_identity_coverage(len(checkpoint_checked_symbols))
            feed.update({"state": "deferred_until_retry", "next_attempt_at_utc": retry_at,
                "error": "The previous source response requires a later retry; this feed was not contacted.",
                "rate_limit": resume.get("rate_limit"),
                "deferred_reason": resume.get("deferred_reason") or ("recent_invalid_response_cooldown" if cooldown_until else None),
                "report_ids": list(report_items.values()), "new_reports": 0,
                "archived_report_items": len(report_items),
                **deferred_coverage, "pages_fetched_this_run": 0,
                "latest_published_at": newest,
                "last_successful_retrieval_utc": max((x.get("retrieved_at_utc") for x in feed["raw_pages"] if x.get("retrieved_at_utc")), default=None),
                "pagination_complete": False,
                "identities_checked_path": str(audit_path.relative_to(ROOT)).replace("\\", "/")})
            save_json(resume_path, {"state": "deferred_invalid_response" if cooldown_until else "rate_limited",
                "audits": audits, "report_items": report_items, "raw_pages": feed["raw_pages"],
                "pages": feed["pages"], "cursor": cursor, "latest_published_at": newest,
                "next_attempt_at_utc": retry_at,
                "deferred_reason": feed.get("deferred_reason"), "rate_limit": feed.get("rate_limit")})
            save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
            report["feeds"][key] = feed
            continue
        completed_symbols = {str(x.get("symbol")) for x in audits if str(x.get("status", "")).startswith("checked_")}
        page_error = None
        stop_feed = False
        for identity_index, row in enumerate(symbols_df.itertuples(index=False), 1):
            symbol, company_id = str(row.symbol), str(row.company_id)
            if symbol in completed_symbols:
                continue
            watermark = watermarks[letter_type].get(company_id)
            from_date = window_start(watermark)
            if cursor and cursor.get("symbol") == symbol:
                audits = [x for x in audits if str(x.get("symbol")) != symbol]
                audit = cursor["audit"]
                expected_pages = cursor.get("expected_pages")
                start_page = int(cursor.get("next_page", 1))
                first_total = cursor.get("first_total")
            else:
                audit = {"symbol": symbol, "company_id": company_id, "status": "failed", "watermark_utc": watermark,
                         "from_date_jalali": from_date, "to_date_jalali": jalali_day(dt.datetime.now(dt.timezone.utc)),
                         "pages_fetched": 0, "expected_pages": None, "reports_in_window": 0,
                         "new_reports": 0, "report_ids": [], "error": None}
                expected_pages = None
                start_page = 1
                first_total = None
            next_confirm_page = start_page
            try:
                if expected_pages is None:
                    first, raw_feed, http = discover_with_evidence(letter_type, 1, symbol=symbol, from_date=from_date)
                    expected_pages = first.total_pages or (1 if not first.reports else None)
                    first_total = first.total
                    start_page = 1
                    first_fetched = (first, raw_feed, http)
                else:
                    first_fetched = None
                if expected_pages is None:
                    raise ValueError("codal_total_pages_missing")
                page_numbers = list(range(start_page, expected_pages + 1))
                for page_no in page_numbers:
                    page_started = dt.datetime.now(dt.timezone.utc).isoformat()
                    if page_no == 1 and first_fetched:
                        page, raw, page_http = first_fetched
                    else:
                        page, raw, page_http = discover_with_evidence(letter_type, page_no, symbol=symbol, from_date=from_date)
                    if page.total != first_total:
                        raise ValueError("codal_pagination_total_changed")
                    raw_path = raw_dir / f"letter-{letter_type}-{symbol}-{page_no}.json.gz"
                    raw_path.write_bytes(gzip.compress(raw, compresslevel=6))
                    page_meta = {"path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
                        "sha256": digest(raw), "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "report_count": len(page.reports), **page_http}
                    feed["raw_pages"].append(page_meta)
                    feed["pages"] += 1
                    feed["pages_fetched_this_run"] += 1
                    for report_item in page.reports:
                        if report_item.ticker != symbol:
                            continue
                        feed["reports_seen"] += 1
                        audit["reports_in_window"] += 1
                        pub_utc = report_item.published_at.replace(tzinfo=TEHRAN).astimezone(dt.timezone.utc) if report_item.published_at else None
                        pub = pub_utc.isoformat() if pub_utc else None
                        if pub:
                            newest = max(newest, pub) if newest else pub
                        record = {"tracing_no": report_item.report_id, "symbol": symbol,
                            "company_id": company_id, "title": report_item.title, "published_at": pub,
                            "published_at_raw_jalali": report_item.published_at_raw, "url": report_item.report_url,
                            "version_metadata": {str(k): v for k, v in (report_item.raw or {}).items()
                                if any(token in str(k).lower() for token in ("version", "correction", "previous", "reference", "supersed"))},
                            "letter_type": letter_type, "discovery_retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
                        previous_item = report_items.get(report_item.report_id, {})
                        if pub and (not watermark or parse_stamp(pub) > parse_stamp(watermark)):
                            report_items[report_item.report_id] = record
                            audit["new_reports"] += 1
                            if report_item.report_id not in audit["report_ids"]:
                                audit["report_ids"].append(report_item.report_id)
                        elif previous_item and previous_item.get("published_at") == pub:
                            # Preserve locally stored valid bodies and their receipt
                            # times when an overlap page returns the same metadata.
                            report_items[report_item.report_id] = {**record, **{
                                k: v for k, v in previous_item.items()
                                if k in ("body_evidence", "invalid_response_evidence", "financial_pages", "financial_pages_complete")}}
                    cursor = {"symbol": symbol, "company_id": company_id, "from_date_jalali": from_date,
                        "expected_pages": expected_pages, "first_total": first_total, "next_page": page_no + 1,
                        "last_confirmed_page": page_no, "audit": audit}
                    next_confirm_page = page_no + 1
                    save_json(resume_path, {"state": "in_progress", "audits": audits, "report_items": report_items,
                        "raw_pages": feed["raw_pages"], "pages": feed["pages"], "cursor": cursor,
                        "latest_published_at": newest})
                    save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                        "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
                    time.sleep(0.15)
                audit.update({"pages_fetched": expected_pages, "expected_pages": expected_pages,
                              "total_consistent": True,
                              "status": "checked_with_new_reports" if audit["new_reports"] else "checked_no_new_reports"})
                feed["frozen_symbol_reports"] += audit["reports_in_window"]
                audits.append(audit)
                cursor = None
                completed_symbols.add(symbol)
                save_json(resume_path, {"state": "in_progress", "audits": audits, "report_items": report_items,
                    "raw_pages": feed["raw_pages"], "pages": feed["pages"], "cursor": None,
                    "latest_published_at": newest})
                save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                    "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
            except ReadOnlyRateLimitedError as exc:
                audit["error"] = str(exc)
                audit["status"] = "failed_rate_limited"
                page_error = audit["error"]
                feed["rate_limit"] = {"attempts": exc.attempts, "retry_after_seconds": exc.retry_after_seconds,
                    "next_attempt_at_utc": exc.retry_at_utc, "source_stopped": True}
                stop_feed = True
                cursor = {"symbol": symbol, "company_id": company_id, "from_date_jalali": from_date,
                    "expected_pages": expected_pages, "first_total": first_total,
                    "next_page": next_confirm_page,
                    "last_confirmed_page": next_confirm_page - 1, "audit": audit}
                save_json(resume_path, {"state": "rate_limited", "audits": audits, "report_items": report_items,
                    "raw_pages": feed["raw_pages"], "pages": feed["pages"], "cursor": cursor,
                    "latest_published_at": newest, "next_attempt_at_utc": exc.retry_at_utc,
                    "rate_limit": feed["rate_limit"]})
            except Exception as exc:
                audit["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                page_error = page_error or audit["error"]
                audits.append(audit)
            if stop_feed:
                break
            if identity_index % 10 == 0:
                time.sleep(0.5)
        feed["report_ids"] = list(report_items.values())
        run_audits = [x for x in audits if str(x.get("symbol")) not in checkpoint_checked_symbols]
        feed["new_reports"] = sum(int(x.get("new_reports", 0)) for x in run_audits)
        feed["archived_report_items"] = len(report_items)
        feed["companies_checked"] = sum(x["status"].startswith("checked_") for x in run_audits)
        feed["companies_new_reports"] = sum(x["status"] == "checked_with_new_reports" for x in run_audits)
        feed["companies_no_new_reports"] = sum(x["status"] == "checked_no_new_reports" for x in run_audits)
        feed["companies_failed"] = sum(x["status"] in ("failed", "failed_rate_limited") for x in run_audits)
        feed["companies_previously_checked"] = len(checkpoint_checked_symbols)
        feed["companies_unchecked"] = 254 - feed["companies_checked"] - feed["companies_failed"]
        audit_path = out / f"identity-checks-{key}.json"
        audit_by_symbol = {str(x.get("symbol")): x for x in audits}
        full_audit = [audit_by_symbol.get(str(row.symbol), {"symbol": str(row.symbol), "company_id": str(row.company_id),
            "status": "not_checked_after_source_stop" if stop_feed else "not_checked",
            "watermark_utc": watermarks[letter_type].get(str(row.company_id)),
            "from_date_jalali": window_start(watermarks[letter_type].get(str(row.company_id))),
            "to_date_jalali": jalali_day(dt.datetime.now(dt.timezone.utc)), "pages_fetched": 0,
            "expected_pages": None, "reports_in_window": 0, "new_reports": 0, "report_ids": [],
            "error": "source_stopped_after_rate_limit" if stop_feed else "not_checked"})
            for row in symbols_df.itertuples(index=False)]
        audits = full_audit
        audit_path.write_text(json.dumps({"letter_type": letter_type, "search_window_policy": feed["search_window_policy"],
            "identities": full_audit}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        feed["identities_checked_path"] = str(audit_path.relative_to(ROOT)).replace("\\", "/")
        fresh_reports = list(report_items.values())
        feed["archive_reuse"]["reprocessed_from_local_body"] = 0
        feed["archive_reuse"]["retried_after_missing_or_invalid_body"] = 0
        for idx, item in enumerate(fresh_reports, 1):
            if item.get("body_evidence", {}).get("http_200_error_page"):
                legacy_error = item.pop("body_evidence")
                item["invalid_response_evidence"] = {**legacy_error,
                    "kind": legacy_error.get("http_200_error_kind", "legacy_unclassified_invalid_http_200")}
            if item.get("body_evidence") and (key != "financial" or item.get("financial_pages_complete")):
                continue
            if stop_feed:
                break
            url = urllib.parse.urlparse(item.get("url", ""))
            if url.scheme != "https" or url.hostname not in ("codal.ir", "www.codal.ir", "excel.codal.ir"):
                feed["report_body_errors"].append({"tracing_no": item["tracing_no"], "error": "untrusted_report_url"})
                continue
            try:
                body_was_received = bool(item.get("body_evidence"))
                if not body_was_received and (item.get("invalid_response_evidence") or item.get("body_error")
                      or (parse_stamp(item.get("discovery_retrieved_at_utc"))
                          and parse_stamp(item["discovery_retrieved_at_utc"]) < run_started)):
                    feed["archive_reuse"]["retried_after_missing_or_invalid_body"] += 1
                request = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/pdf,*/*", "Referer": "https://www.codal.ir/ReportList.aspx"})
                body = None
                if item.get("body_evidence"):
                    try:
                        body = read_archived_body(item)
                        feed["archive_reuse"]["reprocessed_from_local_body"] += 1
                    except (OSError, EOFError, KeyError, ValueError) as exc:
                        item.pop("body_evidence", None)
                        item["body_error"] = f"archived_body_unusable: {type(exc).__name__}: {str(exc)[:120]}"
                        feed["archive_reuse"]["retried_after_missing_or_invalid_body"] += 1
                if body is None:
                    response, attempts, wait = open_readonly(request, timeout=35)
                    with response:
                        body = response.read(8 * 1024 * 1024 + 1)
                        http_status, http_date, content_type = response.status, response.headers.get("Date"), response.headers.get("Content-Type")
                        response_retry_after = response.headers.get("Retry-After")
                    if len(body) > 8 * 1024 * 1024:
                        raise ValueError("report_body_over_8mb")
                    if http_status != 200:
                        raise ValueError(f"http_{http_status}")
                    invalid_kind = http_200_error_kind(body)
                    if invalid_kind:
                        invalid_path = raw_dir / f"invalid-{letter_type}-tracing-{item['tracing_no']}.body.gz"
                        invalid_path.write_bytes(gzip.compress(body, compresslevel=6))
                        record_report_body_evidence(item, body,
                            path=str(invalid_path.relative_to(ROOT)).replace("\\", "/"),
                            content_type=content_type, http_date=http_date,
                            retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                            request_attempts=attempts, retry_wait_seconds=wait)
                        feed["report_body_errors"].append({"tracing_no": item["tracing_no"], "error": f"{invalid_kind}_http_200"})
                        save_json(resume_path, {"state": "in_progress", "audits": audits, "report_items": report_items,
                            "raw_pages": feed["raw_pages"], "pages": feed["pages"], "cursor": None,
                            "latest_published_at": newest})
                        save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                            "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
                        if invalid_kind in ("codal_captcha_page", "codal_rate_limit_page"):
                            next_attempt = invalid_response_retry_at(response_retry_after)
                            feed["deferred_reason"] = invalid_kind
                            feed["rate_limit"] = {"attempts": attempts, "retry_after_seconds": wait,
                                "retry_after_header": response_retry_after, "next_attempt_at_utc": next_attempt,
                                "source_stopped": True, "stage": "report_body", "http_status": http_status}
                            stop_feed = True
                            save_json(resume_path, {"state": "deferred_invalid_response", "audits": audits,
                                "report_items": report_items, "raw_pages": feed["raw_pages"], "pages": feed["pages"],
                                "cursor": {"stage": "report_body", "tracing_no": item["tracing_no"]},
                                "latest_published_at": newest, "next_attempt_at_utc": next_attempt,
                                "deferred_reason": invalid_kind, "rate_limit": feed["rate_limit"]})
                            break
                        continue
                    body_path = raw_dir / f"letter-{letter_type}-tracing-{item['tracing_no']}.body.gz"
                    body_path.write_bytes(gzip.compress(body, compresslevel=6))
                    record_report_body_evidence(item, body,
                        path=str(body_path.relative_to(ROOT)).replace("\\", "/"),
                        content_type=content_type, http_date=http_date,
                        retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                        request_attempts=attempts, retry_wait_seconds=wait)
                if key == "financial":
                    acquire_financial_sheets(item, body, raw_dir)
                if not body_was_received and item.get("body_evidence") and not item["body_evidence"].get("http_200_error_page"):
                    feed["report_bodies_received"] += 1
                save_json(resume_path, {"state": "in_progress", "audits": audits, "report_items": report_items,
                    "raw_pages": feed["raw_pages"], "pages": feed["pages"], "cursor": None,
                    "latest_published_at": newest})
                save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                    "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
            except ReadOnlyRateLimitedError as exc:
                feed["report_body_errors"].append({"tracing_no": item["tracing_no"], "error": str(exc)})
                item["body_error"] = str(exc)
                feed["rate_limit"] = {"attempts": exc.attempts, "retry_after_seconds": exc.retry_after_seconds,
                    "next_attempt_at_utc": exc.retry_at_utc, "source_stopped": True, "stage": "report_body"}
                stop_feed = True
                save_json(resume_path, {"state": "rate_limited", "audits": audits, "report_items": report_items,
                    "raw_pages": feed["raw_pages"], "pages": feed["pages"],
                    "cursor": {"stage": "report_body", "tracing_no": item["tracing_no"]},
                    "latest_published_at": newest, "next_attempt_at_utc": exc.retry_at_utc,
                    "rate_limit": feed["rate_limit"]})
                save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                    "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
            except Exception as exc:
                feed["report_body_errors"].append({"tracing_no": item["tracing_no"], "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                item["body_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
                    "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
            if idx % 5 == 0:
                time.sleep(1.0)
        feed["reports_seen"] = sum(int(x.get("reports_in_window", 0)) for x in audits)
        feed["frozen_symbol_reports"] = feed["reports_seen"]
        total_checked = feed["companies_checked"] + feed["companies_previously_checked"]
        feed.update({"state": "received" if total_checked == 254 and not feed["companies_unchecked"] and not feed["report_body_errors"] else "partial",
                     "last_successful_retrieval_utc": max((x.get("retrieved_at_utc") for x in feed["raw_pages"] if x.get("retrieved_at_utc")), default=None),
                     "latest_published_at": newest, "frozen_identity_coverage": total_checked,
                     "pagination_complete": total_checked == 254 and not feed["companies_unchecked"],
                     "previous_checkpoint_complete": len(checkpoint_checked_symbols) == 254,
                     "error": page_error if feed["companies_unchecked"] else None,
                     "next_attempt_at_utc": (feed.get("rate_limit") or {}).get("next_attempt_at_utc")})
        feed["archive_reuse"].update({
            "fresh_report_metadata": feed["new_reports"],
            "fresh_report_bodies_received_this_run": feed["report_bodies_received"],
            "valid_cached_bodies_available": sum(bool(x.get("body_evidence")) for x in report_items.values()),
            "body_receipts_from_this_run": sum(bool(parse_stamp(x.get("body_evidence", {}).get("retrieved_at_utc"))
                and parse_stamp(x["body_evidence"]["retrieved_at_utc"]) >= run_started)
                for x in report_items.values())})
        save_json(cache_path, {"schema_version": 1, "letter_type": letter_type,
            "updated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "report_items": report_items})
        if not stop_feed and feed["companies_checked"] == 254:
            save_json(resume_path, {"state": "complete", "completed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
        feed["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        report["feeds"][key] = feed
    report["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["limits"] = ["Per-identity searches use that identity's local latest publication minus a seven-day overlap; identities without a local watermark are searched for 365 days.",
                        "Every page reported by the Codal Total field is fetched and page totals must remain consistent.",
                        "A complete search window does not prove completeness before its recorded FromDate.",
                        "HTTP 200 Codal system-error pages are retained as evidence and counted as body errors, never as valid report bodies.",
                        "HTTP 200 CAPTCHA/rate-limit pages are retained as invalid evidence, never as successful report bodies or extraction input.",
                        "Receipt timestamps are this run's timestamps and are not attributed to historical archive records."]
    path = out / "manifest.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(path.relative_to(ROOT)).replace("\\", "/"),
        "feeds": {k: {f: v.get(f) for f in ("state", "pages", "reports_seen", "companies_checked", "companies_new_reports", "companies_no_new_reports", "companies_failed", "new_reports", "report_bodies_received", "latest_published_at", "error")}
                  for k, v in report["feeds"].items()}}, ensure_ascii=False))
    return 0 if all(x["state"] in ("received", "empty") for x in report["feeds"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
