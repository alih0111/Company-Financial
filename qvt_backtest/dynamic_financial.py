"""Codal's explicitly dated dynamic cells, without JavaScript execution.

Only official catalog identities, parent tables, statement-local million-rial
descriptions and the report's own column qualify. Raw pages are immutable.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import time
import sys
import urllib.parse
import urllib.request
import urllib.error
from bs4 import BeautifulSoup
import pandas as pd
import collect_financial_history as H

VERSION = "codal-dynamic-source-v6"
STORE = H.OUT / "dynamic_sources"


def payload(html):
    match = re.search(r"\bvar\s+datasource\s*=\s*", html)
    if not match:
        raise ValueError("no_dynamic_datasource")
    data, _ = json.JSONDecoder().raw_decode(html[match.end():])
    if not isinstance(data, dict):
        raise ValueError("invalid_dynamic_datasource")
    return data


def parsed_page(html, rec):
    data = payload(html)
    if str(data.get("tracingNo")) != str(rec["tracing_no"]):
        raise ValueError("dynamic_report_identity_mismatch")
    published = H.parse_persian_datetime(data.get("publishDateTime"))
    if published is None or published != dt.datetime.fromisoformat(rec["published_at"]):
        raise ValueError("dynamic_publication_mismatch")
    date = H.F.jalali_date_in(data.get("periodEndToDate", ""))
    if date is None or date.isoformat() != rec["period_end"]:
        raise ValueError("dynamic_report_period_mismatch")
    result = {"statements": {}, "period_headers": {}, "consolidation": {}}
    legacy = rec.get("parser_version") == "codal-dynamic-source-v1"
    if type(data.get("isConsolidated")) is not bool or (legacy and data.get("isConsolidated") is not False):
        return result
    # The report may contain both parent and consolidated sheets. Require an
    # explicitly separate parent option and its matching sheet/table captions.
    options = {}
    note = ""
    if not legacy:
        soup = BeautifulSoup(html, "html.parser")
        selector = soup.find("select", id="ctl00_ddlTable")
        modern_options = rec.get("parser_version", VERSION) in ("codal-dynamic-source-v3", "codal-dynamic-source-v4", "codal-dynamic-source-v5", "codal-dynamic-source-v6")
        if modern_options and selector is None:
            selector = soup.find("select", id="ddlTable")
        if selector:
            options = {o.get("value"): H.P._caption_kind(" ".join(o.find_all(string=True, recursive=False)) if modern_options else o.get_text()) for o in selector.find_all("option")}
        price_note = soup.find("p", id="ctl00_pPriceNote")
        note = H.P.norm_title(price_note.get_text()) if price_note else ""
    for sheet in data.get("sheets", []):
        for table in sheet.get("tables", []):
            caption = H.P._caption_kind(table.get("title_Fa") or "")
            if not caption or caption[1]:
                continue
            statement = caption[0]
            explicit_unit = "میلیونریال" in H.P.norm_title(table.get("description") or "")
            page_unit = not legacy and "کلیهمبالغدرجشدهبهمیلیونریال" in note
            if not explicit_unit and not page_unit:
                continue
            if data.get("isConsolidated") is True:
                if (H.P._caption_kind(sheet.get("title_Fa") or "") != (statement, False) or
                        options.get(str(sheet.get("code"))) != (statement, False) or
                        not any(kind == (statement, True) for kind in options.values()) or
                        str(table.get("aliasName") or "").startswith("Consolidated")):
                    continue
            columns, grid = {}, {}
            for cell in table.get("cells", []):
                if cell.get("isVisible") is not True:
                    continue
                row, column = cell.get("rowSequence"), cell.get("columnSequence")
                if not isinstance(row, int) or not isinstance(column, int):
                    continue
                if cell.get("cellGroupName") == "Header" and cell.get("periodEndToDate"):
                    d = H.P.jalali_in(cell["periodEndToDate"])
                    if d:
                        if column in columns and columns[column] != d:
                            raise ValueError("conflicting_dynamic_period_column")
                        columns[column] = d
                elif cell.get("cellGroupName") == "Body":
                    if (row, column) in grid:
                        raise ValueError("duplicate_dynamic_cell")
                    grid[row, column] = cell
            ordered = sorted(columns)
            if not ordered or H.F.jalali_to_gregorian(*columns[ordered[0]]).isoformat() != rec["period_end"]:
                continue
            if len({columns[c] for c in ordered}) != len(ordered):
                continue
            if len(ordered) >= 2 and columns[ordered[0]] <= columns[ordered[1]]:
                continue
            titles = {H.P.norm_title(v): k[1] for k, v in H.P.ROW_TITLES.items() if k[0] == statement}
            if statement == "income_statement":
                titles[H.P.norm_title("جمع درآمدهای عملیاتی")] = "revenue"
                titles[H.P.norm_title("سود (زیان) پایه هر سهم (ریال)")] = "eps"
            elif statement == "balance_sheet":
                titles[H.P.norm_title("جمع حقوق صاحبان سهام")] = "total_equity"
                titles[H.P.norm_title("جمع دارائیها")] = "total_assets"
                titles[H.P.norm_title("جمع دارائیهای جاری")] = "current_assets"
            bucket, ambiguous = {}, set()
            for (row, column), cell in grid.items():
                if column != 1:
                    continue
                metric = titles.get(H.P.norm_title(cell.get("value") or ""))
                if metric is None:
                    continue
                if metric in bucket:
                    ambiguous.add(metric)
                values = {}
                for order, number_column in enumerate(ordered[:3], 1):
                    value_cell = grid.get((row, number_column), {})
                    if value_cell.get("periodEndToDate") and H.P.jalali_in(value_cell["periodEndToDate"]) != columns[number_column]:
                        raise ValueError("dynamic_cell_header_period_conflict")
                    value = H.P.to_number(str(value_cell.get("value") if value_cell.get("value") is not None else ""))
                    if value is not None and math.isfinite(value):
                        values[order] = value
                if values:
                    bucket[metric] = values
            for metric in ambiguous:
                bucket.pop(metric, None)
            if statement in result["statements"]:
                raise ValueError("ambiguous_dynamic_statement")
            result["statements"][statement] = bucket
            result["period_headers"][statement] = [columns[c] for c in ordered[:3]]
            result["consolidation"][statement] = "parent"
    return result


def own_facts(parsed):
    facts = []
    for statement, bucket in parsed["statements"].items():
        if statement == "balance_sheet":
            totals = [bucket.get(k, {}).get(1) for k in ("total_assets", "total_liabilities", "total_equity")]
            if all(x is not None for x in totals) and abs(totals[0] - totals[1] - totals[2]) > max(2, abs(totals[0]) * 1e-6):
                continue
        for metric, values in bucket.items():
            if 1 in values:
                facts.append({"statement_type": statement, "metric_code": metric,
                              "value": values[1] if metric in H.P.PER_SHARE else values[1] * 1e6,
                              "unit": "rial_per_share" if metric in H.P.PER_SHARE else "rial", "basis": "parent", "period_order": 1})
    return sorted(facts, key=lambda f: (f["statement_type"], f["metric_code"]))


def verified_parsed(rec):
    path = Path(rec["dynamic_manifest_path"])
    if not path.resolve().is_relative_to(STORE.resolve()):
        raise ValueError("dynamic_manifest_outside_archive")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != rec["dynamic_manifest_sha256"]:
        raise ValueError("dynamic_manifest_hash_mismatch")
    manifest = json.loads(raw)
    if str(manifest["tracing_no"]) != str(rec["tracing_no"]):
        raise ValueError("dynamic_manifest_identity_mismatch")
    required_page_ids = manifest.get("required_page_ids")
    if required_page_ids is not None:
        present_page_ids = [str(page.get("page_id")) for page in manifest.get("pages", [])]
        if (len(present_page_ids) != len(set(present_page_ids))
                or not set(map(str, required_page_ids)).issubset(present_page_ids)):
            raise ValueError("dynamic_required_page_missing_or_duplicate")
    result = {"statements": {}, "period_headers": {}, "consolidation": {}}
    for page in manifest["pages"]:
        source = Path(page["path"])
        if not source.resolve().is_relative_to(STORE.resolve()):
            raise ValueError("dynamic_page_outside_archive")
        body = source.read_bytes()
        if hashlib.sha256(body).hexdigest() != page["sha256"]:
            raise ValueError("dynamic_page_hash_mismatch")
        html = body.decode("utf8", "strict")
        if page.get("role") == "navigation_only" and rec.get("parser_version") in ("codal-dynamic-source-v4", "codal-dynamic-source-v5", "codal-dynamic-source-v6"):
            # An auditor landing page provides only observed dropdown links.
            # Every financial sheet still proves report identity/publication.
            try:
                payload(html)
            except ValueError as exc:
                if str(exc) == "no_dynamic_datasource":
                    continue
                raise
            raise ValueError("financial_datasource_marked_navigation_only")
        if page.get("role") == "rejected_financial" and rec.get("parser_version") in ("codal-dynamic-source-v5", "codal-dynamic-source-v6"):
            try:
                parsed_page(html, rec)
            except ValueError as exc:
                if str(exc) == page.get("reason") == "duplicate_dynamic_cell":
                    continue
                raise
            raise ValueError("rejected_financial_page_is_not_ambiguous")
        parsed = parsed_page(html, rec)
        for statement, bucket in parsed["statements"].items():
            if statement in result["statements"] and result["statements"][statement] != bucket:
                raise ValueError("conflicting_dynamic_pages")
            result["statements"][statement] = bucket
            result["period_headers"][statement] = parsed["period_headers"][statement]
            result["consolidation"][statement] = "parent"
    native = manifest.get("native_export")
    if native:
        if rec.get("parser_version") != "codal-dynamic-source-v6":
            raise ValueError("paired export requires its declared parser version")
        from paired_balance import prove_unit, parse_balance, source_hash_modes
        original_path = H.OUT / "reports" / f"{rec['company_id']}_{rec['tracing_no']}.json"
        if hashlib.sha256(original_path.read_bytes()).hexdigest() != native["original_record_sha256"]:
            raise ValueError("paired original-record hash mismatch")
        original = H.C.read(original_path)
        if any(original.get(key) != rec.get(key) for key in ("company_id", "symbol", "tracing_no", "title", "period_end", "published_at", "observed_at", "sha256")):
            raise ValueError("paired export record identity mismatch")
        path = Path(native["path"])
        if not path.resolve().is_relative_to(STORE.resolve()):
            raise ValueError("paired export outside archive")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != native["sha256"] or not source_hash_modes(body, original["sha256"]):
            raise ValueError("paired export source hash mismatch")
        proof = prove_unit(rec, original, manifest["pages"])
        if proof is None or proof != native["unit_proof"]:
            raise ValueError("paired same-report unit evidence mismatch")
        parsed = parse_balance(body.decode("utf8", "strict"), rec["period_end"])
        if parsed is None:
            raise ValueError("paired parent balance not unambiguous and balanced")
        balance = parsed["statements"]["balance_sheet"]
        old = result["statements"].get("balance_sheet", {})
        if any(balance.get(metric, {}).get(1) != values.get(1) for metric, values in old.items()):
            raise ValueError("paired balance conflicts with existing own-column values")
        result["statements"]["balance_sheet"] = balance
        result["period_headers"]["balance_sheet"] = parsed["period_headers"]["balance_sheet"]
        result["consolidation"]["balance_sheet"] = "parent"
    return result


def source_url(raw):
    url = urllib.parse.urljoin("https://www.codal.ir/", raw)
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname not in ("www.codal.ir", "codal.ir") or not p.path.startswith("/Reports/"):
        raise ValueError("not_official_catalog_report_url")
    return url


def get_page(url, path, delay):
    if path.exists():
        return path.read_bytes()
    time.sleep(delay)
    try:
        from codal_session import request
        body = request(url)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise H.C.CollectionPaused(f"HTTP {exc.code}; saved checkpoint, no further requests") from exc
        raise
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("oversized_report_page")
    if "captcha" in body.decode("utf8", "replace").lower():
        raise H.C.CollectionPaused("captcha; human verification required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-reports", type=int, default=20)
    ap.add_argument("--delay", type=float, default=1.5)
    args = ap.parse_args()
    latest = H.C.read(H.ROOT / "qvt_backtest/output/roadmap_latest.json")
    queue = pd.read_csv(Path(latest["run_path"]) / "report_recovery_queue.csv", dtype=str)
    catalog = {str(r["letter"]["TracingNo"]): r for r in H.C.read(H.OUT / "catalog_versions.json")}
    results = []
    prior_progress = STORE / "progress.json"
    if prior_progress.exists():
        # Cached failures are evidence, but only unchanged unsupported layouts
        # are skipped; a new parser version must be allowed to revisit them.
        previous = H.C.read(prior_progress)
        old_results = previous.get("results", []) if previous.get("parser_version") == VERSION else []
    else:
        old_results = []
    unsupported = {r["tracing_no"] for r in old_results if r.get("reason") == "no_dynamic_datasource"}
    for row in queue.to_dict("records"):
        if len(results) >= args.max_reports:
            break
        tracing = row["tracing_no"]
        if tracing in unsupported:
            continue
        original = H.OUT / "reports" / (row["company_id"] + "_" + tracing + ".json")
        if original.exists() and H.load_archived_report(original)["facts"]:
            continue
        item, directory = catalog[tracing], STORE / tracing
        directory.mkdir(parents=True, exist_ok=True)
        letter = item["letter"]
        rec = {"company_id": item["company_id"], "symbol": item["symbol"], "tracing_no": tracing,
               "period_end": item["period"], "published_at": item["published_at"], "title": letter["Title"]}
        try:
            url = source_url(letter.get("Url", ""))
            first_path = directory / "catalog_page.html"
            body = get_page(url, first_path, args.delay)
            html = body.decode("utf8", "strict")
            role, rejected_reason, shown_codes = "financial", None, set()
            try:
                parsed_page(html, rec)
                shown_codes = {str(sheet.get("code")) for sheet in payload(html).get("sheets", [])}
            except ValueError as exc:
                if str(exc) == "duplicate_dynamic_cell":
                    # Identity/publication/period were verified before parsing
                    # cells. Reject this sheet, still inspect other statements.
                    role, rejected_reason = "rejected_financial", str(exc)
                    shown_codes = {str(sheet.get("code")) for sheet in payload(html).get("sheets", [])}
                elif str(exc) == "no_dynamic_datasource":
                    role = "navigation_only"
                else:
                    raise
                # Some official catalog links land on the auditor opinion.
                # It contributes no facts; observed parent sheets are followed
                # below and each must match the catalog tracing/date/period.
            soup = BeautifulSoup(html, "html.parser")
            selector = soup.find("select", id="ctl00_ddlTable") or soup.find("select", id="ddlTable")
            pages = [{"source": url, "path": str(first_path), "sha256": hashlib.sha256(body).hexdigest(), "role": role, "reason": rejected_reason}]
            if selector:
                for option in selector.find_all("option"):
                    kind = H.P._caption_kind(" ".join(option.find_all(string=True, recursive=False)))
                    code = option.get("value")
                    if not kind or kind[1] or not code or not code.isdigit():
                        continue
                    if code in shown_codes:
                        continue
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)
                    if query.get("sheetId") == [code]:
                        continue
                    query["sheetId"] = [code]
                    p = urllib.parse.urlsplit(url)
                    sheet_url = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(query, doseq=True), ""))
                    page_path = directory / ("sheet_" + code + ".html")
                    page = get_page(sheet_url, page_path, args.delay)
                    sheet_role, reason = "financial", None
                    try:
                        parsed_page(page.decode("utf8", "strict"), rec)
                    except ValueError as exc:
                        if str(exc) != "duplicate_dynamic_cell":
                            raise
                        sheet_role, reason = "rejected_financial", str(exc)
                    pages.append({"source": sheet_url, "path": str(page_path), "sha256": hashlib.sha256(page).hexdigest(), "role": sheet_role, "reason": reason})
            manifest = directory / "manifest.json"
            H.C.write(manifest, {"pages": pages, "tracing_no": tracing})
            rec.update({"dynamic_manifest_path": str(manifest), "dynamic_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "parser_version": VERSION})
            facts = own_facts(verified_parsed(rec))
            if not facts:
                raise ValueError("no_proven_dynamic_parent_facts")
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            warnings = [{"source": page["source"], "reason": page["reason"]} for page in pages if page.get("role") == "rejected_financial"]
            if original.exists():
                old = H.C.read(original)
                record = {**old, **{k: rec[k] for k in ("dynamic_manifest_path", "dynamic_manifest_sha256", "parser_version")},
                          "facts": facts, "recovered_at": now, "original_record_sha256": hashlib.sha256(original.read_bytes()).hexdigest()}
                target = H.OUT / "recovered_reports" / original.name
            else:
                record = {**rec, "facts": facts, "observed_at": now, "source": url,
                          "sha256": rec["dynamic_manifest_sha256"], "history_basis": "reconstructed_publication_history"}
                target = original
            if warnings:
                # Record the gap rather than treating a partial recovery as a
                # complete statement set. No ambiguous cell contributes facts.
                record["extraction_warnings"] = warnings
            H.C.write(target, record)
            result = {"symbol": rec["symbol"], "tracing_no": tracing, "status": "recovered", "facts": len(facts)}
        except H.C.CollectionPaused as exc:
            results.append({"symbol": rec["symbol"], "tracing_no": tracing, "status": "paused", "reason": str(exc)})
            break
        except Exception as exc:
            result = {"symbol": rec["symbol"], "tracing_no": tracing, "status": "unresolved", "reason": str(exc)}
        results.append(result)
        H.C.write(STORE / "progress.json", {"status": "running", "parser_version": VERSION, "results": old_results + results})
        print(json.dumps(result, ensure_ascii=False), flush=True)
    H.C.write(STORE / "progress.json", {"status": "paused" if results and results[-1]["status"] == "paused" else "batch_complete", "parser_version": VERSION, "results": old_results + results})


if __name__ == "__main__":
    # Windows redirected stdout can default to a Western code page. Evidence
    # is saved before logging, but logging must never stop Persian collection.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
