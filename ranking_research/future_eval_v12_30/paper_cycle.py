"""Run the local ranking and paper-order review as one auditable daily cycle."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import subprocess
import sys
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv/Scripts/python.exe"
OUT = ROOT / "ranking_research/output/paper_cycle"
PUBLIC = ROOT / "client/public/research/v12-38"
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
CHECK = PUBLIC / "paper-account-check.json"
CONTRACT = ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json"
RULES = ROOT / "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json"
TZ = dt.timezone.utc
TEHRAN = ZoneInfo("Asia/Tehran")

try:
    from ranking_research import paper_calendar
except ImportError:  # direct-file execution
    sys.path.insert(0, str(ROOT))
    from ranking_research import paper_calendar


def is_weekly_stock_market_closure(now: dt.datetime | None = None) -> bool:
    """Iranian listed equities do not trade on Thursday or Friday."""
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(TEHRAN)
    return local.weekday() in (3, 4)


def latest_complete_market_manifest() -> Path | None:
    market_root = OUT / "market"
    manifests = sorted(market_root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (int(data.get("completed_count", 0)) == 254 and int(data.get("failed_count", 1)) == 0
                    and data.get("dataset_id") == "v12_35_official_tsetmc_frozen_254"):
                return path
        except (OSError, ValueError, TypeError):
            continue
    return None


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ranking_comparison(before_path: Path, after_path: Path, admission: dict | None = None,
                       before_panel_path: Path | None = None, after_panel_path: Path | None = None,
                       market_manifest_path: Path | None = None, run_id: str | None = None) -> dict:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    before_rows = {str(r["company_id"]): r for r in before.get("rows", [])}
    after_rows = {str(r["company_id"]): r for r in after.get("rows", [])}
    out = {"before": {"path": str(before_path.relative_to(ROOT)).replace("\\", "/"),
                       "artifact_sha256": before.get("artifact_sha256"),
                       "evaluation_date": before.get("evaluation_date"),
                       "scored_count": before.get("scored_count"),
                       "factor_observed_counts": before.get("factor_observed_counts")},
           "after": {"path": str(after_path.relative_to(ROOT)).replace("\\", "/"),
                      "artifact_sha256": after.get("artifact_sha256"),
                      "evaluation_date": after.get("evaluation_date"),
                      "scored_count": after.get("scored_count"),
                      "factor_observed_counts": after.get("factor_observed_counts")},
           "rank_changes": {}, "rank_change_evidence": [],
           "p1_coverage_mean_before": None, "p1_coverage_mean_after": None,
           "p3_coverage_mean_before": None, "p3_coverage_mean_after": None}
    before_panel = after_panel = None
    if before_panel_path and before_panel_path.is_file() and after_panel_path and after_panel_path.is_file():
        import pandas as pd
        before_panel = pd.read_parquet(before_panel_path).set_index("company_id", drop=False)
        after_panel = pd.read_parquet(after_panel_path).set_index("company_id", drop=False)
    market_records = {}
    market_artifact = None
    if market_manifest_path and market_manifest_path.is_file():
        market_artifact = json.loads(market_manifest_path.read_text(encoding="utf-8"))
        market_records = {str(x.get("company_id")): x for x in market_artifact.get("records", [])}
    factor_names = list(before.get("factor_observed_counts", {}))
    global_factor_changes = {}
    if before_panel is not None and after_panel is not None:
        for factor in factor_names:
            if factor not in before_panel.columns or factor not in after_panel.columns:
                continue
            changes = []
            for cid in before_panel.index.union(after_panel.index):
                old_value = before_panel.at[cid, factor] if cid in before_panel.index else None
                new_value = after_panel.at[cid, factor] if cid in after_panel.index else None
                old_missing = old_value is None or pd.isna(old_value)
                new_missing = new_value is None or pd.isna(new_value)
                if old_missing and new_missing:
                    continue
                if old_missing != new_missing or (not old_missing and not new_missing
                        and abs(float(old_value) - float(new_value)) > 1e-12):
                    source = market_records.get(str(cid), {})
                    daily = source.get("sources", {}).get("daily", {})
                    changes.append({"company_id": str(cid),
                        "symbol": (after_panel.at[cid, "symbol"] if cid in after_panel.index and "symbol" in after_panel.columns else None),
                        "before": None if old_missing else float(old_value),
                        "after": None if new_missing else float(new_value),
                        "market_source_evidence": ({"dataset_id": market_artifact.get("dataset_id"),
                            "data_date": source.get("latest_quote_date"), "retrieved_at_utc": daily.get("retrieved_at_utc"),
                            "raw_sha256": daily.get("raw_sha256"), "url": daily.get("url")} if daily else None)})
            if changes:
                global_factor_changes[factor] = {"changed_identity_count": len(changes), "inputs": changes}
    for method in ("P1", "P3"):
        changed = 0
        comparable = 0
        for cid in before_rows.keys() & after_rows.keys():
            b = before_rows[cid].get("methods", {}).get(method, {}).get("rank")
            a = after_rows[cid].get("methods", {}).get(method, {}).get("rank")
            if b is not None and a is not None:
                comparable += 1
                if b != a:
                    changed += 1
                    old_row, new_row = before_rows[cid], after_rows[cid]
                    details = {"method": method, "company_id": cid, "symbol": new_row.get("symbol"),
                        "rank_before": b, "rank_after": a,
                        "score_before": old_row.get("methods", {}).get(method, {}).get("score"),
                        "score_after": new_row.get("methods", {}).get(method, {}).get("score"),
                        "changed_factor_values": [],
                        "cross_section_factor_inputs_changed": list(global_factor_changes)}
                    if before_panel is not None and after_panel is not None and cid in before_panel.index and cid in after_panel.index:
                        old_features, new_features = before_panel.loc[cid], after_panel.loc[cid]
                        for factor in factor_names:
                            if factor not in old_features.index or factor not in new_features.index:
                                continue
                            old_value, new_value = old_features[factor], new_features[factor]
                            if pd.isna(old_value) and pd.isna(new_value):
                                continue
                            if pd.isna(old_value) != pd.isna(new_value) or (not pd.isna(old_value) and not pd.isna(new_value)
                                    and abs(float(old_value) - float(new_value)) > 1e-12):
                                details["changed_factor_values"].append({"factor": factor,
                                    "before": None if pd.isna(old_value) else float(old_value),
                                    "after": None if pd.isna(new_value) else float(new_value)})
                    source = market_records.get(cid, {})
                    daily = source.get("sources", {}).get("daily", {})
                    details["market_source_evidence"] = ({"dataset_id": market_artifact.get("dataset_id"),
                        "data_date": source.get("latest_quote_date"),
                        "retrieved_at_utc": daily.get("retrieved_at_utc"),
                        "raw_sha256": daily.get("raw_sha256"), "url": daily.get("url")}
                        if daily else None)
                    out["rank_change_evidence"].append(details)
        out["rank_changes"][method] = {"changed": changed, "comparable_scored_identities": comparable}
    for method, prefix in (("P1", "p1"), ("P3", "p3")):
        for suffix, rows in (("before", before.get("rows", [])), ("after", after.get("rows", []))):
            values = [float(r["methods"][method]["financial_factor_coverage"]) for r in rows
                      if r.get("methods", {}).get(method, {}).get("score") is not None
                      and r["methods"][method].get("financial_factor_coverage") is not None]
            out[f"{prefix}_coverage_mean_{suffix}"] = sum(values) / len(values) if values else None
    out["market_comparison_input"] = ({"manifest": str(market_manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "dataset_id": market_artifact.get("dataset_id"), "retrieved_at_utc": market_artifact.get("retrieved_at_utc"),
        "latest_quote_dates": market_artifact.get("latest_quote_dates"),
        "frozen_universe_sha256": market_artifact.get("frozen_universe_sha256")}
        if market_artifact else None)
    out["global_factor_changes"] = global_factor_changes
    out["execution_binding"] = {"run_id": run_id,
        "ranking_before_sha256": sha(before_path), "ranking_after_sha256": sha(after_path),
        "panel_before_sha256": sha(before_panel_path) if before_panel_path and before_panel_path.is_file() else None,
        "panel_after_sha256": sha(after_panel_path) if after_panel_path and after_panel_path.is_file() else None,
        "market_manifest_path": str(market_manifest_path.relative_to(ROOT)).replace("\\", "/") if market_manifest_path and market_manifest_path.is_file() else None,
        "market_manifest_sha256": sha(market_manifest_path) if market_manifest_path and market_manifest_path.is_file() else None,
        "comparison_scope": "same-run ranking output compared with the named prior archive; changed ranks are associated with raw-factor differences and per-identity market evidence below; Codal effect is reported separately"}
    admitted_count = sum(int((admission or {}).get(feed, {}).get("admitted", 0)) for feed in ("financial", "sales"))
    out["fresh_codal_factor_effect"] = ({"state": "admitted_effect_not_isolated", "p1_scored_count_delta": None,
        "p3_scored_count_delta": None, "p1_coverage_delta": None, "p1_rank_changes": None, "p3_rank_changes": None,
        "reason": "Codal records were admitted but an otherwise identical market-only shadow build was unavailable."}
        if admitted_count else {"state": "no_fresh_codal_inputs_admitted", "p1_scored_count_delta": 0,
        "p3_scored_count_delta": 0, "p1_coverage_delta": 0.0, "p1_rank_changes": 0, "p3_rank_changes": 0,
        "reason": "No fresh financial/sales candidates were admitted to this ranking artifact; no effect is attributed to unadmitted reports."})
    return out


def causal_codal_effect(before_path: Path, after_path: Path, admission: dict) -> dict:
    before = json.loads(before_path.read_text(encoding="utf-8")); after = json.loads(after_path.read_text(encoding="utf-8"))
    b_rows = {str(r["company_id"]): r for r in before.get("rows", [])}
    a_rows = {str(r["company_id"]): r for r in after.get("rows", [])}
    docs = {}
    for feed in ("financial", "sales"):
        for item in admission.get(feed, {}).get("admitted_inputs", []):
            docs.setdefault(str(item["company_id"]), []).append({"feed": feed, "tracing_no": item["tracing_no"],
                "symbol": item["symbol"], "period_end": item.get("period_end"),
                "source_body_sha256": item.get("source_body_sha256")})
    changed_rows = []
    rank_changes = {}
    for method in ("P1", "P3"):
        changes = []
        for cid in b_rows.keys() & a_rows.keys():
            br = b_rows[cid].get("methods", {}).get(method, {}).get("rank")
            ar = a_rows[cid].get("methods", {}).get(method, {}).get("rank")
            if br is not None and ar is not None and br != ar:
                changes.append({"company_id": cid, "symbol": a_rows[cid].get("symbol"), "rank_before": br,
                    "rank_after": ar, "source_reports": docs.get(cid, [])})
        rank_changes[method] = len(changes)
        changed_rows.extend({"method": method, **x} for x in changes)
    observed_before = before.get("factor_observed_counts", {}); observed_after = after.get("factor_observed_counts", {})
    factors = {k: {"before": observed_before.get(k), "after": observed_after.get(k),
                   "delta": (observed_after.get(k, 0) - observed_before.get(k, 0))
                       if isinstance(observed_before.get(k), (int, float)) and isinstance(observed_after.get(k), (int, float)) else None}
               for k in sorted(set(observed_before) | set(observed_after))}
    p1_before = int(before.get("scored_count", {}).get("P1", 0)); p1_after = int(after.get("scored_count", {}).get("P1", 0))
    p3_before = int(before.get("scored_count", {}).get("P3", 0)); p3_after = int(after.get("scored_count", {}).get("P3", 0))
    return {"state": "isolated_same_market_shadow_comparison", "market_evaluation_date_before": before.get("evaluation_date"),
        "market_evaluation_date_after": after.get("evaluation_date"), "p1_scored_before": p1_before,
        "p1_scored_after": p1_after, "p1_scored_delta": p1_after - p1_before,
        "p3_scored_before": p3_before, "p3_scored_after": p3_after, "p3_scored_delta": p3_after - p3_before,
        "factor_observed_counts": factors, "rank_changes": rank_changes, "changed_rank_rows": changed_rows,
        "admitted_source_reports": [r for items in docs.values() for r in items],
        "attribution_note": "Shadow build uses the same market package, date, locked contract, and scorer; only admitted Codal input files differ."}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        last_error = None
        for attempt in range(8):
            try:
                os.replace(temp, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.2 * (attempt + 1))
        # Some Windows readers deny delete/rename sharing while serving JSON.
        # A flushed in-place write is the final fallback for this generated report.
        try:
            with path.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            raise last_error
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def run_stage(name: str, command: list[str], timeout: int, env: dict | None = None) -> dict:
    started = dt.datetime.now(TZ).isoformat()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout,
                                env={**os.environ, **(env or {}), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
        return {"stage": name, "status": "process_exited_zero" if result.returncode == 0 else "process_failed",
                "started_at_utc": started, "finished_at_utc": dt.datetime.now(TZ).isoformat(),
                "exit_code": result.returncode,
                "summary": result.stdout[-3000:] if result.returncode == 0 else None,
                "error": result.stderr[-1000:] if result.returncode != 0 else None}
    except subprocess.TimeoutExpired as exc:
        return {"stage": name, "status": "timed_out", "started_at_utc": started,
                "finished_at_utc": dt.datetime.now(TZ).isoformat(), "timeout_seconds": timeout,
                "stdout_tail": str(exc.stdout or "")[-5000:], "stderr_tail": str(exc.stderr or "")[-5000:]}


def task_status() -> dict:
    script = ("$t=Get-ScheduledTask -TaskName 'CompanyFinancial-PaperCycle' -ErrorAction SilentlyContinue; "
              "if($null -eq $t){ @{installed=$false} | ConvertTo-Json -Compress; exit }; "
              "$i=Get-ScheduledTaskInfo -TaskName 'CompanyFinancial-PaperCycle'; "
              "$a=$t.Actions[0]; $tr=$t.Triggers[0]; "
              "@{installed=$true;state=$t.State.ToString();enabled=($t.State.ToString() -ne 'Disabled' -and $tr.Enabled);next_run_time=$i.NextRunTime.ToString('o');"
              "last_run_time=$i.LastRunTime.ToString('o');last_task_result=$i.LastTaskResult;"
              "run_as=$t.Principal.UserId;logon_type=$t.Principal.LogonType.ToString();"
              "start_when_available=$t.Settings.StartWhenAvailable;wake_to_run=$t.Settings.WakeToRun;"
              "multiple_instances=$t.Settings.MultipleInstances.ToString();"
              "execution_time_limit=$t.Settings.ExecutionTimeLimit.ToString();"
              "restart_count=$t.Settings.RestartCount;restart_interval=$t.Settings.RestartInterval.ToString();"
              "action_path=$a.Execute;action_arguments=$a.Arguments;working_directory=$a.WorkingDirectory;"
              "trigger_start_boundary=$tr.StartBoundary.ToString();trigger_days_interval=$tr.DaysInterval;"
              "number_of_missed_runs=$i.NumberOfMissedRuns} | ConvertTo-Json -Compress")
    fallback_path = OUT / "task-config.json"
    configured = json.loads(fallback_path.read_text(encoding="utf-8")) if fallback_path.exists() else {}
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        queried = json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else {}
        return {**configured, **queried, "query_error": False}
    except Exception:
        return {**configured, "installed": bool(configured.get("installed")), "query_error": True}


def acquire_cycle_lock(lock_path: Path) -> int | None:
    """Create the cycle lock, reclaiming it only when its recorded PID is gone."""
    for attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{os.getpid()} {dt.datetime.now(TZ).isoformat()}".encode())
            return fd
        except FileExistsError:
            try:
                recorded_pid = int(lock_path.read_text(encoding="ascii").split()[0])
                if os.name == "nt":
                    import ctypes
                    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
                    kernel.OpenProcess.restype = ctypes.c_void_p
                    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                    kernel.WaitForSingleObject.restype = ctypes.c_uint32
                    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                    process = kernel.OpenProcess(0x00100000, False, recorded_pid)  # SYNCHRONIZE
                    if process:
                        try:
                            state = kernel.WaitForSingleObject(process, 0)
                            if state == 0x00000102:  # WAIT_TIMEOUT
                                return None
                            if state != 0x00000000:  # Any indeterminate state: fail closed.
                                return None
                        finally:
                            kernel.CloseHandle(process)
                    elif ctypes.get_last_error() != 87:  # Unknown/access denied: fail closed.
                        return None
                else:
                    os.kill(recorded_pid, 0)
                    return None  # The prior runner is still alive, regardless of lock age.
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
            except (OSError, ValueError, IndexError):
                return None  # Unknown owner: fail closed instead of stealing a live lock.
    return None


def acquire_order_calendar(*, provider: str, run_id: str, out_root: Path,
                           account_path: Path | None = None,
                           calendar_policy_path: Path | None = None,
                           reference_now_utc: str | None = None,
                           run_stage_fn=None) -> dict:
    """One auditable order-calendar acquisition stage for one provider.

    ``nscstart`` keeps the token-gated current behavior unchanged. ``public``
    is not conditional on any token: it runs the token-free public collector
    into a run-scoped directory and consumes ONLY that same run's manifest —
    a failed or manifest-less run never falls back to an older manifest by
    glob/mtime. The order's own profile stays pinned by the account, so a
    public acquisition against an account not bound to the public policy is
    reported as a profile mismatch, never as fill permission.
    """
    account_path = account_path or ACCOUNT
    stage_fn = run_stage_fn or run_stage
    result = {"provider": provider, "stage": None, "manifest_path": None,
              "calendar_state": "unavailable", "profile_mismatch": False,
              "answer_summary": None, "token_required": provider == "nscstart"}
    if provider == "nscstart":
        calendar_manifest_path = None
        if os.environ.get("TSETMC_READONLY_BEARER_TOKEN") and os.environ.get("TSETMC_CREDENTIAL_IDENTITY_STATE", "matched_task_identity") == "matched_task_identity":
            calendar_fetch_stage = stage_fn("order_calendar_recent_acquisition", [str(PYTHON),
                str(ROOT / "ranking_research/future_eval_v12_30/acquire_tsetmc_open_sessions.py")], 180)
            if calendar_fetch_stage.get("exit_code") == 0:
                manifests = sorted((ROOT / "ranking_research/output/paper_v12_38_first_fill/session_calendar").glob("NSCStart.*.manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if manifests:
                    calendar_manifest_path = manifests[0]
                    os.environ["TSETMC_CALENDAR_MANIFEST"] = str(calendar_manifest_path)
                    calendar_fetch_stage["status"] = "received_recent_order_calendar"
                else:
                    calendar_fetch_stage["status"] = "manifest_missing_after_successful_process"
            else:
                fetch_error = str(calendar_fetch_stage.get("error") or "")
                if "TSETMC_TOKEN_INVALID_OR_EXPIRED_HTTP_401" in fetch_error:
                    calendar_fetch_stage["status"] = "credential_invalid_or_expired"
                elif "TSETMC_PERMISSION_DENIED_HTTP_403" in fetch_error:
                    calendar_fetch_stage["status"] = "credential_permission_denied"
                else:
                    calendar_fetch_stage["status"] = "calendar_fetch_failed_non_auth"
        else:
            calendar_fetch_stage = {"stage": "order_calendar_recent_acquisition",
                "status": "blocked_missing_credential" if os.environ.get("TSETMC_CREDENTIAL_STATE") == "absent" else "blocked_credential_unreadable_or_identity_mismatch",
                "exit_code": None, "error": "No authenticated NSCStart request was attempted; no token value was present in the report."}
        result["stage"] = calendar_fetch_stage
        result["manifest_path"] = calendar_manifest_path
        result["calendar_state"] = ("verified_recent_window" if calendar_manifest_path
                                    else calendar_fetch_stage.get("status", "unavailable"))
        return result
    if provider != "public":
        raise ValueError(f"unknown calendar provider {provider!r}")

    account = json.loads(Path(account_path).read_text(encoding="utf-8"))
    decision = account.get("active_decision") or {}
    order = account.get("paper_order") or {}
    window_start = str(decision.get("decision_local_date", "")).replace("-", "")
    if not window_start:
        stage = {"stage": "order_calendar_public_acquisition",
                 "status": "blocked_no_pinned_decision_date", "exit_code": None}
        result["stage"] = stage
        result["calendar_state"] = "blocked_no_pinned_decision_date"
        return result
    out_dir = Path(out_root) / "public_calendar" / run_id
    stage = stage_fn("order_calendar_public_acquisition", [str(PYTHON),
        str(ROOT / "ranking_research/future_eval_v12_30/acquire_public_market_calendar.py"),
        "--window-start", window_start, "--output-dir", str(out_dir),
        "--cross-check-lookback-days", "60"], 900)
    result["stage"] = stage
    if stage.get("exit_code") != 0:
        # A failed acquisition never selects an older manifest by glob/mtime.
        stage["status"] = "calendar_public_acquisition_failed_no_fallback"
        result["calendar_state"] = "blocked_public_acquisition_failed"
        return result
    latest = out_dir / "latest-manifest.json"
    if not latest.is_file():
        stage["status"] = "manifest_missing_after_successful_process_no_fallback"
        result["calendar_state"] = "blocked_public_manifest_missing"
        return result
    reference = json.loads(latest.read_text(encoding="utf-8"))
    manifest_path = Path(reference.get("manifest_path", ""))
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not manifest_path.is_file() or sha(manifest_path) != reference.get("manifest_sha256"):
        stage["status"] = "public_manifest_hash_mismatch"
        result["calendar_state"] = "blocked_public_manifest_hash_mismatch"
        return result
    result["manifest_path"] = manifest_path
    stage["status"] = "received_public_order_calendar"
    # Adapter resolution: the same pinned evidence the fill/status paths use.
    try:
        policy_path = calendar_policy_path or paper_calendar.DEFAULT_PUBLIC_POLICY_PATH
        policy = paper_calendar.load_policy(policy_path)
        manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
        pinned_candidate = manifest_doc.get("candidate") or {}
        if reference_now_utc:
            now = dt.datetime.fromisoformat(reference_now_utc)
            now = now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
        else:
            now = dt.datetime.now(dt.timezone.utc)
        answer = paper_calendar.resolve_public_calendar(
            manifest_path=manifest_path,
            expected_manifest_sha256=reference["manifest_sha256"],
            policy=policy, policy_sha256=sha(policy_path),
            candidate={"symbol": order.get("symbol", ""),
                       "ins_code": str(pinned_candidate.get("ins_code", ""))},
            decision_local_date=decision.get("decision_local_date", ""),
            decision_at_utc=dt.datetime.fromisoformat(decision["decided_at_utc"]),
            now_utc=now, consumption_mode="live-preview")
    except (paper_calendar.CalendarRefusal, KeyError, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        stage["status"] = f"public_calendar_refused:{code}"
        result["calendar_state"] = f"blocked_public_{code.lower()}"
        return result
    binding = decision.get("calendar_policy") or {}
    result["profile_mismatch"] = binding.get("id") != policy["policy_id"]
    sessions = answer["sessions_after_decision"]
    result["answer_summary"] = {
        "first_session": sessions["first_session"],
        "session_count": sessions["count"],
        "session_count_is_unknown": sessions["count"] is None,
        "state": sessions["state"],
        "calendar_ready": answer["readiness"]["calendar_ready"],
        "blocking_reasons": answer["readiness"]["blocking_reasons"],
        "quality": answer["quality"],
        "freshness_state": answer["freshness"]["state"],
    }
    if result["profile_mismatch"]:
        result["calendar_state"] = "blocked_calendar_profile_mismatch"
        stage["status"] = ("acquired_public_calendar_but_order_profile_not_bound;"
                           " no order consumption")
    elif not answer["readiness"]["calendar_ready"]:
        result["calendar_state"] = "blocked_public_calendar_not_ready"
        stage["status"] = "public_calendar_not_ready;" + ",".join(
            answer["readiness"]["blocking_reasons"][:3])
    else:
        result["calendar_state"] = "verified_public_calendar"
        stage["status"] = ("verified_public_calendar_no_new_session"
                           if sessions["count"] == 0 else "verified_public_calendar")
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calendar-provider", choices=("nscstart", "public"),
                        default=os.environ.get("PAPER_CYCLE_CALENDAR_PROVIDER", "nscstart"),
                        help="explicit order-calendar profile for this cycle; the order's own "
                             "consumption profile stays pinned by the account/rules")
    args = parser.parse_args()
    if not PYTHON.is_file():
        print("BLOCKED_RUNTIME: project .venv Python was not found", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    lock_path = OUT / "cycle.lock"
    lock_fd = acquire_cycle_lock(lock_path)
    if lock_fd is None:
        print("SKIPPED_OVERLAP: another paper cycle holds the lock")
        return 0

    run_id = f"paper-cycle-{dt.datetime.now(TZ).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    started = dt.datetime.now(TZ).isoformat()
    stages: list[dict] = []
    try:
        archive_reprocess_stage = run_stage("codal_archive_local_reprocessing", [str(PYTHON),
            str(ROOT / "ranking_research/future_eval_v12_30/reprocess_codal_archive.py"),
            "--run-id", f"archive-reprocess-{run_id.removeprefix('paper-cycle-')}"], 1800)
        if archive_reprocess_stage.get("exit_code") == 0:
            reprocess_summary_path = OUT / "codal" / f"archive-reprocess-{run_id.removeprefix('paper-cycle-')}" / "archive-reprocess-summary.json"
            archive_reprocess_summary = json.loads(reprocess_summary_path.read_text(encoding="utf-8"))
            archive_reprocess_stage["status"] = (
                "local_bodies_reprocessed_with_quarantined_documents"
                if archive_reprocess_summary.get("parse_errors") else
                "local_archive_bodies_reprocessed" if archive_reprocess_summary.get("archive_bodies_reused")
                else "no_verified_local_bodies")
            archive_reprocess_stage["summary"] = json.dumps({k: archive_reprocess_summary.get(k) for k in
                ("archive_bodies_reused", "financial_parsed", "sales_parsed", "parse_errors", "network_requests")}, ensure_ascii=False)
        else:
            archive_reprocess_summary = {}
            archive_reprocess_stage["status"] = "local_archive_reprocessing_failed"
        stages.append(archive_reprocess_stage)

        weekly_closure = is_weekly_stock_market_closure()
        reuse_dir = os.environ.get("PAPER_CYCLE_REUSE_MARKET_DIR")
        reuse_manifest_path = Path(reuse_dir) / "manifest.json" if reuse_dir else None
        reuse_ok = False
        if reuse_manifest_path and reuse_manifest_path.is_file():
            try:
                candidate = json.loads(reuse_manifest_path.read_text(encoding="utf-8"))
                age = (dt.datetime.now(TZ) - dt.datetime.fromisoformat(candidate["retrieved_at_utc"])).total_seconds()
                reuse_ok = 0 <= age <= 7200
            except Exception:
                reuse_ok = False
        closure_market_manifest = latest_complete_market_manifest() if weekly_closure else None
        if weekly_closure and closure_market_manifest:
            market_manifest_path = closure_market_manifest
            market_dir = closure_market_manifest.parent.relative_to(ROOT)
            closure_manifest = json.loads(closure_market_manifest.read_text(encoding="utf-8"))
            market_stage = {"stage": "market_prices_254", "status": "natural_weekly_closure_prices_not_requested",
                "started_at_utc": dt.datetime.now(TZ).isoformat(), "finished_at_utc": dt.datetime.now(TZ).isoformat(),
                "exit_code": None, "request_skipped": True,
                "summary": "Thursday/Friday stock-market closure; no price endpoint was called. The last complete official market package is reused with original data and receipt dates.",
                "reused_market_manifest": str(closure_market_manifest.relative_to(ROOT)).replace("\\", "/"),
                "reused_market_manifest_sha256": sha(closure_market_manifest),
                "reused_latest_quote_dates": closure_manifest.get("latest_quote_dates")}
        elif weekly_closure:
            market_dir = Path("ranking_research/output/paper_cycle/market") / "no-market-package-on-weekly-closure"
            market_manifest_path = ROOT / market_dir / "manifest.json"
            market_stage = {"stage": "market_prices_254", "status": "natural_weekly_closure_no_cached_package",
                "started_at_utc": dt.datetime.now(TZ).isoformat(), "finished_at_utc": dt.datetime.now(TZ).isoformat(),
                "exit_code": None, "request_skipped": True,
                "summary": "Thursday/Friday stock-market closure; no price endpoint was called. No complete prior package was available."}
        elif reuse_ok:
            market_dir = Path(reuse_dir).resolve().relative_to(ROOT)
            market_partial = int(candidate.get("completed_count", 0)) != int(candidate.get("universe_count", 254))
            market_stage = {"stage": "market_prices_254",
                "status": "reused_recent_partial_acquisition" if market_partial else "reused_recent_successful_acquisition",
                "started_at_utc": dt.datetime.now(TZ).isoformat(), "finished_at_utc": dt.datetime.now(TZ).isoformat(),
                "exit_code": 0, "summary": "Reused a recent acquisition within the 2-hour window; its per-identity coverage, retrieval timestamps, and hashes remain in the manifest."}
        else:
            market_dir = Path("ranking_research/output/paper_cycle/market") / run_id
            market_stage = run_stage("market_prices_254", [str(PYTHON),
                str(ROOT / "ranking_research/future_eval_v12_30/acquire_official_tsetmc_v12_35.py"),
                "--output-dir", str(market_dir)], 5400)
        stages.append(market_stage)
        if not weekly_closure or not closure_market_manifest:
            market_manifest_path = ROOT / market_dir / "manifest.json"

        reuse_codal_dir = os.environ.get("PAPER_CYCLE_REUSE_CODAL_DIR")
        reuse_codal_manifest = Path(reuse_codal_dir) / "manifest.json" if reuse_codal_dir else None
        reuse_codal_ok = False
        if reuse_codal_manifest and reuse_codal_manifest.is_file():
            try:
                candidate = json.loads(reuse_codal_manifest.read_text(encoding="utf-8"))
                age = (dt.datetime.now(TZ) - dt.datetime.fromisoformat(candidate["finished_at_utc"])).total_seconds()
                reuse_codal_ok = 0 <= age <= 7200
            except Exception:
                reuse_codal_ok = False
        if reuse_codal_ok:
            codal_manifest_path = reuse_codal_manifest.resolve()
            codal_partial = any(feed_manifest.get("state") != "complete" or not feed_manifest.get("pagination_complete")
                                for feed_manifest in candidate.get("feeds", {}).values())
            codal_stage = {"stage": "financial_sales_incremental_codal",
                "status": "reused_recent_partial_acquisition" if codal_partial else "reused_recent_successful_acquisition",
                "started_at_utc": dt.datetime.now(TZ).isoformat(), "finished_at_utc": dt.datetime.now(TZ).isoformat(),
                "exit_code": 0, "summary": "Reused the latest raw financial/sales acquisition within the 2-hour retry window, including its partial coverage; original retrieval timestamps and body hashes are retained."}
        else:
            codal_stage = run_stage("financial_sales_incremental_codal", [str(PYTHON),
                str(ROOT / "ranking_research/future_eval_v12_30/acquire_codal_incremental.py"), run_id], 1800)
            codal_manifest_path = ROOT / "ranking_research/output/paper_cycle/codal" / run_id / "manifest.json"
        stages.append(codal_stage)

        if codal_manifest_path.exists():
            extraction_stage = run_stage("codal_report_extraction", [str(PYTHON),
                str(ROOT / "ranking_research/future_eval_v12_30/prepare_codal_inputs.py"),
                str(codal_manifest_path)], 1800)
            if extraction_stage.get("exit_code") == 0:
                prepared_probe = json.loads((codal_manifest_path.parent / "prepared/prepared-inputs.json").read_text(encoding="utf-8"))
                if prepared_probe.get("counts", {}).get("parse_errors", 0):
                    extraction_stage["status"] = "partial_extraction_with_invalid_bodies"
                elif prepared_probe.get("counts", {}).get("financial_parsed", 0) + prepared_probe.get("counts", {}).get("sales_parsed", 0):
                    extraction_stage["status"] = "valid_documents_extracted_and_units_checked"
                else:
                    extraction_stage["status"] = "no_valid_documents_to_extract"
                extraction_stage["summary"] = json.dumps(prepared_probe.get("counts", {}), ensure_ascii=False)
            else:
                extraction_stage["status"] = "partial_or_failed_extraction"
            stages.append(extraction_stage)
            prepared_inputs_path = codal_manifest_path.parent / "prepared/prepared-inputs.json"
        else:
            extraction_stage = {"stage": "codal_report_extraction", "status": "not_run_acquisition_manifest_missing", "exit_code": None}
            stages.append(extraction_stage)
            prepared_inputs_path = None
        o00_stage = run_stage("o00_global_calendar_validation", [str(PYTHON),
            str(ROOT / "ranking_research/future_eval_v12_30/audit_o00_calendar.py")], 120)
        if o00_stage.get("exit_code") == 0:
            o00_payload = json.loads((OUT / "o00-calendar-check.json").read_text(encoding="utf-8"))
            o00_stage["status"] = o00_payload.get("state", "incomplete")
        else:
            o00_payload = {}
            o00_stage["status"] = "validation_failed"
        stages.append(o00_stage)
        calendar_stage_info = acquire_order_calendar(provider=args.calendar_provider,
                                                     run_id=run_id, out_root=OUT)
        calendar_fetch_stage = calendar_stage_info["stage"]
        calendar_manifest_path = calendar_stage_info["manifest_path"]
        stages.append(calendar_fetch_stage)

        market = json.loads(market_manifest_path.read_text(encoding="utf-8")) if market_manifest_path.exists() else {}
        latest_dates = market.get("latest_quote_dates", {})
        market_rank_date = next((date for date, count in latest_dates.items() if int(count) == 254), None)
        ranking_out = Path("ranking_research/output/return_v12_37") / f"v12_37_daily_{run_id}"
        rank_env = {}
        if market_rank_date and int(market.get("completed_count", 0)) == 254 and int(market.get("failed_count", 1)) == 0:
            rank_env = {"V1237_MARKET_PACK": str((ROOT / market_dir).resolve()),
                        "V1237_RANKING_DATE": market_rank_date,
                        "V1237_OUTPUT_DIR": str((ROOT / ranking_out).resolve())}
        else:
            ranking_out = Path("ranking_research/output/return_v12_37/v12_37_20261022_existing_archive_extraction_fix_01")
        factor_input_dir = (codal_manifest_path.parent / "factor-inputs") if codal_manifest_path.exists() else (OUT / "factor-inputs" / run_id)
        factor_eval_date = market_rank_date
        if not factor_eval_date:
            try:
                factor_eval_date = json.loads((ROOT / "client/public/research/v12-37/latest-ranking.json").read_text(encoding="utf-8")).get("evaluation_date")
            except Exception:
                factor_eval_date = None
        sales_timing_calendar_manifest_path = calendar_manifest_path
        if calendar_stage_info["provider"] == "public":
            sales_status = ("public_calendar_validated_sales_capability_not_granted"
                            if sales_timing_calendar_manifest_path
                            else "blocked_missing_market_wide_sessions")
        else:
            sales_status = ("verified_market_wide_sessions" if sales_timing_calendar_manifest_path
                            else "blocked_missing_market_wide_sessions")
        sales_calendar_stage = {"stage": "sales_factor_timing_calendar_validation",
            "status": sales_status,
            "manifest": str(sales_timing_calendar_manifest_path.relative_to(ROOT)).replace("\\", "/") if sales_timing_calendar_manifest_path else None,
            "provider": calendar_stage_info["provider"],
            "purpose": "assign the locked monthly-sales factor's first eligible signal session after publication; does not consume order review state or O00 index"}
        stages.append(sales_calendar_stage)
        factor_args = [str(PYTHON), str(ROOT / "ranking_research/future_eval_v12_30/build_codal_factor_inputs.py"),
            str(codal_manifest_path), "--evaluation-date", factor_eval_date or "2026-10-21", "--output-dir", str(factor_input_dir)] if codal_manifest_path.exists() else None
        if factor_args:
            if sales_timing_calendar_manifest_path:
                factor_args.extend(["--sales-timing-calendar-manifest", str(sales_timing_calendar_manifest_path),
                                    "--sales-timing-calendar-provider", args.calendar_provider])
            factor_stage = run_stage("factor_input_preparation", factor_args, 1200)
            if factor_stage.get("exit_code") == 0:
                admission_path = factor_input_dir / "admission.json"
                admission = json.loads(admission_path.read_text(encoding="utf-8"))
                financial_admitted = int(admission.get("financial", {}).get("admitted", 0))
                sales_admitted = int(admission.get("sales", {}).get("admitted", 0))
                factor_stage["status"] = "factors_prepared_and_cutoff_validated" if financial_admitted or sales_admitted else "validated_no_fresh_inputs_admitted"
                factor_stage["summary"] = json.dumps({"financial_admitted": financial_admitted, "sales_admitted": sales_admitted,
                    "financial_documents_parsed": admission.get("financial", {}).get("parsed_candidates", 0),
                    "sales_documents_parsed": admission.get("sales", {}).get("parsed_candidates", 0),
                    "financial_held": admission.get("financial", {}).get("held", 0), "sales_held": admission.get("sales", {}).get("held", 0)}, ensure_ascii=False)
                if rank_env.get("V1237_MARKET_PACK"):
                    rank_env.update({"V1237_REPORTS_PATH": str(factor_input_dir / "input_reports.json"),
                        "V1237_OWNER_LINEAGE_PATH": str(factor_input_dir / "current_live_lineage.json"),
                        "V1237_EVENTS_PATH": str(factor_input_dir / "monthly_sales_events.parquet"),
                        "V1237_FRESH_FINANCIAL_IDS_PATH": str(factor_input_dir / "fresh-financial-ids.json")})
            else:
                admission = {}
                factor_stage["status"] = "factor_preparation_failed"
                financial_admitted = sales_admitted = 0
            stages.append(factor_stage)
        else:
            admission = {}; financial_admitted = sales_admitted = 0
            factor_stage = {"stage": "factor_input_preparation", "status": "not_run_codal_manifest_missing", "exit_code": None}
            stages.append(factor_stage)
        shadow_ranking_path = None
        admitted_total = financial_admitted + sales_admitted
        if admitted_total > 0 and rank_env.get("V1237_MARKET_PACK"):
            shadow_out = ROOT / "ranking_research/output/return_v12_37" / f"v12_37_market_only_shadow_{run_id}"
            shadow_env = {"V1237_MARKET_PACK": rank_env["V1237_MARKET_PACK"],
                "V1237_RANKING_DATE": rank_env["V1237_RANKING_DATE"],
                "V1237_OUTPUT_DIR": str(shadow_out.resolve())}
            shadow_stage = run_stage("ranking_market_only_shadow", [str(PYTHON),
                str(ROOT / "ranking_research/future_eval_v12_30/build_latest_supported_v12_37.py")], 3600, shadow_env)
            shadow_stage["status"] = "complete" if shadow_stage.get("exit_code") == 0 else "failed"
            stages.append(shadow_stage)
            shadow_ranking_path = shadow_out / "ranking/latest-ranking.json"
        ranking_stage = run_stage("ranking_p1_p3", [str(PYTHON),
            str(ROOT / "ranking_research/future_eval_v12_30/build_latest_supported_v12_37.py")], 3600, rank_env)
        if ranking_stage["status"] == "process_exited_zero":
            ranking_stage["status"] = "rebuilt_with_fresh_market_and_archived_fundamentals" if rank_env else "rebuilt_from_archives_only"
        stages.append(ranking_stage)
        ranking_path = ROOT / "client/public/research/v12-37/latest-ranking.json"
        impact_path = ranking_comparison(
            ROOT / "ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01/ranking/latest-ranking.json",
            ranking_path, admission,
            ROOT / "ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01/normalized_raw_factor_panel.parquet",
            ROOT / ranking_out / "normalized_raw_factor_panel.parquet",
            market_manifest_path, run_id) if ranking_path.is_file() else {}
        if shadow_ranking_path and shadow_ranking_path.is_file() and ranking_path.is_file():
            impact_path["fresh_codal_factor_effect"] = causal_codal_effect(shadow_ranking_path, ranking_path, admission)
        if ranking_stage.get("exit_code") == 0:
            rank_obj = json.loads(ranking_path.read_text(encoding="utf-8"))
            validation = run_stage("ranking_contract_validation", [str(PYTHON),
                str(ROOT / "ranking_research/future_eval_v12_30/validate_latest_ranking.py"),
                "--artifact-dir", str(ROOT / ranking_out / "ranking"),
                "--panel", str(ROOT / ranking_out / "normalized_raw_factor_panel.parquet"),
                "--dataset-id", f"v12_37_balance_marker_safe_{market_rank_date.replace('-', '')}" if rank_env.get("V1237_MARKET_PACK") else "v12_37_balance_marker_safe_20261021"], 600)
            if validation.get("exit_code") == 0:
                validation["status"] = "validated"
                ranking_stage["status"] = "validated_with_fresh_market_and_archived_fundamentals" if rank_env else "validated_from_archives_only"
            stages.append(validation)
        else:
            stages.append({"stage": "ranking_contract_validation", "status": "not_run_dependency_failed", "exit_code": None})

        # This command refreshes the pinned candidate evidence and, when the
        # DPAPI credential is provisioned, validates the recent official calendar.
        order_stage = run_stage("order_review_and_order_calendar", [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(ROOT / "ranking_research/future_eval_v12_30/check_paper_order.ps1"),
            "-SkipTokenPrompt"], 300)
        stages.append(order_stage)

        account = json.loads(ACCOUNT.read_text(encoding="utf-8"))
        check = json.loads(CHECK.read_text(encoding="utf-8")) if CHECK.exists() else {}
        finished = dt.datetime.now(TZ).isoformat()
        calendar_state = next((x.get("state") for x in check.get("barriers", [])
                               if x.get("id") == "authoritative_market_calendar"), "unavailable")
        if calendar_stage_info["provider"] == "public":
            # the public profile is adapter-driven, not read back from the
            # NSCStart-based check file
            calendar_state = calendar_stage_info["calendar_state"]
        codal = json.loads(codal_manifest_path.read_text(encoding="utf-8")) if codal_manifest_path.exists() else {}
        prepared = json.loads(prepared_inputs_path.read_text(encoding="utf-8")) if prepared_inputs_path and prepared_inputs_path.exists() else {}
        market_count = int(market.get("completed_count", 0))
        if market_stage.get("status") != "natural_weekly_closure_prices_not_requested":
            market_stage["status"] = "complete" if market_count == 254 and market.get("failed_count", 1) == 0 else ("partial" if market_count else "failed")
        codal_feeds = codal.get("feeds", {})
        by_name = {x["stage"]: x for x in stages}
        financial_source = codal_feeds.get("financial", {})
        sales_source = codal_feeds.get("sales", {})
        cycle_started_utc = dt.datetime.fromisoformat(started).astimezone(dt.timezone.utc)
        def archived_body_before_cycle(item: dict) -> bool:
            value = item.get("body_evidence", {}).get("retrieved_at_utc")
            if not value:
                return False
            try:
                return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(dt.timezone.utc) < cycle_started_utc
            except (TypeError, ValueError):
                return False
        for source in (financial_source, sales_source):
            reuse = source.setdefault("archive_reuse", {})
            # Extraction runs over every verified archived body listed in the
            # prepared manifest. Count by original receipt time, keeping fresh
            # bodies from this execution separate from local reprocessing.
            reuse["reprocessed_from_local_body"] = sum(archived_body_before_cycle(item)
                                                        for item in source.get("report_ids", []))
        def accepted_receipt_time(feed_name: str) -> str | None:
            values = [str(x.get("received_at_utc")) for x in prepared.get(feed_name, []) if x.get("received_at_utc")]
            return max(values) if values else None
        def latest_body_receipt_time(feed_source: dict) -> str | None:
            values = [str(r.get("body_evidence", {}).get("retrieved_at_utc"))
                      for r in feed_source.get("report_ids", [])
                      if r.get("body_evidence", {}).get("retrieved_at_utc")]
            return max(values) if values else None
        def source_retrieval_time(records: list[dict], source_key: str) -> str | None:
            values = [str(x.get("sources", {}).get(source_key, {}).get("retrieved_at_utc"))
                      for x in records if x.get("sources", {}).get(source_key, {}).get("retrieved_at_utc")]
            return max(values) if values else None
        def discovery_audit(feed_source: dict) -> dict:
            audit_rel = feed_source.get("identities_checked_path")
            audit_path = ROOT / audit_rel if audit_rel else None
            identities = []
            if audit_path and audit_path.is_file():
                try:
                    identities = json.loads(audit_path.read_text(encoding="utf-8")).get("identities", [])
                except Exception:
                    identities = []
            starts = [x.get("from_date_jalali") for x in identities if x.get("from_date_jalali")]
            ends = [x.get("to_date_jalali") for x in identities if x.get("to_date_jalali")]
            return {"pages_fetched": feed_source.get("pages_fetched_this_run", feed_source.get("pages")),
                    "checkpoint_pages_fetched": feed_source.get("pages"),
                    "pagination_complete": feed_source.get("pagination_complete"),
                    "search_window_policy": feed_source.get("search_window_policy"),
                    "search_window_from_min": min(starts) if starts else None,
                    "search_window_to_max": max(ends) if ends else None,
                    "identity_audit_path": str(audit_path.relative_to(ROOT)).replace("\\", "/") if audit_path and audit_path.exists() else None,
                    "identity_audit_count": len(identities)}
        codal_complete = (financial_source.get("state") in ("received", "empty")
                          and sales_source.get("state") in ("received", "empty")
                          and financial_source.get("pagination_complete") is True
                          and sales_source.get("pagination_complete") is True)
        if codal_complete:
            codal_stage["status"] = "complete"
        elif codal_stage.get("exit_code") == 0 and codal_stage.get("status", "").startswith("reused_recent"):
            codal_stage["status"] = "partial_incomplete_acquisition"
        else:
            codal_stage["status"] = "partial_or_failed"
        if calendar_state in ("verified", "verified_public_calendar"):
            by_name["order_review_and_order_calendar"]["status"] = "reviewed"
        else:
            by_name["order_review_and_order_calendar"]["status"] = "calendar_unavailable_or_unverified"
        # Preserve separate state for model intake, decision, execution and valuation.
        fresh_admitted = bool(financial_admitted or sales_admitted)
        decision_state = "not_due_or_not_provable; no new decision created"
        global_cal_ok = False
        cash_only_valuation_ok = bool(check.get("cash_reconciliation", {}).get("balanced")
            and int(check.get("cash_reconciliation", {}).get("cash_toman", -1)) == int(account.get("cash_toman", -2))
            and int(check.get("cash_reconciliation", {}).get("holdings_value_toman", -1)) == 0
            and not account.get("holdings"))
        cycle_blockers = []
        if calendar_state not in ("verified", "verified_public_calendar"):
            cycle_blockers.append(calendar_fetch_stage.get("status", "order_calendar_unavailable"))
        if o00_stage.get("status") != "verified":
            cycle_blockers.append("o00_global_history_extension_unavailable")
        if weekly_closure and market_stage.get("status") == "natural_weekly_closure_no_cached_package":
            cycle_blockers.append("no_complete_market_package_available_during_weekly_closure")
        elif market_count != 254 or market.get("failed_count", 1) != 0:
            cycle_blockers.append("market_prices_incomplete")
        if financial_source.get("state") not in ("received", "empty"):
            cycle_blockers.append("financial_codal_incremental_incomplete")
        if sales_source.get("state") not in ("received", "empty"):
            cycle_blockers.append("sales_codal_incremental_incomplete")
        if prepared.get("errors"):
            cycle_blockers.append("codal_extraction_errors")
        if not fresh_admitted:
            cycle_blockers.append("no_fresh_codal_factors_admitted")
        overall = "IMPLEMENTED_WITH_OPERATIONAL_BLOCKERS" if cycle_blockers else "cycle_reviewed"
        try:
            import subprocess as sp
            commit = sp.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, encoding="ascii", timeout=10).stdout.strip() or None
        except Exception:
            commit = None
        result = {
            "schema_version": 1, "run_id": run_id, "status": overall,
            "status_fa": "چرخهٔ پیاده‌سازی‌شده با موانع عملیاتی" if cycle_blockers else "چرخه بررسی شد",
            "started_at_utc": started, "finished_at_utc": finished,
            "timezone": "Asia/Tehran", "code_commit": commit,
            "code_sha256": {"cycle": sha(Path(__file__)),
                            "ranking_builder": sha(ROOT / "ranking_research/future_eval_v12_30/build_latest_supported_v12_37.py"),
                            "ranking_builder_impl": sha(ROOT / "ranking_research/future_eval_v12_30/build_latest_supported_v12_37_impl.py"),
                            "market_acquirer": sha(ROOT / "ranking_research/future_eval_v12_30/acquire_official_tsetmc_v12_35.py"),
                            "codal_acquirer": sha(ROOT / "ranking_research/future_eval_v12_30/acquire_codal_incremental.py"),
                            "codal_parser": sha(ROOT / "ranking_research/future_eval_v12_30/prepare_codal_inputs.py"),
                            "codal_factor_preparer": sha(ROOT / "ranking_research/future_eval_v12_30/build_codal_factor_inputs.py"),
                            "o00_calendar_audit": sha(ROOT / "ranking_research/future_eval_v12_30/audit_o00_calendar.py"),
                            "ranking_rebuilder": sha(ROOT / "ranking_research/future_eval_v12_30/rebuild_latest_supported_v12_37.py"),
                            "order_checker": sha(ROOT / "ranking_research/future_eval_v12_30/check_paper_order.ps1"),
                            "candidate_acquirer": sha(ROOT / "ranking_research/future_eval_v12_30/acquire_paper_candidate_evidence.py"),
                            "http_retry": sha(ROOT / "ranking_research/future_eval_v12_30/http_retry.py"),
                            "paper_fill_rules_engine": sha(ROOT / "ranking_research/future_eval_v12_30/apply_paper_fill.py")},
            "contract": {"id": account["contract"]["id"], "sha256": sha(CONTRACT),
                         "execution_rules_id": account["assumptions_version"], "execution_rules_sha256": sha(RULES)},
            "inputs": {"ranking": {"path": "client/public/research/v12-37/latest-ranking.json",
                                     "sha256": sha(ranking_path) if ranking_path.is_file() else None,
                "source_receipt_time": "unknown for local archived financial inputs; run-scoped Codal receipts are separately timestamped in factor_inputs/admission.json"},
                       "order_evidence_manifest": check.get("source_sha256", {}).get("evidence_manifest"),
                       "order_evidence_path": json.loads((ROOT / "ranking_research/output/paper_v12_38_first_fill/latest-manifest.json").read_text(encoding="utf-8")).get("manifest_path") if (ROOT / "ranking_research/output/paper_v12_38_first_fill/latest-manifest.json").exists() else None,
                       "ranking_extraction_manifest": {"path": str(ranking_out / "extraction_manifest.json").replace("\\", "/"),
                                                       "sha256": sha(ROOT / ranking_out / "extraction_manifest.json") if (ROOT / ranking_out / "extraction_manifest.json").is_file() else None},
                       "account_sha256": sha(ACCOUNT)},
            "stages": stages,
            "local_archive_reprocessing": archive_reprocess_summary,
            "cycle_blockers": cycle_blockers,
            "stage_statuses": {
                "codal_archive_local_reprocessing": archive_reprocess_stage["status"],
                "market_prices_254": market_stage["status"],
                "calendar_for_order": ("verified_recent_window" if calendar_state == "verified"
                                       else "verified_public_calendar_window" if calendar_state == "verified_public_calendar"
                                       else "unavailable_or_unverified"),
                "calendar_for_o00": o00_stage["status"],
                "sales_factor_timing_calendar": sales_calendar_stage["status"],
                "financial_incremental_discovery": f"{financial_source.get('companies_checked', 0)}/254 checked this run; {financial_source.get('companies_new_reports', 0)} with new reports; {financial_source.get('companies_no_new_reports', 0)} without; {financial_source.get('companies_failed', 0)} failed; {financial_source.get('companies_unchecked', 254)} unchecked/deferred; prior checkpoint {financial_source.get('companies_previously_checked', 0)}",
                "sales_incremental_discovery": f"{sales_source.get('companies_checked', 0)}/254 checked this run; {sales_source.get('companies_new_reports', 0)} with new reports; {sales_source.get('companies_no_new_reports', 0)} without; {sales_source.get('companies_failed', 0)} failed; {sales_source.get('companies_unchecked', 254)} unchecked/deferred; prior checkpoint {sales_source.get('companies_previously_checked', 0)}",
                "ranking": ranking_stage["status"],
                "codal_report_extraction": extraction_stage["status"],
                "factor_input_preparation": factor_stage["status"],
                "decision": decision_state,
                "order_execution": "fill_recorded" if account.get("execution_recorded") else "pending_locked_order_rules",
                "valuation": "cash_only_reconciled; zero assets" if cash_only_valuation_ok else ("pending_fresh_official_close" if account.get("holdings") else "cash_reconciliation_failed"),
            },
            "decision": {"state": decision_state,
                         "o00_rule": "global session index from 2021-04-03; (index - 0) mod 63 == 0; no reset",
                         "last_locked_panel_index": 1165, "next_scheduled_global_index": 1197,
                         "next_review": "unknown until the complete official global session history from 2026-02-24 is validated; index 1197 is a target index, not a date or next-due claim",
                         "o00_calendar_coverage_verified": global_cal_ok,
                         "order_calendar_coverage": {"state": ("verified_recent_window" if calendar_state == "verified"
                                 else "verified_public_calendar_window" if calendar_state == "verified_public_calendar"
                                 else "unavailable_or_unverified"),
                             "sessions_after_decision": check.get("eligible_sessions_after_decision"),
                             "decision_local_date": (check.get("decision") or {}).get("decision_local_date"),
                             "sufficient_for_order": bool(calendar_state in ("verified", "verified_public_calendar")
                                 and (check.get("eligible_sessions_after_decision") or 0) > 0)}},
            "paper_account": {"account_id": account["account_id"], "cash_toman": account["cash_toman"],
                              "holdings_count": len(account.get("holdings", [])),
                              "order_id": account.get("paper_order", {}).get("order_id"),
                              "order_status": account.get("paper_order", {}).get("status"),
                              "fill_recorded": account.get("execution_recorded", False),
                              "reconciliation_balanced": check.get("cash_reconciliation", {}).get("balanced")},
            "blockers": check.get("blockers", []),
            "last_successful_full_cycle": None,
            "schedule": {"task_name": "CompanyFinancial-PaperCycle", "daily_local_time": "22:30",
                         "timezone": "Asia/Tehran", "start_when_available": True,
                         "missed_run_behavior": "StartWhenAvailable; runs after the PC becomes available, but WakeToRun is disabled and interactive logon is required.",
                         "last_task_result_is_cycle_success": False,
                         "window_requires_user_session": True, **task_status()},
            "data_sources": {
                "market": {"state": market_stage["status"],
                    "market_day_status": "weekly_closed" if weekly_closure else "unknown_without_verified_session_calendar",
                    "exceptional_closure_status": "not_verified_by_authoritative_market_notice",
                    "fetch_skipped": bool(market_stage.get("request_skipped")),
                    "latest_successful_retrieval_utc": source_retrieval_time(market.get("records", []), "daily"),
                    "latest_data_date": max((x.get("latest_quote_date") or "" for x in market.get("records", [])), default=None) or None,
                    "coverage": {"completed": market_count, "universe": 254, "failed": market.get("failed_count")},
                    "failed_identities": [{"company_id": x.get("company_id"), "symbol": x.get("symbol"),
                        "latest_data_date": x.get("latest_quote_date"), "error": x.get("errors", [])}
                        for x in market.get("records", []) if not x.get("daily") or not x.get("latest_quote_date")],
                    "error": None if (market_count == 254 and market.get("failed_count", 0) == 0) or weekly_closure else "One or more identity fetches failed; cached historical data is not counted as a successful current retrieval.",
                    "closure_evidence": "Thursday/Friday weekly non-trading schedule; exceptional holidays and exchange-wide suspensions require a verified official notice/calendar.",
                    "manifest": str(market_manifest_path.relative_to(ROOT)).replace("\\", "/") if market_manifest_path.exists() else None},
                "share_changes": {
                    "state": "complete" if market.get("share_change_failed_count", 254) == 0 else "partial",
                    "latest_successful_retrieval_utc": max((x.get("sources", {}).get("share_change", {}).get("retrieved_at_utc", "") for x in market.get("records", []) if x.get("share_changes") is not None), default=None) or None,
                    "latest_data_date": max((f"{str(y.get('dEven'))[:4]}-{str(y.get('dEven'))[4:6]}-{str(y.get('dEven'))[6:8]}" for x in market.get("records", []) for y in x.get("share_changes", []) if len(str(y.get("dEven", ""))) == 8), default=None),
                    "coverage": {"completed": sum(x.get("share_changes") is not None for x in market.get("records", [])), "universe": 254, "failed": int(market.get("share_change_failed_count", 254))},
                    "error": None if market.get("share_change_failed_count", 254) == 0 else "Share-change endpoint failed for one or more identities.",
                    "manifest": str(market_manifest_path.relative_to(ROOT)).replace("\\", "/") if market_manifest_path.exists() else None,
                    "ranking_admission": "latest effective share count used when present; archived snapshot inherited for one identity without a change record"},
                "calendar_for_order": {"state": ("verified" if calendar_state == "verified" else "verified_public_calendar" if calendar_state == "verified_public_calendar" else "unavailable_or_unverified"), "latest_complete_session": check.get("latest_official_completed_session"), "coverage": check.get("eligible_sessions_after_decision"), "error": None if calendar_state == "verified" else "Official recent market calendar not validated; TSETMC read-only credential may be absent or rejected."},
                "calendar_for_sales_factor_timing": {"state": sales_calendar_stage["status"], "manifest": sales_calendar_stage["manifest"],
                    "purpose": sales_calendar_stage["purpose"], "independent_of_order_gate": True, "independent_of_o00": True},
                "calendar_for_o00": {"state": o00_stage["status"], "coverage_from": "2026-02-25", "target_global_index": 1197,
                    "local_calendar_computed_index_at_panel_end": o00_payload.get("local_calendar_computed_index_at_panel_end"),
                    "locked_panel_index": o00_payload.get("locked_panel_index"), "latest_local_calendar_date": o00_payload.get("latest_local_calendar_date"),
                    "index_matches_locked_panel": o00_payload.get("index_matches_locked_panel"),
                    "locked_prefix_date_mapping_complete": o00_payload.get("locked_prefix_date_mapping_complete"),
                    "locked_prefix_extra_local_dates": o00_payload.get("extra_local_dates", []),
                    "missing_locked_dates": o00_payload.get("missing_locked_dates", []),
                    "date_mapping_validation": o00_payload.get("date_mapping_validation"),
                    "continuation_validation": o00_payload.get("continuation_validation"),
                    "source_provenance": o00_payload.get("source_provenance"),
                    "local_to_locked_mapping_path": o00_payload.get("local_to_locked_mapping_path"),
                    "error": o00_payload.get("error", "O00 official global calendar remains unverified; order window is separate.")},
                "financial": {"state": financial_source.get("state", "not_run"), **discovery_audit(financial_source), "archive_reuse": financial_source.get("archive_reuse", {}), "last_successful_retrieval_utc": financial_source.get("last_successful_retrieval_utc"), "latest_accepted_candidate_receipt_utc": accepted_receipt_time("financial"), "latest_body_received_at_utc": latest_body_receipt_time(financial_source), "latest_data_date": financial_source.get("latest_published_at"), "companies_checked": financial_source.get("companies_checked", 0), "companies_new_reports": financial_source.get("companies_new_reports", 0), "companies_no_new_reports": financial_source.get("companies_no_new_reports", 0), "companies_failed": financial_source.get("companies_failed", 0), "companies_unchecked": financial_source.get("companies_unchecked", 254), "companies_previously_checked": financial_source.get("companies_previously_checked", 0), "coverage_universe": 254, "new_reports": financial_source.get("new_reports", 0), "report_bodies_received": financial_source.get("report_bodies_received", 0), "documents_extracted": len(prepared.get("financial", [])), "extraction_errors": sum(e.get("feed") == "financial" for e in prepared.get("errors", [])), "report_body_errors": len(financial_source.get("report_body_errors", [])), "retry_after": financial_source.get("rate_limit"), "next_attempt_at_utc": financial_source.get("next_attempt_at_utc"), "error": financial_source.get("error"), "document_admission_count": financial_admitted, "raw_manifest": str(codal_manifest_path.relative_to(ROOT)).replace("\\", "/") if codal_manifest_path.exists() else None, "ranking_admission": f"{financial_admitted} factors admitted after cutoff/version validation; held reports remain traceable in admission manifest"},
                "sales": {"state": sales_source.get("state", "not_run"), **discovery_audit(sales_source), "archive_reuse": sales_source.get("archive_reuse", {}), "last_successful_retrieval_utc": sales_source.get("last_successful_retrieval_utc"), "latest_accepted_candidate_receipt_utc": accepted_receipt_time("sales"), "latest_body_received_at_utc": latest_body_receipt_time(sales_source), "latest_data_date": sales_source.get("latest_published_at"), "companies_checked": sales_source.get("companies_checked", 0), "companies_new_reports": sales_source.get("companies_new_reports", 0), "companies_no_new_reports": sales_source.get("companies_no_new_reports", 0), "companies_failed": sales_source.get("companies_failed", 0), "companies_unchecked": sales_source.get("companies_unchecked", 254), "companies_previously_checked": sales_source.get("companies_previously_checked", 0), "coverage_universe": 254, "new_reports": sales_source.get("new_reports", 0), "report_bodies_received": sales_source.get("report_bodies_received", 0), "documents_extracted": len(prepared.get("sales", [])), "extraction_errors": sum(e.get("feed") == "sales" for e in prepared.get("errors", [])), "report_body_errors": len(sales_source.get("report_body_errors", [])), "retry_after": sales_source.get("rate_limit"), "next_attempt_at_utc": sales_source.get("next_attempt_at_utc"), "error": sales_source.get("error"), "document_admission_count": sales_admitted, "raw_manifest": str(codal_manifest_path.relative_to(ROOT)).replace("\\", "/") if codal_manifest_path.exists() else None, "ranking_admission": f"{sales_admitted} factors admitted only with authenticated next-session evidence; held reports remain traceable in admission manifest"},
                "corporate_actions": {"state": "candidate_share_change_evidence_refreshed"},
            },
            "ranking_input_admission": {"fresh_market_prices": bool(rank_env), "fresh_financial_reports": bool(financial_admitted), "fresh_monthly_sales": bool(sales_admitted),
                "ranking_artifact_dir": str(ranking_out).replace("\\", "/"),
                "prepared_financial_candidates": len(prepared.get("financial", [])), "prepared_sales_candidates": len(prepared.get("sales", [])),
                "sales_timing_calendar": {"state": sales_calendar_stage["status"], "manifest": sales_calendar_stage["manifest"],
                    "purpose": sales_calendar_stage["purpose"], "contract_dependency": "Monthly sales needs the first verified market session after publication to assign signal_entry_date; this is a factor-timing requirement, independent of order-fill review and O00 global-index validation."},
                "reason": "Codal retrieval, document extraction, and locked-factor admission are reported separately. A parsed document reaches P1/P3 only after complete per-identity discovery, locked publication and receipt cutoffs, explicit correction lineage, and (for monthly sales) verified next-session timing pass; only then is the locked scorer recomputed. No unadmitted report changes ranking."},
            "ranking_impact": impact_path,
            "credential": {"state": os.environ.get("TSETMC_CREDENTIAL_STATE", "not_checked"),
                "task_identity_state": os.environ.get("TSETMC_CREDENTIAL_IDENTITY_STATE", "not_checked"),
                "stored_dpapi_file_present": os.environ.get("TSETMC_CREDENTIAL_STATE", "") not in ("absent", "not_checked"),
                "remote_validity": ("accepted" if calendar_state == "verified" else
                    "public_calendar_no_credential_used" if calendar_state == "verified_public_calendar" else
                    "not_attempted_absent" if os.environ.get("TSETMC_CREDENTIAL_STATE") == "absent" else
                    "dpapi_unreadable_or_user_mismatch" if os.environ.get("TSETMC_CREDENTIAL_STATE") == "dpapi_unreadable_or_user_mismatch" else
                    "task_identity_mismatch" if os.environ.get("TSETMC_CREDENTIAL_STATE") == "task_identity_mismatch" else
                    "invalid_or_expired" if calendar_fetch_stage.get("status") == "credential_invalid_or_expired" else
                    "permission_denied" if calendar_fetch_stage.get("status") == "credential_permission_denied" else
                    "not_proven"),
                "future_validity_guaranteed": False},
        }
        atomic_json(OUT / "runs" / f"{run_id}.json", result)
        atomic_json(PUBLIC / "paper-cycle-latest.json", result)
        print(json.dumps({"run_id": run_id, "status": overall, "started_at_utc": started,
                          "finished_at_utc": finished, "order_status": result["paper_account"]["order_status"],
                          "fill_recorded": result["paper_account"]["fill_recorded"],
                          "calendar_state": calendar_state,
                          "stages": [{"stage": x["stage"], "status": x["status"], "process_exit_code": x.get("exit_code")} for x in stages]}, ensure_ascii=False))
        # The scheduler's process result only reports that orchestration ended.
        # Data success is determined from the per-source coverage and admission fields.
        return 0 if all(x.get("exit_code") == 0 for x in stages) else 1
    finally:
        os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
