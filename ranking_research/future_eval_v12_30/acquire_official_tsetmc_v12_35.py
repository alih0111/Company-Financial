"""Read official TSETMC quote and share-change archives for the frozen V12.34 universe.

Uses only the frozen company/symbol map and local security cache; it never opens a DB.
Raw responses, retrieval timestamps, URLs and hashes are retained per identity.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
import argparse
from pathlib import Path
from http_retry import ReadOnlyRateLimitedError, open_readonly

import pandas as pd

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv"
SECURITIES = ROOT / "score_v2_research/_cache/securities.parquet"
OUT = ROOT / "ranking_research/output/return_v12_35/official_tsetmc_20261022"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*",
           "Accept-Language": "fa-IR,fa;q=0.9", "Referer": "https://cdn.tsetmc.com/"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_one(row):
    cid, symbol, security_id, ins_code = map(str, row)
    result = {"company_id": cid, "symbol": symbol, "security_id": security_id,
              "ins_code": ins_code, "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "status": "started", "sources": {}}
    for kind, url in (
        ("daily", f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins_code}/0"),
        ("share_change", f"https://cdn.tsetmc.com/api/Instrument/GetInstrumentShareChange/{ins_code}"),
    ):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            response = None
            attempts = 0
            retry_wait = 0.0
            for transport_attempt in range(2):
                try:
                    response, request_attempts, request_retry_wait = open_readonly(req, timeout=35)
                    attempts += request_attempts
                    retry_wait += request_retry_wait
                    break
                except ReadOnlyRateLimitedError as exc:
                    attempts += exc.attempts
                    raise
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionResetError) as exc:
                    code = getattr(exc, "code", None)
                    reason = getattr(exc, "reason", None)
                    transient = code in (500, 502, 503, 504) or isinstance(exc, (TimeoutError, ConnectionResetError)) or isinstance(reason, (TimeoutError, ConnectionResetError))
                    if not transient or transport_attempt == 1:
                        raise
                    attempts += 1
                    retry_wait += 1.0
                    time.sleep(1.0)
            if response is None:
                raise RuntimeError("READ_ONLY_RETRY_WITHOUT_RESPONSE")
            with response:
                raw = response.read(32 * 1024 * 1024 + 1)
                status, http_date = response.status, response.headers.get("Date")
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("RESPONSE_OVER_32MB")
            if status != 200:
                raise ValueError(f"HTTP_{status}")
            doc = json.loads(raw)
            if kind == "daily":
                records = doc.get("closingPriceDaily")
                if not isinstance(records, list): raise ValueError("DAILY_LIST_MISSING")
                for item in records:
                    if str(item.get("insCode")) != ins_code: raise ValueError("INSCODE_MISMATCH")
                dated = []
                seen = set()
                for item in records:
                    raw_day = str(item.get("dEven", ""))
                    if len(raw_day) != 8 or not raw_day.isdigit(): continue
                    day = dt.datetime.strptime(raw_day, "%Y%m%d").date().isoformat()
                    if day in seen: raise ValueError("DUPLICATE_QUOTE_DATE")
                    seen.add(day)
                    values = {"close": item.get("pClosing"), "trade_value": item.get("qTotCap"), "volume": item.get("qTotTran5J")}
                    try: values = {k: float(v) for k, v in values.items()}
                    except (TypeError, ValueError): continue
                    if all(pd.notna(v) for v in values.values()):
                        dated.append({"date": day, "close_rial": values["close"],
                                      "trade_value_rial": values["trade_value"], "volume": values["volume"]})
                dated.sort(key=lambda x: x["date"])
                result["daily"] = dated[-60:]
                result["daily_total_rows"] = len(records)
                result["latest_quote_date"] = dated[-1]["date"] if dated else None
            else:
                changes = doc.get("instrumentShareChange")
                if not isinstance(changes, list): raise ValueError("SHARE_CHANGE_LIST_MISSING")
                for item in changes:
                    if str(item.get("insCode")) != ins_code: raise ValueError("SHARE_CHANGE_INSCODE_MISMATCH")
                result["share_changes"] = changes
            raw_path = OUT / "raw" / f"{cid}.{kind}.json.gz"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(gzip.compress(raw, compresslevel=6))
            result["sources"][kind] = {"url": url, "http_status": status, "http_date": http_date,
                "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "raw_path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
                "raw_sha256": sha(raw), "raw_bytes": len(raw)}
            result["sources"][kind]["request_attempts"] = attempts
            result["sources"][kind]["retry_wait_seconds"] = retry_wait
        except Exception as exc:  # preserve item-level failure evidence
            result["status"] = "partial_failure"
            result.setdefault("errors", []).append({"kind": kind, "error_type": type(exc).__name__, "error": str(exc)[:500]})
            break
    if result["status"] == "started": result["status"] = "complete"
    return result


def main():
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT,
                        help="Fresh run directory; use a new directory for each daily acquisition.")
    args = parser.parse_args()
    OUT = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    OUT.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(UNIVERSE, dtype=str)
    securities = pd.read_parquet(SECURITIES).astype(str)
    if len(universe) != 254 or universe.company_id.nunique() != 254:
        raise SystemExit("FROZEN_UNIVERSE_NOT_254_UNIQUE")
    if securities.symbol.duplicated().any():
        raise SystemExit("CACHED_PRIMARY_SECURITY_SYMBOL_NOT_UNIQUE")
    # The frozen map resolves company_id -> symbol; the local primary-security cache
    # resolves that exact symbol -> security_id/ins_code. These are different ID domains.
    matched = universe.merge(securities, on="symbol", how="left", validate="one_to_one")
    if matched.ins_code.isna().any() or matched.security_id.isna().any():
        raise SystemExit("FROZEN_IDENTITY_TO_CACHED_INSCODE_JOIN_FAILED")
    targets = list(matched[["company_id", "symbol", "security_id", "ins_code"]].itertuples(index=False, name=None))
    checkpoint = OUT / "progress.jsonl"
    done = {}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if item.get("status") == "complete": done[item["company_id"]] = item
            except Exception: pass
    # Keep request concurrency low for the public official endpoint. Resume is cache-first.
    for i, row in enumerate(targets, 1):
        cid = str(row[0])
        if cid in done: continue
        item = fetch_one(row)
        with checkpoint.open("a", encoding="utf-8") as f: f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(json.dumps({"n": i, "of": len(targets), "symbol": item["symbol"], "status": item["status"],
                          "latest_quote_date": item.get("latest_quote_date"), "errors": item.get("errors")}, ensure_ascii=False), flush=True)
        if item["status"] != "complete":
            # Keep collecting independent identities and report every failure.
            # A throttled identity has its own bounded Retry-After-aware retry.
            pass
        else:
            done[cid] = item
        time.sleep(0.12)
    progress = []
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            try: progress.append(json.loads(line))
            except Exception: pass
    latest_by_id = {str(x["company_id"]): x for x in progress if x.get("company_id")}
    records = sorted(latest_by_id.values(), key=lambda x: x["company_id"])
    for record in records:
        (OUT / f"{record['company_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    daily_ok = [x for x in records if x.get("daily") and x.get("latest_quote_date")]
    registration = {"dataset_id": "v12_35_official_tsetmc_frozen_254", "as_of": "per_identity_latest_source_date",
        "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "frozen_universe_path": str(UNIVERSE.relative_to(ROOT)).replace("\\", "/"),
        "security_map_path": str(SECURITIES.relative_to(ROOT)).replace("\\", "/"),
        "raw_endpoint_count": sum(len(x.get("sources", {})) for x in records), "database_connections": 0}
    (OUT / "registration.json").write_text(json.dumps(registration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    all_records = []
    for item in records:
        all_records.append(item)
    manifest = {"dataset_id": "v12_35_official_tsetmc_frozen_254", "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "universe_count": len(targets), "completed_count": len(daily_ok),
                "failed_count": len(targets) - len(daily_ok),
                "share_change_failed_count": sum("share_changes" not in x for x in records),
                "latest_quote_dates": pd.Series([x.get("latest_quote_date") for x in daily_ok]).value_counts(dropna=False).to_dict(),
                "records": records, "frozen_universe_sha256": sha(UNIVERSE.read_bytes()),
                "cached_security_map_sha256": sha(SECURITIES.read_bytes()), "database_connections": 0}
    # JSON object keys must be strings for stable serialization.
    manifest["latest_quote_dates"] = {str(k): int(v) for k, v in manifest["latest_quote_dates"].items()}
    path = OUT / "manifest.json"
    data = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(data)
    print(json.dumps({k: manifest[k] for k in ("dataset_id", "universe_count", "completed_count", "failed_count", "latest_quote_dates")}, ensure_ascii=False))


if __name__ == "__main__": main()
