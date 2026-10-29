"""Offline, isolated diagnostic for a pinned ranking snapshot."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / "ranking_research/future_eval_v12_30/validate_latest_ranking.py"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "artifact_sha256"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    return str(value)


def parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def temporal_receipt_status(received_at: str | None, decision_at: str | None) -> str:
    if not received_at:
        return "UNKNOWN_NO_RECEIPT"
    received = parse_aware(received_at)
    if received is None:
        return "INVALID_OR_TIMEZONE_MISSING"
    if decision_at is None:
        return "NOT_CHECKED_NO_DECISION_TIME"
    decision = parse_aware(decision_at)
    if decision is None:
        return "DECISION_TIME_INVALID_OR_TIMEZONE_MISSING"
    return "AFTER_DECISION" if received > decision else "BEFORE_OR_AT_DECISION"


def temporal_evidence(received_at: Any, source: str, observed_at: datetime,
                      decision_at: str | None = None) -> dict[str, Any]:
    receipt = parse_aware(received_at)
    source_valid = bool(receipt and source in {"market_package_manifest_hash_bound", "source_receipt_hash_bound"}
                        and receipt <= observed_at)
    observed_cmp = ("RECEIPT_AFTER_OBSERVATION" if receipt > observed_at else "RECEIPT_BEFORE_OR_AT_OBSERVATION") if source_valid else "NOT_VERIFIED"
    decision_cmp = temporal_receipt_status(received_at if source_valid else None, decision_at)
    return {"value": received_at, "claimed_source": source, "timestamp_syntax_and_timezone_valid": receipt is not None,
            "source_provenance_valid": source_valid, "relative_to_observation": observed_cmp,
            "relative_to_hypothetical_decision": decision_cmp}


def publication_time(value: Any) -> datetime | None:
    if isinstance(value, str) and len(value) == 10:
        try:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return parse_aware(value)


def cutoff_comparison(left: Any, right: Any) -> dict[str, Any]:
    a, b = publication_time(left), publication_time(right)
    if a is None or b is None:
        return {"timezone_aware_values_valid": False, "same_instant": False, "same_tehran_boundary_within_1us": False, "difference_microseconds": None}
    delta_us = abs((a.astimezone(timezone.utc) - b.astimezone(timezone.utc)) // timedelta(microseconds=1))
    tehran = timezone(timedelta(hours=3, minutes=30))
    a_local, b_local = a.astimezone(tehran), b.astimezone(tehran)
    same_day = a_local.date() == b_local.date()
    day_step = abs((a_local.date() - b_local.date()).days) == 1
    end_of_day = (a_local.hour, a_local.minute, a_local.second, a_local.microsecond) == (23, 59, 59, 999999)
    start_of_day = (b_local.hour, b_local.minute, b_local.second, b_local.microsecond) == (0, 0, 0, 0)
    reverse_end = (b_local.hour, b_local.minute, b_local.second, b_local.microsecond) == (23, 59, 59, 999999)
    reverse_start = (a_local.hour, a_local.minute, a_local.second, a_local.microsecond) == (0, 0, 0, 0)
    boundary_adjacent = day_step and ((end_of_day and start_of_day) or (reverse_end and reverse_start))
    # Selection comparisons use the same instant unless a separately sourced
    # contract explicitly defines another operator.
    exact_inclusive_exclusive_boundary = False
    return {"timezone_aware_values_valid": True, "same_instant": delta_us == 0,
            "same_tehran_boundary_within_1us": delta_us == 0,
            "display_boundary_difference": bool(boundary_adjacent and delta_us == 1),
            "exact_inclusive_exclusive_boundary_equivalent": False,
            "difference_microseconds": delta_us}


def panel_provenance(panel_path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd
    import json as _json
    frame = pd.read_parquet(panel_path)
    summary: dict[str, Any] = {"path": str(panel_path), "sha256": sha256(panel_path), "rows": len(frame)}
    for column in ("price_date", "financial_period_end", "financial_latest_published_at", "financial_factor_period_end"):
        if column in frame:
            vals = frame[column].dropna().astype(str)
            if column == "financial_latest_published_at":
                parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
                valid = parsed.dropna()
                max_idx = valid.idxmax() if len(valid) else None
                summary[column] = {"nonnull": int(len(valid)), "min": valid.min().isoformat() if len(valid) else None,
                    "max": valid.max().isoformat() if len(valid) else None,
                    "max_original": str(frame.loc[max_idx, column]) if max_idx is not None else None,
                    "unique": int(valid.nunique()), "comparison_timezone": "UTC"}
            else:
                summary[column] = {"nonnull": int(len(vals)), "min": vals.min() if len(vals) else None,
                                   "max": vals.max() if len(vals) else None, "unique": int(vals.nunique())}
    summary["panel_sha256"] = sha256(panel_path)
    for column in ("received_at", "price_age_days", "financial_age_days", "price_valid_sessions_30d"):
        if column in frame:
            series = frame[column]
            summary[column] = {"nonnull": int(series.notna().sum()), "null": int(series.isna().sum()),
                               "distribution": {str(k): int(v) for k, v in series.value_counts(dropna=False).sort_index().items()}}
    extraction = panel_path.parent / "extraction_manifest.json"
    if extraction.is_file():
        manifest = json.loads(extraction.read_text(encoding="utf-8-sig"))
        market = manifest.get("market_package", {})
        summary["extraction_manifest"] = {"path": str(extraction), "sha256": sha256(extraction),
            **{k: manifest.get(k) for k in ("dataset_id", "evaluation_date", "publication_cutoff_at", "received_at", "receipt_limitation", "source_reuse_note", "official_ledger_written", "network_requests", "panel_sha256", "official_tsetmc_source_manifest_sha256", "source_dates", "financial")},
            "market_package": {"path": market.get("path"), "registration_sha256": market.get("registration_sha256"),
                "shares_source_path": market.get("shares_source_path"), "audit": market.get("audit"),
                "volume_audit": market.get("volume_audit")}}
        source_dates = manifest.get("source_dates", {})
        financial_info = manifest.get("financial", {})
        archive_path = ROOT / str(financial_info.get("reports_path", panel_path.parent / "input_reports.json"))
        archive_check = {"available": archive_path.is_file(), "sha256": sha256(archive_path) if archive_path.is_file() else None}
        declared_archive_sha = (manifest.get("source_sha256") or {}).get(str(financial_info.get("reports_path", "")))
        archive_check["declared_sha256"] = declared_archive_sha
        archive_check["sha256_matches_declaration"] = bool(archive_check["sha256"] and declared_archive_sha == archive_check["sha256"])
        archive_max = None
        if archive_path.is_file():
            archive_doc = json.loads(archive_path.read_text(encoding="utf-8-sig"))
            reports = archive_doc.get("reports", archive_doc) if isinstance(archive_doc, dict) else archive_doc
            dates = [publication_time(x.get("published_at")) for x in reports if isinstance(x, dict) and x.get("published_at")]
            dates = [x for x in dates if x]
            archive_max = max(dates).astimezone(timezone.utc).isoformat() if dates else None
        source_latest = publication_time(source_dates.get("financial_latest_published_at"))
        archive_consistent = bool(archive_path.is_file() and archive_check["sha256_matches_declaration"] and archive_max and source_latest and archive_max == source_latest.astimezone(timezone.utc).isoformat())
        selected_latest = publication_time(summary.get("financial_latest_published_at", {}).get("max"))
        cutoff = publication_time(manifest.get("publication_cutoff_at"))
        cutoff_match = cutoff_comparison(manifest.get("publication_cutoff_at"), snapshot.get("publication_cutoff_at"))
        # The financial selector rejects published_at >= cutoff; report the
        # same half-open boundary here so equality is out of scope.
        selected_within_cutoff = bool(selected_latest and cutoff and selected_latest < cutoff)
        comparisons = {
            "dataset_id_matches": manifest.get("dataset_id") == (snapshot.get("source") or {}).get("dataset_id"),
            "evaluation_date_matches": manifest.get("evaluation_date") == snapshot.get("evaluation_date"),
            "publication_cutoff_matches": cutoff_match["same_instant"],
            "publication_cutoff_same_instant": cutoff_match["same_instant"],
            "publication_cutoff_comparison": cutoff_match,
            "price_latest_matches_panel": source_dates.get("evaluation_price_latest") == summary.get("price_date", {}).get("max"),
            "archive_financial_stat_matches_file_and_hash": archive_consistent,
            "selected_panel_financial_latest_within_cutoff": selected_within_cutoff,
            "manifest_panel_hash_matches": manifest.get("panel_sha256") == summary["panel_sha256"],
        }
        summary["extraction_manifest"]["consistency_checks"] = comparisons
        summary["financial_date_scopes"] = {"source_dates_financial_latest_published_at_scope": "all input_reports archive", "archive_actual_max_utc": archive_max,
            "archive_path": str(archive_path), "archive_sha256": archive_check["sha256"], "selected_panel_max": summary.get("financial_latest_published_at", {}).get("max"),
            "selected_panel_cutoff": manifest.get("publication_cutoff_at"), "selected_panel_within_cutoff": selected_within_cutoff,
            "selected_panel_lineage_status": "TRACE_FROM_PANEL_ROW_REQUIRED; see top_p1_source_lineage"}
        if "financial_latest_published_at" in frame:
            parsed = pd.to_datetime(frame["financial_latest_published_at"], errors="coerce", utc=True)
            max_idx = parsed.idxmax() if parsed.notna().any() else None
            if max_idx is not None:
                max_row = frame.loc[max_idx]
                def decode_lineage(value: Any) -> Any:
                    try:
                        return _json.loads(value) if isinstance(value, str) else value
                    except (TypeError, ValueError):
                        return value
                summary["selected_financial_max_row"] = {
                    "symbol": str(max_row.get("symbol")), "company_id": str(max_row.get("company_id")),
                    "financial_latest_published_at_original": str(max_row.get("financial_latest_published_at")),
                    "financial_latest_published_at_utc": parsed.loc[max_idx].isoformat(),
                    "financial_period_end": str(max_row.get("financial_period_end")),
                    "financial_lineage": decode_lineage(max_row.get("financial_lineage")),
                    "financial_factor_lineage": decode_lineage(max_row.get("financial_factor_lineage")),
                    "interpretation": "Selected-row lineage only; each report body and receipt require independent source/hash verification."}
        leaders = snapshot.get("top_candidates", {}).get("P1", [])
        if leaders:
            row = frame.loc[frame.company_id.astype(str).eq(str(leaders[0].get("company_id")))]
            if len(row) == 1:
                r = row.iloc[0]
                traces = {}
                for col in ("financial_factor_lineage", "financial_lineage", "sales_lineage", "valuation_provenance"):
                    if col not in frame.columns:
                        continue
                    raw = r.get(col)
                    try:
                        val = _json.loads(raw) if isinstance(raw, str) else raw
                    except (TypeError, ValueError):
                        val = raw
                    if col == "financial_factor_lineage" and isinstance(val, list):
                        traces[col] = [{k: item.get(k) for k in ("tracing_no", "period_end", "published_at", "observed_at", "received_at", "sha256", "source", "document_type")} for item in val[:8]]
                    elif col == "financial_lineage" and isinstance(val, list):
                        received = sorted(str(x.get("received_at")) for x in val if x.get("received_at"))
                        published = sorted(str(x.get("published_at")) for x in val if x.get("published_at"))
                        traces[col] = {"report_count": len(val), "received_count": len(received), "received_at_min": received[0] if received else None, "received_at_max": received[-1] if received else None, "received_at_alias_warning": "extractor maps observed_at to received_at; not accepted as source receipt" if received else None, "published_at_min": published[0] if published else None, "published_at_max": published[-1] if published else None}
                    elif col == "sales_lineage" and isinstance(val, dict):
                        versions = val.get("selected_month_versions", [])
                        known = sorted(str(x.get("known_from")) for x in versions if x.get("known_from"))
                        traces[col] = {"selected_month_versions": len(versions), "known_from_min": known[0] if known else None, "known_from_max": known[-1] if known else None, "published_at_recorded_count": sum(bool(x.get("published_at") not in (None, "None")) for x in versions), "received_at_recorded_count": sum(bool(x.get("received_at")) for x in versions)}
                    else:
                        traces[col] = val
                summary["top_p1_source_lineage"] = {k: r.get(k) for k in ("financial_period_end", "financial_latest_published_at", "financial_factor_period_end", "financial_age_days", "price_date", "price_age_days", "price_valid_sessions_30d") if k in frame.columns} | traces
    return summary


def inspect_snapshot(snapshot: Path, manifest_path: Path | None = None, observed_at: datetime | None = None) -> dict[str, Any]:
    raw = snapshot.read_bytes()
    doc = json.loads(raw.decode("utf-8-sig"))
    embedded = doc.get("artifact_sha256")
    calculated = canonical_sha(doc)
    rows = doc.get("rows", [])
    company_ids = [str(r.get("company_id")) for r in rows]
    symbols = [str(r.get("symbol")) for r in rows]
    p1_top = [r for r in rows if r.get("methods", {}).get("P1", {}).get("rank") == 1]
    p3_top = [r for r in rows if r.get("methods", {}).get("P3", {}).get("rank") == 1]
    scoreability = {}
    for method in ("P1", "P3"):
        reasons: dict[str, int] = {}
        for row in rows:
            detail = row.get("methods", {}).get(method, {})
            if detail.get("rank") is None:
                reason = detail.get("scoreability_reason") or detail.get("quality") or "REASON_NOT_RECORDED"
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
        scoreability[method] = reasons
    observed_at = observed_at or datetime.now(timezone.utc)
    mdata = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path and manifest_path.is_file() else None
    manifest_matches = bool(mdata and mdata.get("json_sha256") == hashlib.sha256(raw).hexdigest()
                            and mdata.get("artifact_sha256") == embedded
                            and mdata.get("contract_sha256") == doc.get("contract_sha256"))
    return {
        "snapshot_path": str(snapshot.resolve()), "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_artifact_sha256": embedded, "canonical_hash_matches": embedded == calculated,
        "contract_sha256": doc.get("contract_sha256"), "source": doc.get("source"),
        "artifact_id": doc.get("artifact_id"), "status": doc.get("status"),
        "computed_at_utc": doc.get("computed_at_utc"), "evaluation_date": doc.get("evaluation_date"),
        "publication_cutoff_at": doc.get("publication_cutoff_at"), "received_at": doc.get("received_at"),
        "received_at_status": doc.get("received_at_status"), "counts": {
            "rows": len(rows), "unique_symbols": len(set(symbols)), "unique_company_ids": len(set(company_ids)),
            "scored": doc.get("scored_count"), "unscored": doc.get("unscored_count")},
        "unscored_reason_counts": scoreability,
        "top_candidates": {"P1": [{k: r.get(k) for k in ("symbol", "company_id", "identity_status", "price_effective_date", "publication_cutoff_at", "received_at")} | {"rank": r["methods"]["P1"].get("rank"), "score": r["methods"]["P1"].get("score"), "coverage": r["methods"]["P1"].get("financial_factor_coverage")} for r in p1_top],
                           "P3": [{"symbol": r.get("symbol"), "company_id": r.get("company_id"), "rank": r["methods"]["P3"].get("rank"), "score": r["methods"]["P3"].get("score")} for r in p3_top]},
        "manifest": {"path": str(manifest_path.resolve()) if manifest_path else None, "present": bool(mdata), "matches_snapshot": manifest_matches,
                     "recorded_artifact_sha256": mdata.get("artifact_sha256") if mdata else None,
                     "recorded_json_sha256": mdata.get("json_sha256") if mdata else None},
        "observed_at_utc": observed_at.isoformat(),
    }


def assess(snapshot: Path, output_dir: Path, manifest_path: Path | None = None, panel: Path | None = None,
           *, decision_at: str | None = None, _observed_at: datetime | None = None) -> dict[str, Any]:
    snapshot = snapshot.resolve()
    output_dir = output_dir.resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(f"SNAPSHOT_NOT_FOUND: {snapshot}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"OUTPUT_DIR_NOT_EMPTY: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    observed = inspect_snapshot(snapshot, manifest_path, _observed_at)
    copied = output_dir / "latest-ranking.json"
    shutil.copyfile(snapshot, copied)
    sealed_at = datetime.now(timezone.utc).isoformat()
    sealed = {"schema_version": 1, "observed_at_utc": sealed_at, "path_at_observation": str(snapshot),
              "copied_path": str(copied), "sha256": sha256(copied),
              "meaning": "ثبت وجود همین bytes در observed_at_utc؛ این زمان، received_at منبع یا دریافت در evaluation_date نیست."}
    (output_dir / "observed-manifest.json").write_text(json.dumps(sealed, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    source = observed.get("source") or {}
    selected_panel = panel.resolve() if panel else (ROOT / str(source.get("path", ""))).resolve()
    validator_result: dict[str, Any] = {"status": "NOT_RUN", "exit_code": None, "stdout": "", "stderr": ""}
    if observed["canonical_hash_matches"] and selected_panel.is_file():
        cmd = [sys.executable, "-X", "utf8", str(VALIDATOR), "--artifact-dir", str(output_dir), "--panel", str(selected_panel), "--dataset-id", str(source.get("dataset_id", ""))]
        cp = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
        validator_result = {"status": "PASS" if cp.returncode == 0 else "FAIL", "exit_code": cp.returncode,
                            "command": cmd, "stdout": cp.stdout.strip(), "stderr": cp.stderr.strip(),
                            "validation_path": str(output_dir / "validation.json") if (output_dir / "validation.json").exists() else None}
    elif not selected_panel.is_file():
        validator_result["reason"] = "SOURCE_PANEL_UNAVAILABLE_FOR_VALIDATOR"
    validation_ok = validator_result["status"] == "PASS"
    identity_cardinality_ok = observed["counts"]["rows"] == 254 and observed["counts"]["unique_symbols"] == 254 and observed["counts"]["unique_company_ids"] == 254
    universe_path = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv"
    identity_match = False
    identity_detail = {"status": "NOT_VERIFIED", "universe_path": str(universe_path), "reason": "validator_not_passed_or_universe_missing"}
    if validation_ok and universe_path.is_file():
        import pandas as pd
        universe = pd.read_csv(universe_path, dtype={"symbol": str, "company_id": str})
        expected = {(str(row.company_id), str(row.symbol)) for row in universe.itertuples()}
        actual = {(str(row.get("company_id")), str(row.get("symbol"))) for row in json.loads(snapshot.read_text(encoding="utf-8-sig")).get("rows", [])}
        identity_match = len(expected) == 254 and actual == expected
        identity_detail = {"status": "PASS" if identity_match else "FAIL", "universe_path": str(universe_path), "expected_count": len(expected), "actual_count": len(actual), "missing_count": len(expected - actual), "unexpected_count": len(actual - expected)}
    identity_ok = identity_cardinality_ok and identity_match
    top_ok = len(observed["top_candidates"]["P1"]) == 1 and len(observed["top_candidates"]["P3"]) == 1
    lineage_ok = bool(observed["manifest"]["matches_snapshot"] and observed.get("source", {}).get("sha256") and observed.get("contract_sha256"))
    calculation_valid = bool(observed["canonical_hash_matches"] and identity_ok and top_ok and validation_ok)
    panel_summary = panel_provenance(selected_panel, observed) if selected_panel.is_file() else {"status": "UNAVAILABLE"}
    panel_hash_matches = bool(selected_panel.is_file() and observed.get("source", {}).get("sha256") == sha256(selected_panel))
    extraction = panel_summary.get("extraction_manifest", {})
    receipt_cov = panel_summary.get("received_at", {})
    checks = extraction.get("consistency_checks", {})
    extraction_consistent = bool(checks and checks.get("dataset_id_matches") and checks.get("evaluation_date_matches") and checks.get("publication_cutoff_matches") and checks.get("manifest_panel_hash_matches") and checks.get("archive_financial_stat_matches_file_and_hash") and checks.get("selected_panel_financial_latest_within_cutoff") and checks.get("price_latest_matches_panel"))
    lineage_ok = bool(lineage_ok and panel_hash_matches and extraction_consistent)
    extraction_manifest = extraction.get("path")
    receipt_rows = []
    if selected_panel.is_file():
        for _, r in __import__("pandas").read_parquet(selected_panel).iterrows():
            raw_lineage = r.get("financial_lineage")
            try: items = json.loads(raw_lineage) if isinstance(raw_lineage, str) else raw_lineage
            except (TypeError, ValueError): items = []
            if isinstance(items, list):
                for item in items:
                    claimed = item.get("received_at")
                    source_kind = "unverified_lineage_field; extractor observed_at-to-received_at alias cannot be ruled out" if claimed else "unknown"
                    receipt_rows.append(temporal_evidence(claimed, source_kind, datetime.fromisoformat(observed["observed_at_utc"]), decision_at))
    receipt_status = "SOURCE_RECEIPT_NOT_VERIFIED" if not any(x["source_provenance_valid"] for x in receipt_rows) else "RECORDED_REQUIRES_SOURCE_AUDIT"
    panel_manifest = json.loads(Path(extraction_manifest).read_text(encoding="utf-8-sig")) if extraction_manifest and Path(extraction_manifest).is_file() else {}
    market_manifest_ref = panel_manifest.get("market_package", {}).get("path")
    market_manifest_path = (ROOT / str(market_manifest_ref) / "manifest.json") if market_manifest_ref else None
    market_evidence = {"status": "UNKNOWN", "manifest_path": market_manifest_path, "manifest_sha256": sha256(Path(market_manifest_path)) if market_manifest_path and Path(market_manifest_path).is_file() else None}
    market_dir = Path(market_manifest_path).parent if market_manifest_path else None
    registration_path = market_dir / "registration.json" if market_dir else None
    registration = json.loads(registration_path.read_text(encoding="utf-8-sig")) if registration_path and registration_path.is_file() else {}
    registration_hash = sha256(registration_path) if registration_path and registration_path.is_file() else None
    declared_registration = panel_manifest.get("market_package", {}).get("registration_sha256")
    registration_hash_match = bool(registration_hash and declared_registration == registration_hash)
    declared_market_manifest = panel_manifest.get("official_tsetmc_source_manifest_sha256")
    market_manifest_hash_match = bool(market_evidence["manifest_sha256"] and declared_market_manifest
                                      and market_evidence["manifest_sha256"] == declared_market_manifest)
    declaration_present = bool(declared_registration and declared_market_manifest)
    raw_checks = []
    market_doc = {}
    if market_manifest_path and Path(market_manifest_path).is_file():
        try:
            market_doc = json.loads(Path(market_manifest_path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            market_doc = {}
    if market_doc and isinstance(market_doc.get("records"), list):
        for record in market_doc["records"]:
            for source_name, source in (record.get("sources") or {}).items():
                rel, expected = source.get("raw_path"), source.get("raw_sha256")
                if not rel or not expected:
                    raw_checks.append({"source": source_name, "status": "NOT_VERIFIED_MISSING_RAW_DECLARATION"})
                    continue
                raw_path = (ROOT / rel).resolve()
                stored_sha = sha256(raw_path) if raw_path.is_file() else None
                payload_sha = stored_sha
                decode_status = "STORED_BYTES"
                if raw_path.is_file() and raw_path.suffix.lower() == ".gz":
                    try:
                        payload_sha = hashlib.sha256(gzip.decompress(raw_path.read_bytes())).hexdigest()
                        decode_status = "GZIP_DECOMPRESSED_PAYLOAD"
                    except (OSError, EOFError):
                        payload_sha = None
                        decode_status = "GZIP_INVALID"
                raw_checks.append({"source": source_name, "path": str(raw_path), "expected_payload_sha256": expected,
                                   "stored_file_sha256": stored_sha, "actual_payload_sha256": payload_sha,
                                   "digest_domain": decode_status,
                                   "status": "PASS" if payload_sha == expected else "FAIL_OR_MISSING"})
        shares_rel = panel_manifest.get("market_package", {}).get("shares_source_path")
        if shares_rel:
            raw_path = (ROOT / str(shares_rel)).resolve()
            expected = (market_doc.get("share_snapshot_sha256") or
                        panel_manifest.get("source_sha256", {}).get(str(shares_rel)))
            actual = sha256(raw_path) if raw_path.is_file() else None
            raw_checks.append({"source": "share_snapshot", "path": str(raw_path), "expected_sha256": expected,
                               "actual_sha256": actual, "status": "PASS" if expected and actual == expected else "NOT_VERIFIED" if actual else "FAIL_OR_MISSING"})
    raw_status = "NOT_VERIFIED" if not raw_checks else ("PASS" if all(x["status"] == "PASS" for x in raw_checks) else "FAIL")
    market_received = registration.get("retrieved_at_utc")
    market_evidence.update({"registration_path": str(registration_path) if registration_path else None,
        "registration_sha256": registration_hash, "declared_registration_sha256": declared_registration,
        "registration_hash_matches_declaration": registration_hash_match,
        "source_manifest_sha256_declared_in_extraction": declared_market_manifest,
        "source_manifest_sha256_matches_declaration": market_manifest_hash_match,
        "declaration_present": declaration_present, "raw_status": raw_status,
        "referenced_raw_count": len(raw_checks), "referenced_raw_checks": raw_checks,
        "registration_endpoint_count": registration.get("raw_endpoint_count"),
        "timestamp": temporal_evidence(market_received, "market_package_manifest_hash_bound" if registration_hash_match and market_manifest_hash_match and declaration_present else "unknown", datetime.fromisoformat(observed["observed_at_utc"]), decision_at)})
    market_evidence["status"] = ("RECORDED_HASH_BOUND" if market_evidence["timestamp"]["source_provenance_valid"]
        and market_manifest_hash_match and declaration_present and raw_status == "PASS" else "NOT_VERIFIED")
    blockers = []
    unknowns = []
    if not observed["canonical_hash_matches"]: blockers.append("ARTIFACT_CANONICAL_HASH_MISMATCH")
    if not identity_cardinality_ok: blockers.append("FROZEN_UNIVERSE_CARDINALITY_MISMATCH")
    if validation_ok and not identity_match: blockers.append("FROZEN_UNIVERSE_IDENTITY_MISMATCH")
    if not top_ok: blockers.append("P1_OR_P3_TOP_RANK_NOT_UNIQUE")
    if not validation_ok: blockers.append("LOCKED_VALIDATOR_DID_NOT_PASS")
    if not panel_hash_matches: blockers.append("SOURCE_PANEL_HASH_MISMATCH")
    if extraction and not extraction_consistent: blockers.append("UPSTREAM_EXTRACTION_MANIFEST_METADATA_MISMATCH")
    if not observed["manifest"]["matches_snapshot"]: unknowns.append("SNAPSHOT_MANIFEST_MISSING_OR_NOT_MATCHING_BYTES")
    if receipt_status == "PARTIAL_MARKET_RECEIPT_FINANCIAL_RECEIPT_INCOMPLETE":
        unknowns.append("MARKET_PACKAGE_RECEIPT_IS_RECORDED; FINANCIAL_RECEIPT_IS_NOT_PER_ROW_RECORDED")
    if not any(x["source_provenance_valid"] for x in receipt_rows):
        unknowns.append("FINANCIAL_RECEIPT_NOT_VERIFIED; observed_at_alias_is_not_source_receipt")
    unknowns += ["FINANCIAL_SOURCE_RECEIPT_AND_AS_OF_LINEAGE_NOT_PROVEN_BY_RANKING_ARTIFACT",
                 "FRESHNESS_POLICY_FOR_A_NEW_PUBLIC_PAPER_DECISION_IS_UNDEFINED_OR_NOT_EVIDENCED",
                 "PRICE_AND_CORPORATE_ACTION_COMPLETENESS_REQUIRES_CURRENT_DECISION_SPECIFIC_REVIEW",
                 "CURRENTNESS_DOES_NOT_PROVE_NO_NEW_DISCLOSURES_AFTER_SOURCE_CUTOFF"]
    public_ready = False
    official_ready = False  # no prospective sealed decision/evaluation and no official ledger authorization
    result = {"schema_version": 1, "diagnostic_success": True, "snapshot": observed,
              "sealed_observation": sealed, "validator": validator_result, "panel_provenance": panel_summary,
              "time_evidence": {"observed_at_utc": observed["observed_at_utc"], "hypothetical_decision_at": decision_at, "financial_lineage_receipts": receipt_rows[:100], "financial_lineage_receipt_count": len(receipt_rows), "market_receipt": market_evidence},
              "controls": {"calculation_valid": calculation_valid, "source_panel_hash_matches": panel_hash_matches, "extraction_manifest_matches_snapshot": extraction_consistent,
                           "identity_cardinality": "PASS" if identity_cardinality_ok else "FAIL", "identity_universe_match": identity_detail,
                           "identity_and_lineage_status": "PASS" if lineage_ok and identity_ok else "INCOMPLETE",
                           "lineage_status": "PASS" if lineage_ok else "INCOMPLETE", "receipt_evidence_status": receipt_status,
                           "freshness_status": "UNKNOWN", "unique_top_rank_and_identity": "PASS" if top_ok and identity_ok else "FAIL",
                           "coverage_rule": "LOCKED_RULE_REFERENCE: 50% weighted financial coverage; no 100% coverage gate added",
                           "scoreability_rule_verification": "VERIFIED_BY_LOCKED_VALIDATOR" if validation_ok else "NOT_VERIFIED",
                           "public_paper_decision_ready": public_ready, "official_future_evaluation_ready": official_ready},
              "blocked_reasons": blockers, "unknown_reasons": unknowns,
              "observation_limits": ["observed_at_utc proves only that these exact bytes were present and hashed at observation time.",
                                     "It does not prove source receipt time, historical availability, freshness, absence of newer disclosures, or authorization.",
                                     "No order, decision, official event, prospective evaluation, or source data was written."]}
    result = jsonable(result)
    (output_dir / "readiness.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--panel", type=Path)
    p.add_argument("--decision-at", help="Optional hypothetical decision timestamp; must include an explicit UTC offset.")
    args = p.parse_args()
    try:
        result = assess(args.snapshot, args.output_dir, args.manifest, args.panel, decision_at=args.decision_at)
        print(json.dumps({"diagnostic_success": result["diagnostic_success"], "snapshot_sha256": result["snapshot"]["snapshot_sha256"],
                          "canonical_hash_matches": result["snapshot"]["canonical_hash_matches"],
                          "validator": result["validator"]["status"], "controls": result["controls"],
                          "blocked_reasons": result["blocked_reasons"], "unknown_reasons": result["unknown_reasons"],
                          "readiness_path": str((args.output_dir.resolve() / "readiness.json"))}, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"diagnostic_success": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
