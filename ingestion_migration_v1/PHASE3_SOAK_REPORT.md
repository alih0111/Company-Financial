# PHASE 3 — SUSTAINED REAL DUAL-WRITE SOAK REPORT

Mode: `CDF_INGESTION_MODE=dual_write` (opt-in). SQL Server authoritative and
unchanged. No canonical-only cutover. Shadow PostgreSQL
`company_financial_analytics_shadow_v121`.

## 1. Cycles executed

Driver `drivers/run_phase3_soak.py` ran **15 real cycles** through the wired
scripts/hooks against live SQL Server + BRS:

| Domain | Cycles | Real work |
| --- | --- | --- |
| market_price | 3 | live BRS `resolve_matched_symbols` + `build_daily_row` + `upsert_rows` + hook |
| monthly_activity | 6 (3 cycles × 2 companies) | `dual_write_monthly_values` on real `mahane` periods |
| financial_statement | 6 (3 cycles × 2 companies) | `dual_write_financial_by_key` on real `miandore2` periods |

## 2. Results (`phase3_soak_cycles.csv`, `phase3_summary.json`)

| Metric | Value |
| --- | --- |
| canonical inserted | 6 (new monthly periods for چکاپا) |
| canonical skipped (idempotent) | 378 |
| canonical errors | **0** |
| quarantined during cycles | **0** |
| unexplained mismatches | **0** |

- **Market**: cycle 1–3 each `inserted=0, skipped=3` — new live BRS rows were
  matched by natural-key/hash and were idempotent; same logical observation
  never duplicated.
- **Monthly**: cycle 1 for چکاپا inserted 6 (report/version/parse_run/monthly for
  2 previously-absent periods); cycles 2–3 inserted 0. Duplicate periods: none.
- **Financial**: all cycles inserted 0, skipped 28/25 — statements/facts reused;
  no duplicate facts.
- Idempotency holds across cycles (second and third runs insert nothing new).

## 3. Reconciliation (`phase3_reconciliation.csv`)

Per-cycle exact = inserted + skipped; mismatch = 0 for every cycle. Phase-2
metric-level reconciliation (`EXACT_EQUIVALENT` 14, `EXPECTED_UNIT_CONVERSION`
41) remains valid; no mismatch class observed in any soak cycle.

## 4. Market soak specifics

- New observations enter PostgreSQL on first sight; reruns deduplicate.
- `collected_at` = actual collection time (`now` +03:30) for new fetches.
- No historical row overwritten (append-only).
- Security identity via `legacy_entity_map`; no identity failures in the target
  sample.

## 5. Quarantine review (`phase3_quarantine.csv`)

33 open `identity_conflict` DQ rows: `EXPECTED_SCOPE_EXCLUSION` 28,
`TRANSIENT_ERROR` 5 (from deliberate failure injection). Representative cases
are out-of-universe companies/funds (e.g. `تولیدی حسنانو`/`زشک`,
`کیمیا پلی استر قم`/`شکیمیا` — a known legacy-only symbol). No canonical
mapping bug; **no entities were fabricated**.

## 6. Freshness (`output/canonical_ingestion_freshness.json`)

Tracks per domain: legacy latest date/period, canonical row counts and last
write time, open quarantines, mode. Example: market canonical 706,054 rows,
legacy latest 2026-09-25; monthly canonical 12,075 rows, legacy latest
1405/06/31; financial facts 71,361. Freshness is now measurable per domain.

## 7. Analytics visibility smoke

New canonical data is visible to the canonical read paths:
`market.daily_prices` 705,689 rows, `fundamentals.monthly_activities` for the
recent period present, `fundamentals.financial_facts` 71,361 rows. Existing
`analytics.score_runs` (4) and `analytics.company_scores` were **not** modified
(no score overwrite).

## 8. Go trigger

`POST /api/brs/collect {mode:"backfill", symbol:"کیمیا"}` executed the same
`py/brs_prices.py` script with `CDF_INGESTION_MODE=dual_write` (venv interpreter
on PATH). Legacy returned a no-op (`upserted=0 skipped=1`, data fresh), so no
canonical write was expected; no API response contract changed. The trigger →
script → legacy → canonical path is confirmed for the wired code.

## 9. Retry

`CANONICAL_RETRY_SPEC.md`; failures append a deterministic entry to
`output/canonical_retry_manifest.jsonl` (verified during failure injection) so
the canonical side can be replayed without rerunning legacy.

## 10. Gate

**`CANONICAL_INGESTION_SOAK_PASS`** — no SQL Server behavior removed, no
canonical-only cutover.
