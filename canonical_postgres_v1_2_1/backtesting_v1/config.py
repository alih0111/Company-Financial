"""Backtesting v1 configuration + frozen model identifiers.

Phase 1: infrastructure correctness + untuned baseline. No weight/formula changes.
Canonical analytics semantics are consumed from analytics_canonical_v1 (not copied).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
CANON = BASE / "analytics_canonical_v1"

SCORE_VERSION = "canonical-v1-dev"
IMPLEMENTATION_REVISION = "report-chain-ttm-v1"


@dataclass
class BacktestConfig:
    start_date: str = "2021-01-01"
    end_date: str = "2026-06-30"
    rebalance_freq: str = "M"                 # M | W | Q
    signal_convention: str = "close_of_signal_date_as_of"
    execution_convention: str = "next_trading_day_close"
    return_convention: str = "raw_price_return"   # corporate_actions empty -> not adjusted
    horizons: tuple = (5, 21, 63)             # trading days, diagnostics
    portfolio_mode: str = "top_n"             # top_n | top_pct
    top_n: int = 20
    top_pct: float = 0.10
    weighting: str = "equal"
    cost_bps_per_side: float = 10.0           # illustrative only
    benchmark: str = "equal_weight_tradable_universe"
    quantile_buckets: int = 5
    coverage_buckets: tuple = (7, 14)         # low <=7, medium 8..14, high >=15 (observed distribution)
    min_tradable_signals: int = 5

    def hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()


def frozen_model_identifiers() -> dict:
    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""

    return {
        "score_version": SCORE_VERSION,
        "implementation_revision": IMPLEMENTATION_REVISION,
        "metric_spec_hash": sha(CANON / "metric_spec.json"),
        "report_chain_spec_hash": sha(CANON / "report_chain_ttm_spec.md"),
        "factor_review_hash": sha(CANON / "factor_review.md"),
        "missing_data_contract_hash": sha(CANON / "data_work" / "missing_data_contract.md"),
        "weights_validated": False,
        "baseline_weights_note": "NOT VALIDATED FOR CANONICAL V1 (prototype baseline)",
    }
