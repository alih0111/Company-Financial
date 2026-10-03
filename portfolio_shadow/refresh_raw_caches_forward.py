"""SHADOW V1.1 — forward raw-cache refresh (spec §5c).

One acquisition cycle = paced re-fetch of the TSETMC GetClosingPriceDailyList API for
(1) every existing raw closing cache and (2) every scored company of the latest
production run that passes deterministic identity checks but has no cache yet (onboarding).

MERGE SEMANTICS (append/update, documented):
  - records are keyed by (dEven, hEven);
  - records already on disk are kept VERBATIM (first-seen-wins: no retrospective rewrite
    of a session close, PIT-preserving; vendor revisions of past closes are counted and
    ignored, listed in evidence);
  - new keys are appended; a file is rewritten (sorted) only when it gains records;
  - every added record must carry insCode equal to the file's ins_code (source identity
    check) and is stored with all vendor fields, incl. raw pClosing, unchanged.

The script never touches shadow decisions/state and never writes observation artifacts.
Evidence is written to launch_audit/forward_refresh_evidence.json (one file per cycle,
timestamped; never overwritten within a cycle).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\RFA\Company-Financial")
SHADOW = ROOT / "portfolio_shadow"
RAW = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
IDX = json.loads((ROOT / "historical_codal_backfill" / "output" / "tsetmc_share" / "index.json")
                 .read_text(encoding="utf-8"))
AUDIT = SHADOW / "launch_audit"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
     "Accept": "application/json, text/plain, */*", "Referer": "https://cdn.tsetmc.com/"}
LAST = {"t": 0.0}
ILLEGAL = set('<>:"/\\|?*')


def paced_get(url: str) -> str:
    for attempt, backoff in enumerate([0, 10, 30, 60, 120]):
        if backoff:
            time.sleep(backoff)
        w = 1.5 - (time.time() - LAST["t"])
        if w > 0:
            time.sleep(w)
        LAST["t"] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 403) and attempt < 4:
                continue
            raise
    raise RuntimeError(f"throttled: {url}")


def load_records(sym: str, ins: str) -> dict | None:
    gz = RAW / f"raw_{sym}_{ins}.json.gz"
    if not gz.exists():
        return None
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        return json.loads(fh.read())


def key_of(r: dict) -> tuple[int, int]:
    return int(r["dEven"]), int(r.get("hEven") or 0)


def d_iso(d_int: int) -> str:
    s = str(d_int)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=None, help="evidence file path override")
    args = ap.parse_args()

    state = json.loads((SHADOW / "shadow_v1_state.json").read_text(encoding="utf-8"))
    freeze = state["spec_frozen_at_utc"]
    freeze_dt = dt.datetime.fromisoformat(freeze.replace("Z", "+00:00"))

    # targets: existing caches (refresh) + scored-but-uncached identity-clean names (onboard)
    targets: dict[tuple[str, str], str] = {}   # (symbol, ins_code) -> kind
    for gz in sorted(RAW.glob("raw_*.json.gz")):
        # filename layout: raw_{symbol}_{ins_code}.json.gz — strip both extensions
        name = gz.name[len("raw_"):-len(".json.gz")]
        ins = name.rsplit("_", 1)[-1]
        targets[(name[: -(len(ins) + 1)], ins)] = "refresh"

    import psycopg
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (cs.company_id)
                              cs.company_id::text, s.codal_symbol, s.tsetmc_ins_code::text
                       FROM analytics.company_scores cs
                       JOIN analytics.score_runs sr ON sr.id = cs.run_id
                       JOIN core.securities s ON s.id = cs.primary_security_id
                       WHERE sr.score_version = 'canonical-v1-dev'
                       ORDER BY cs.company_id, sr.completed_at DESC""")
        scored = cur.fetchall()
    n_scored = len(scored)
    for cid, sym, ins in scored:
        if not sym or not ins:
            continue
        bad = ILLEGAL & set(sym)
        if bad:
            continue
        if (sym, ins) not in targets:
            targets[(sym, ins)] = "onboard"

    evidence = {
        "artifact_kind": "FORWARD_RAW_CACHE_REFRESH_EVIDENCE",
        "cycle_started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "spec_frozen_at_utc": freeze,
        "merge_semantics": ("append by (dEven,hEven); existing records kept verbatim "
                            "(first-seen-wins, PIT-preserving); rewrite only on additions; "
                            "vendor revisions of existing records counted and ignored"),
        "n_scored_companies_latest_run": n_scored,
        "symbols": [], "failures": [], "vendor_revisions_ignored": 0,
        "added_session_dates": [], "thu_fri_added_dates": [], "identity_mismatch_records": 0,
    }
    print(f"targets: {len(targets)} (refresh={sum(1 for k in targets.values() if k == 'refresh')}, "
          f"onboard={sum(1 for k in targets.values() if k == 'onboard')})", flush=True)

    for i, ((sym, ins), kind) in enumerate(sorted(targets.items())):
        row = {"symbol": sym, "ins_code": ins, "kind": kind,
               "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            old_doc = load_records(sym, ins)
            old_recs = list((old_doc or {}).get("closingPriceDaily", []))
            old_by_key = {key_of(r): r for r in old_recs}
            old_dEven = {int(r["dEven"]) for r in old_recs}
            body = paced_get(f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins}/0")
            fresh = json.loads(body).get("closingPriceDaily") or []
            added, revisions, id_bad, late_arrivals = [], 0, 0, 0
            for r in fresh:
                k = key_of(r)
                if k in old_by_key:
                    if json.dumps(old_by_key[k], sort_keys=True) != json.dumps(r, sort_keys=True):
                        revisions += 1
                    continue
                if int(r["dEven"]) in old_dEven:
                    # a second intraday record for an already-covered session: the certified
                    # chain reads last-record-per-dEven, so accepting it could rewrite history.
                    # First-seen-wins: skip and count (PIT-preserving).
                    late_arrivals += 1
                    continue
                if str(r.get("insCode")) != str(ins):
                    id_bad += 1
                    continue
                added.append(r)
            merged = old_recs + sorted(added, key=key_of)   # old order preserved verbatim, new appended
            all_d = [int(r["dEven"]) for r in merged]
            row.update({"rows_before": len(old_recs), "rows_fetched": len(fresh),
                        "added": len(added), "vendor_revisions_ignored": revisions,
                        "late_arrivals_for_existing_session_skipped": late_arrivals,
                        "identity_mismatch_records": id_bad,
                        "max_date_before": d_iso(max(old_dEven)) if old_dEven else None,
                        "max_date_after": d_iso(max(all_d)) if all_d else None})
            evidence["vendor_revisions_ignored"] += revisions
            evidence["identity_mismatch_records"] += id_bad
            evidence["late_arrivals_skipped_total"] = evidence.get("late_arrivals_skipped_total", 0) + late_arrivals
            for r in added:
                evidence["added_session_dates"].append(d_iso(int(r["dEven"])))
            if added:
                gz = RAW / f"raw_{sym}_{ins}.json.gz"
                row["sha_before"] = hashlib.sha256(gz.read_bytes()).hexdigest() if gz.exists() else None
                tmp = Path(str(gz) + ".tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                    fh.write(json.dumps({"closingPriceDaily": merged}, ensure_ascii=False))
                tmp.replace(gz)
                row["sha_after"] = hashlib.sha256(gz.read_bytes()).hexdigest()
                row["status"] = "updated"
            else:
                row["status"] = "no_change" if old_recs else "empty_response"
        except Exception as e:                                   # noqa: BLE001 — evidence, not control flow
            row["status"] = "failed"
            row["error"] = f"{type(e).__name__}: {e}"
            evidence["failures"].append(row)
        evidence["symbols"].append(row)
        if (i + 1) % 25 == 0:
            print(f"[{i+1}/{len(targets)}] last={sym} status={row['status']}", flush=True)

    # aggregate verification
    dates = sorted(set(evidence["added_session_dates"]))
    evidence["added_session_dates_distinct"] = dates
    evidence["added_session_dates_weekday_hist"] = {}
    for d in dates:
        wd = dt.date.fromisoformat(d).strftime("%a")
        evidence["added_session_dates_weekday_hist"][wd] = \
            evidence["added_session_dates_weekday_hist"].get(wd, 0) + 1
        if dt.date.fromisoformat(d).weekday() in (3, 4):
            evidence["thu_fri_added_dates"].append(d)
    evidence["cycle_finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    status_counts = {}
    for r in evidence["symbols"]:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    evidence["status_counts"] = status_counts
    # coverage of the current production universe
    have = {(r["symbol"], r["ins_code"]) for r in evidence["symbols"]
            if r["status"] in ("updated", "no_change", "empty_response")}
    evidence["production_universe_cache_coverage"] = {
        "scored_companies": n_scored,
        "scored_with_cache_after_cycle": sum(1 for _, sym, ins in scored if (sym, ins) in have),
    }
    evidence["all_fetches_after_freeze"] = all(
        dt.datetime.fromisoformat(r["fetched_at_utc"]) > freeze_dt for r in evidence["symbols"])
    evidence["min_fetched_at_utc"] = min(r["fetched_at_utc"] for r in evidence["symbols"])

    AUDIT.mkdir(parents=True, exist_ok=True)
    out = Path(args.evidence) if args.evidence else \
        AUDIT / f"forward_refresh_evidence_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(evidence, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"evidence": str(out), "status_counts": status_counts,
                      "added_distinct_dates": dates, "thu_fri_added": evidence["thu_fri_added_dates"],
                      "failures": len(evidence["failures"]),
                      "all_fetches_after_freeze": evidence["all_fetches_after_freeze"],
                      "coverage": evidence["production_universe_cache_coverage"]},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
