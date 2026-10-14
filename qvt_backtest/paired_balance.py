"""Same-report unit evidence for parent balance sheets in archived exports.

No inferred units: a hashed official report page must prove the report-wide
million-rial declaration and the same encrypted report serial as the export.
Only an unambiguous, dated, balanced parent table qualifies.
"""
import hashlib
import math
from pathlib import Path
import urllib.parse
from bs4 import BeautifulSoup
import collect_financial_history as H


def serial_from_export(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "excel.codal.ir" or not parsed.path.startswith("/service/Excel/GetAll/"):
        return None
    parts = parsed.path.rstrip("/").split("/")
    return urllib.parse.unquote(parts[-2]) if len(parts) >= 2 else None


def source_hash_modes(body, expected):
    candidates = {"file_bytes": body, "inverse_windows_newline_write": body.replace(b"\r\n", b"\n"),
                  "cached_universal_newline_read": body.decode("utf8").replace("\r\n", "\n").replace("\r", "\n").encode()}
    return [name for name, value in candidates.items() if hashlib.sha256(value).hexdigest() == expected]


def prove_unit(rec, original, pages):
    from dynamic_financial import parsed_page
    serial = serial_from_export(original.get("source", ""))
    if not serial:
        return None
    for page in pages:
        if page.get("role", "financial") != "financial":
            continue
        url = urllib.parse.urlsplit(page["source"])
        if (url.scheme != "https" or url.hostname not in ("codal.ir", "www.codal.ir") or
                urllib.parse.parse_qs(url.query).get("LetterSerial") != [serial]):
            continue
        body = Path(page["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != page["sha256"]:
            raise ValueError("paired unit page hash mismatch")
        html = body.decode("utf8", "strict")
        parsed_page(html, rec)  # report identity, publication and own period
        note = BeautifulSoup(html, "html.parser").find("p", id="ctl00_pPriceNote")
        if note and "کلیهمبالغدرجشدهبهمیلیونریال" in H.P.norm_title(note.get_text()):
            return {"path": page["path"], "sha256": page["sha256"], "source": page["source"],
                    "scope": "Explicit same-report all-amounts million-rial declaration; per-share rows excluded"}
    return None


def parse_balance(html, period):
    candidates = []
    titles = {H.P.norm_title(title): metric for (statement, metric), title in H.P.ROW_TITLES.items() if statement == "balance_sheet"}
    for title, metric in [("جمع حقوق صاحبان سهام", "total_equity"), ("جمع دارائیها", "total_assets"), ("جمع دارائیهای جاری", "current_assets")]:
        titles[H.P.norm_title(title)] = metric
    for caption, table in H.P._tables_with_captions(html):
        if H.P._caption_kind(caption) != ("balance_sheet", False):
            continue
        rows = H.P._rows(table)
        dated_headers = []
        for row in rows[:4]:
            dated = [(column, H.P.jalali_in(value)) for column, value in enumerate(row) if H.P.jalali_in(value)]
            if len(dated) >= 2:
                dated_headers.append(dated)
        if len(dated_headers) != 1:
            continue
        dated = dated_headers[0]
        # Mirrored panels and repeated dates require a separate proven layout.
        if (len({date for _, date in dated}) != len(dated) or dated[0][1] <= dated[1][1] or
                H.F.jalali_to_gregorian(*dated[0][1]).isoformat() != period or dated[0][0] != 1):
            continue
        bucket, ambiguous = {}, set()
        for row in rows:
            metric = titles.get(H.P.norm_title(row[0])) if row else None
            if metric is None:
                continue
            if metric in bucket:
                ambiguous.add(metric)
            values = {}
            for order, (column, _) in enumerate(dated[:3], 1):
                value = H.P.to_number(row[column]) if len(row) > column else None
                if value is not None and math.isfinite(value):
                    values[order] = value
            if values:
                bucket[metric] = values
        for metric in ambiguous:
            bucket.pop(metric, None)
        totals = [bucket.get(metric, {}).get(1) for metric in ("total_assets", "total_liabilities", "total_equity")]
        if (any(value is None for value in totals) or totals[0] < 0 or totals[1] < 0 or
                abs(totals[0] - totals[1] - totals[2]) > max(2, abs(totals[0]) * 1e-6)):
            continue
        candidates.append((bucket, [date for _, date in dated[:3]]))
    if len(candidates) != 1:
        return None
    bucket, dates = candidates[0]
    return {"statements": {"balance_sheet": bucket}, "period_headers": {"balance_sheet": dates},
            "consolidation": {"balance_sheet": "parent"}}


def process(publish=False, limit=20):
    import json
    from dynamic_financial import verified_parsed, own_facts, STORE
    import datetime as dt
    results, errors = [], []
    for rec in H.C.read(H.OUT / "reports.json"):
        if not rec.get("dynamic_manifest_path") or any(f["metric_code"] == "total_equity" for f in rec["facts"]):
            continue
        original_path = H.OUT / "reports" / f"{rec['company_id']}_{rec['tracing_no']}.json"
        original = H.C.read(original_path)
        existing_overlay = H.OUT / "recovered_reports" / original_path.name
        if existing_overlay.exists():
            candidate = H.C.read(existing_overlay)
            if candidate.get("parser_version") == "codal-dynamic-source-v6" and any(f["metric_code"] == "total_equity" for f in candidate["facts"]):
                H.load_archived_report(original_path)
                continue
        if not serial_from_export(original.get("source", "")):
            continue
        try:
            verified_parsed(rec)
            manifest = H.C.read(Path(rec["dynamic_manifest_path"]))
            proof = prove_unit(rec, original, manifest["pages"])
            if not proof:
                continue
            html, path = H.C.report_html(rec["symbol"], {"TracingNo": rec["tracing_no"]}, False, 0)
            if not html or not source_hash_modes(Path(path).read_bytes(), original["sha256"]):
                continue
            parsed = parse_balance(html, rec["period_end"])
            if not parsed:
                continue
            if publish:
                directory = STORE / rec["tracing_no"]
                directory.mkdir(parents=True, exist_ok=True)
                native_path = directory / "native_export_v6.html"
                body = Path(path).read_bytes()
                if native_path.exists() and native_path.read_bytes() != body:
                    raise ValueError("immutable paired export changed")
                if not native_path.exists():
                    native_path.write_bytes(body)
                enriched_manifest = {**manifest, "native_export": {"path": str(native_path),
                    "sha256": hashlib.sha256(body).hexdigest(), "original_record_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(), "unit_proof": proof}}
                manifest_path = directory / "manifest_enriched_v6.json"
                H.C.write(manifest_path, enriched_manifest)
                proposed = {**rec, "parser_version": "codal-dynamic-source-v6",
                            "dynamic_manifest_path": str(manifest_path), "dynamic_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                            "original_record_sha256": hashlib.sha256(original_path.read_bytes()).hexdigest(),
                            "balance_enriched_at": dt.datetime.now(dt.timezone.utc).isoformat()}
                facts = own_facts(verified_parsed(proposed))
                new = {(f["statement_type"], f["metric_code"]): f for f in facts}
                if any(new.get((f["statement_type"], f["metric_code"])) != f for f in rec["facts"]):
                    raise ValueError("paired enrichment changed existing facts")
                if len(facts) <= len(rec["facts"]):
                    continue
                proposed["facts"] = facts
                H.C.write(H.OUT / "recovered_reports" / original_path.name, proposed)
                H.load_archived_report(original_path)  # normal consumer verifies it too
            results.append({"symbol": rec["symbol"], "tracing_no": rec["tracing_no"], "own_balance_metrics": len(parsed["statements"]["balance_sheet"]), "unit_proof": proof})
        except Exception as exc:
            errors.append({"symbol": rec["symbol"], "tracing_no": rec["tracing_no"], "reason": str(exc)})
        if limit and len(results) >= limit:
            break
    H.C.write(H.OUT / ("paired_balance_recovery.json" if publish else "paired_balance_probe.json"),
              {"mode": "verified_overlay_recovery" if publish else "diagnostic_only", "candidates": results, "errors": errors, "facts_changed": publish and bool(results), "originals_changed": False})
    print(json.dumps({"verified_candidates": len(results), "errors": len(errors), "facts_changed": publish and bool(results), "originals_changed": False}))


def main():
    import argparse
    from run_investment_pipeline import pipeline_lock
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish", action="store_true", help="Publish verified, nonconflicting source overlays; no original changes")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    limit = args.limit if args.limit is not None else (0 if args.publish else 20)
    if args.publish:
        with pipeline_lock(H.ROOT / "qvt_backtest/output/pipeline/run.lock"):
            process(True, limit)
    else:
        process(False, limit)


if __name__ == "__main__":
    main()
