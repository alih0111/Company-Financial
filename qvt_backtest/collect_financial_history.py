"""Version-preserving public Codal archive. Separate from live facts and DB.

Only the report's own current column becomes a historical fact. Comparative
columns cannot silently revise earlier periods. Publication and observation
times remain separate; this is reconstructed public history, not first-seen PIT.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "provenance_v1"))
import complete_ranking_coverage as C
import codal_fs_fetch as F
import codal_fs_parse as P
from codal_publish_resolver import parse_persian_datetime

OUT = ROOT / "qvt_backtest/output/financial_history"


def verify_frozen_record(rec):
    """Verify the retained version, not a later recovery overlay at that path."""
    path = OUT / "reports" / f"{rec['company_id']}_{rec['tracing_no']}.json"
    original = C.read(path)
    identity = ("company_id", "symbol", "tracing_no", "title", "period_end", "published_at", "observed_at", "sha256")
    if any(rec.get(key) != original.get(key) for key in identity):
        raise ValueError("frozen report identity differs from original archive")
    if rec.get("original_record_sha256"):
        if rec["original_record_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("frozen overlay original-record hash mismatch")
    elif rec["facts"] != original["facts"]:
        raise ValueError("frozen original facts changed")
    if rec.get("parser_version", "").startswith("codal-dynamic-source-"):
        from dynamic_financial import verified_parsed, own_facts
        if own_facts(verified_parsed(rec)) != rec["facts"]:
            raise ValueError("frozen dynamic facts do not match source")
    elif rec.get("parser_version") == "legacy-separate-header-v1":
        from legacy_financial import legacy_facts
        html, _ = C.report_html(rec["symbol"], {"TracingNo": rec["tracing_no"]}, False, 0)
        if html is None or legacy_facts(html, rec["period_end"]) != rec["facts"]:
            raise ValueError("frozen legacy facts do not match source")
    else:
        html, _ = C.report_html(rec["symbol"], {"TracingNo": rec["tracing_no"]}, False, 0)
        if html is None or own_column(html, rec["period_end"]) != rec["facts"]:
            raise ValueError("frozen native facts do not match source")
    return rec


def load_archived_report(path):
    """Preserve original evidence, admit a separately verified parsed overlay."""
    rec = C.read(path)
    overlay_path = OUT / "recovered_reports" / path.name
    dynamic_versions = ("codal-dynamic-source-v1", "codal-dynamic-source-v2", "codal-dynamic-source-v3", "codal-dynamic-source-v4", "codal-dynamic-source-v5", "codal-dynamic-source-v6")
    if rec.get("parser_version") in dynamic_versions:
        from dynamic_financial import verified_parsed, own_facts
        if own_facts(verified_parsed(rec)) != rec["facts"]:
            raise ValueError("dynamic facts do not match archived source")
        if not overlay_path.exists():
            return rec
    if (rec["facts"] and rec.get("parser_version") not in dynamic_versions) or not overlay_path.exists():
        return rec
    overlay = C.read(overlay_path)
    if (overlay.get("parser_version") not in ("legacy-separate-header-v1", *dynamic_versions) or
            overlay.get("original_record_sha256") != hashlib.sha256(path.read_bytes()).hexdigest() or
            any(overlay.get(k) != rec.get(k) for k in ("company_id", "symbol", "tracing_no", "title", "period_end", "published_at", "observed_at", "sha256"))):
        raise ValueError("invalid recovered-report lineage")
    if overlay["parser_version"] in dynamic_versions:
        from dynamic_financial import verified_parsed, own_facts
        if own_facts(verified_parsed(overlay)) != overlay["facts"]:
            raise ValueError("dynamic recovered facts do not match source")
        old_values = {(f["statement_type"], f["metric_code"]): f["value"] for f in rec["facts"]}
        new_values = {(f["statement_type"], f["metric_code"]): f["value"] for f in overlay["facts"]}
        if any(new_values.get(key) != value for key, value in old_values.items()):
            raise ValueError("dynamic upgrade conflicts with original facts")
    else:
        from legacy_financial import legacy_facts
        html, _ = C.report_html(rec["symbol"], {"TracingNo": rec["tracing_no"]}, False, 0)
        if html is None or legacy_facts(html, rec["period_end"]) != overlay["facts"]:
            raise ValueError("recovered facts do not match source")
    return overlay


def eligible_versions(letters, cutoff):
    versions = {}
    for letter in letters:
        title = P.norm(letter.get("Title", ""))
        if re.search(r"\(\s*شرکت\b", title):
            continue
        period = F.jalali_date_in(title)
        pub = parse_persian_datetime(letter.get("PublishDateTime"))
        tracing = str(letter.get("TracingNo") or "")
        if (not tracing or pub is None or pub > cutoff or period is None
                or not dt.date(2019, 1, 1) <= period <= cutoff.date()
                or F.classify_letter(letter) not in ("annual", "annual_audited", "interim")):
            continue
        record = {"period": period.isoformat(), "published_at": pub.isoformat(), "letter": letter}
        if tracing in versions and versions[tracing] != record:
            raise ValueError(f"conflicting catalog identity {tracing}")
        versions[tracing] = record
    return sorted(versions.values(), key=lambda r: (r["published_at"], str(r["letter"]["TracingNo"])))


def select_asof(records, cutoff):
    """Latest report version available at the cutoff, independently per period."""
    selected = {}
    for rec in records:
        published = dt.datetime.fromisoformat(rec["published_at"])
        if published >= cutoff:
            continue
        key = rec["company_id"], rec["period_end"]
        old = selected.get(key)
        if old is None or published > dt.datetime.fromisoformat(old["published_at"]):
            selected[key] = rec
        elif published == dt.datetime.fromisoformat(old["published_at"]) and rec["tracing_no"] != old["tracing_no"]:
            raise ValueError("ambiguous same-instant versions")
    return list(selected.values())


def own_column(html, period):
    parsed = P.parse_report(html, parent_only=True)
    rows = []
    for statement, metrics in parsed["statements"].items():
        headers = parsed["period_headers"].get(statement, [])
        if not headers or F.jalali_to_gregorian(*headers[0]).isoformat() != period:
            continue
        if statement == "balance_sheet":
            totals = [metrics.get(k, {}).get(1) for k in ("total_assets", "total_liabilities", "total_equity")]
            if all(v is not None for v in totals) and abs(totals[0] - totals[1] - totals[2]) > max(2, abs(totals[0]) * 1e-6):
                continue
        for metric, values in metrics.items():
            value = values.get(1)
            if value is None or not math.isfinite(value):
                continue
            rows.append({"statement_type": statement, "metric_code": metric,
                         "value": value if metric in P.PER_SHARE else value * 1e6,
                         "unit": "rial_per_share" if metric in P.PER_SHARE else "rial",
                         "basis": "parent", "period_order": 1})
    return rows


def refresh_recovered():
    """Promote verified recoveries for previously empty entries, under a lock."""
    from run_investment_pipeline import pipeline_lock
    with pipeline_lock(ROOT / "qvt_backtest/output/pipeline/run.lock"):
        reports = C.read(OUT / "reports.json")
        progress = C.read(OUT / "progress.json")
        if (progress["status"] != "batch_complete" or
                sum(bool(r["facts"]) for r in reports) != progress["parsed_reports"] or
                sum(len(r["facts"]) for r in reports) != progress["facts"]):
            raise ValueError("Cannot refresh an incomplete or inconsistent archive aggregate")
        changed = 0
        for index, old in enumerate(reports):
            path = OUT / "reports" / f"{old['company_id']}_{old['tracing_no']}.json"
            if not path.exists():
                continue
            if old["facts"]:
                overlay_path = OUT / "recovered_reports" / path.name
                if not overlay_path.exists() or len(C.read(overlay_path)["facts"]) <= len(old["facts"]):
                    continue
            recovered = load_archived_report(path)
            if not recovered["facts"]:
                continue
            if any(old[key] != recovered[key] for key in ("company_id", "symbol", "tracing_no", "title", "period_end", "published_at")):
                raise ValueError("Recovered report metadata changed")
            old_facts = {(f["statement_type"], f["metric_code"]): f for f in old["facts"]}
            new_facts = {(f["statement_type"], f["metric_code"]): f for f in recovered["facts"]}
            if any(new_facts.get(key) != fact for key, fact in old_facts.items()):
                raise ValueError("Recovery changed an existing financial fact")
            reports[index] = recovered
            changed += 1
        progress.update(parsed_reports=sum(bool(r["facts"]) for r in reports),
                        facts=sum(len(r["facts"]) for r in reports),
                        unusable_reports=sum(not r["facts"] and r.get("archive_status") != "missing" for r in reports),
                        missing_html=sum(r.get("archive_status") == "missing" for r in reports),
                        companies_with_facts=len({r["company_id"] for r in reports if r["facts"]}),
                        cached_refresh_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                        cached_refresh_reports=changed)
        C.write(OUT / "reports.json", reports)
        C.write(OUT / "progress.json", progress)
        print(json.dumps({"refreshed_reports": changed, "parsed_reports": progress["parsed_reports"], "facts": progress["facts"]}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--max-downloads", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--refresh-recovered", action="store_true", help="Update only empty aggregate entries from verified local recoveries")
    args = ap.parse_args()
    if args.refresh_recovered:
        refresh_recovered()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    ranking = C.read(ROOT / "qvt_paper/output/current_ranking.json")
    stocks = [r for r in ranking["ranked"] + ranking["unscored"] if r["model_family"] == "general"]
    cutoff = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    queue = []
    for stock in stocks:
        for version in eligible_versions(C.letters_for(stock["symbol"], False, 0), cutoff):
            queue.append({**version, "company_id": stock["company_id"], "symbol": stock["symbol"]})
    C.write(OUT / "catalog_versions.json", queue)
    # Restore previously parsed evidence first, so a long network request never
    # makes the checkpoint temporarily appear to have lost the existing archive.
    queue.sort(key=lambda item: (not (OUT / "reports" / f"{item['company_id']}_{item['letter']['TracingNo']}.json").exists(),
                                 item["published_at"], item["company_id"]))
    stats = {"version": "codal-history-own-column-v1", "catalog_reports": len(queue),
             "companies": len(stocks), "parsed_reports": 0, "facts": 0,
             "missing_html": 0, "unusable_reports": 0, "downloads_attempted": 0,
             "errors": 0, "status": "running", "paused_reason": None,
             "history_basis": "reconstructed_publication_history", "full_model_ready": False}
    # Preserve first observation of identical evidence across resumptions.
    records = []
    C.write(OUT / "progress.json", stats)
    for index, item in enumerate(queue):
        if index and index % 100 == 0:
            stats["reports_checked"] = index
            stats["remaining_unprocessed"] = len(queue) - len(records)
            C.write(OUT / "progress.json", stats)
            C.write(OUT / "reports.json", records)
        letter = item["letter"]
        tracing = str(letter["TracingNo"])
        path = OUT / "reports" / f"{item['company_id']}_{tracing}.json"
        if path.exists():
            record = load_archived_report(path)
            records.append(record)
            stats["parsed_reports"] += bool(record["facts"])
            stats["unusable_reports"] += not bool(record["facts"])
            stats["facts"] += len(record["facts"])
            continue
        html, source = C.report_html(item["symbol"], letter, False, 0)
        try:
            if html is None and args.fetch and stats["downloads_attempted"] < args.max_downloads:
                stats["downloads_attempted"] += 1
                html, source = C.report_html(item["symbol"], letter, True, args.delay)
            if html is None:
                stats["missing_html"] += 1
                continue
            record = {"company_id": item["company_id"], "symbol": item["symbol"],
                      "tracing_no": tracing, "title": letter["Title"],
                      "period_end": item["period"], "published_at": item["published_at"],
                      "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                      "sha256": hashlib.sha256(html.encode()).hexdigest(), "source": source,
                      "history_basis": stats["history_basis"], "facts": own_column(html, item["period"])}
            C.write(path, record)
            records.append(record)
            stats["parsed_reports"] += bool(record["facts"])
            stats["unusable_reports"] += not bool(record["facts"])
            stats["facts"] += len(record["facts"])
        except C.CollectionPaused as exc:
            stats["status"], stats["paused_reason"] = "paused", str(exc)
            break
        except Exception as exc:
            stats["errors"] += 1
            with (OUT / "errors.jsonl").open("a", encoding="utf8") as log:
                log.write(json.dumps({"symbol": item["symbol"], "tracing_no": tracing,
                                      "error": str(exc)}, ensure_ascii=False) + "\n")
        if len(records) % 100 == 0:
            C.write(OUT / "progress.json", stats)
    if stats["status"] == "running":
        stats["status"] = "batch_complete"
    stats["remaining_unprocessed"] = len(queue) - len(records)
    stats["companies_with_facts"] = len({r["company_id"] for r in records if r["facts"]})
    stats["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    C.write(OUT / "progress.json", stats)
    # Missing downloads still represent publicly known report versions. Their
    # metadata must invalidate older-profit fallback; absence is never zero.
    archived = {(r["company_id"], r["tracing_no"]) for r in records}
    for item in queue:
        tracing = str(item["letter"]["TracingNo"])
        if (item["company_id"], tracing) in archived:
            continue
        records.append({"company_id": item["company_id"], "symbol": item["symbol"],
                        "tracing_no": tracing, "title": item["letter"]["Title"],
                        "period_end": item["period"], "published_at": item["published_at"],
                        "observed_at": None, "source": "catalog_versions.json", "facts": [],
                        "history_basis": "catalog_metadata_only", "archive_status": "missing"})
    C.write(OUT / "reports.json", records)
    print(json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
