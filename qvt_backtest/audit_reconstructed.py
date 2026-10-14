"""Independent artifact checks before exposing a reconstructed replay in the app."""
import datetime as dt
import json
from pathlib import Path
import numpy as np
import pandas as pd
import reconstructed_replay as B
import collect_financial_history as H


def catalog_errors(reports, catalog):
    expected = {(r["company_id"], str(r["letter"]["TracingNo"])): (r["period"], r["published_at"]) for r in catalog}
    actual = {(r["company_id"], str(r["tracing_no"])): (r["period_end"], r["published_at"]) for r in reports}
    errors = []
    if len(expected) != len(catalog) or len(actual) != len(reports):
        errors.append("duplicate report/catalog identity")
    if expected != actual:
        errors.append("frozen catalog/report metadata incomplete or mismatched")
    return errors


def main():
    candidate = B.R.HERE / "output/reconstructed_candidate.json"
    summary = H.C.read(candidate if candidate.exists() else B.R.HERE / "output/reconstructed_latest.json")
    run = Path(summary["run_path"])
    hashes = H.C.read(run / "input_hashes.json")
    snapshot_errors = []
    for name in ("financial_panel.csv", "reports.json", "share_intervals.json", "catalog_versions.json"):
        snapshot = run / ("input_" + name)
        if not snapshot.exists() or B.R.sha(snapshot) != hashes.get(name):
            snapshot_errors.append("input snapshot hash mismatch: " + name)
    scores = pd.read_parquet(run / "scores.parquet")
    inputs = pd.read_parquet(run / "reconstructed_inputs.parquet")
    errors = snapshot_errors
    if scores.duplicated(["as_of", "symbol"]).any() or not scores.ui_score.between(0, 76).all():
        errors.append("invalid score range/identity")
    if scores.groupby("as_of").size().min() < 20:
        errors.append("insufficient comparable population")
    if (pd.to_datetime(inputs.as_of) - pd.to_datetime(inputs.financial_period_end)).dt.days.max() > 365:
        errors.append("stale financial period")
    if inputs.used_older_income_report.any():
        errors.append("older-income fallback")
    for factor, den in [("pe", "net_profit_ttm"), ("pb", "total_equity"), ("ps", "revenue_ttm")]:
        positive = inputs[den] > 0
        if not np.allclose(inputs.loc[positive, factor], inputs.loc[positive, "market_cap"] / inputs.loc[positive, den]):
            errors.append(f"direct {factor} identity")
    reports = {}
    frozen_reports = H.C.read(run / "input_reports.json")
    frozen_by_key = {(r["company_id"], r["tracing_no"]): r for r in frozen_reports}
    errors.extend(catalog_errors(frozen_reports, H.C.read(run / "input_catalog_versions.json")))
    by_company = {}
    for metadata in frozen_reports:
        by_company.setdefault(metadata["company_id"], []).append(metadata)
    referenced = set()
    for row in inputs.to_dict("records"):
        cut = B.cutoff_for(str(row["as_of"])[:10])
        available_metadata = [r for r in by_company[row["company_id"]] if dt.datetime.fromisoformat(r["published_at"]) < cut]
        if max((r["period_end"] for r in available_metadata), default=row["financial_period_end"]) != row["financial_period_end"]:
            errors.append("known newer report masked by older income")
        for tracing in json.loads(row["source_reports"]):
            key = row["company_id"], tracing
            referenced.add(key)
            if key not in reports:
                reports[key] = H.verify_frozen_record(frozen_by_key[key])
            record = reports[key]
            if dt.datetime.fromisoformat(record["published_at"]) >= cut:
                errors.append("future financial report")
        if dt.datetime.fromisoformat(row["share_knowledge_from"]) > cut:
            errors.append("future share evidence")
    for key in referenced:
        report = reports[key]
        if report.get("parser_version") in ("codal-dynamic-source-v1", "codal-dynamic-source-v2", "codal-dynamic-source-v3", "codal-dynamic-source-v4", "codal-dynamic-source-v5", "codal-dynamic-source-v6"):
            source_path = Path(report["dynamic_manifest_path"])
            expected_hash = report["dynamic_manifest_sha256"]
        else:
            _, source = H.C.report_html(report["symbol"], {"TracingNo": report["tracing_no"]}, False, 0)
            source_path = Path(source)
            expected_hash = report["sha256"]
        if not source_path.is_file():
            errors.append(f"report archive hash mismatch {key}")
            continue
        raw = source_path.read_bytes()
        # Previous Windows write_text translated each LF to CRLF, including
        # existing CRLF -> CRCRLF. This inverse is exact and reversible; never
        # broadly strip whitespace or change the original report hash.
        candidates = {"file_bytes": raw, "inverse_windows_newline_write": raw.replace(b"\r\n", b"\n"),
                      "cached_universal_newline_read": source_path.read_text(encoding="utf8").encode()}
        matches = [mode for mode, body in candidates.items() if H.hashlib.sha256(body).hexdigest() == expected_hash]
        if not matches:
            errors.append(f"report archive hash mismatch {key}")
        report["audit_archive"] = {"file_sha256": H.hashlib.sha256(raw).hexdigest(), "original_hash_match_modes": matches,
                                   "path": str(source_path)}
    H.C.write(run / "financial_lineage.json", list(reports.values()))
    for name, ascending in [("QVT_TOP10", False), ("QVT_BOTTOM10", True)]:
        expected = scores.sort_values(["as_of", "ui_score", "symbol"], ascending=[True, ascending, True]).groupby("as_of").head(10)
        actual = pd.read_csv(run / f"{name}_selections.csv")
        if list(zip(expected.as_of, expected.symbol)) != list(zip(actual.as_of, actual.symbol)):
            errors.append(f"{name} fixed selection mismatch")
    ledger_rows, daily_rows = 0, 0
    for label, perf in summary["performance"].items():
        ledger = pd.read_csv(run / f"{label}_ledger.csv")
        daily = pd.read_csv(run / f"{label}_daily.csv")
        ledger_rows += len(ledger)
        daily_rows += len(daily)
        rate = float(label.rsplit("_", 1)[1])
        if not np.allclose(ledger.value_post_trade, ledger.value_pre_trade - ledger.transaction_cost, atol=1e-10):
            errors.append(label + " NAV identity")
        if not np.allclose(ledger.transaction_cost, rate * ledger.traded_notional, atol=1e-10):
            errors.append(label + " cost identity")
        if (ledger.cash_post < -1e-9).any() or not (ledger.exec_date > ledger.score_date).all():
            errors.append(label + " cash/next-session contract")
        if (ledger.exec_date == perf["execution_end"]).any():
            errors.append(label + " unintended final rebalance")
        if "_1m_" in label and len(ledger) != scores.as_of.nunique() - 1:
            errors.append(label + " missing monthly decision")
        wealth = np.r_[1, daily.nav.to_numpy()]
        drawdown = float((wealth / np.maximum.accumulate(wealth) - 1).min() * 100)
        if not np.isclose(drawdown, perf["max_drawdown_pct"]):
            errors.append(label + " daily drawdown mismatch")
    result = {"status": "passed" if not errors else "failed", "errors": sorted(set(errors)),
              "score_rows": len(scores), "financial_source_reports_hashed": len(referenced),
              "ledger_rows": ledger_rows, "daily_nav_rows": daily_rows,
              "full_live_model_certified": False,
              "note": "Artifact/source timestamp/accounting checks, not independent share-chain certification or executable return guarantee"}
    H.C.write(run / "audit.json", result)
    print(json.dumps({**result, "errors": result["errors"][:10], "error_count": len(result["errors"])}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)
    H.C.write(B.R.HERE / "output/reconstructed_latest.json", summary)

if __name__ == "__main__":
    main()
