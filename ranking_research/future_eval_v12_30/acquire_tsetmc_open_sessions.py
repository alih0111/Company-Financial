"""Fetch the official authenticated 20-session list, using a read-only bearer token."""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from http_retry import open_readonly

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ranking_research/output/paper_v12_38_first_fill/session_calendar"
URL = "https://api.tsetmc.com/MarketInfo/NSCStart"


def main() -> None:
    token = os.environ.get("TSETMC_READONLY_BEARER_TOKEN")
    if not token:
        raise SystemExit("MISSING_READ_ONLY_ACCESS: set TSETMC_READONLY_BEARER_TOKEN to a valid read-only TSETMC API bearer token; token value is never printed or saved.")
    now = dt.datetime.now(dt.timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ")
    req = urllib.request.Request(URL, data=b"{}", method="POST", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    })
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        response, attempts, retry_wait = open_readonly(req, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SystemExit("TSETMC_TOKEN_INVALID_OR_EXPIRED_HTTP_401; token value omitted")
        if exc.code == 403:
            raise SystemExit("TSETMC_PERMISSION_DENIED_HTTP_403; token value omitted")
        raise SystemExit(f"TSETMC_CALENDAR_HTTP_{exc.code}; token value omitted")
    except Exception as exc:
        raise SystemExit(f"TSETMC_CALENDAR_ACCESS_ERROR_{type(exc).__name__}; token value omitted")
    with response:
        raw = response.read(2_000_000)
        status, http_date = response.status, response.headers.get("Date")
    retrieved = dt.datetime.now(dt.timezone.utc).isoformat()
    doc = json.loads(raw)
    if status != 200 or doc.get("IsSuccess") is not True or not isinstance(doc.get("Data"), list):
        raise SystemExit("TSETMC_NSCSTART_RESPONSE_INVALID; no retry was attempted")
    records = doc["Data"]
    dates = [str(x.get("DEven", "")) for x in records]
    if not records or any(len(x) != 8 or not x.isdigit() for x in dates):
        raise SystemExit("TSETMC_NSCSTART_DATES_INVALID")
    OUT.mkdir(parents=True, exist_ok=True)
    raw_path = OUT / f"NSCStart.{run_id}.json.gz"
    raw_path.write_bytes(gzip.compress(raw, compresslevel=6))
    manifest = {
        "source": "TSETMC documented API MarketInfo/NSCStart",
        "url": URL, "method": "POST", "http_status": status,
        "http_date": http_date, "request_started_at_utc": started,
        "retrieved_at_utc": retrieved, "raw_path": str(raw_path.relative_to(ROOT)).replace("\\", "/"),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "request_attempts": attempts, "retry_wait_seconds": retry_wait,
        "session_count": len(records),
        "sessions": [{"DEven": str(x["DEven"]), "HEven": x.get("HEven"), "NSCEnd": str(x.get("NSCEnd", ""))} for x in records],
        "scope": "read-only; no future date is inferred; no DB or order endpoint",
    }
    path = OUT / f"NSCStart.{run_id}.manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(path.relative_to(ROOT)), "retrieved_at_utc": retrieved,
                      "session_count": len(records), "latest_session": max(dates),
                      "raw_sha256": manifest["raw_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
