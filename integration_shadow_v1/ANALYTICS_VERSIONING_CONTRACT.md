# ANALYTICS VERSIONING CONTRACT — Phase 1

## 1. Principle

Analytics consumed by the application are **version-selected**, never hard-coded
into handlers. The current default canonical model is `canonical-v1-dev`; future
`canonical-v2-*` models must be selectable without rewriting handlers.

Go does **not** reimplement factor formulas. It reads the canonical analytics
outputs produced by the canonical analytics engine.

## 2. Canonical analytics tables consumed

| Table | Role | Consumed fields |
| --- | --- | --- |
| `analytics.score_runs` | run registry / version + PIT | `id`, `score_version`, `as_of_date`, `source_cutoff_at`, `started_at`, `code_version`, `status` |
| `analytics.company_scores` | immutable score output | `run_id`, `company_id`, `primary_security_id`, `quant_score`, `data_quality_score`, `growth_score`, `profitability_score`, `valuation_score`, `market_score` |
| `analytics.factor_scores` | immutable factor output | `factor_code`, `raw_value`, `percentile`, `weighted_score`, `weight` (available for future expansion) |
| `analytics.metric_snapshots` | immutable PIT metric output | `metric_code`, `value`, `unit`, `calculation_version`, `source_cutoff_at` (empty in the current shadow run; interface reserved) |

## 3. Version selection

Selection is deterministic and centralized in `integration.PG.SelectScoreRun` /
`ScoresByLegacyIDs`:

```sql
SELECT id, score_version
FROM analytics.score_runs
WHERE score_version = $1 AND status = 'completed'
ORDER BY as_of_date DESC, started_at DESC
LIMIT 1
```

- The version string comes from `Config.ScoreVersion` (`CDF_CANONICAL_SCORE_VERSION`,
  default `canonical-v1-dev`).
- Outputs are joined to the selected run by `run_id`; `metric_snapshots` additionally
  carry `calculation_version`.
- No handler contains a literal score version. Only the config default constant
  `integration.DefaultScoreVersion` defines the current Phase-1 default.
- Experimental versions (e.g. `canonical-v2-*`) are selectable by env var and are
  **not** production defaults.

## 4. Point-in-time guarantees

- Each selected run carries `source_cutoff_at`. The application consumes the run's
  PIT semantics rather than re-deriving them.
- The integration layer never substitutes a naive "latest row" query for PIT-aware
  canonical analytics.

## 5. Score/semantic compatibility

- Canonical `quant_score` and component scores are **not** expected to equal the
  legacy v3.7 `QuantScore`. Such differences are classified as
  `EXPECTED_CANONICAL_SEMANTIC_CHANGE`.
- Canonical identity (`company_id`) is resolved to the legacy `CompanyID` only for
  comparison/translation via `core.legacy_entity_map`; public IDs are unchanged.
- Legacy `v3.7-compat` (`compat_v37.scoring_subjects`) is an **oracle only** and is
  never exposed as application architecture.
- Legacy heuristics (`Product1`, `NPUnitRatio`, `OpK`, `OpAmt`) must not enter
  canonical paths.

## 6. Default run observed (shadow DB `company_financial_analytics_shadow_v121`)

| Field | Value |
| --- | --- |
| Default version | `canonical-v1-dev` |
| Selected run id | `c6cb1579-2c28-4526-b3eb-f71d781ca4a4` |
| `as_of_date` | `2026-09-24` |
| `code_version` | `canonical-v1-dev+report-chain-ttm` |
| Implementation revision | `report-chain-ttm-v1` |
| Company scores | 267 |
| Older version present | `v3.7-compat` (oracle, 273 rows) |

## 7. Future API migration (documented, not performed)

If canonical identity or units are ever exposed to clients, a compatibility
translation layer is required. Phase 1 preserves the existing contract: no JSON
field renames, no ID changes, no unit changes at the response boundary.
