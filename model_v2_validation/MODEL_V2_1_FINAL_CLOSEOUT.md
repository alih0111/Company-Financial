# MODEL V2.1 — FINAL CLOSEOUT (immutable)

Frozen: 2026-10-02. This document closes Model v2.1 formally. No artifact it references
may be modified. Diagnostics that motivated the successor preregistration are recorded
separately (`MODEL_V2_1_R2_DIAGNOSTICS` below) and are Development-only.

## MODEL_V2_1_FINAL_STATUS = VALIDATION_WEAK

Per the frozen selection rule in `MODEL_V2_1_PREREGISTRATION.md`: no candidate eligible
under R1-R4 ⇒ `MODEL_V2_1_VALIDATION_WEAK`. The preregistered gate outcome is FAIL;
the strongest candidate (canonical-v2.1-a) passes R1, R3, R4 and fails only R2
(Dev positive-fraction 0.7222 vs required 0.75). This is the accepted final result.
No rescue attempts are permitted.

## Final data versions (hash-pinned)

| artifact | version | sha256 (prefix) |
|---|---|---|
| forward-return target | `FORWARD_RETURN_ADJUSTED_V1` (`phase3_signals_adjusted_v1.csv`) | `bf7cc191bf907e914` |
| direct PERank | `PERank_DIRECT_V2` = `perank-direct-v2+tsetmc-shares+codal-knowledge+ambiguity-resolved` (`pe_direct_universe_v2.jsonl`) | `121dbb512f5c7897` |
| adjusted-return evaluation | `MODEL_V2_ADJUSTED_RETURN_EVAL` | `41b19c16aea3f2fd` |
| direct rebaseline (raw-return reference) | `MODEL_V2_DIRECT_PERANK_REBASELINE_V2` | `b19d7c2272169645` |
| canonical price basis | `CANONICAL_RETURN_PRICE = TSETMC pClosing` (raw), vendor pDrCotVal series retained as legacy comparison only | — |
| corporate actions | `market.corporate_actions` source `tsetmc_gap_rule_v1`, 7,013 rows, semantics/evidence graded | — |
| return-series integrity | `RETURN_SERIES_INTEGRITY = PASS`; `PRICE_ADJUSTMENT_PIPELINE = PASS`; `CORPORATE_ACTION_SEMANTICS = PARTIAL` | — |
| historical-share integrity | `HISTORICAL_SHARE_REPAIR_COMPLETE = YES` (PASS) | — |

## Final factor set (frozen robust six)

`PERank` (consumed as PERank_DIRECT_V2), `NetProfitGrowthRank`, `SalesGrowthRank`,
`SalesGrowth3MRank`, `RevenueGrowthRank`, `LowVolatilityRank` — ranks from the frozen
Phase-3 snapshot; missing policy `drop_unavailable_renormalize`; direction as stored.

## Final candidate definitions

- baseline `canonical-v1-dev`: frozen `quant_score` column.
- `canonical-v2.1-a`: equal weights 1/6 over the robust six.
- `canonical-v2.1-b`: weights from Dev statistics per the frozen `dev_stat_weights` rule.
- `canonical-v2.1-c`: a-weights with `beta_c` coverage tilt per the frozen rule.
- ablation `canonical-v2.1-a-NPGX`: a-weights minus NetProfitGrowthRank (1/5).

## Final Dev / Validation metrics (IC21, adjusted target, direct world)

Baseline canonical-v1-dev: Dev 0.0753 / Val 0.1801.

| candidate | Dev IC21 | Val IC21 | Dev pf | Val pf | Dev turn | Val turn | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|---|---|---|---|---|
| canonical-v2.1-a | +0.0992 | +0.1932 | 0.7222 | 0.9167 | 0.650 | 0.641 | PASS | **FAIL** | PASS | PASS |
| canonical-v2.1-b | +0.0974 | +0.1533 | 0.6111 | 0.8333 | 0.633 | 0.629 | FAIL | **FAIL** | PASS | PASS |
| canonical-v2.1-c | +0.0989 | +0.1935 | 0.7222 | 0.9167 | 0.658 | 0.616 | PASS | **FAIL** | PASS | FAIL |

Holdout 2025 / Forward 2026 were inspected descriptively only (see the evaluation JSON);
they are NOT confirmatory evidence (data-snooping statement in
`MODEL_V2_2_PREREGISTRATION.md`).

## R2 diagnostic record (Development only — explanation, not tuning)

Full data: `output/model_v2_1_r2_diagnostics.json` (script
`model_v2_1_r2_diagnostics.py`). Headline:

- 36 Dev dates: **26 positive / 10 negative / 7 near-zero (|IC|<0.02)**; pos-frac 0.7222 —
  exactly **one date** short of 27/36 = 0.75. The smallest |IC| among negatives is 0.0022.
- Negatives are DIFFUSE: present in all three years (9/8/9 positive per year) and in 8 of
  12 quarters; longest consecutive negative run = 2. Two heavy dates carry most negative
  mass: 2022-07-31 (IC −0.332) and 2023-10-31 (−0.233).
- Quarter-block bootstrap (B=2000): pos-frac p05/p50/p95 = 0.611/0.722/0.833;
  **P(pos-frac ≥ 0.75) = 0.432** — the frozen threshold sits inside the sampling
  distribution; the Dev result is statistically indistinguishable from the threshold.
- Factor attribution on the five worst dates: LowVolatilityRank strongly negative on all
  five (−0.125…−0.530), PERank negative on four; growth factors mostly positive there.
- Factor-level (Dev): mean IC PERank 0.093 / NPGX 0.092 / SalesGrowth3M 0.065 /
  SalesGrowth 0.059 / RevenueGrowth 0.048 / LowVol 0.037 (pf 0.556, lowest).
  **Availability**: PERank 56.4%, NPGX 76.7%, SalesGrowth 29.7%, SalesGrowth3M 59.4%,
  **RevenueGrowth 5.2%**, LowVol 99.99%.
- Redundancy (mean pairwise rank correlation): SalesGrowth|RevenueGrowth 0.649,
  NPGX|SalesGrowth 0.591, NPGX|RevenueGrowth 0.484 — the four growth ranks form one
  correlated family (4/6 of the weight).
- Leave-one-out (DIAGNOSTIC ONLY, not candidate mining): dropping NPGX −0.0223 (largest
  loss), SalesGrowth +0.0005 (zero marginal), RevenueGrowth −0.0009 (nil, consistent with
  5.2% availability), LowVol −0.0048, PERank −0.0115, SalesGrowth3M −0.0141.

**Stability verdict (Part 4)**: predominantly a small-number-of-dates stability issue
(one date flips the gate; nearest negative |IC| = 0.0022; P(≥0.75) = 0.432), on a thin
DIFFUSE margin (not one clustered regime failure), with two heavy regime dates. Not broad
structural weakness (mean Dev IC +0.086; 8-9 positive dates in every year). R2 is NOT
reinterpreted: 0.72 < 0.75 stands as FAIL.

## Successor

`MODEL_V2_2_PREREGISTRATION.md` — frozen before any v2.2 execution. MODEL_V2_2_EXECUTED = NO.
