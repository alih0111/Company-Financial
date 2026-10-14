"""Bounded official report-page probes for highest-impact missing exports.

Only catalog-provided Codal URLs; no URL guessing, captcha bypass or fact inference.
Responses are evidence, not automatically admitted financial inputs.
"""
import datetime as dt
import hashlib
import json
import time
import urllib.parse
import urllib.request
import pandas as pd
import collect_financial_history as H


def main():
    latest = H.C.read(H.ROOT / "qvt_backtest/output/roadmap_latest.json")
    queue = pd.read_csv(H.Path(latest["run_path"]) / "report_recovery_queue.csv", dtype=str)
    queue = queue[queue.gap_type.eq("not_archived") & pd.to_numeric(queue.potential_affected_dates).gt(0)].head(3)
    catalog = {str(r["letter"]["TracingNo"]): r for r in H.C.read(H.OUT / "catalog_versions.json")}
    out = H.OUT / "alternate_report_pages"
    out.mkdir(exist_ok=True)
    results = []
    for row in queue.to_dict("records"):
        tracing = row["tracing_no"]
        url = urllib.parse.urljoin("https://www.codal.ir/", catalog[tracing]["letter"].get("Url", ""))
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ("codal.ir", "www.codal.ir") or not parsed.path.startswith("/Reports/"):
            results.append({"tracing_no": tracing, "status": "no_allowed_catalog_report_url"})
            continue
        result = {"symbol": row["symbol"], "tracing_no": tracing, "source": url,
                  "observed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.codal.ir/"})
            with urllib.request.urlopen(req, timeout=20) as response:
                body = response.read(8 * 1024 * 1024)
                html = body.decode("utf8", "replace")
                result.update({"http_status": response.status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                               "has_tables": "<table" in html.lower(), "has_embedded_cells": '"cells"' in html,
                               "has_captcha": "captcha" in html.lower(), "has_million_rial_text": "میلیونریال" in H.P.norm_title(html)})
                (out / (tracing + ".html")).write_bytes(body)
                result["status"] = "human_verification_required" if result["has_captcha"] else "archived_for_format_review"
        except Exception as exc:
            result.update({"status": "request_failed", "error": str(exc)})
        results.append(result)
        H.C.write(out / "probe_summary.json", results)
        print(json.dumps({k: v for k, v in result.items() if k != "source"}, ensure_ascii=False), flush=True)
        if result.get("has_captcha"):
            break
        time.sleep(1.5)


if __name__ == "__main__":
    main()
