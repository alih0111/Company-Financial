"""Acquire bounded read-only TSETMC evidence for the active paper decision."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from http_retry import open_readonly

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
OUT = ROOT / "ranking_research/output/paper_v12_38_first_fill"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(key: str, url: str, run_id: str, max_bytes: int = 32 * 1024 * 1024) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    response, attempts, retry_wait = open_readonly(req, timeout=35)
    with response:
        raw = response.read(max_bytes + 1)
        status, http_date = response.status, response.headers.get("Date")
    received = dt.datetime.now(dt.timezone.utc).isoformat()
    if len(raw) > max_bytes:
        raise ValueError(f"{key}: response exceeded {max_bytes} bytes")
    if status != 200:
        raise ValueError(f"{key}: HTTP {status}")
    raw_path = OUT / "raw" / f"{key}.{run_id}.bin.gz"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(gzip.compress(raw, compresslevel=6))
    return {
        "key": key, "url": url, "http_status": status,
        "http_date": http_date, "request_started_at_utc": started,
        "retrieved_at_utc": received, "raw_path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
        "raw_sha256": sha(raw), "raw_bytes": len(raw), "raw_content_sha256_basis": "uncompressed response bytes",
        "request_attempts": attempts, "retry_wait_seconds": retry_wait,
        "body": raw,
    }


def main() -> None:
    account = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    candidate = account["ranking"]["top_candidate"]
    if not candidate or candidate["symbol"] != "غاذر":
        raise SystemExit("PAPER_CANDIDATE_CHANGED; inspect and pin a new decision before acquisition")
    security_map = json.loads((ROOT / "ranking_research/output/return_v12_35/official_tsetmc_20261022/manifest.json").read_text(encoding="utf-8"))
    record = next(x for x in security_map["records"] if x["company_id"] == candidate["company_id"])
    ins_code = str(record["ins_code"])
    OUT.mkdir(parents=True, exist_ok=True)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    entries = []
    for i, (key, url) in enumerate([
        ("last_possible_session", "https://service.tsetmc.com/tsev2/data/TseClient2.aspx?t=LastPossibleDeven"),
        ("candidate_daily", f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{ins_code}/0"),
        ("candidate_calendar", f"https://cdn.tsetmc.com/api/ClosingPrice/GetInstrumentCalendar/{ins_code}"),
        ("candidate_share_changes", f"https://cdn.tsetmc.com/api/Instrument/GetInstrumentShareChange/{ins_code}"),
    ]):
        if i:
            time.sleep(1.2)
        item = fetch(key, url, run_id)
        body = item.pop("body")
        if key == "last_possible_session":
            item["reported_last_possible_session"] = body.decode("utf-8", "replace").strip()
        elif key in ("candidate_daily", "candidate_calendar"):
            doc = json.loads(body)
            field = "closingPriceDaily" if key == "candidate_daily" else "instrumentCalendar"
            rows = doc.get(field)
            if not isinstance(rows, list):
                raise ValueError(f"{key}: expected list field {field}")
            item["row_count"] = len(rows)
            item["latest_source_dates"] = sorted({str(x.get("dEven")) for x in rows if x.get("dEven")}, reverse=True)[:10]
            if key == "candidate_daily":
                item["latest_positive_volume_rows"] = [
                    {k: row.get(k) for k in ("dEven", "hEven", "insCode", "pClosing", "pDrCotVal", "qTotTran5J", "qTotCap")}
                    for row in sorted(rows, key=lambda x: int(x.get("dEven", 0)), reverse=True)
                    if str(row.get("insCode")) == ins_code and float(row.get("qTotTran5J") or 0) > 0
                ][:10]
        else:
            doc = json.loads(body)
            rows = doc.get("instrumentShareChange")
            if not isinstance(rows, list) or any(str(x.get("insCode")) != ins_code for x in rows):
                raise ValueError("candidate_share_changes: missing list or insCode mismatch")
            item["row_count"] = len(rows)
            item["latest_source_dates"] = sorted({str(x.get("dEven")) for x in rows if x.get("dEven")}, reverse=True)[:10]
        entries.append(item)
    manifest = {
        "schema_version": 1, "dataset_id": "paper_v12_38_official_candidate_evidence",
        "account_id": account["account_id"], "candidate": candidate,
        "ins_code": ins_code, "sources": entries,
        "limits": [
            "Only public read-only official TSETMC endpoints were queried; no DB or order endpoint was used.",
            "LastPossibleDeven reports the latest completed session; it does not publish a future session schedule.",
            "Candidate calendar records dates with candidate price observations and is not, by itself, a market-wide session calendar.",
        ],
    }
    manifest_path = OUT / ("manifest.json" if not (OUT / "manifest.json").exists() else f"manifest_{run_id}.json")
    manifest["run_id"] = run_id
    manifest["manifest_path"] = str(manifest_path.relative_to(ROOT)).replace("\\", "/")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "latest-manifest.json").write_text(json.dumps({"run_id": run_id, "manifest_path": manifest["manifest_path"], "manifest_sha256": sha(manifest_path.read_bytes())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"dataset_id": manifest["dataset_id"], "sources": [{k: s[k] for k in ("key", "http_status", "http_date", "retrieved_at_utc", "raw_sha256", "reported_last_possible_session", "latest_source_dates", "latest_positive_volume_rows") if k in s} for s in entries]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
