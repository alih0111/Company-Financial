"""Prepare point-in-time eligible Codal records for the locked V12.37 engines."""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "qvt_backtest"), str(ROOT / "provenance_v1"), str(ROOT / "go-app/py"), str(ROOT)]
import collect_financial_history as H
from qvt_backtest.evidence_paths import provenance_path
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))
OWNER_PACK = Path(os.environ.get("V1237_OWNER_PACK", str(ROOT / "ranking_research/output/owner_current_market_2026-10-15")))
OWNER_REG = json.loads((OWNER_PACK / "registration.json").read_text(encoding="utf-8"))
OWNER_INPUTS = Path(os.environ.get("V1237_OWNER_INPUTS", str(Path(OWNER_REG["financial_path"]).parent)))
BASE_REPORTS = OWNER_INPUTS / "input_reports.json"
BASE_LINEAGE = OWNER_INPUTS / "current_live_lineage.json"
EVENTS = ROOT / "fundamental_event_research/monthly_sales_events_universe_v1_1.parquet"

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_factor_destinations(output_dir: Path, dynamic_store_dir: Path | None, default_store: Path):
    """Resolve fresh run destinations and reject overwrite/shared custom stores."""
    out = output_dir.resolve()
    dynamic_store = (dynamic_store_dir or default_store).resolve()
    if dynamic_store_dir and not dynamic_store.is_relative_to(out):
        raise ValueError("dynamic_store_must_be_inside_factor_output_directory")
    if out.exists() and any(out.iterdir()):
        children = list(out.iterdir())
        only_fresh_raw_dir = (dynamic_store_dir is not None and len(children) == 1
                              and children[0].resolve() == dynamic_store and dynamic_store.is_dir())
        if not only_fresh_raw_dir:
            raise FileExistsError(f"factor_output_directory_not_empty:{out}")
    if dynamic_store.exists() and any(dynamic_store.iterdir()):
        raise FileExistsError(f"dynamic_store_directory_not_empty:{dynamic_store}")
    return out, dynamic_store


def validate_source_evidence(prepared: dict, by_id: dict, evidence_doc: dict, root: Path = ROOT) -> None:
    """Bind candidates to the exact manifest item, receipt, identity and parser replay."""
    evidence_rows = {(x["feed"], str(x["tracing_no"])): x for x in evidence_doc.get("reports", [])}
    for feed in ("financial", "sales"):
        for candidate in prepared.get(feed, []):
            key = (feed, str(candidate.get("tracing_no")))
            audit = evidence_rows.get(key); item = by_id.get(key[1], {})
            ev = item.get("body_evidence") or {}
            path = root / ev.get("path", "__missing__")
            if (not audit or audit.get("receipt_exactly_linked_to_source_manifest") is not True
                    or audit.get("payload_hash_matches") is not True
                    or audit.get("frozen_identity_match") is not True
                    or audit.get("body_path") != ev.get("path") or not path.is_file()):
                raise ValueError(f"source_evidence_audit_binding_failed:{feed}:{key[1]}")
            # The audit booleans are advisory only: reopen the exact source manifest
            # and compare the candidate against its report record and raw receipt.
            manifest_rel = audit.get("source_manifest_path")
            manifest_path = root / str(manifest_rel or "__missing__")
            if not manifest_path.is_file():
                raise ValueError(f"source_manifest_missing:{feed}:{key[1]}")
            manifest_bytes = manifest_path.read_bytes()
            if sha(manifest_bytes) != audit.get("source_manifest_sha256"):
                raise ValueError(f"source_manifest_hash_mismatch:{feed}:{key[1]}")
            manifest = json.loads(manifest_bytes)
            source_rows = manifest.get("feeds", {}).get(feed, {}).get("report_ids", [])
            source = next((x for x in source_rows if str(x.get("tracing_no")) == key[1]), None)
            if not source:
                raise ValueError(f"source_manifest_report_missing:{feed}:{key[1]}")
            source_ev = source.get("body_evidence") or {}
            def same_instant(a, b):
                try:
                    from datetime import datetime, timezone
                    aa = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
                    bb = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
                    if aa.tzinfo is None or bb.tzinfo is None:
                        return a == b
                    return aa.astimezone(timezone.utc) == bb.astimezone(timezone.utc)
                except (TypeError, ValueError):
                    return a == b
            checks = {
                "company_id": (candidate.get("company_id"), item.get("company_id"), audit.get("company_id"), source.get("company_id")),
                "symbol": (candidate.get("symbol"), item.get("symbol"), audit.get("symbol"), source.get("symbol")),
                "raw_path": (ev.get("path"), audit.get("body_path"), source_ev.get("path")),
            }
            for name, values in checks.items():
                if any(value != values[0] for value in values[1:]):
                    raise ValueError(f"source_candidate_{name}_mismatch:{feed}:{key[1]}")
            candidate_pub = candidate.get("published_at_utc", candidate.get("published_at"))
            if not all(same_instant(candidate_pub, x) for x in
                       (item.get("published_at"), audit.get("published_at"), source.get("published_at"))):
                raise ValueError(f"source_candidate_published_at_mismatch:{feed}:{key[1]}")
            if (audit.get("tracing_no") != key[1]
                    or audit.get("company_id") != source.get("company_id")
                    or audit.get("receipt_retrieved_at_utc") != source_ev.get("retrieved_at_utc")
                    or audit.get("declared_payload_sha256") != source_ev.get("sha256")):
                raise ValueError(f"source_receipt_identity_binding_failed:{feed}:{key[1]}")
            compressed = path.read_bytes()
            payload = gzip.decompress(compressed)
            if (sha(compressed) != audit.get("stored_compressed_sha256")
                    or sha(payload) != ev.get("sha256")
                    or sha(payload) != source_ev.get("sha256")
                    or sha(payload) != candidate.get("source_body_sha256")):
                raise ValueError(f"source_evidence_bytes_changed:{feed}:{key[1]}")
            if feed == "financial":
                pages = candidate.get("financial_pages", [])
                expected = {str(x) for x in json.loads(audit.get("required_sheet_ids") or "[]")}
                present = {str(x.get("sheet_id")) for x in pages}
                if expected and not expected.issubset(present):
                    raise ValueError(f"source_financial_pages_incomplete:{key[1]}")
                page_audit = {str(x.get("sheet_id")): x for x in audit.get("financial_pages", [])}
                for page in pages:
                    ref = page_audit.get(str(page.get("sheet_id")))
                    page_path = root / str(page.get("path", "__missing__"))
                    if (not ref or not page_path.is_file()
                            or page.get("path") != ref.get("path")
                            or page.get("retrieved_at_utc") != ref.get("retrieved_at_utc")):
                        raise ValueError(f"source_financial_page_receipt_missing:{key[1]}:{page.get('sheet_id')}")
                    raw_page = page_path.read_bytes()
                    try:
                        page_payload = gzip.decompress(raw_page) if page_path.suffix == ".gz" else raw_page
                    except (OSError, EOFError) as exc:
                        raise ValueError(f"source_financial_page_bytes_changed:{key[1]}:{page.get('sheet_id')}") from exc
                    if (sha(raw_page) != ref.get("stored_sha256")
                            or sha(page_payload) != ref.get("payload_sha256")
                            or page.get("sha256") != ref.get("payload_sha256")):
                        raise ValueError(f"source_financial_page_bytes_changed:{key[1]}:{page.get('sheet_id')}")
                import datetime as dt
                received_inputs = [dt.datetime.fromisoformat(str(ev.get("retrieved_at_utc")).replace("Z", "+00:00"))]
                received_inputs.extend(dt.datetime.fromisoformat(str(p.get("retrieved_at_utc")).replace("Z", "+00:00")) for p in pages)
                if any(x.tzinfo is None for x in received_inputs):
                    raise ValueError(f"source_financial_receipt_time_missing_timezone:{key[1]}")
                latest_received = max(x.astimezone(dt.timezone.utc) for x in received_inputs).isoformat()
                if candidate.get("received_at_utc") != latest_received:
                    raise ValueError(f"source_financial_latest_receipt_mismatch:{key[1]}")
                if expected:
                    # A deterministic replay binds admitted facts to all consumed page bytes.
                    import prepare_codal_inputs as P
                    from datetime import datetime, timezone
                    body_text = payload.decode("utf-8", "strict")
                    identity = {"company_id": item["company_id"], "symbol": item["symbol"]}
                    replay_item = dict(item); replay_item["financial_pages"] = pages
                    replay = P.parse_financial(body_text, replay_item, identity,
                                               candidate["received_at_utc"], sha(payload))
                    for field in ("facts", "period_end", "company_id", "symbol", "tracing_no", "published_at"):
                        if replay.get(field) != candidate.get(field):
                            raise ValueError(f"source_parser_replay_mismatch:{key[1]}:{field}")
            elif candidate.get("received_at_utc") != ev.get("retrieved_at_utc"):
                raise ValueError(f"source_candidate_received_at_utc_mismatch:{feed}:{key[1]}")

def main() -> int:
    import dynamic_financial as D
    from ranking_research.return_v2.events import cutoff
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--evaluation-date", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--dynamic-store-dir", type=Path,
                   help="Isolated destination for parser-owned raw bodies and manifests; must be inside --output-dir.")
    p.add_argument("--source-evidence-audit", type=Path,
                   help="Optional sealed local archive audit; binds every parsed candidate to its exact receipt and raw bytes.")
    p.add_argument("--sales-timing-calendar-manifest", "--session-calendar-manifest",
                   dest="sales_timing_calendar_manifest", type=Path,
                   help="Verified market-wide session evidence used only to assign monthly-sales signal_entry_date.")
    p.add_argument("--sales-timing-calendar-provider", default="nscstart",
                   choices=("nscstart", "public"),
                   help="Calendar profile the provided manifest came from; the public "
                        "profile is refused for sales PIT timing with its own reason.")
    a = p.parse_args()
    if a.sales_timing_calendar_provider == "public":
        raise SystemExit("SALES_PIT_TIMING_CAPABILITY_NOT_GRANTED_PUBLIC_PROFILE")
    src_path = a.manifest.resolve()
    src = json.loads(src_path.read_text(encoding="utf-8"))
    prepared_path = src_path.parent / "prepared/prepared-inputs.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8")) if prepared_path.exists() else {"financial": [], "sales": []}
    by_id = {str(item.get("tracing_no")): item for feed in src.get("feeds", {}).values() for item in feed.get("report_ids", [])}
    if a.source_evidence_audit:
        evidence_doc = json.loads(a.source_evidence_audit.resolve().read_text(encoding="utf-8"))
        validate_source_evidence(prepared, by_id, evidence_doc)
    cut = pd.Timestamp(cutoff(a.evaluation_date))
    out, dynamic_store = resolve_factor_destinations(
        a.output_dir, a.dynamic_store_dir, D.STORE / "automated" / str(src.get("run_id")))
    out.mkdir(parents=True, exist_ok=True)
    dynamic_store.mkdir(parents=True, exist_ok=True)
    D.STORE = dynamic_store

    reports = json.loads(BASE_REPORTS.read_text(encoding="utf-8"))
    lineage = json.loads(BASE_LINEAGE.read_text(encoding="utf-8"))
    used_ids = {(str(x.get("company_id")), str(x.get("tracing_no"))) for x in reports}
    financial_rows = []; financial_blocked = []
    for candidate in prepared.get("financial", []):
        report_id = str(candidate["tracing_no"]); item = by_id.get(report_id, {})
        pub = pd.Timestamp(candidate["published_at"]).tz_convert("UTC")
        received = pd.Timestamp(candidate["received_at_utc"]).tz_convert("UTC")
        reasons = []
        if pub > cut: reasons.append("published_after_locked_cutoff")
        if received > cut: reasons.append("received_after_locked_cutoff")
        if candidate.get("title_is_correction") and not candidate.get("supersedes_tracing_no"):
            reasons.append("correction_predecessor_unresolved")
        key = (str(candidate["company_id"]), report_id)
        if key in used_ids: reasons.append("report_already_in_frozen_archive")
        if reasons:
            financial_blocked.append({"tracing_no": report_id, "symbol": candidate["symbol"], "reasons": reasons})
            continue
        body = gzip.decompress((ROOT / item["body_evidence"]["path"]).read_bytes())
        if sha(body) != candidate["source_body_sha256"]:
            financial_blocked.append({"tracing_no": report_id, "symbol": candidate["symbol"], "reasons": ["raw_body_hash_changed"]})
            continue
        # Preserve every parser input in the admitted record's own STORE.  The
        # upstream capture directory is evidence, not a replay dependency.
        raw_dir = dynamic_store
        main_path = raw_dir / f"financial-{report_id}-main.html"
        pages = [{"role": "financial", "page_id": "main", "source": candidate.get("report_url"),
                  "path": str(main_path.resolve()), "sha256": sha(body),
                  "received_at_utc": (item.get("body_evidence") or {}).get("retrieved_at_utc")}]
        main_path.write_bytes(body)
        for page in candidate.get("financial_pages", []):
            sheet_id = str(page["sheet_id"])
            compressed = (ROOT / page["path"]).read_bytes()
            if sha(compressed) != page.get("stored_compressed_sha256"):
                raise ValueError(f"financial_page_compressed_hash_mismatch:{report_id}:{sheet_id}")
            payload = gzip.decompress(compressed)
            if sha(payload) != page.get("payload_sha256"):
                raise ValueError(f"financial_page_payload_hash_mismatch:{report_id}:{sheet_id}")
            page_path = raw_dir / f"financial-{report_id}-sheet-{sheet_id}.html"
            page_path.write_bytes(payload)
            pages.append({"role": "financial", "page_id": f"sheet:{sheet_id}", "sheet_id": sheet_id,
                          "source": page.get("final_url") or page.get("url"), "path": str(page_path.resolve()),
                          "sha256": sha(payload), "stored_compressed_sha256": page.get("stored_compressed_sha256"),
                          "received_at_utc": page.get("retrieved_at_utc"), "http_status": page.get("http_status"),
                          "redirect_chain": page.get("redirect_chain", [])})
        dyn_manifest = {"tracing_no": report_id, "company_id": candidate["company_id"],
                        "parser_version": D.VERSION, "pages": pages,
                        "required_page_ids": [p["page_id"] for p in pages],
                        "received_at_utc": candidate.get("received_at_utc"),
                        "available_at_utc": max([str(p.get("received_at_utc")) for p in pages if p.get("received_at_utc")], default=candidate.get("received_at_utc"))}
        dyn_path = raw_dir / f"financial-{report_id}.manifest.json"
        dyn_bytes = json.dumps(dyn_manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        dyn_path.write_bytes(dyn_bytes)
        record = {k: candidate[k] for k in ("company_id", "symbol", "tracing_no", "title", "period_end", "published_at", "observed_at", "facts")}
        record.update({"parser_version": D.VERSION, "sha256": sha(body), "financial_pages": pages,
                       "available_at_utc": dyn_manifest["available_at_utc"],
                       "dynamic_manifest_path": str(dyn_path.resolve()), "dynamic_manifest_sha256": sha(dyn_bytes),
                       "source": "codal_incremental_verified", "supersedes_tracing_no": candidate.get("supersedes_tracing_no")})
        reports.append(record); used_ids.add(key); financial_rows.append(record)
        lineage.append({"company_id": record["company_id"], "period": record["period_end"],
                        "published_at": record["published_at"], "observed_at": record["observed_at"],
                        "tracing_no": report_id, "source": "codal_incremental_verified"})

    events = pd.read_parquet(EVENTS)
    sales_timing_manifest = None
    sessions = []
    if a.sales_timing_calendar_manifest:
        sales_timing_manifest = json.loads(a.sales_timing_calendar_manifest.resolve().read_text(encoding="utf-8"))
        raw_path = ROOT / sales_timing_manifest["raw_path"]
        raw = gzip.decompress(raw_path.read_bytes())
        doc = json.loads(raw)
        if (sales_timing_manifest.get("source") != "TSETMC documented API MarketInfo/NSCStart"
                or sha(raw) != sales_timing_manifest.get("raw_sha256")
                or not isinstance(doc.get("Data"), list)):
            raise ValueError("official_sales_timing_calendar_source_or_hash_invalid")
        sessions = sorted({str(x.get("DEven")) for x in doc["Data"]
                           if x.get("NSCEnd") == "1" and len(str(x.get("DEven", ""))) == 8})
    sales_rows = []; sales_blocked = []
    for candidate in prepared.get("sales", []):
        report_id = str(candidate["tracing_no"])
        pub_utc = pd.Timestamp(candidate["published_at_utc"])
        received_utc = pd.Timestamp(candidate["received_at_utc"])
        reasons = []
        if pub_utc > cut: reasons.append("published_after_locked_cutoff")
        if received_utc > cut: reasons.append("received_after_locked_cutoff")
        if candidate.get("is_correction") and not candidate.get("supersedes_tracing_no"):
            reasons.append("correction_predecessor_unresolved")
        already = events.event_id.astype(str).eq(report_id).any()
        if already: reasons.append("report_already_in_frozen_event_archive")
        local_pub_day = pub_utc.tz_convert("Asia/Tehran").strftime("%Y%m%d")
        next_sessions = [d for d in sessions if d > local_pub_day]
        if not next_sessions: reasons.append("no_verified_next_session_in_calendar_window")
        if reasons:
            sales_blocked.append({"tracing_no": report_id, "symbol": candidate["symbol"], "reasons": reasons})
            continue
        next_date = dt.datetime.strptime(next_sessions[0], "%Y%m%d").date().isoformat()
        period = pd.Timestamp(candidate["period_end"]).date()
        row = {c: None for c in events.columns}
        row.update({"event_id": report_id, "publication_role": "correction" if candidate["is_correction"] else "original",
            "is_correction": bool(candidate["is_correction"]), "supersedes_event_id": candidate.get("supersedes_tracing_no"),
            "original_event_id": candidate.get("supersedes_tracing_no"), "security_id": None,
            "symbol": candidate["symbol"], "company_id": candidate["company_id"], "event_type": "monthly_sales_report",
            "period_end": period, "match_status": "MATCH_STRONG_AUTOMATED_UNIT_AND_BODY_VALIDATED",
            "CURRENT_PERIOD_SALES": float(candidate["sales_current_rial"]), "current_value_version_known": True,
            "current_period_has_correction": bool(candidate["is_correction"]),
            "published_at_raw_jalali": candidate["publish_time_raw_jalali"],
            "published_at_tehran": pub_utc.tz_convert("Asia/Tehran").tz_localize(None), "published_at": pub_utc,
            "tehran_date": pub_utc.tz_convert("Asia/Tehran").date(), "signal_entry_date": next_date,
            "letter_title": next((x.get("title") for x in by_id.values() if str(x.get("tracing_no")) == report_id), ""),
            "source_url": candidate.get("report_url"), "source": "codal_incremental_verified",
            "ineligibility_reason": "", "event_eligible": True})
        events = pd.concat([events, pd.DataFrame([row])], ignore_index=True)
        sales_rows.append({"tracing_no": report_id, "company_id": candidate["company_id"], "symbol": candidate["symbol"],
                           "period_end": str(period), "sales_current_rial": candidate["sales_current_rial"],
                           "reported_unit": candidate["reported_unit"], "published_at_utc": str(pub_utc),
                           "received_at_utc": str(received_utc), "signal_entry_date": next_date,
                           "source_body_sha256": candidate["source_body_sha256"], "supersedes_tracing_no": candidate.get("supersedes_tracing_no")})

    reports_path = out / "input_reports.json"; lineage_path = out / "current_live_lineage.json"; events_path = out / "monthly_sales_events.parquet"
    comparative_path = out / "comparative_lineage.json"
    comparisons = json.loads((OWNER_INPUTS / "comparative_lineage.json").read_text(encoding="utf-8"))
    for rec in financial_rows:
        parsed_all = D.verified_parsed(rec)
        page_meta = {str(p.get("page_id")): p for p in json.loads(Path(rec["dynamic_manifest_path"]).read_text(encoding="utf-8"))["pages"]}
        for page_id, page in page_meta.items():
            parsed_page = D.parsed_page(Path(page["path"]).read_text(encoding="utf-8"), rec)
            for statement, bucket in parsed_page["statements"].items():
                headers = parsed_page["period_headers"][statement]
                for metric, orders in bucket.items():
                    for order, raw_value in orders.items():
                        if int(order) == 1:
                            continue
                        jalali = headers[int(order) - 1]
                        period = H.F.jalali_to_gregorian(*jalali).isoformat()
                        unit = "rial_per_share" if metric in H.P.PER_SHARE else "rial"
                        value = float(raw_value) if unit == "rial_per_share" else float(raw_value) * 1_000_000
                        comparisons.append({"company_id": rec["company_id"], "tracing_no": rec["tracing_no"],
                            "period": rec["period_end"], "statement_type": statement, "metric_code": metric,
                            "period_order": int(order), "canonical_value": value, "canonical_unit": unit,
                            "comparative_period": period, "basis": "parent", "source_page_id": page_id,
                            "source_page_path": page["path"], "source_page_sha256": page["sha256"],
                            "source_url": page.get("source"),
                            "source_page_received_at_utc": page.get("received_at_utc"),
                            "available_at_utc": rec.get("available_at_utc"),
                            "published_at": rec["published_at"], "company_id_verified": rec["company_id"],
                            "header_jalali": list(jalali), "parser_version": D.VERSION})
        # Ensure the combined manifest actually supplies the admitted own facts.
        if len(D.own_facts(parsed_all)) != len(rec["facts"]):
            raise ValueError(f"dynamic_store_fact_count_mismatch:{rec['tracing_no']}")

    # Quick Sync writes authoritative values to canonical PostgreSQL.  Merge
    # those already-collected rows before the unchanged ranking engine runs;
    # this is a local database read and never triggers another Codal crawl.
    from canonical_ranking_inputs import merge_canonical_inputs
    canonical = merge_canonical_inputs(reports, lineage, comparisons, events, cut, a.evaluation_date)
    events = canonical.pop("events")
    financial_ids_path = out / "fresh-financial-ids.json"
    reports_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lineage_path.write_text(json.dumps(lineage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparative_path.write_text(json.dumps(comparisons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    events.to_parquet(events_path, index=False, compression="zstd")
    financial_ids = {str(r["company_id"]) for r in financial_rows} | set(canonical["financial_ids"])
    financial_ids_path.write_text(json.dumps(sorted(financial_ids), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    canonical_financial = canonical["financial_inputs"]
    canonical_sales = canonical["sales_inputs"]
    summary = {"state": "prepared" if not prepared.get("errors") else "prepared_with_extraction_errors",
        "evaluation_date": a.evaluation_date, "locked_publication_cutoff_utc": cut.isoformat(),
        "financial": {"parsed_candidates": len(prepared.get("financial", [])), "admitted": len(financial_rows) + len(canonical_financial), "held": len(financial_blocked), "admission_errors": financial_blocked,
                      "admitted_inputs": [{"tracing_no": r["tracing_no"], "company_id": r["company_id"], "symbol": r["symbol"],
                        "period_end": r["period_end"], "published_at": r["published_at"], "received_at": r["observed_at"],
                        "source_body_sha256": r["sha256"], "supersedes_tracing_no": r.get("supersedes_tracing_no")} for r in financial_rows] + canonical_financial},
        "sales": {"parsed_candidates": len(prepared.get("sales", [])), "admitted": len(sales_rows) + len(canonical_sales), "held": len(sales_blocked), "admission_errors": sales_blocked,
                  "sales_timing_calendar_manifest": str(a.sales_timing_calendar_manifest) if a.sales_timing_calendar_manifest else None,
                  "timing_calendar_purpose": "assign the locked monthly-sales factor's first eligible signal_entry_date after publication; independent of order-fill review and O00 global-index validation",
                  "timing_calendar_state": "verified_market_wide_sessions" if sales_timing_manifest else "missing_verified_market_wide_sessions",
                  "timing_calendar_provider": a.sales_timing_calendar_provider,
                  "public_profile_sales_capability_note": ("the public-paper-v1 calendar is not used for sales PIT timing; capability separation is explicit, and refusal is reported with its own reason, not a missing token") if a.sales_timing_calendar_provider == "public" else None,
                  "order_review_state_is_not_a_factor_input": True, "o00_global_calendar_is_not_a_factor_input": True,
                  "admitted_inputs": sales_rows + canonical_sales},
        "canonical_quick_sync": canonical,
        "files": {"reports": provenance_path(reports_path, ROOT),
                  "lineage": provenance_path(lineage_path, ROOT),
                  "sales_events": provenance_path(events_path, ROOT),
                  "fresh_financial_ids": provenance_path(financial_ids_path, ROOT),
                  "comparatives": provenance_path(comparative_path, ROOT)},
        "receipt_time_backdated": False, "frozen_sources_modified": False,
        "contract_id": "future-evaluation-v12.28-p1-p3-o00-g0"}
    out_summary = out / "admission.json"
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"admission": provenance_path(out_summary, ROOT),
        "financial_parsed": len(prepared.get("financial", [])), "financial_admitted": len(financial_rows) + len(canonical_financial),
        "sales_parsed": len(prepared.get("sales", [])), "sales_admitted": len(sales_rows) + len(canonical_sales),
        "financial_held": len(financial_blocked), "sales_held": len(sales_blocked)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
