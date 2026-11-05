"""Convert a normalized, contract-factor panel into a V12.28 snapshot candidate.

This adapter never reads stored model scores. It accepts raw V12.28 factor values,
observation masks, a fixed identity map, and a complete O00 calendar extension.
It writes only to the caller-selected preparation path; it never touches a ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V28 = ROOT / "ranking_research/future_eval_v12_28"
OUT28 = ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01"
sys.path.insert(0, str(ROOT))
from ranking_research.future_eval_v12_28.engine import canonical_json, file_sha256, snapshot_content_hash, validate_snapshot
from ranking_research.return_v8.engine import scores as v8_scores
from ranking_research.return_v8.features import FIELDS, penalties, ranks

FINANCIAL = [i for i in range(21) if i not in (15, 19, 20)]
METHOD_KEYS = {"P1": "valuation_0", "P3": "w0"}
HISTORY_HASH = "879e1361624c62868a722245d612396fa7f756ca4ee0911359dc7e996b52c14b"
FROZEN_UNIVERSE_SHA256 = "f62d72727591da1840abf6ce74a3f0b02d7fb51ba438ae614cc6df9aad27f9b0"


def sha256(path: Path) -> str:
    return file_sha256(path)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_snapshot(panel_path: Path, universe_path: Path, calendar_path: Path, meta_path: Path, contract_path: Path, contract_sha_path: Path) -> dict:
    panel = pd.read_csv(panel_path, encoding="utf-8-sig")
    universe = pd.read_csv(universe_path, encoding="utf-8-sig", dtype={"symbol": str, "company_id": str})
    cal = pd.read_csv(calendar_path, encoding="utf-8-sig", dtype={"date_gregorian": str})
    meta = load_json(meta_path)
    contract = load_json(contract_path)
    contract_sha = contract_sha_path.read_text(encoding="ascii").strip()
    if sha256(contract_path) != contract_sha:
        raise ValueError("LOCKED_CONTRACT_HASH_MISMATCH")
    if sha256(universe_path) != FROZEN_UNIVERSE_SHA256:
        raise ValueError("FROZEN_UNIVERSE_HASH_MISMATCH")
    required_u = {"symbol", "company_id", "symbol_index"}
    if not required_u.issubset(universe.columns) or universe.empty:
        raise ValueError("UNIVERSE_SCHEMA_INVALID")
    if universe.symbol.duplicated().any() or universe.company_id.duplicated().any() or universe.symbol_index.duplicated().any():
        raise ValueError("UNIVERSE_IDENTITY_CONFLICT")
    universe = universe.sort_values("symbol_index", kind="stable").reset_index(drop=True)
    if universe.symbol_index.astype(int).tolist() != list(range(len(universe))):
        raise ValueError("UNIVERSE_INDEX_NOT_CONTIGUOUS")
    if len(universe) != int(meta.get("expected_universe_count", 254)):
        raise ValueError("UNIVERSE_SIZE_MISMATCH")
    required_panel = {"symbol", "company_id", "net_profit_ttm", "dq", *FIELDS, *(f"observed_{name}" for name in FIELDS)}
    if not required_panel.issubset(panel.columns):
        raise ValueError("RAW_FACTOR_PANEL_COLUMNS_MISSING")
    if panel.symbol.duplicated().any() or panel.company_id.duplicated().any():
        raise ValueError("PANEL_IDENTITY_CONFLICT")
    expected = universe[["symbol", "company_id"]].astype(str).sort_values("symbol", kind="stable").reset_index(drop=True)
    actual = panel[["symbol", "company_id"]].astype(str).sort_values("symbol", kind="stable").reset_index(drop=True)
    if not actual.equals(expected):
        raise ValueError("PANEL_UNIVERSE_IDENTITY_OR_COVERAGE_MISMATCH")
    for name in FIELDS:
        mask = panel[f"observed_{name}"]
        if not mask.isin([True, False, 0, 1]).all():
            raise ValueError(f"OBSERVATION_MASK_INVALID:{name}")
    raw = panel[FIELDS].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    observed = np.column_stack([panel[f"observed_{name}"].astype(bool).to_numpy() for name in FIELDS])
    observed &= np.isfinite(raw)
    for index, upper in ((12, 60), (13, 100), (14, 30)):
        observed[:, index] &= (raw[:, index] > 0) & (raw[:, index] <= upper)
    net = pd.to_numeric(panel.net_profit_ttm, errors="coerce").to_numpy(dtype=float)
    dq = pd.to_numeric(panel.dq, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(dq).all() or (dq < 0).any():
        raise ValueError("DQ_INPUT_INVALID")
    raw_rank = ranks(raw)
    penalty = penalties(raw, net)
    methods = contract["methods"]
    coverage = {}
    for method, weight_key in METHOD_KEYS.items():
        w = np.asarray(next(item["weights"] for item in methods if item["method_id"] == method), dtype=float)
        active = w[FINANCIAL]
        coverage[method] = (observed[:, FINANCIAL] @ active) / active.sum()
    score_results = {}
    for method, weight_key in METHOD_KEYS.items():
        method_contract = next(item for item in methods if item["method_id"] == method)
        config = {"weights": np.asarray(method_contract["weights"], dtype=float), "vol_direction": "lower", "missing": "defaults", "penalties": True, "dq": True}
        tensor = {"rank": raw_rank[None, :, :], "observed": observed[None, :, :], "penalty": penalty[None, :, :], "dq": dq[None, :]}
        score_results[method] = v8_scores(tensor, config)[0]
    if len(cal) < 2 or not {"global_session_index", "date_gregorian"}.issubset(cal.columns):
        raise ValueError("CALENDAR_SCHEMA_INVALID")
    cal = cal.sort_values("global_session_index", kind="stable")
    indices = cal.global_session_index.astype(int).tolist()
    dates = cal.date_gregorian.astype(str).tolist()
    if indices != list(range(indices[0], indices[-1] + 1)) or dates != sorted(set(dates)):
        raise ValueError("CALENDAR_GAP_OR_DUPLICATE")
    if indices[0] != 1166 or dates[0] <= "2026-02-24":
        raise ValueError("CALENDAR_EXTENSION_MUST_CONTINUE_AFTER_LOCKED_PREFIX")
    meta_date = str(meta["effective_date"])
    if dates[-1] != meta_date:
        raise ValueError("CALENDAR_DOES_NOT_END_ON_EFFECTIVE_DATE")
    if indices[-1] % 63 != 0:
        raise ValueError("EFFECTIVE_DATE_NOT_O00_REVIEW_INDEX")
    if meta.get("calendar_authoritative") is not True:
        raise ValueError("CALENDAR_AUTHORITY_NOT_ASSERTED")
    source_hashes = {"panel": sha256(panel_path), "universe": sha256(universe_path), "calendar": sha256(calendar_path), "metadata": sha256(meta_path)}
    if meta.get("calendar_source_sha256") != source_hashes["calendar"]:
        raise ValueError("CALENDAR_SOURCE_HASH_MISMATCH")
    rows = []
    for row_i, row in panel.iterrows():
        method_data = {}
        for method, _weight_key in METHOD_KEYS.items():
            score = float(score_results[method][row_i]) if coverage[method][row_i] >= 0.5 and np.isfinite(score_results[method][row_i]) else None
            method_data[method] = {
                "score": score,
                "financial_coverage": float(coverage[method][row_i]),
                "raw_factors": {name: (float(raw[row_i, j]) if np.isfinite(raw[row_i, j]) else None) for j, name in enumerate(FIELDS)},
                "defaulted_factors": [name for j, name in enumerate(FIELDS) if j in FINANCIAL and not np.isfinite(raw[row_i, j])],
                "masked_factors": [name for j, name in enumerate(FIELDS) if j in FINANCIAL and np.isfinite(raw[row_i, j]) and not observed[row_i, j]],
                "dq": float(dq[row_i]),
            }
        rows.append({"symbol": str(row.symbol), "symbol_index": int(universe.loc[universe.symbol.eq(str(row.symbol)), "symbol_index"].iloc[0]), "methods": method_data})
    snapshot = {
        "schema_version": 1, "data_scope": "PROSPECTIVE_FUTURE", "environment": "OFFICIAL_CANDIDATE",
        "snapshot_id": str(meta["snapshot_id"]), "snapshot_sha256": "", "effective_date": meta_date,
        "received_at": str(meta["received_at"]), "decision_cutoff_at": str(meta["decision_cutoff_at"]), "timezone": "Asia/Tehran",
        "contract_sha256": contract_sha, "expected_history_calendar_sha256": HISTORY_HASH,
        "calendar": {"anchor_date": "2021-04-03", "anchor_index": 0, "session_index": indices[-1], "session_date": dates[-1],
                     "complete_through_effective_date": True, "history_prefix_sha256": HISTORY_HASH, "additional_session_dates": dates,
                     "calendar_sha256": "", "calendar_source_sha256": source_hashes["calendar"], "next_session_open_at": str(meta["next_session_open_at"])},
        "score_provenance": {"uses_only_snapshot_inputs": True, "scorer_contract_sha256": contract_sha,
                             "raw_input_sha256": source_hashes["panel"], "scorer_version": "return_v11.core.score delegates to return_v8.engine.scores; return_v8.features@locked-contract"},
        "universe": rows,
    }
    from ranking_research.future_eval_v12_28.engine import canonical_json as _canonical_json, sha256_bytes
    snapshot["calendar"]["calendar_sha256"] = sha256_bytes(_canonical_json({"history_prefix_sha256": HISTORY_HASH, "additional_session_dates": dates}))
    snapshot["snapshot_sha256"] = snapshot_content_hash(snapshot)
    validate_snapshot(snapshot, contract_sha, now=datetime.now(timezone.utc))
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("panel", "universe", "calendar", "meta", "output"):
        parser.add_argument(f"--{arg}", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=OUT28 / "future_evaluation_contract.locked.json")
    parser.add_argument("--contract-sha256", type=Path, default=OUT28 / "future_evaluation_contract.sha256")
    args = parser.parse_args()
    snap = build_snapshot(args.panel, args.universe, args.calendar, args.meta, args.contract, args.contract_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snap, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    source_manifest = {
        "snapshot_id": snap["snapshot_id"], "snapshot_sha256": snap["snapshot_sha256"],
        "contract_sha256": sha256(args.contract),
        "input_sha256": {name: sha256(getattr(args, name)) for name in ("panel", "universe", "calendar", "meta")},
        "scorer_sources": {
            "ranking_research/return_v11/core.py": sha256(ROOT / "ranking_research/return_v11/core.py"),
            "ranking_research/return_v8/engine.py": sha256(ROOT / "ranking_research/return_v8/engine.py"),
            "ranking_research/return_v8/features.py": sha256(ROOT / "ranking_research/return_v8/features.py"),
        },
        "official_ledger_written": False,
    }
    args.output.with_suffix(".sources.json").write_text(json.dumps(source_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SNAPSHOT_CANDIDATE_PREPARED", "snapshot_id": snap["snapshot_id"], "snapshot_sha256": snap["snapshot_sha256"], "official_ledger_written": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
