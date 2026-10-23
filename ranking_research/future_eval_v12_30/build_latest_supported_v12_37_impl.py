"""Build a separate V12.37 ranking from immutable V12.36 inputs and the corrected extractor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("V1237_OUTPUT_DIR", str(ROOT / "ranking_research/output/return_v12_37/v12_37_20261022_existing_archive_extraction_fix_01")))
PUBLIC = ROOT / "client/public/research/v12-37"
BASE = ROOT / "ranking_research/future_eval_v12_30/rebuild_latest_supported_v12_37.py"
V36 = ROOT / "ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01"
V36_PANEL = V36 / "normalized_raw_factor_panel.parquet"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    spec = importlib.util.spec_from_file_location("v1235_source_build", ROOT / "ranking_research/future_eval_v12_30/build_latest_supported_v12_35.py")
    b = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = b
    spec.loader.exec_module(b)
    # Preserve the registered archive unchanged. For an explicit fresh market
    # package, derive current shares only from its official source responses.
    if not os.environ.get("V1237_MARKET_PACK"):
        b.update_current_shares = lambda: None
    b.BASE = BASE
    b.OUT = OUT
    b.MARKET = Path(os.environ.get("V1237_MARKET_PACK", str(b.MARKET)))
    # The fresh share snapshot is produced from official effective share events;
    # an existing validated snapshot is copied only in archive-only mode.
    market_share_copy = b.MARKET / "share_snapshot.json"
    if not market_share_copy.exists():
        import shutil
        market_share_copy.write_bytes(b.OLD_SHARE.read_bytes())
    b.main()
    extraction_manifest_path = OUT / "extraction_manifest.json"
    extraction_manifest = json.loads(extraction_manifest_path.read_text(encoding="utf-8"))
    extraction_manifest["network_requests"] = 0
    extraction_manifest["database_connections"] = 0
    extraction_manifest["source_reuse_note"] = "V12.37 reused local archived Codal inputs and the supplied versioned TSETMC market package; this extraction made no network or database call."
    extraction_manifest["financial_statement_selection"] = "income-statement factors are recalculated from the latest eligible income-statement chain; newer balance-only periods do not block them or relabel their period."
    extraction_manifest_path.write_text(json.dumps(extraction_manifest, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")

    rank_script = ROOT / "ranking_research/future_eval_v12_30/build_latest_ranking.py"
    subprocess.run([sys.executable, str(rank_script), "--panel", str(OUT / "normalized_raw_factor_panel.parquet"),
        "--output-dir", str(OUT / "ranking"), "--public-dir", str(PUBLIC),
        "--dataset-id", f"v12_37_balance_marker_safe_{os.environ.get('V1237_RANKING_DATE', '2026-10-21').replace('-', '')}"], check=True, cwd=ROOT)

    # Preserve the exact source lineage for the newly restored financial factors.
    panel = pd.read_parquet(OUT / "normalized_raw_factor_panel.parquet")
    old = pd.read_parquet(V36_PANEL).set_index("company_id")
    rank_path = OUT / "ranking/latest-ranking.json"
    rank = json.loads(rank_path.read_text(encoding="utf-8"))
    old_rank = json.loads((V36 / "ranking/latest-ranking.json").read_text(encoding="utf-8"))
    old_rows = {x["company_id"]: x for x in old_rank["rows"]}
    new_rows = {x["company_id"]: x for x in rank["rows"]}
    panel_by_id = panel.set_index("company_id", drop=False)
    sales_events_path = ROOT / "fundamental_event_research/monthly_sales_events_universe_v1_1.parquet"
    sales_events = pd.read_parquet(sales_events_path, columns=["published_at"])
    monthly_max_pub = pd.to_datetime(sales_events.published_at, errors="coerce", utc=True).max().isoformat()
    tsetmc_manifest_path = b.MARKET / "manifest.json"
    tsetmc_manifest = json.loads(tsetmc_manifest_path.read_text(encoding="utf-8"))
    received = sorted(x.get("retrieved_at_utc") or x.get("sources", {}).get("daily", {}).get("retrieved_at_utc")
                      for x in tsetmc_manifest["records"]
                      if x.get("retrieved_at_utc") or x.get("sources", {}).get("daily", {}).get("retrieved_at_utc"))
    for row in rank["rows"]:
        source = panel_by_id.loc[row["company_id"]]
        versions = json.loads(source.sales_lineage).get("selected_month_versions", [])
        pubs = [str(x.get("published_at")) for x in versions if x.get("published_at")]
        row.update({"financial_period_end": source.financial_period_end if pd.notna(source.financial_period_end) else None,
            "financial_latest_published_at": source.financial_latest_published_at if pd.notna(source.financial_latest_published_at) else None,
            "financial_factor_period_end": source.financial_factor_period_end if pd.notna(source.financial_factor_period_end) else None,
            "financial_factor_lineage": json.loads(source.financial_factor_lineage or "[]"),
            "monthly_sales_latest_period": json.loads(source.sales_lineage).get("latest_period"),
            "monthly_sales_latest_published_at": max(pubs) if pubs else None})
    rank["source_provenance"] = {
        "TSETMC": {"retrieved_at_range_utc": [received[0], received[-1]] if received else None, "retrieval_status": "KNOWN_FROM_CURRENT_RAW_MANIFEST",
            "source_manifest": str(tsetmc_manifest_path.relative_to(ROOT)).replace("\\", "/"),
            "universe_count": tsetmc_manifest.get("universe_count"), "completed_count": tsetmc_manifest.get("completed_count"),
            "failed_count": tsetmc_manifest.get("failed_count"), "latest_quote_dates": tsetmc_manifest.get("latest_quote_dates")},
        "financial_archive": {"latest_published_at": "2026-10-11T13:36:29+03:30", "latest_period_end": "2026-09-22",
            "received_at": None, "received_at_status": "UNKNOWN_IN_ARCHIVE", "source": "ranking_research/output/owner_current_inputs_20261014T215850582899Z/input_reports.json",
            "report_versions": 7321, "comparative_facts": 17393},
        "monthly_sales_archive": {"latest_published_at": monthly_max_pub, "received_at": None,
            "received_at_status": "UNKNOWN_IN_ARCHIVE", "latest_event_period": "1405-06", "source": "fundamental_event_research/monthly_sales_events_universe_v1_1.parquet"},
        "database_audit": {"read_only": True, "written": False, "summary": "ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01/ranking/local_source_inventory_audit.json"}}
    rank["limitations"].extend([
        "Financial observations are aligned to each selected income-statement period; these periods can be older than the latest balance-sheet period and are not relabeled as current.",
        "Financial archive and monthly-sales archive do not record actual receipt timestamps; no point-in-time availability is claimed.",
        "TSETMC retrieval time is explicitly recorded in its source manifest and is not treated as evidence that the data were known at evaluation time.",
    ])
    from ranking_research.future_eval_v12_28.engine import canonical_json
    rank.pop("artifact_sha256", None)
    rank["artifact_sha256"] = hashlib.sha256(canonical_json(rank)).hexdigest()
    rank_bytes = (json.dumps(rank, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    rank_path.write_bytes(rank_bytes)
    (PUBLIC / "latest-ranking.json").write_bytes(rank_bytes)
    gaps = []
    factors = ("operating_profit_growth", "net_profit_growth", "margin_trend", "earnings_quality")
    for row in panel.to_dict("records"):
        cid = str(row["company_id"])
        prior = old.loc[cid]
        a = old_rows[cid]["methods"]["P1"]
        n = new_rows[cid]["methods"]["P1"]
        missing = [f for f in factors if row.get(f) is None or pd.isna(row.get(f))]
        lineage = json.loads(row.get("financial_factor_lineage") or "[]")
        gaps.append({"symbol": row["symbol"], "company_id": cid, "v12_36_p1_score": a["score"], "v12_36_p1_coverage": a["financial_factor_coverage"],
            "v12_37_p1_score": n["score"], "v12_37_p1_coverage": n["financial_factor_coverage"],
            "scoreability_transition": "recovered" if a["score"] is None and n["score"] is not None else "lost" if a["score"] is not None and n["score"] is None else "unchanged",
            "coverage_gap_to_50pct": max(0.0, 0.5 - float(n["financial_factor_coverage"])),
            "income_factor_period": row.get("financial_factor_period_end"), "income_report_lineage": json.dumps(lineage, ensure_ascii=False),
            "missing_p1_weight_factors": "|".join(json.loads(new_rows[cid]["scoreability_reason"] is None and "[]" or "[]")),
            "missing_trend_quality_factors": "|".join(missing),
            "missing_factor_weights_p1": "|".join(f"{f}:{float(rank['contract_weights']['P1'][f]):.8f}" for f in missing) if rank.get("contract_weights") else "",
            "financial_report_source_status": "no_qualifying_income_report_found_in_available_period_chain" if not lineage else "raw_local_income_report_extracted_with_trace",
            "monthly_sales_source_status": "source_event_chain_present" if int(json.loads(row.get("sales_lineage") or "{}").get("known_months", 0) or 0) > 0 else "no_eligible_monthly_event_chain",
            "p1_reason": n["scoreability_reason"]})
    gaps_df = pd.DataFrame(gaps)
    # Add locked P1 coverage factors and weights as explicit, auditable columns.
    contract_path = ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    p1_weights = dict(zip(contract["factor_order"], next(x["weights"] for x in contract["methods"] if x["method_id"] == "P1")))
    for i, row in gaps_df.iterrows():
        rr = new_rows[row.company_id]
        missing_weighted = [f for f in contract["factor_order"] if f not in ("avg_trade_value_30d", "volatility_30d", "price_momentum_30d") and not rr["observed_factors"].get(f, False) and p1_weights[f] > 0]
        gaps_df.at[i, "missing_p1_weight_factors"] = "|".join(missing_weighted)
        gaps_df.at[i, "missing_factor_weights_p1"] = "|".join(f"{f}:{p1_weights[f]:.8f}" for f in missing_weighted)
        missing = set(missing_weighted)
        need = []
        financial_missing = missing.intersection({"revenue_growth", "operating_profit_growth", "net_profit_growth", "margin_trend", "earnings_quality"})
        if financial_missing:
            metric_map = {"revenue_growth": "درآمد", "operating_profit_growth": "سود عملیاتی", "net_profit_growth": "سود خالص", "margin_trend": "درآمد و سود عملیاتی", "earnings_quality": "سود عملیاتی و سایر اقلام غیرعملیاتی"}
            need.append("گزارش مالی والدِ آخرین دورهٔ واجد شرایط برای " + "؛ ".join(metric_map[x] for x in sorted(financial_missing)) + "; گزارش هم‌دورهٔ سال قبل/زنجیرهٔ لازم TTM و همهٔ اصلاحیه‌ها با TracingNo، published_at، period_end، واحد و basis.")
        if "sales_growth_12m" in missing:
            need.append("گزارش‌های فروش ماهانهٔ پیوسته 1403-07 تا 1405-06 (۲۴ ماه)، مبلغ فروش، ماه گزارش، TracingNo، زمان انتشار و پیوند اصلاحیه/جایگزینی.")
        if "sales_growth_3m" in missing:
            need.append("گزارش‌های فروش ماهانهٔ پیوسته 1405-01 تا 1405-06 (۶ ماه)، مبلغ فروش، TracingNo، زمان انتشار و اصلاحیه‌ها.")
        if "sales_stability" in missing:
            need.append("گزارش‌های فروش ماهانهٔ پیوسته 1404-07 تا 1405-06 (۱۲ ماه)، مبلغ فروش، TracingNo، زمان انتشار و اصلاحیه‌ها.")
        gaps_df.at[i, "specific_documents_needed"] = " | ".join(need) if need else "گزارش/مقدار دارای وزن P1 باقی نمانده؛ کمبود احتمالی فقط عامل‌های خارج از مخرج پوشش یا عامل صفر‌وزن است."
    gaps_df.to_csv(OUT / "ranking/company_factor_gaps_v12_37.csv", index=False, encoding="utf-8-sig")
    gaps_df.to_csv(PUBLIC / "company-factor-gaps.csv", index=False, encoding="utf-8-sig")
    csv_rank = pd.DataFrame([{"evaluation_date": r["evaluation_date"], "symbol": r["symbol"], "company_id": r["company_id"], "rank_p1": r["methods"]["P1"]["rank"],
        "score_p1": r["methods"]["P1"]["score"], "coverage_p1": r["methods"]["P1"]["financial_factor_coverage"], "rank_p3": r["methods"]["P3"]["rank"],
        "score_p3": r["methods"]["P3"]["score"], "price_date": r["price_effective_date"], "financial_period_end": r.get("financial_period_end"),
        "financial_factor_period_end": r.get("financial_factor_period_end"), "monthly_sales_latest_period": r.get("monthly_sales_latest_period"),
        "dq": r["dq"], "p1_reason": r["methods"]["P1"]["scoreability_reason"]} for r in rank["rows"]])
    csv_rank.to_csv(OUT / "ranking/latest-ranking.csv", index=False, encoding="utf-8-sig")
    csv_rank.to_csv(PUBLIC / "latest-ranking.csv", index=False, encoding="utf-8-sig")

    # Factor and per-symbol weighted coverage reconciliation; indices 15, 19, 20
    # remain excluded from the financial coverage denominator by contract.
    excluded = {"avg_trade_value_30d", "volatility_30d", "price_momentum_30d"}
    audit = []
    for f in contract["factor_order"]:
        if f in excluded:
            continue
        before = sum(bool(old_rows[c]["observed_factors"].get(f, False)) for c in old_rows)
        after = sum(bool(new_rows[c]["observed_factors"].get(f, False)) for c in new_rows)
        audit.append({"factor": f, "p1_weight": p1_weights[f], "v12_36_observed": before, "v12_37_observed": after,
            "gained": after-before, "weight_share_if_gained": p1_weights[f]*(after-before)/254/100})
    pd.DataFrame(audit).to_csv(OUT / "ranking/financial_factor_coverage_delta_v12_36_to_v12_37.csv", index=False, encoding="utf-8-sig")
    summary = {"universe": 254, "v12_36_p1_scored": old_rank["scored_count"]["P1"], "v12_37_p1_scored": rank["scored_count"]["P1"],
        "v12_36_p1_unscored": old_rank["unscored_count"]["P1"], "v12_37_p1_unscored": rank["unscored_count"]["P1"],
        "recovered_p1": int(((gaps_df.scoreability_transition == "recovered")).sum()), "lost_p1": int((gaps_df.scoreability_transition == "lost").sum()),
        "financial_weighted_coverage_mean_v12_36": float(sum(x["methods"]["P1"]["financial_factor_coverage"] for x in old_rank["rows"])/254),
        "financial_weighted_coverage_mean_v12_37": float(sum(x["methods"]["P1"]["financial_factor_coverage"] for x in rank["rows"])/254),
        "database_read_only": True, "database_written": False, "network_requests": 0, "official_ledger_written": False,
        "contract_sha256": rank["contract_sha256"], "v12_36_artifact_sha256": old_rank["artifact_sha256"], "v12_37_artifact_sha256": rank["artifact_sha256"],
        "factor_delta_csv": "financial_factor_coverage_delta_v12_36_to_v12_37.csv", "symbol_gaps_csv": "company_factor_gaps_v12_37.csv"}
    (OUT / "ranking/coverage_reconciliation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    # Rebuild hashes after metadata enrichment and attach source inventory evidence.
    manifest_path = OUT / "ranking/manifest.json"
    out_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_manifest.update({"artifact_sha256": rank["artifact_sha256"], "json_sha256": sha(rank_path), "csv_sha256": sha(OUT / "ranking/latest-ranking.csv"),
        "public_json_sha256": sha(PUBLIC / "latest-ranking.json"), "public_csv_sha256": sha(PUBLIC / "latest-ranking.csv"),
        "official_ledger_written": False, "future_evaluation_activated": False, "network_requests_during_v12_37_build": 0,
        "database_access": "READ_ONLY_SOURCE_AUDIT_ONLY; NO WRITES"})
    manifest_path.write_text(json.dumps(out_manifest, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    (OUT / "ranking/local_source_inventory_audit.json").write_text(json.dumps({
        "scope": "read-only local source audit; no database writes", "database_tables": {
            "dbo.CodalReports": {"rows":65,"completed":45,"failed":6,"unsupported":14,"max_published_at":"2026-10-01T10:42:47"},
            "dbo.mahane": {"rows":12122,"companies":193,"exact_frozen_symbol_matches":182,"period_range":"1398/10/30..1405/06/31","rows_with_event_value_crosswalk":9612,"crosswalk_companies":163,"db_Value3_to_event_rial_ratio":0.000001,"unit":"million rial (confirmed by exact crosswalk)"},
            "dbo.miandore2": {"rows":6865,"companies":267,"exact_frozen_symbol_matches":247,"period_range":"1398/01/31..1405/05/31","native_retrieval_timestamp_or_tracing_id":False},
            "dbo.statements": {"rows":5920,"companies":1,"period_range":"1400/09/30..1405/03/31","unit_codes":["unknown"],"usable_for_frozen_universe":False}},
        "local_archives": {"raw_financial_report_files":332,"raw_financial_companies":118,"financial_cache_files":256,"financial_cache_company_ids":256,
            "owner_input_reports":7321,"verified_comparative_facts":17393,"monthly_sales_event_rows":12183,"monthly_sales_companies":164},
        "limitations": ["DB financial rows have no Codal tracing number or published_at; they are not used to repair the verified report lineage.",
            "The monthly-sales database value has a proven 1e6 unit conversion against 9,612 event rows, but DB rows have no source tracing/published_at or correction chain, so are not substituted into the contract event chain.",
            "Raw archived report/cache sources exist for all 192 V12.35 unscored company IDs; 104 gained a valid score after correcting statement-type selection. Remaining gaps are listed in company_factor_gaps_v12_37.csv.",
            "Codal HTTP 429 attempt is retained in V12.35. Its Retry-After header was not captured; no further request was made without a verifiable retry time."]},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
