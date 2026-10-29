"""Build a separate Oct-21 ranking with official TSETMC prices and unchanged V12 contract."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "ranking_research/future_eval_v12_30/rebuild_latest_supported_v12_34.py"
MARKET = Path(os.environ.get("V1237_MARKET_PACK", str(ROOT / "ranking_research/output/return_v12_35/official_tsetmc_20261022")))
OUT = Path(os.environ.get("V1237_OUTPUT_DIR", str(ROOT / "ranking_research/output/return_v12_35/v12_35_20261022_latest_supported_official_market_01")))
OLD_SHARE = ROOT / "ranking_research/output/data_collection_20261014T201505878357Z/market_all_symbols.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builder():
    spec = importlib.util.spec_from_file_location("locked_v1234_rebuild", BASE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.DATE = os.environ.get("V1237_RANKING_DATE", "2026-10-21")
    module.PACK = MARKET
    module.SHARE_PATH = MARKET / "share_snapshot.json"
    module.OUT = OUT
    return module


def update_current_shares():
    """Use exact official effective share counts after the Oct-14 local snapshot."""
    snap = json.loads(OLD_SHARE.read_text(encoding="utf-8"))
    m = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
    by_id = {str(r.get("id")): r for r in snap.get("rows", []) if r.get("id") is not None}
    source_rows = []
    for item in m["records"]:
        changes = [x for x in item.get("share_changes", [])
                   if str(x.get("insCode")) == str(item["ins_code"])
                   and str(x.get("dEven", "")).isdigit()
                   and x.get("numberOfShareNew") is not None]
        latest = max(changes, key=lambda x: int(x["dEven"])) if changes else None
        previous = by_id.get(str(item["ins_code"]))
        if latest:
            row = previous or {"id": item["ins_code"], "l18": item["symbol"]}
            if previous is None:
                snap.setdefault("rows", []).append(row)
                by_id[str(item["ins_code"])] = row
            row["z"] = float(latest["numberOfShareNew"])
            source_rows.append({"company_id": item["company_id"], "symbol": item["symbol"],
                "ins_code": item["ins_code"], "effective_date": str(latest["dEven"]),
                "number_of_shares": float(latest["numberOfShareNew"]),
                "source_url": item["sources"]["share_change"]["url"],
                "retrieved_at_utc": item["sources"]["share_change"]["retrieved_at_utc"],
                "raw_sha256": item["sources"]["share_change"]["raw_sha256"],
                "inherited_previous_snapshot": False})
        else:
            source_rows.append({"company_id": item["company_id"], "symbol": item["symbol"],
                "ins_code": item["ins_code"], "effective_date": None,
                "number_of_shares": float(previous["z"]) if previous and previous.get("z") else None,
                "source_url": item.get("sources", {}).get("share_change", {}).get("url"),
                "retrieved_at_utc": item.get("sources", {}).get("share_change", {}).get("retrieved_at_utc"),
                "raw_sha256": item.get("sources", {}).get("share_change", {}).get("raw_sha256"),
                "inherited_previous_snapshot": True})
    snap["collected_at"] = m["retrieved_at_utc"]
    snap["source"] = "TSETMC GetInstrumentShareChange latest effective share event per identity; prior snapshot retained only where source had no event"
    path = MARKET / "share_snapshot.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    pd.DataFrame(source_rows).to_csv(MARKET / "share_updates.csv", index=False, encoding="utf-8-sig")


def main():
    update_current_shares()
    b = load_builder()
    b.main()
    manifest_path = OUT / "extraction_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    official = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
    report_archive = b.REPORTS_PATH
    comparisons = b.COMPARATIVES_PATH
    reports = json.loads(report_archive.read_text(encoding="utf-8"))
    events = pd.read_parquet(b.EVENTS)
    market_records = official["records"]
    manifest.update({
        "dataset_id": os.environ.get("V1237_DATASET_ID", "v12_35_official_tsetmc_owner_local_fundamentals_20261021"),
        "status": "PREPARATION_UNCONFIRMED",
        "evaluation_date": manifest["evaluation_date"],
        "publication_cutoff_at": manifest["publication_cutoff_at"],
        "received_at": official["retrieved_at_utc"],
        "receipt_limitation": "TSETMC receipt timestamps are observed now and do not prove historical availability. Codal report/event archives lack actual receipt timestamps; no PIT claim is made.",
        "network_requests": 0,
        "database_connections": 0,
        "package_installs": 0,
        "official_ledger_written": False,
        "source_dates": {
            "evaluation_price_latest": str(pd.to_datetime(pd.read_parquet(OUT / "normalized_raw_factor_panel.parquet")["price_date"], errors="coerce").max().date()),
            "tsetmc_last_trade_date_by_symbol": {str(k): int(v) for k, v in pd.Series([x.get("latest_quote_date") for x in market_records]).value_counts(dropna=False).items()},
            "tsetmc_daily_retrieved_at": "per source record in the pinned market package manifest",
            "tsetmc_share_change_retrieved_at": "per source record in the pinned market package manifest",
            "financial_latest_published_at": max(r["published_at"] for r in reports),
            "financial_latest_period_end": max(r["period_end"] for r in reports),
            "monthly_sales_latest_published_at": str(events.published_at.max()),
            "monthly_sales_latest_event_month": str(events.period_end.max()),
            "codal_received_at": None,
            "corporate_action_adjustment_cache_effective_through": "2026-09-30",
        },
        "official_sources": {
            "tsetmc": {"manifest_path": str((MARKET / "manifest.json").relative_to(ROOT)).replace("\\", "/"),
                "manifest_sha256": sha(MARKET / "manifest.json"), "company_count": len(market_records),
                "daily_endpoint": "local pinned market raw; no request in this run",
                "share_change_endpoint": "local pinned market raw; no request in this run",
                "all_raw_hashes_recorded": True},
            "codal": {"attempted_historically": True, "evidence_scope": "archived_attempt; not this offline invocation",
                "archived_url": "https://search.codal.ir/api/search/v2/q", "archived_http_status": 429,
                "archived_response_body_sha256": None, "archived_request_count": 2, "archived_attempts": 1,
                "preliminary_attempt_body_or_timestamp_retained": False, "retried_or_bypassed": False,
                "requests_during_this_offline_reuse": 0,
                "local_financial_archive_used": str(report_archive.relative_to(ROOT)).replace("\\", "/"),
                "local_monthly_archive_used": str(b.EVENTS.relative_to(ROOT)).replace("\\", "/")},
        },
        "scoreability_notes": [
            "Contract, weights, frozen 254 identities, masks, coverage threshold, DQ and tie rules are unchanged.",
            "Volatility_30d and price_momentum_30d remain masked for all symbols because the locally confirmed price-adjustment chain ends 2026-09-30; the TSETMC share-change feed does not certify a complete adjusted-price corporate-action chain.",
            "Owner financial and monthly sales archives are reused without changing their published_at. Actual Codal receipt time is not available.",
            "Market source timestamps are retained per record in the pinned package manifest; they do not establish earlier point-in-time availability.",
        ],
        "official_tsetmc_source_manifest_sha256": sha(MARKET / "manifest.json"),
        "share_updates_sha256": sha(MARKET / "share_updates.csv"),
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "panel": str(OUT / "normalized_raw_factor_panel.parquet"),
        "evaluation_date": manifest["evaluation_date"], "factor_observed_counts": manifest["factors"]["factor_observed_counts"],
        "network_requests": manifest["network_requests"], "TSETMC_records": len(market_records)}, ensure_ascii=False))


if __name__ == "__main__": main()
