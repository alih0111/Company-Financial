# Out-of-Sample Validation Protocol (Phase 3, FROZEN)

Machine-readable: `output/oos_protocol.json`.

## Chronological split (no performance-based selection)

| role | period |
| --- | --- |
| **Development** | 2021–2023 |
| **Validation** | 2024 |
| **Holdout** | 2025 |
| **Forward monitoring** | 2026 (n=2 in-sample; insufficient for inference) |

Rationale: preserves chronological order, gives the largest block to development,
one year each to validation and holdout. No split was chosen by inspecting returns.

## Rules

1. Model/weight/hyperparameter selection only on **development + validation**.
2. **Holdout (2025) is never used for selection**; each experiment version is
   evaluated on it **once**.
3. 2026 is forward monitoring only; not used for strong inference.
4. Same infrastructure as Phases 1–2: dynamic PIT universe, `trade_date` market
   proxy, raw price returns (corporate actions unavailable), monthly rebalance,
   equal-weight assessment, coverage-controlled diagnostics.
5. All candidate models use **new version identifiers** (e.g. `canonical-v2-exp-A`);
   canonical-v1 is never mutated.
6. Multiple-testing awareness across 21 factors; dependence-aware (block bootstrap
   over rebalance dates).

## Frozen status

`holdout_used_for_selection = false`; protocol frozen for all Phase-4 experiments.
