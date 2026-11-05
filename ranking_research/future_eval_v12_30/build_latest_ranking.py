"""Build a clearly historical P1/P3 ranking from the latest locked raw feature panel.

This is a read-only research display artifact. It never creates a prospective
snapshot, changes the locked contract, or writes to an evaluation ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ranking_research.future_eval_v12_28.engine import canonical_json, file_sha256
from ranking_research.return_v8.engine import scores as score_engine
from ranking_research.return_v8.features import FIELDS, penalties, ranks

PACK = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01"
CONTRACT_DIR = ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01"
SOURCE_PANEL = ROOT / "ranking_research/output/return_v12_23/v12_23_20261021_fresh_local_baseline_01/reconstruction/fresh_feature_panel.parquet"
OUT = ROOT / "ranking_research/output/return_v12_31/v12_31_20261022_latest_locked_ranking_01"
PUBLIC = ROOT / "client/public/research/v12-30"
FINANCIAL = [i for i in range(21) if i not in (15, 19, 20)]
METHOD_KEYS = {"P1": "valuation_0", "P3": "w0"}
VERSION = "v12.30-locked-ranking-display/1.0.0"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(panel_path: Path = SOURCE_PANEL, received_at: str | None = None, dataset_id: str = "v12_23_local_v3_archive_plus_pit_events_20261016") -> dict:
    contract_path = CONTRACT_DIR / "future_evaluation_contract.locked.json"
    contract_hash_path = CONTRACT_DIR / "future_evaluation_contract.sha256"
    universe_path = PACK / "frozen_universe_identity_map.csv"
    contract_hash = contract_hash_path.read_text(encoding="ascii").strip()
    if file_sha256(contract_path) != contract_hash:
        raise ValueError("LOCKED_CONTRACT_HASH_MISMATCH")
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    if contract.get("factor_order") != FIELDS:
        raise ValueError("LOCKED_FACTOR_ORDER_MISMATCH")
    universe = pd.read_csv(universe_path, dtype={"symbol": str, "company_id": str})
    panel = pd.read_parquet(panel_path)
    if sha(universe_path.read_bytes()) != "f62d72727591da1840abf6ce74a3f0b02d7fb51ba438ae614cc6df9aad27f9b0":
        raise ValueError("FROZEN_UNIVERSE_HASH_MISMATCH")
    if len(universe) != 254 or universe.symbol.duplicated().any() or universe.company_id.duplicated().any():
        raise ValueError("FROZEN_UNIVERSE_IDENTITY_INVALID")
    if not set(FIELDS).issubset(panel.columns) or not {"decision_time", "symbol", "company_id", "dq", "net_profit_ttm", "publication_cutoff", "price_date"}.issubset(panel.columns):
        raise ValueError("RAW_FEATURE_PANEL_SCHEMA_MISMATCH")

    latest_date = str(panel.decision_time.astype(str).max())
    if latest_date > datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat():
        raise ValueError("FUTURE_EVALUATION_DATE_REJECTED")
    rows = panel.loc[panel.decision_time.astype(str).eq(latest_date)].copy()
    expected = universe[["symbol", "company_id"]].astype(str).sort_values("symbol").reset_index(drop=True)
    actual = rows[["symbol", "company_id"]].astype(str).sort_values("symbol").reset_index(drop=True)
    if len(rows) != 254 or rows.symbol.duplicated().any() or not actual.equals(expected):
        raise ValueError("LATEST_PANEL_UNIVERSE_OR_IDENTITY_MISMATCH")
    if "symbol_index" in rows.columns:
        expected_index = universe.set_index("symbol").symbol_index
        if not rows.apply(lambda r: int(r.symbol_index) == int(expected_index.loc[str(r.symbol)]), axis=1).all():
            raise ValueError("PANEL_SYMBOL_INDEX_DIFFERS_FROM_FROZEN_UNIVERSE")
    else:
        rows = rows.merge(universe[["symbol", "symbol_index"]], on="symbol", how="left", validate="one_to_one")
    rows = rows.sort_values("symbol_index", kind="stable").reset_index(drop=True)

    raw = rows[FIELDS].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    observed = np.isfinite(raw)
    for index, upper in ((12, 60), (13, 100), (14, 30)):
        observed[:, index] &= (raw[:, index] > 0) & (raw[:, index] <= upper)
    net = pd.to_numeric(rows.net_profit_ttm, errors="coerce").to_numpy(dtype=float)
    dq = pd.to_numeric(rows.dq, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(dq).all() or (dq < 0).any():
        raise ValueError("DQ_INPUT_INVALID")
    raw_rank = ranks(raw)
    penalty = penalties(raw, net)

    scored: dict[str, np.ndarray] = {}
    coverage: dict[str, np.ndarray] = {}
    for method in ("P1", "P3"):
        method_contract = next(m for m in contract["methods"] if m["method_id"] == method)
        weights = np.asarray(method_contract["weights"], dtype=float)
        coverage[method] = (observed[:, FINANCIAL] @ weights[FINANCIAL]) / weights[FINANCIAL].sum()
        config = {"weights": weights, "vol_direction": "lower", "missing": "defaults", "penalties": True, "dq": True}
        tensor = {"rank": raw_rank[None, :, :], "observed": observed[None, :, :], "penalty": penalty[None, :, :], "dq": dq[None, :]}
        result = score_engine(tensor, config)[0]
        result[coverage[method] < 0.5] = np.nan
        scored[method] = result

    def method_ranks(method: str) -> list[int | None]:
        vals = scored[method]
        valid = np.flatnonzero(np.isfinite(vals))
        ordered = sorted(valid, key=lambda i: (-float(vals[i]), int(rows.iloc[i].symbol_index)))
        output: list[int | None] = [None] * len(rows)
        for rank_no, i in enumerate(ordered, 1):
            output[i] = rank_no
        return output

    rank_p1, rank_p3 = method_ranks("P1"), method_ranks("P3")
    factor_observed_counts = {name: int(observed[:, j].sum()) for j, name in enumerate(FIELDS)}
    publication_cutoffs = sorted(set(str(x) for x in rows.publication_cutoff.dropna()))
    if len(publication_cutoffs) != 1:
        raise ValueError("LATEST_PANEL_PUBLICATION_CUTOFF_NOT_COMMON")
    calculated = datetime.now(timezone.utc).isoformat()
    if received_at is not None:
        received_dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        if received_dt.tzinfo is None or received_dt > datetime.now(timezone.utc):
            raise ValueError("RECEIVED_AT_MUST_BE_REAL_AWARE_TIMESTAMP_NOT_IN_FUTURE")
    else:
        received_dt = None
    status = "HISTORICAL" if latest_date <= "2026-02-24" else "PREPARATION_UNCONFIRMED"
    entries = []
    for i, row in rows.iterrows():
        method_data = {}
        for method, rank_values in (("P1", rank_p1), ("P3", rank_p3)):
            score = float(scored[method][i]) if np.isfinite(scored[method][i]) else None
            method_data[method] = {
                "rank": rank_values[i],
                "score": score,
                "financial_factor_coverage": float(coverage[method][i]),
                "quality": ("SCORED_HISTORICAL" if status == "HISTORICAL" else "SCORED_PREPARATION_UNCONFIRMED") if score is not None else "UNSCORED_COVERAGE_BELOW_50_PERCENT",
                "scoreability_reason": None if score is not None else f"پوشش وزن‌دار {coverage[method][i]:.1%} است و از حداقل ۵۰٪ قفل‌شده کمتر است.",
            }
        px_date = None if pd.isna(row.price_date) or str(row.price_date) in ("None", "nan", "") else str(row.price_date)
        entries.append({
            "symbol": str(row.symbol), "company_id": str(row.company_id), "symbol_index": int(row.symbol_index),
            "identity_status": "FROZEN_IDENTITY_RESOLVED", "current_trading_status": "UNKNOWN_FROM_COMPATIBLE_SOURCE",
            "evaluation_date": latest_date, "price_effective_date": px_date,
            "publication_cutoff_at": publication_cutoffs[0], "received_at": received_at,
            "received_at_status": "ACTUAL_RECEIPT_TIME_PROVIDED" if received_at else "NOT_RECORDED_IN_SOURCE; file creation time is not substituted",
            "dq": float(dq[i]), "methods": method_data,
            "raw_factors": {name: (float(raw[i, j]) if np.isfinite(raw[i, j]) else None) for j, name in enumerate(FIELDS)},
            "observed_factors": {name: bool(observed[i, j]) for j, name in enumerate(FIELDS)},
            "defaulted_factors": [name for j, name in enumerate(FIELDS) if j in FINANCIAL and not observed[i, j]],
            "masked_factors": [name for j, name in enumerate(FIELDS) if j in FINANCIAL and np.isfinite(raw[i, j]) and not observed[i, j]],
            "scoreability_reason": None,
        })
    source_hashes = {
        "contract": file_sha256(contract_path), "contract_sha_file": file_sha256(contract_hash_path),
        "frozen_universe": file_sha256(universe_path), "raw_feature_panel": file_sha256(panel_path),
        "scorer_engine": file_sha256(ROOT / "ranking_research/return_v8/engine.py"),
        "factor_rules": file_sha256(ROOT / "ranking_research/return_v8/features.py"),
        "adapter_reference": file_sha256(ROOT / "ranking_research/future_eval_v12_29/prepare_snapshot.py"),
    }
    try:
        panel_display_path = str(panel_path.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        panel_display_path = str(panel_path.resolve())
    payload = {
        "schema_version": 1, "artifact_id": f"{dataset_id}-ranking-{latest_date}",
        "status": status, "status_detail": "بازامتیازدهی تاریخی." if status == "HISTORICAL" else "آماده‌سازی تأییدنشده؛ رتبهٔ رسمی یا ارزیابی آینده نیست.",
        "model": {"primary": {"id": "P1", "name": "valuation_0"}, "comparison": {"id": "P3", "name": "w0"}},
        "contract_id": contract["contract_id"], "contract_sha256": contract_hash,
        "scorer_version": VERSION, "scorer_sources": source_hashes,
        "evaluation_date": latest_date, "publication_cutoff_at": publication_cutoffs[0],
        "computed_at_utc": calculated, "computed_at_tehran": datetime.now(ZoneInfo("Asia/Tehran")).isoformat(),
        "received_at": received_at, "received_at_status": "ACTUAL_RECEIPT_TIME_PROVIDED" if received_at else "SOURCE DOES NOT RECORD ACTUAL RECEIPT TIME",
        "universe_count": len(entries), "scored_count": {m: int(np.isfinite(scored[m]).sum()) for m in ("P1", "P3")},
        "unscored_count": {m: int((~np.isfinite(scored[m])).sum()) for m in ("P1", "P3")},
        "factor_observed_counts": factor_observed_counts,
        "source": {"dataset_id": dataset_id, "path": panel_display_path, "sha256": source_hashes["raw_feature_panel"]},
        "identity_source": {"path": str(universe_path.relative_to(ROOT)).replace("\\", "/"), "sha256": source_hashes["frozen_universe"]},
        "limitations": [
            (f"Evaluation data effective date is {latest_date}; this result is a historical reconstruction and must not be presented as a live quote." if status == "HISTORICAL" else f"Evaluation data effective date is {latest_date}; preparation is unconfirmed and must not be presented as a live quote or official ranking."),
            "Publication cutoff is not source receipt time; the source has no recorded received_at.",
            "One common decision/evaluation date is used; per-row price_effective_date can be earlier or absent.",
            "Frozen identities are joined by exact company_id; current trading/listing status is not asserted.",
            "No prospective snapshot, O00 decision, order, return, NAV, or official ledger event was created.",
        ],
        "rows": entries,
    }
    payload["artifact_sha256"] = sha(canonical_json(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--public-dir", type=Path, default=PUBLIC)
    parser.add_argument("--panel", type=Path, default=SOURCE_PANEL)
    parser.add_argument("--received-at", help="Actual receipt timestamp with timezone; never infer it from publication cutoff.")
    parser.add_argument("--dataset-id", default="v12_23_local_v3_archive_plus_pit_events_20261016")
    args = parser.parse_args()
    payload = build(args.panel, args.received_at, args.dataset_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.public_dir.mkdir(parents=True, exist_ok=True)
    json_bytes = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    csv_path = args.output_dir / "latest-ranking.csv"
    json_path = args.output_dir / "latest-ranking.json"
    json_path.write_bytes(json_bytes)
    flat = []
    for row in payload["rows"]:
        flat.append({"evaluation_date": row["evaluation_date"], "symbol": row["symbol"], "company_id": row["company_id"], "symbol_index": row["symbol_index"],
                     "rank_p1": row["methods"]["P1"]["rank"], "score_p1": row["methods"]["P1"]["score"], "coverage_p1": row["methods"]["P1"]["financial_factor_coverage"],
                     "rank_p3": row["methods"]["P3"]["rank"], "score_p3": row["methods"]["P3"]["score"], "coverage_p3": row["methods"]["P3"]["financial_factor_coverage"],
                     "dq": row["dq"], "quality_p1": row["methods"]["P1"]["quality"], "reason_p1": row["methods"]["P1"]["scoreability_reason"],
                     "quality_p3": row["methods"]["P3"]["quality"], "reason_p3": row["methods"]["P3"]["scoreability_reason"],
                     "identity_status": row["identity_status"], "current_trading_status": row["current_trading_status"], "price_effective_date": row["price_effective_date"],
                     "publication_cutoff_at": row["publication_cutoff_at"], "received_at": row["received_at"], "scoreability_reason": row["scoreability_reason"],
                     "raw_factors_json": json.dumps(row["raw_factors"], ensure_ascii=False, separators=(",", ":")),
                     "observed_factors_json": json.dumps(row["observed_factors"], ensure_ascii=False, separators=(",", ":"))})
    pd.DataFrame(flat).to_csv(csv_path, index=False, encoding="utf-8-sig")
    # Publish the exact hashed outputs used by /ranking; never pick files by directory recency.
    shutil.copyfile(json_path, args.public_dir / "latest-ranking.json")
    shutil.copyfile(csv_path, args.public_dir / "latest-ranking.csv")
    gaps_path = args.output_dir / "current_ranking_input_gaps.fa.md"
    if gaps_path.exists():
        shutil.copyfile(gaps_path, args.public_dir / "current-ranking-input-gaps.fa.md")
    manifest = {"artifact_sha256": payload["artifact_sha256"], "json_sha256": file_sha256(json_path), "csv_sha256": file_sha256(csv_path),
                "public_json_sha256": file_sha256(args.public_dir / "latest-ranking.json"), "public_csv_sha256": file_sha256(args.public_dir / "latest-ranking.csv"),
                "status": payload["status"], "evaluation_date": payload["evaluation_date"], "contract_sha256": payload["contract_sha256"],
                "scored_count": payload["scored_count"], "unscored_count": payload["unscored_count"],
                "current_input_gaps_sha256": file_sha256(gaps_path) if gaps_path.exists() else None,
                "public_current_input_gaps_sha256": file_sha256(args.public_dir / "current-ranking-input-gaps.fa.md") if gaps_path.exists() else None,
                "official_ledger_written": False, "future_evaluation_activated": False}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
