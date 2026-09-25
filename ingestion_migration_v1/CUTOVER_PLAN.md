# CANONICAL INGESTION CUTOVER PLAN

This is a plan only. **No cutover was performed.** SQL Server remains the
authoritative ingestion path.

## Phase 1 (this phase) — DONE

- Canonical writer layer + dual-write, default `LEGACY_ONLY`.
- Four domains capable of safe dual-write; bounded sample validated; idempotency,
  reconciliation and failure isolation proven.

## Phase 2 — wire dual-write into legacy scripts (still additive) — MOSTLY DONE

1. **DONE:** `canonical_ingest` invoked from `py/brs_prices.py` (market),
   `py/MianSql2.py` (monthly), `py/MianSql.py` (financial) immediately after each
   legacy commit, gated by `CDF_INGESTION_MODE`.
2. **DONE:** per-batch reconciliation artifacts
   (`output/phase2_reconciliation.csv`, `phase2_real_batches.csv`); mismatch
   classes are surfaced, not hidden in logs.
3. **DONE:** `LEGACY_ONLY` remains the deployment default; `DUAL_WRITE` is opt-in
   per host.
4. **DONE:** real `collected_at` for new market fetches; Codal raw payload
   capture remains Phase 3 (`py/sync_codal.py`).

## Phase 3 — reconcile and retire duplicates

1. Reconcile `py2`'s separate PostgreSQL schema with canonical; keep a single
   parser per domain.
2. Backfill raw payloads only where legitimately re-fetchable; never fabricate
   historical raw content.
3. Resolve legacy identity ambiguities (duplicate-symbol collisions) at the
   intake boundary; keep the canonical identity guard.

## Phase 4 — shadow read + ingestion parity soak

1. Run `DUAL_WRITE` for a sustained window; require zero unexplained mismatch.
2. Prove canonical-only reads already validated for price-history remain exact.
3. Define monitoring and rollback: flipping `CDF_INGESTION_MODE` back to
   `LEGACY_ONLY` must stop canonical writes with no code/DB change.

## Phase 5 — controlled canonical-only (separate approval)

Only after sustained dual-write parity, per-domain, with:
- explicit approval and a maintenance window,
- legacy tables retained read-only (not dropped),
- a documented rollback to legacy ingestion,
- monitoring for write volume/latency and constraint failures.

## Measurable cutover criteria (do not execute)

A selected ingestion domain may be switched to canonical-authoritative behind a
rollback switch only when **all** hold, measured from real ingestion runs:

| Criterion | Target | Evidence field |
| --- | --- | --- |
| sustained real DUAL_WRITE success | ≥ N consecutive cycles (N=3 exercised) with 0 errors | `phase3_soak_cycles.csv` |
| unexplained mismatches | 0 across MISSING_CANONICAL/IDENTITY_MISMATCH/NUMERIC_MISMATCH/DATE_MISMATCH/WRITE_ERROR/UNCLASSIFIED | `phase3_reconciliation.csv` |
| idempotency | reruns insert 0 duplicates (rows, monthly periods, facts, observations, versions, parse runs) | `phase2_idempotency.json`, `phase3_soak_cycles.csv` |
| quarantine | all cases classified; no fabricated entities | `phase3_quarantine.csv`, `PHASE3_SOAK_REPORT.md` |
| Codal live lineage | report/version/parse_run/raw wired; version+raw semantics proven | `CODAL_LIVE_LINEAGE_REPORT.md` |
| market collected_at | actual source collection time, not migration time | phase2/3 tests |
| freshness observable | per-domain artifact exists | `canonical_ingestion_freshness.json` |
| retry/recovery | canonical failures replayable without rerunning legacy | `CANONICAL_RETRY_SPEC.md`, `canonical_retry_manifest.jsonl` |
| Go triggers compatible | same scripts, no API contract change | `GO_INGESTION_TRIGGER_PLAN.md` |
| analytics consumption | new canonical data visible; score runs untouched | `PHASE3_SOAK_REPORT.md` §7 |
| rollback path | `CDF_INGESTION_MODE=LEGACY_ONLY` stops canonical writes, config only | `DUAL_WRITE_SPEC.md` |

Rollback switch: setting `CDF_INGESTION_MODE=LEGACY_ONLY` (default) immediately
stops canonical writes with no code/DB change; SQL Server remains authoritative
throughout. SQL Server tables/code are not deleted.

## Phase 4 — MARKET_PRICE canonical-primary (DONE, reversible)

MARKET_PRICE promoted to canonical-authoritative in the shadow environment via
`CDF_MARKET_INGESTION_AUTHORITY=canonical` (bounded real cycles, failure
injection, retry recovery, Go read smoke). Rollback is one config flip to
`legacy`. MONTHLY_ACTIVITY / FINANCIAL_STATEMENT / CODAL remain unchanged.
Detail: `MARKET_AUTHORITY_REPORT.md`. Routine-use readiness:
`MARKET_CANONICAL_PRIMARY_READY_FOR_ROUTINE_USE`.

## Phase 5 — MARKET routine soak + MONTHLY canonical-primary (DONE)

- MARKET routine soak: 5 real cycles, 1 new observation, HEALTHY, backlog 0 →
  `MARKET_ROUTINE_SOAK_PASS`.
- MONTHLY_ACTIVITY promoted to canonical-primary (`CDF_MONTHLY_INGESTION_AUTHORITY=canonical`,
  default legacy) after market passed; 12 real cycles, unit reconciliation
  `EXPECTED_UNIT_CONVERSION`, 0 mismatch; mirror-failure isolated; retry replay
  returns backlog 0. Gates: `MONTHLY_CANONICAL_AUTHORITY_READY`,
  `MONTHLY_CANONICAL_PRIMARY_READY_FOR_ROUTINE_USE`.
- FINANCIAL_STATEMENT and CODAL remain legacy-authoritative. SQL Server retained.

## Phase 6 — MONTHLY routine soak + FINANCIAL canonical-primary (DONE)

- MONTHLY routine soak: 16 cycles, HEALTHY, backlog 0, 0 mismatch → `MONTHLY_ROUTINE_SOAK_PASS`.
- FINANCIAL_STATEMENT promoted to canonical-primary (`CDF_FINANCIAL_INGESTION_AUTHORITY=canonical`,
  default legacy) after monthly passed: 20 cycles, `EXPECTED_UNIT_CONVERSION`
  reconciliation, 0 mismatch, parser-rerun semantics, retry replay, mirror-failure
  isolation. Gates: `FINANCIAL_CANONICAL_AUTHORITY_READY`,
  `FINANCIAL_CANONICAL_PRIMARY_READY_FOR_ROUTINE_USE`.
- CODAL remains unchanged. SQL Server retained as mirror/fallback.

## Phase 7 — FINANCIAL routine soak + CODAL canonical-primary (DONE)

- FINANCIAL routine soak: 24 cycles, HEALTHY, backlog 0, 0 mismatch →
  `FINANCIAL_ROUTINE_SOAK_PASS`.
- CODAL lineage promoted to canonical-authoritative
  (`CDF_CODAL_INGESTION_AUTHORITY=canonical`, default legacy): TracingNo identity,
  raw-first, version/parse semantics, supersession, quarantine classification,
  retry, combined freshness. Gate: `CODAL_CANONICAL_AUTHORITY_READY`.
- All four domains canonical-primary; ingestion layer:
  `CANONICAL_INGESTION_LAYER_READY`. SQL Server remains mirror/fallback/rollback.

## Explicit non-goals (this phase)

No disabling SQL Server writes, no removing pyodbc, no deleting legacy tables,
no changing Go triggers to canonical-only, no deployment default changes.
