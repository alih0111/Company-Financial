"""Freeze the exact v3.7 compatibility output as a Golden Regression Oracle.

COMPATIBILITY_ONLY_NOT_CANONICAL / GOLDEN REGRESSION ORACLE.

Recomputes the frozen compat metrics deterministically and writes:
  * golden_output.json   (ordered 276 subject IDs -> base metrics, 21 factors,
                          penalties, category scores, QuantScore)
  * golden_hash.txt      (sha256 of the canonical JSON payload)
  * _artifact_hashes.json (sha256 of the frozen inputs / reference / code)

Run only intentionally; normal compat runs must not overwrite these.
No SQL Server access, no canonical writes.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "analytics_v37_compat"))
sys.path.insert(0, str(BASE / "migration_tools"))

import compute_v37_legacy_full as V  # noqa: E402


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    metrics = V.build_metrics()
    payload = V.golden_payload(metrics)
    h = V.golden_hash(metrics)

    (HERE / "golden_output.json").write_text(
        json.dumps(payload, sort_keys=True, indent=1, default=str), encoding="utf-8")
    (HERE / "golden_hash.txt").write_text(h + "\n", encoding="utf-8")

    artifacts = {
        "canonical_postgres_v1_2_1/analytics_parity/reference/v37_full_snapshot.csv":
            BASE / "analytics_parity/reference/v37_full_snapshot.csv",
        "canonical_postgres_v1_2_1/analytics_parity/reference_context.json":
            BASE / "analytics_parity/reference_context.json",
        "canonical_postgres_v1_2_1/analytics_parity_debug/v37_scoring_subjects.csv":
            BASE / "analytics_parity_debug/v37_scoring_subjects.csv",
        "canonical_postgres_v1_2_1/analytics_parity_debug/reference/legacy_v37_financial_inputs.csv":
            BASE / "analytics_parity_debug/reference/legacy_v37_financial_inputs.csv",
        "canonical_postgres_v1_2_1/analytics_parity_debug/reference/legacy_v37_monthly_inputs.csv":
            BASE / "analytics_parity_debug/reference/legacy_v37_monthly_inputs.csv",
        "canonical_postgres_v1_2_1/analytics_parity_debug/reference/legacy_v37_market_inputs.csv":
            BASE / "analytics_parity_debug/reference/legacy_v37_market_inputs.csv",
        "canonical_postgres_v1_2_1/analytics_v37_compat/compute_v37_faithful.py":
            BASE / "analytics_v37_compat/compute_v37_faithful.py",
        "canonical_postgres_v1_2_1/analytics_v37_compat/compute_v37_legacy_full.py":
            BASE / "analytics_v37_compat/compute_v37_legacy_full.py",
    }
    hashes = {k: sha256_file(p) for k, p in artifacts.items() if p.exists()}
    hashes["golden_hash"] = h
    hashes["subject_count"] = len(payload)
    (HERE / "_artifact_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")

    print("subjects:", len(payload))
    print("golden_hash:", h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
