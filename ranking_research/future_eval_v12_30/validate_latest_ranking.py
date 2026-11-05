"""Recompute and validate a published locked-factor ranking artifact."""
from __future__ import annotations

import json
import hashlib
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ranking_research.future_eval_v12_30.build_latest_ranking import OUT, build
from ranking_research.return_v8.engine import scores as locked_score
from ranking_research.return_v8.features import FIELDS, penalties, ranks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=OUT)
    parser.add_argument("--panel", type=Path, default=ROOT / "ranking_research/output/return_v12_23/v12_23_20261021_fresh_local_baseline_01/reconstruction/fresh_feature_panel.parquet")
    parser.add_argument("--received-at")
    parser.add_argument("--dataset-id", default="v12_23_local_v3_archive_plus_pit_events_20261016")
    args = parser.parse_args()
    saved = json.loads((args.artifact_dir / "latest-ranking.json").read_text(encoding="utf-8-sig"))
    expected = build(args.panel, args.received_at, args.dataset_id)
    saved_hash = saved.pop("artifact_sha256")
    calculated_hash = hashlib.sha256(json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    saved["artifact_sha256"] = saved_hash
    if saved_hash != calculated_hash:
        raise SystemExit("ARTIFACT_CONTENT_HASH_MISMATCH")
    if saved["contract_sha256"] != expected["contract_sha256"] or saved["source"] != expected["source"]:
        raise SystemExit("RANKING_SOURCE_OR_CONTRACT_MISMATCH")
    panel = pd.read_parquet(args.panel)
    latest = panel.loc[panel.decision_time.astype(str).eq(expected["evaluation_date"])].copy()
    universe_path = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv"
    universe = pd.read_csv(universe_path, dtype={"symbol": str, "company_id": str})
    if "symbol_index" in latest.columns:
        expected_index = universe.set_index("symbol").symbol_index
        if not latest.apply(lambda r: int(r.symbol_index) == int(expected_index.loc[str(r.symbol)]), axis=1).all():
            raise ValueError("PANEL_SYMBOL_INDEX_DIFFERS_FROM_FROZEN_UNIVERSE")
    else:
        latest = latest.merge(universe[["symbol", "symbol_index"]], on="symbol", validate="one_to_one")
    latest = latest.sort_values("symbol_index", kind="stable")
    raw = latest[FIELDS].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    observed = np.isfinite(raw)
    for j, upper in ((12, 60), (13, 100), (14, 30)):
        observed[:, j] &= (raw[:, j] > 0) & (raw[:, j] <= upper)
    dq = pd.to_numeric(latest.dq, errors="coerce").to_numpy(float)
    net = pd.to_numeric(latest.net_profit_ttm, errors="coerce").to_numpy(float)
    tensor = {"rank": ranks(raw)[None, :, :], "observed": observed[None, :, :], "penalty": penalties(raw, net)[None, :, :], "dq": dq[None, :]}
    contract = json.loads((ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json").read_text(encoding="utf-8-sig"))
    checks = {"all_254_frozen_identities_retained": len(saved["rows"]) == 254 and len({r["company_id"] for r in saved["rows"]}) == 254,
              "recomputed_payload_matches_saved_source_snapshot": all(a["symbol"] == b["symbol"] and a["company_id"] == b["company_id"] and a["raw_factors"] == b["raw_factors"] and a["methods"] == b["methods"] for a, b in zip(saved["rows"], expected["rows"])),
              "status_matches_data_date_and_receipt_is_unknown": saved["status"] == expected["status"] and saved["received_at"] is None and all(r["received_at"] is None for r in saved["rows"]),
              "not_prospective_and_no_ledger": saved["evaluation_date"] == expected["evaluation_date"] and not (args.artifact_dir / "official_event_ledger.jsonl").exists()}
    direct_scores = {}
    for method in ("P1", "P3"):
        weights = next(m["weights"] for m in contract["methods"] if m["method_id"] == method)
        values = locked_score(tensor, {"weights": np.asarray(weights), "vol_direction": "lower", "missing": "defaults", "penalties": True, "dq": True})[0]
        # The scoreability cutoff is the locked >=50% weighted coverage rule.
        fin = [i for i in range(21) if i not in (15, 19, 20)]
        coverage = (observed[:, fin] @ np.asarray(weights)[fin]) / np.asarray(weights)[fin].sum()
        values[coverage < 0.5] = np.nan
        direct_scores[method] = values
        stored = np.asarray([r["methods"][method]["score"] if r["methods"][method]["score"] is not None else np.nan for r in saved["rows"]])
        checks[f"{method}_scores_match_locked_return_v8_engine"] = bool(np.allclose(stored, values, rtol=0, atol=1e-12, equal_nan=True))
        ranked = np.flatnonzero(np.isfinite(values))
        expected_order = sorted(ranked, key=lambda i: (-float(values[i]), int(saved["rows"][i]["symbol_index"])))
        expected_ranks = np.full(254, np.nan)
        for rank_no, i in enumerate(expected_order, 1): expected_ranks[i] = rank_no
        actual_ranks = np.asarray([r["methods"][method]["rank"] if r["methods"][method]["rank"] is not None else np.nan for r in saved["rows"]], dtype=float)
        checks[f"{method}_ties_and_rank_order_match_contract"] = bool(np.array_equal(np.isnan(actual_ranks), np.isnan(expected_ranks)) and np.allclose(actual_ranks, expected_ranks, equal_nan=True))
        checks[f"{method}_score_count_matches_manifest"] = int(np.isfinite(values).sum()) == saved["scored_count"][method]
    checks["historical_common_date_and_cutoff"] = len({r["evaluation_date"] for r in saved["rows"]}) == 1 and len({r["publication_cutoff_at"] for r in saved["rows"]}) == 1
    if not all(checks.values()):
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        raise SystemExit("RANKING_VALIDATION_FAILED")
    report = {"status": "PASS", "checks": checks, "contract_sha256": saved["contract_sha256"], "artifact_sha256": saved["artifact_sha256"],
              "evaluation_date": saved["evaluation_date"], "scored_count": saved["scored_count"], "unscored_count": saved["unscored_count"],
              "all_254_symbols_present": True, "official_ledger_written": False}
    (args.artifact_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
