"""Build an auditable, non-scoring factor coverage table for a verified build."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd

from scripts.verify_isolated_rebuild import file_sha, strict_json, verify


MONTHLY = {"sales_growth_12m", "sales_growth_3m", "sales_stability"}
VALUATION = {"pe", "ps", "pb"}
MARKET = {"avg_trade_value_30d", "volatility_30d", "price_momentum_30d"}
UNITS = {
    "sales_growth_12m": "percent", "sales_growth_3m": "percent", "revenue_growth": "percent",
    "operating_profit_growth": "percent", "net_profit_growth": "percent", "operating_margin": "percent",
    "net_margin": "percent", "roe": "percent", "margin_trend": "percentage_points",
    "interest_coverage": "ratio", "cash_conversion": "ratio", "earnings_quality": "percent",
    "pe": "ratio", "ps": "ratio", "pb": "ratio", "avg_trade_value_30d": "rial_per_session",
    "sales_stability": "unitless", "leverage": "ratio", "current_ratio": "ratio",
    "volatility_30d": "percent", "price_momentum_30d": "percent",
}


def coverage_rows(panel: pd.DataFrame, rank: dict, contract: dict, extraction: dict) -> list[dict]:
    fields = contract["factor_order"]
    if len(fields) != len(set(fields)) or set(fields) != set(UNITS):
        raise ValueError("COVERAGE_FACTOR_CONTRACT_MISMATCH")
    methods = {m["method_id"]: dict(zip(fields, m["weights"], strict=True)) for m in contract["methods"]}
    if set(methods) != {"P1", "P3"}:
        raise ValueError("COVERAGE_METHOD_CONTRACT_MISMATCH")
    by_id = {str(row["company_id"]): row for row in rank["rows"]}
    if len(by_id) != len(rank["rows"]) or panel["company_id"].astype(str).duplicated().any():
        raise ValueError("COVERAGE_DUPLICATE_IDENTITY")
    if set(by_id) != set(panel["company_id"].astype(str)):
        raise ValueError("COVERAGE_IDENTITY_MISMATCH")
    rows = []
    for item in panel.to_dict("records"):
        current = by_id[str(item["company_id"])]
        if str(item["symbol"]) != str(current["symbol"]):
            raise ValueError("COVERAGE_SYMBOL_MISMATCH")
        for factor in fields:
            raw = item.get(factor)
            value = float(raw) if raw is not None and pd.notna(raw) and math.isfinite(float(raw)) else None
            rank_value = current["raw_factors"][factor]
            if (value is None) != (rank_value is None) or (value is not None and not math.isclose(value, float(rank_value), rel_tol=1e-10, abs_tol=1e-8)):
                raise ValueError("COVERAGE_VALUE_MISMATCH:" + factor)
            observed = current["observed_factors"][factor]
            if not isinstance(observed, bool) or (observed and value is None):
                raise ValueError("COVERAGE_OBSERVED_MASK_INVALID:" + factor)
            group = "monthly_sales" if factor in MONTHLY else "valuation" if factor in VALUATION else "market" if factor in MARKET else "financial"
            if observed:
                reason = None
            elif factor in current.get("masked_factors", []):
                reason = "VALUE_REJECTED_BY_MODEL_MASK"
            elif factor in ("volatility_30d", "price_momentum_30d") and "masked:" in str(extraction["factors"].get(factor, "")):
                reason = "CORPORATE_ACTION_CHAIN_NOT_VERIFIED_AFTER_2026_09_30"
            elif group == "monthly_sales" and item.get("sales_lineage"):
                recorded = json.loads(item["sales_lineage"]).get("missing_reasons", {}).get(factor)
                allowed = {"no_verified_values", "insufficient_or_noncontiguous_24m", "insufficient_or_noncontiguous_6m",
                           "insufficient_or_noncontiguous_12m", "zero_denominator"}
                reason = "MONTHLY_" + recorded.upper() if recorded in allowed else "MISSING_REASON_NOT_RECORDED"
            else:
                reason = "MISSING_REASON_NOT_RECORDED"
            sales_context = item.get("sales_lineage") if group == "monthly_sales" else None
            financial_context = item.get("financial_factor_lineage") if group in ("financial", "valuation") else None
            valuation_context = item.get("valuation_provenance") if group == "valuation" else None
            rows.append({
                "company_id": str(item["company_id"]), "symbol": str(item["symbol"]), "factor": factor,
                "group": group, "value": value, "unit": UNITS[factor], "model_observed": observed,
                "model_defaulted": factor in current.get("defaulted_factors", []), "missing_reason": reason,
                "p1_weight": methods["P1"][factor], "p3_weight": methods["P3"][factor],
                "p1_missing_weight": 0 if observed else methods["P1"][factor],
                "p3_missing_weight": 0 if observed else methods["P3"][factor],
                "included_in_financial_coverage": factor not in MARKET,
                "p1_missing_coverage_weight": methods["P1"][factor] if not observed and factor not in MARKET else 0,
                "p3_missing_coverage_weight": methods["P3"][factor] if not observed and factor not in MARKET else 0,
                "p1_score": current["methods"]["P1"]["score"], "p3_score": current["methods"]["P3"]["score"],
                "p1_financial_coverage": current["methods"]["P1"].get("financial_factor_coverage"),
                "p3_financial_coverage": current["methods"]["P3"].get("financial_factor_coverage"),
                "p1_scoreability_reason": current["methods"]["P1"]["scoreability_reason"],
                "p3_scoreability_reason": current["methods"]["P3"]["scoreability_reason"],
                "evaluation_date": rank["evaluation_date"], "ranking_artifact_sha256": rank["artifact_sha256"],
                "financial_period_context": current.get("financial_factor_period_end") if group in ("financial", "valuation") else None,
                "financial_publication_context": current.get("financial_latest_published_at") if group in ("financial", "valuation") else None,
                "monthly_period_context": current.get("monthly_sales_latest_period") if group == "monthly_sales" else None,
                "monthly_publication_context": current.get("monthly_sales_latest_published_at") if group == "monthly_sales" else None,
                "price_date_context": current.get("price_effective_date") if group in ("market", "valuation") else None,
                "price_age_days_context": item.get("price_age_days") if group in ("market", "valuation") else None,
                "financial_age_days_context": item.get("financial_age_days") if group in ("financial", "valuation") else None,
                "received_at": None, "received_at_status": "NOT_PROVEN_PER_FACTOR",
                "financial_lineage_context": financial_context, "sales_lineage_context": sales_context,
                "valuation_lineage_context": valuation_context,
            })
    return rows


def build(output: Path, public: Path, source_root: Path, contract_path: Path, destination: Path) -> dict:
    verification = verify(output, public, source_root)
    rank = strict_json(output / "ranking/latest-ranking.json")
    extraction = strict_json(output / "extraction_manifest.json")
    if file_sha(contract_path) != rank["contract_sha256"]:
        raise ValueError("COVERAGE_CONTRACT_HASH_MISMATCH")
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    rows = coverage_rows(pd.read_parquet(output / "normalized_raw_factor_panel.parquet"), rank, contract, extraction)
    scored = {method: sum(row["methods"][method]["score"] is not None for row in rank["rows"])
              for method in ("P1", "P3")}
    if scored != rank["scored_count"]:
        raise ValueError("COVERAGE_SCOREABILITY_COUNT_MISMATCH")
    destination.mkdir(parents=True, exist_ok=False)
    table = destination / "factor_coverage.csv"
    pd.DataFrame(rows).to_csv(table, index=False, encoding="utf-8-sig")
    missing_by_factor = Counter(row["factor"] for row in rows if not row["model_observed"])
    missing_weight = {method: {factor: sum(row[f"{method.lower()}_missing_weight"] for row in rows if row["factor"] == factor)
                               for factor in contract["factor_order"]} for method in ("P1", "P3")}
    coverage_weight = {method: {factor: sum(row[f"{method.lower()}_missing_coverage_weight"] for row in rows if row["factor"] == factor)
                                for factor in contract["factor_order"]} for method in ("P1", "P3")}
    summary = {"scope": f"Frozen {len(rank['rows'])}-company research universe, not the whole market; context dates are not per-factor receipt proof.",
               "ranking_artifact_sha256": rank["artifact_sha256"], "contract_sha256": rank["contract_sha256"],
               "input_hashes_verified": verification["input_hashes_verified"], "rows": len(rows),
               "companies": len(rank["rows"]), "factors": len(contract["factor_order"]),
               "scored_count": scored, "unobserved_by_factor": dict(missing_by_factor),
               "missing_weight_sum_by_factor": missing_weight,
               "financial_coverage_missing_weight_sum_by_factor": coverage_weight,
               "missing_weight_unit": "contract weight points summed across companies; not a coverage percentage",
               "unobserved_reasons": dict(Counter(row["missing_reason"] for row in rows if row["missing_reason"])),
               "table_sha256": file_sha(table)}
    (destination / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.public, args.source_root, args.contract, args.destination), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
