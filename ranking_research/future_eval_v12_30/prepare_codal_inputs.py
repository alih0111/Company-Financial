"""Parse newly acquired Codal bodies into traceable, unit-normalized candidates.

This stage never modifies the frozen archive. It emits a run-scoped factor input
bundle; admission is separately gated by the locked publication cutoff and the
order/global-session calendar where session timing is required.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import html as html_lib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "qvt_backtest"), str(ROOT / "provenance_v1"), str(ROOT / "go-app/py"), str(ROOT)]
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jalali_gregorian(value: str) -> dt.date:
    import jdatetime
    normalized = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    m = re.search(r"(13|14)\d{2}/\d{1,2}/\d{1,2}", normalized)
    if not m:
        raise ValueError("report_period_missing")
    y, month, day = map(int, m.group(0).split("/"))
    return jdatetime.date(y, month, day).togregorian()


def parse_number(value):
    if value is None:
        return None
    text = str(value).strip().replace("٬", "").replace(",", "").replace("٫", ".")
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    if text in ("", "-", "--", "—"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    number = float(text)
    return -abs(number) if negative else number


def datasource(html: str) -> dict:
    match = re.search(r"\bvar\s+datasource\s*=\s*", html)
    if not match:
        raise ValueError("codal_dynamic_datasource_missing")
    value, _ = json.JSONDecoder().raw_decode(html[match.end():])
    if not isinstance(value, dict):
        raise ValueError("codal_dynamic_datasource_invalid")
    return value


def correction_predecessor(item: dict, html: str) -> str | None:
    """Accept only an explicit previous-version reference, never infer by title/date."""
    metadata = item.get("version_metadata") or {}
    allowed = {"previoustracingno", "prevtracingno", "supersedestracingno",
               "referencetracingno", "previousversiontracingno"}
    for key, value in metadata.items():
        normalized = re.sub(r"[^a-z]", "", str(key).lower())
        if normalized not in allowed:
            continue
        digits = str(value or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        match = re.fullmatch(r"\s*(\d+)\s*", digits)
        if match and match.group(1) != str(item.get("tracing_no")):
            return match.group(1)
    previous = re.search(r"نسخه\s*قبلی[^\d۰-۹٠-٩]*\(?\s*([\d۰-۹٠-٩]{5,})", html)
    if previous:
        value = previous.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        if value != str(item.get("tracing_no")):
            return value
    return None


def parse_financial(html: str, item: dict, identity: dict, retrieved: str, body_sha: str) -> dict:
    import dynamic_financial as D
    from bs4 import BeautifulSoup
    source_pub = dt.datetime.fromisoformat(item["published_at"])
    local_pub = source_pub
    published_utc = source_pub.astimezone(dt.timezone.utc)
    rec = {"company_id": identity["company_id"], "symbol": item["symbol"],
           "tracing_no": str(item["tracing_no"]), "title": item["title"],
           "period_end": jalali_gregorian(item["title"]).isoformat(),
           # Preserve the source offset (including historical Tehran DST offsets)
           # because the locked parser compares the page publication timestamp.
           "published_at": local_pub.isoformat(timespec="seconds"),
           "observed_at": retrieved, "sha256": body_sha,
           "parser_version": D.VERSION}
    parsed = {"statements": {}, "period_headers": {}, "consolidation": {}}
    pages = [{"html": html, "sha256": body_sha}]
    received_stamps = [dt.datetime.fromisoformat(retrieved.replace("Z", "+00:00"))]
    for page in item.get("financial_pages", []):
        page_path = Path(page["path"])
        page_bytes = gzip.decompress(page_path.read_bytes()) if page_path.suffix == ".gz" else page_path.read_bytes()
        if sha(page_bytes) != page.get("sha256"):
            raise ValueError("financial_sheet_body_hash_mismatch")
        stamp = dt.datetime.fromisoformat(str(page.get("retrieved_at_utc", "")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("financial_sheet_receipt_time_missing_timezone")
        received_stamps.append(stamp.astimezone(dt.timezone.utc))
        pages.append({"html": page_bytes.decode("utf-8", "strict"), "sha256": page["sha256"]})
    for index, page in enumerate(pages):
        try:
            one = D.parsed_page(page["html"], rec)
        except ValueError as exc:
            if index == 0 and str(exc) == "no_dynamic_datasource":
                continue
            raise
        for statement, bucket in one["statements"].items():
            if statement in parsed["statements"]:
                if parsed["statements"][statement] != bucket:
                    raise ValueError("financial_statement_conflicts_across_sheets")
                continue
            parsed["statements"][statement] = bucket
            parsed["period_headers"][statement] = one["period_headers"][statement]
            parsed["consolidation"][statement] = one["consolidation"][statement]
    facts = D.own_facts(parsed)
    if not facts:
        raise ValueError("no_verified_parent_financial_facts")
    if any(f.get("unit") not in ("rial", "rial_per_share") or f.get("basis") != "parent" for f in facts):
        raise ValueError("financial_fact_unit_or_basis_invalid")
    supersedes = correction_predecessor(item, html)
    soup = BeautifulSoup(html, "html.parser")
    body_symbol = soup.find(attrs={"id": re.compile(r"lbl(?:Symbol|SymbolName|CompanyName)", re.I)})
    if re.search(r"\bvar\s+datasource\s*=", html) and body_symbol and identity["symbol"] not in body_symbol.get_text(" ", strip=True):
        raise ValueError("financial_body_symbol_mismatch")
    received_latest = max(x.astimezone(dt.timezone.utc) for x in received_stamps).isoformat()
    return {**rec, "observed_at": received_latest, "published_at": published_utc.isoformat(), "published_at_tehran": rec["published_at"],
            "facts": facts, "period_headers": parsed.get("period_headers", {}),
            "received_at_utc": received_latest, "source_body_sha256": body_sha,
            "financial_pages": item.get("financial_pages", []),
            "report_url": item.get("url"), "title_is_correction": "اصلاحیه" in item.get("title", ""),
            "supersedes_tracing_no": supersedes,
            "version_linkage_state": "explicit_previous_version" if supersedes else ("correction_unlinked" if "اصلاحیه" in item.get("title", "") else "original")}


def parse_sales(html: str, item: dict, retrieved: str, body_sha: str) -> dict:
    data = datasource(html)
    if str(data.get("tracingNo")) != str(item["tracing_no"]):
        raise ValueError("monthly_report_identity_mismatch")
    import jdatetime
    period_j = str(data.get("periodEndToDate") or "")
    period_g = jalali_gregorian(period_j)
    title_period_g = jalali_gregorian(item.get("title", ""))
    if title_period_g != period_g:
        raise ValueError("monthly_title_period_mismatch")
    period_month = jdatetime.date(*map(int, period_j.split("/")[:3])).strftime("%Y-%m")
    local_pub = dt.datetime.fromisoformat(item["published_at"]).astimezone(TEHRAN)
    api_local_pub = dt.datetime.fromisoformat(item["published_at"]).astimezone(TEHRAN).replace(tzinfo=None)
    import codal_feed
    body_pub = codal_feed.parse_persian_datetime(str(data.get("publishDateTime") or ""))
    if body_pub is None or body_pub != api_local_pub:
        raise ValueError("monthly_publication_time_mismatch")
    title_correction = "اصلاحیه" in item.get("title", "")
    supersedes = correction_predecessor(item, html)
    accepted = []
    reasons = []
    for sheet in data.get("sheets", []):
        for table in sheet.get("tables", []):
            alias = str(table.get("aliasName") or "")
            title = str(table.get("title_Fa") or "")
            if alias not in ("ProductionAndSales", "Service"):
                continue
            cells = [c for c in table.get("cells", []) if c.get("isVisible") is True]
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            note = soup.find(id="ctl00_pPriceNote")
            note_text = note.get_text(" ", strip=True) if note else ""
            unit_text = html_lib.unescape(" ".join((title, str(sheet.get("title_Fa") or ""), note_text)))
            unit_text = unit_text.translate(str.maketrans({"ي": "ی", "ك": "ک"}))
            unit_norm = re.sub(r"\s+", "", unit_text)
            scale = 1.0
            unit = None
            if "میلیونریال" in unit_norm:
                scale, unit = 1_000_000.0, "million_rial"
            elif "هزارریال" in unit_norm:
                scale, unit = 1_000.0, "thousand_rial"
            elif "ریال" in unit_norm:
                scale, unit = 1.0, "rial"
            if unit is None:
                reasons.append(f"{alias}:unit_unproven")
                continue
            headers = {}
            for c in cells:
                if c.get("cellGroupName") != "Header" or int(c.get("rowSequence") or 0) > 2:
                    continue
                seq = int(c.get("columnSequence") or 0)
                row_number = int(c.get("rowSequence") or 0)
                value = str(c.get("value") or "")
                date_value = str(c.get("periodEndToDate") or "")
                span = max(1, int(c.get("colSpan") or c.get("colspan") or 1))
                for target_col in range(seq, seq + span):
                    headers.setdefault(target_col, []).append((row_number, value, date_value))
            current_columns = []
            for seq, parts in headers.items():
                labels = " ".join(v for _, v, _ in sorted(parts))
                dates = [d for _, _, d in parts if d]
                def normalized_header(value: str) -> str:
                    value = value.replace("‌", "").translate(str.maketrans({"ي": "ی", "ك": "ک", "۱": "1"}))
                    return re.sub(r"\s+", "", value)
                one_month_header = any(row == 1 and ("دورهیکماهه" in normalized_header(text)
                                        or "دوره1ماهه" in normalized_header(text)) for row, text, _ in parts)
                if period_j in dates and one_month_header and "مبلغ فروش" in labels:
                    current_columns.append(seq)
                elif period_j in dates and one_month_header and alias == "Service" and ("درآمد" in labels or "مبلغ" in labels):
                    current_columns.append(seq)
            if len(current_columns) != 1:
                reasons.append(f"{alias}:current_month_sales_column_ambiguous")
                continue
            labels_by_row = {}
            values_by_row = {}
            for c in cells:
                row, col = int(c.get("rowSequence") or 0), int(c.get("columnSequence") or 0)
                if col == 1:
                    labels_by_row[row] = str(c.get("value") or "").strip()
                if col == current_columns[0] and c.get("cellGroupName") == "Body":
                    values_by_row[row] = parse_number(c.get("value"))
            totals = [(row, values_by_row.get(row)) for row, label in labels_by_row.items()
                      if label in ("جمع", "جمع کل", "مجموع", "جمع درآمدهای عملیاتی", "جمع درآمد عملیاتی")]
            totals = [(row, value) for row, value in totals if value is not None]
            if len(totals) != 1:
                reasons.append(f"{alias}:monthly_total_row_ambiguous")
                continue
            amount = float(totals[0][1]) * scale
            accepted.append({"sales_rial": amount, "reported_unit": unit,
                             "reported_value": float(totals[0][1]), "table_alias": alias,
                             "total_row": labels_by_row[totals[0][0]], "column_sequence": current_columns[0]})
    if len(accepted) != 1:
        raise ValueError("monthly_sales_parse_not_unique:" + (";".join(reasons) or f"valid_tables={len(accepted)}"))
    return {"tracing_no": str(item["tracing_no"]), "company_id": item["company_id"],
            "symbol": item["symbol"], "period_end": period_g.isoformat(), "period_month_jalali": period_month,
            "sales_current_rial": accepted[0]["sales_rial"], "reported_value": accepted[0]["reported_value"],
            "reported_unit": accepted[0]["reported_unit"], "table": accepted[0]["table_alias"],
            "publish_time_raw_jalali": data.get("publishDateTime"),
            "published_at_utc": local_pub.astimezone(dt.timezone.utc).isoformat(),
            "received_at_utc": retrieved, "source_body_sha256": body_sha,
            "report_url": item.get("url"), "is_correction": title_correction,
            "supersedes_tracing_no": supersedes,
            "version_linkage_state": "explicit_previous_version" if supersedes else ("correction_unlinked" if title_correction else "original")}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    universe = __import__("pandas").read_csv(ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv", dtype=str)
    identity_by_symbol = {r.symbol: {"symbol": r.symbol, "company_id": r.company_id} for r in universe.itertuples(index=False)}
    out_dir = manifest_path.parent / "prepared"
    out_dir.mkdir(parents=True, exist_ok=True)
    output = {"schema_version": 1, "run_id": source.get("run_id"), "source_manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
              "prepared_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "financial": [], "sales": [],
              "errors": [], "lineage": {"publication_time_preserved": True, "receipt_time_preserved": True,
                  "received_at_backdated": False, "raw_body_hash_required": True}}
    by_feed = source.get("feeds", {})
    for feed_name in ("financial", "sales"):
        feed = by_feed.get(feed_name, {})
        for item in feed.get("report_ids", []):
            body_evidence = item.get("body_evidence")
            if not body_evidence:
                continue
            try:
                raw_path = ROOT / body_evidence["path"]
                compressed = raw_path.read_bytes()
                body = gzip.decompress(compressed)
                if sha(body) != body_evidence.get("sha256"):
                    raise ValueError("source_body_hash_mismatch")
                retrieved = str(body_evidence["retrieved_at_utc"])
                if not item.get("symbol") or item["symbol"] not in identity_by_symbol:
                    raise ValueError("symbol_not_in_frozen_universe")
                identity = identity_by_symbol[item["symbol"]]
                if str(item.get("company_id")) != str(identity["company_id"]):
                    raise ValueError("frozen_identity_mapping_mismatch")
                html = body.decode("utf-8", "strict")
                if "خطای سیستمی | کدال" in html or "خطاى سيستمى | كدال" in html:
                    raise ValueError("codal_system_error_page_http_200")
                lowered = html.lower()
                if ("captchaimage" in lowered or "captchaCode" in html
                        or "429 too many requests" in lowered
                        or "درخواست‌های بیش از حد" in html):
                    raise ValueError("codal_captcha_or_rate_limit_page_http_200")
                if not re.search(r"\bvar\s+datasource\s*=", html) and not re.search(r"<table\b", html, re.I):
                    raise ValueError("codal_body_is_not_a_report_http_200")
                if feed_name == "financial":
                    if not item.get("financial_pages_complete"):
                        raise ValueError("financial_statement_pages_incomplete")
                    record = parse_financial(html, item, identity, retrieved, sha(body))
                    output["financial"].append(record)
                else:
                    record = parse_sales(html, {**item, **identity}, retrieved, sha(body))
                    output["sales"].append(record)
            except Exception as exc:
                output["errors"].append({"feed": feed_name, "tracing_no": item.get("tracing_no"),
                                         "symbol": item.get("symbol"), "error": f"{type(exc).__name__}:{str(exc)[:220]}"})
    output["counts"] = {"financial_bodies": sum(bool(x.get("body_evidence")) and not x.get("body_evidence", {}).get("http_200_error_page") for x in by_feed.get("financial", {}).get("report_ids", [])),
                         "financial_parsed": len(output["financial"]), "sales_bodies": sum(bool(x.get("body_evidence")) and not x.get("body_evidence", {}).get("http_200_error_page") for x in by_feed.get("sales", {}).get("report_ids", [])),
                         "sales_parsed": len(output["sales"]), "parse_errors": len(output["errors"])}
    target = out_dir / "prepared-inputs.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"prepared": str(target.relative_to(ROOT)).replace("\\", "/"), **output["counts"]}, ensure_ascii=False))
    return 0 if output["counts"]["parse_errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
