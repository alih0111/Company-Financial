"""Offline, isolated diagnostic for a pinned ranking snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
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


def temporal_receipt_status(received_at: str | None, decision_at: str) -> str:
    if not received_at:
        return "UNKNOWN"
    received = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
    decision = datetime.fromisoformat(decision_at.replace("Z", "+00:00"))
    if received.tzinfo is None or decision.tzinfo is None:
        return "UNKNOWN_TIMEZONE"
    return "AFTER_DECISION" if received > decision else "BEFORE_OR_AT_DECISION"


def panel_provenance(panel_path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd
    import json as _json
    frame = pd.read_parquet(panel_path)
    summary: dict[str, Any] = {"path": str(panel_path), "sha256": sha256(panel_path), "rows": len(frame)}
    for column in ("price_date", "financial_period_end", "financial_latest_published_at", "financial_factor_period_end"):
        if column in frame:
            vals = frame[column].dropna().astype(str)
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
        comparisons = {
            "dataset_id_matches": manifest.get("dataset_id") == (snapshot.get("source") or {}).get("dataset_id"),
            "evaluation_date_matches": manifest.get("evaluation_date") == snapshot.get("evaluation_date"),
            "publication_cutoff_matches": manifest.get("publication_cutoff_at") == snapshot.get("publication_cutoff_at"),
            "price_latest_matches_panel": source_dates.get("evaluation_price_latest") == summary.get("price_date", {}).get("max"),
            "financial_latest_published_matches_panel": source_dates.get("financial_latest_published_at") == summary.get("financial_latest_published_at", {}).get("max"),
            "manifest_panel_hash_matches": manifest.get("panel_sha256") == summary["panel_sha256"],
        }
        summary["extraction_manifest"]["consistency_checks"] = comparisons
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
                        traces[col] = [{k: item.get(k) for k in ("tracing_no", "period_end", "published_at", "observed_at", "received_at", "sha256", "source")} for item in val[:8]]
                    elif col == "financial_lineage" and isinstance(val, list):
                        received = sorted(str(x.get("received_at")) for x in val if x.get("received_at"))
                        published = sorted(str(x.get("published_at")) for x in val if x.get("published_at"))
                        traces[col] = {"report_count": len(val), "received_count": len(received), "received_at_min": received[0] if received else None, "received_at_max": received[-1] if received else None, "published_at_min": published[0] if published else None, "published_at_max": published[-1] if published else None}
                    elif col == "sales_lineage" and isinstance(val, dict):
                        versions = val.get("selected_month_versions", [])
                        known = sorted(str(x.get("known_from")) for x in versions if x.get("known_from"))
                        traces[col] = {"selected_month_versions": len(versions), "known_from_min": known[0] if known else None, "known_from_max": known[-1] if known else None, "published_at_recorded_count": sum(bool(x.get("published_at") not in (None, "None")) for x in versions), "received_at_recorded_count": sum(bool(x.get("received_at")) for x in versions)}
                    else:
                        traces[col] = val
                summary["top_p1_source_lineage"] = {k: r.get(k) for k in ("financial_period_end", "financial_latest_published_at", "financial_factor_period_end", "financial_age_days", "price_date", "price_age_days", "price_valid_sessions_30d") if k in frame.columns} | traces
    return summary


def inspect_snapshot(snapshot: Path, manifest_path: Path | None = None) -> dict[str, Any]:
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
    observed_at = datetime.now(timezone.utc).isoformat()
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
        "observed_at_utc": observed_at,
    }


def assess(snapshot: Path, output_dir: Path, manifest_path: Path | None = None, panel: Path | None = None) -> dict[str, Any]:
    snapshot = snapshot.resolve()
    output_dir = output_dir.resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(f"SNAPSHOT_NOT_FOUND: {snapshot}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"OUTPUT_DIR_NOT_EMPTY: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    observed = inspect_snapshot(snapshot, manifest_path)
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
    identity_ok = observed["counts"]["rows"] == 254 and observed["counts"]["unique_symbols"] == 254 and observed["counts"]["unique_company_ids"] == 254
    top_ok = len(observed["top_candidates"]["P1"]) == 1 and len(observed["top_candidates"]["P3"]) == 1
    lineage_ok = bool(observed["manifest"]["matches_snapshot"] and observed.get("source", {}).get("sha256") and observed.get("contract_sha256"))
    validation_ok = validator_result["status"] == "PASS"
    calculation_valid = bool(observed["canonical_hash_matches"] and identity_ok and top_ok and validation_ok)
    panel_summary = panel_provenance(selected_panel, observed) if selected_panel.is_file() else {"status": "UNAVAILABLE"}
    panel_hash_matches = bool(selected_panel.is_file() and observed.get("source", {}).get("sha256") == sha256(selected_panel))
    extraction = panel_summary.get("extraction_manifest", {})
    receipt_cov = panel_summary.get("received_at", {})
    extraction_consistent = bool(extraction.get("consistency_checks") and all(extraction["consistency_checks"].values()))
    lineage_ok = bool(lineage_ok and panel_hash_matches and extraction_consistent)
    receipt_status = ("PARTIAL_MARKET_RECEIPT_FINANCIAL_RECEIPT_INCOMPLETE"
                      if extraction.get("received_at") and receipt_cov.get("nonnull", 0) == 0
                      else "UNKNOWN" if observed.get("received_at") is None
                      else "RECORDED_REQUIRES_SOURCE_AUDIT")
    blockers = []
    unknowns = []
    if not observed["canonical_hash_matches"]: blockers.append("ARTIFACT_CANONICAL_HASH_MISMATCH")
    if not identity_ok: blockers.append("FROZEN_UNIVERSE_IDENTITY_OR_COUNT_MISMATCH")
    if not top_ok: blockers.append("P1_OR_P3_TOP_RANK_NOT_UNIQUE")
    if not validation_ok: blockers.append("LOCKED_VALIDATOR_DID_NOT_PASS")
    if not panel_hash_matches: blockers.append("SOURCE_PANEL_HASH_MISMATCH")
    if extraction and not extraction_consistent: blockers.append("UPSTREAM_EXTRACTION_MANIFEST_METADATA_MISMATCH")
    if not observed["manifest"]["matches_snapshot"]: unknowns.append("SNAPSHOT_MANIFEST_MISSING_OR_NOT_MATCHING_BYTES")
    if receipt_status == "PARTIAL_MARKET_RECEIPT_FINANCIAL_RECEIPT_INCOMPLETE":
        unknowns.append("MARKET_PACKAGE_RECEIPT_IS_RECORDED; FINANCIAL_RECEIPT_IS_NOT_PER_ROW_RECORDED")
    elif not observed.get("received_at"):
        unknowns.append("SOURCE_RECEIPT_TIME_NOT_RECORDED; OBSERVATION_TIME_IS_NOT_RECEIPT_TIME")
    unknowns += ["FINANCIAL_SOURCE_RECEIPT_AND_AS_OF_LINEAGE_NOT_PROVEN_BY_RANKING_ARTIFACT",
                 "FRESHNESS_POLICY_FOR_A_NEW_PUBLIC_PAPER_DECISION_IS_UNDEFINED_OR_NOT_EVIDENCED",
                 "PRICE_AND_CORPORATE_ACTION_COMPLETENESS_REQUIRES_CURRENT_DECISION_SPECIFIC_REVIEW",
                 "CURRENTNESS_DOES_NOT_PROVE_NO_NEW_DISCLOSURES_AFTER_SOURCE_CUTOFF"]
    public_ready = False
    official_ready = False  # no prospective sealed decision/evaluation and no official ledger authorization
    result = {"schema_version": 1, "diagnostic_success": True, "snapshot": observed,
              "sealed_observation": sealed, "validator": validator_result, "panel_provenance": panel_summary,
              "controls": {"calculation_valid": calculation_valid, "source_panel_hash_matches": panel_hash_matches, "extraction_manifest_matches_snapshot": extraction_consistent,
                           "identity_and_lineage_status": "PASS" if lineage_ok and identity_ok else "INCOMPLETE",
                           "lineage_status": "PASS" if lineage_ok else "INCOMPLETE", "receipt_evidence_status": receipt_status,
                           "freshness_status": "UNKNOWN", "unique_top_rank_and_identity": "PASS" if top_ok and identity_ok else "FAIL",
                           "scoreability_reasoning": "PASS_LOCKED_RULE; 50% weighted financial coverage retained; no 100% coverage gate added",
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
    args = p.parse_args()
    try:
        result = assess(args.snapshot, args.output_dir, args.manifest, args.panel)
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
